"""Controlled typed-place inclusion prototype. Explicitly NOT an accepted backend.

Consumes rustc API records, never parsed MIR display strings. Unsupported
operations prohibit acceptance; no type-only or dynamic-trace fallback exists.
"""
from collections import defaultdict
import hashlib
import json
try:
    from .body_ledger import ledger
except ImportError:
    from body_ledger import ledger


def analyze(probe, *, roots=None, cast_audit=None):
    functions={row['instance_identity']:row for row in probe['instances']}
    cells_by_local=defaultdict(set)
    class Cells(defaultdict):
        def __missing__(self,key):
            # Reads create typed cells too; preserve these in precision-loss
            # evidence even when their current points-to set is empty.
            cells_by_local[key[:2]].add(key)
            return super().__missing__(key)
    values=Cells(set)
    losses=set()
    sites={}
    allocations={}
    receiver_reports={}
    collapsed=set()
    collapse_evidence=defaultdict(lambda:{'source_spans':set(),'affected_fields':set(),'reasons':set(),'affected_callsites':set()})
    current_span='unknown MIR source'

    def root(cell):return (cell[0],cell[1],())

    def canonical(cell):return root(cell) if root(cell) in collapsed else cell

    def collapse(cells,reason):
        nonlocal changed
        for cell in cells:
            base=root(cell)
            if base not in collapsed:
                collapsed.add(base);changed=True
            record=collapse_evidence[base]
            record['source_spans'].add(current_span)
            record['reasons'].add(reason)
            incoming=set()
            for key in list(cells_by_local[base[:2]]):
                incoming.update(values[key])
                if key[2]:record['affected_fields'].add('/'.join(key[2]))
            store({base},incoming)
    active=set(functions) if roots is None else set(roots)
    for absent_root in active - functions.keys():
        losses.add((absent_root, 'required_root_unavailable'))
    if not functions:
        losses.add(('<program>', 'empty_instance_inventory'))

    def locations(owner,place):
        local,projections=place
        current={(owner,local,())}
        for projection in projections:
            if projection=='deref':
                erased={value[1] for cell in current for value in values[canonical(cell)] if value[0]=='erased_address'}
                collapse(erased,'dereference_after_pointer_reinterpretation')
                current={canonical(value[1]) for cell in current for value in values[canonical(cell)] if value[0]=='address'}
            elif projection.startswith(('field:','variant:')):
                current={canonical((i,l,p+(projection,))) for i,l,p in current}
            elif projection=='unknown_index':
                collapse(current,'unknown_index_or_offset')
                current={canonical(c) for c in current}
            else:
                losses.add((owner,'unsupported_projection'))
                return set()
        return current

    def operand(owner,source):
        if 'unsupported_constant' in source:
            losses.add((owner,'constant_payload_unmodeled'))
        if 'function' in source:return {('function',source['function'])}
        if 'reference' in source:return {('address',p) for p in locations(owner,source['reference'])}
        if 'place' in source:
            cells=locations(owner,source['place'])
            if source.get('union_read'):
                collapse(cells,'union_access')
            return set().union(*(values[canonical(p)] for p in cells))
        if 'constant_reference' in source:
            scope='' if source['constant_reference'].startswith('static:') else owner+':'
            cell=('constant:'+scope+source['constant_reference'],0,())
            store({cell},{('type',source['pointee_key'])})
            for field in source.get('fields',[]):
                store({(cell[0],0,tuple(field['path']))},{('function',field['function'])})
            if not source.get('payload_decoded',source['zero_sized']):losses.add((owner,'constant_payload_unmodeled'))
            return {('address',cell)}
        return set()

    changed=False
    def store(cells,incoming):
        nonlocal changed
        for cell in cells:
            cell=canonical(cell)
            cells_by_local[cell[:2]].add(cell)
            old=len(values[cell]); values[cell].update(incoming)
            changed |= old!=len(values[cell])

    def copy(owner,destination,source,source_owner=None):
        source_owner=source_owner or owner
        cells=locations(owner,destination)
        store(cells,operand(source_owner,source))
        for field in source.get('constant_fields',[]):
            store({(i,l,p+tuple(field['path'])) for i,l,p in cells},{('function',field['function'])})
        if 'place' in source:
            # Whole-value copies preserve each typed subfield, not their union.
            for src in locations(source_owner,source['place']):
                if root(src) in collapsed:
                    collapse(cells,'copy_of_collapsed_object')
                for key in list(cells_by_local[src[:2]]):
                    if key[2][:len(src[2])]==src[2]:
                        suffix=key[2][len(src[2]):]
                        store({(i,l,p+suffix) for i,l,p in cells},values[key])

    def allocate(owner, site):
        model=site['semantic_operation']
        evidence={'instance':owner,'allocation_source_span':site['source'],
                  'allocation_ordinal':site['block'],'allocated_type':model['allocated_type'],
                  'type_key':model['type_key'],'source_def_path':model['source_def_path']}
        allocation='heap:'+hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
        allocations[allocation]={'abstract_object_id':allocation,**evidence,
                                 'established_by':model['kind']}
        address={('address',(allocation,0,()))}
        # Seed prefixes through the compiler-exported Box/Unique/NonNull
        # representation. Object payload fields are stored separately.
        destination=site['destination']
        store(locations(owner,destination),address)
        for path in model['pointer_paths']:
            for length in range(1,len(path)+1):
                store(locations(owner,[destination[0],destination[1]+path[:length]]),address)
        if model['kind']=='box_new':copy(allocation,[0,[]],site['arguments'][0],owner)
        store({(allocation,0,())},{('type',model['type_key'])})

    converged=False
    for _ in range(256):
        changed=False
        for owner,row in functions.items():
            if owner not in active:
                continue
            for local,t in enumerate(row.get('local_types',[])):
                store({(owner,local,())},{('type',t)})
            if row.get('body_availability') == 'missing MIR':
                losses.add((owner, 'required_body_unavailable'))
            for constraint in row['constraints']:
                kind=constraint['kind']; dst=constraint['destination']; src=constraint['source']
                current_span=constraint.get('source_span','unknown MIR source')
                if constraint.get('union_write'):
                    collapse(locations(owner,dst),'union_access')
                if kind=='scalar_operation':pass  # Cannot carry pointers or callable values.
                elif kind=='pointer_free_scalar_extract':pass  # Compiler layout/field proof; no pointer payload.
                elif kind=='pointer_address_bits':
                    # This is not provenance exposure and cannot feed a dereference
                    # or indirect call. Reconstruction has its own fail-closed gate.
                    store(locations(owner,dst),{('address_bits',v[1]) for v in operand(owner,src)
                                               if v[0] in ('address','erased_address')})
                elif kind=='provenance_free_pointer':
                    # Integer transmute does not recover an allocation's provenance.
                    # This is distinct from PointerWithExposedProvenance (unsupported).
                    store(locations(owner,dst),{('provenance_free_pointer',owner)})
                elif kind=='copy':copy(owner,dst,src)
                elif kind=='pointer_metadata':
                    incoming=operand(owner,src)
                    objects={v[1] for v in incoming if v[0] in ('address','erased_address')}
                    metadata={v for v in incoming if v[0]=='type'}
                    metadata.update(v for p in objects for v in values[canonical(p)] if v[0]=='type')
                    store(locations(owner,dst),metadata)
                elif kind=='raw_pointer_aggregate':
                    copy(owner,dst,src[0])
                    store(locations(owner,dst),{v for v in operand(owner,src[1]) if v[0]=='type'})
                elif kind=='byte_copy':
                    source_cells={v[1] for v in operand(owner,src[0]) if v[0]=='address'}
                    dest_cells={v[1] for v in operand(owner,src[1]) if v[0]=='address'}
                    collapse(source_cells|dest_cells,'byte_copy')
                    incoming=set().union(*(values[canonical(p)] for p in source_cells))
                    store({canonical(p) for p in dest_cells},incoming)
                elif kind=='pointer_offset':
                    incoming=operand(owner,src)
                    collapse({v[1] for v in incoming if v[0]=='address'},'unknown_index_or_offset')
                    store(locations(owner,dst),incoming)
                elif kind=='pointer_cast':
                    incoming=operand(owner,src.get('operand',src))
                    restored={v[1] for v in incoming if v[0]=='address' and
                              ('type',src.get('pointee_key')) in values[canonical(v[1])]}
                    incoming={v for v in incoming if not (v[0]=='erased_address' and v[1] in restored)}
                    incoming |= {('erased_address',v[1]) for v in incoming if v[0]=='address' and v[1] not in restored}
                    store(locations(owner,dst),incoming)
                elif kind=='reinterpret':
                    cells=locations(owner,dst)
                    if 'place' in src:
                        collapse(locations(owner,src['place']),'transmute')
                    collapse(cells,'transmute')
                    copy(owner,dst,src)
                elif kind=='reference':
                    store(locations(owner,dst),{('address',p) for p in locations(owner,src['place'])})
                elif kind=='aggregate':
                    # Only the untagged field case is represented by this probe.
                    # Enum/downcast layout is not silently claimed supported.
                    losses.add((owner,'aggregate_variant_kind_not_exported'))
                    for index,field in enumerate(src):
                        copy(owner,[dst[0],dst[1]+['field:'+str(index)]],field)
                elif kind=='typed_aggregate':
                    for index,field in enumerate(src['fields']):
                        copy(owner,[dst[0],dst[1]+src['prefix']+['field:'+str(index)]],field)
                elif kind=='repeat_aggregate':
                    for index in range(src['count']):
                        copy(owner,[dst[0],dst[1]+['field:'+str(index)]],src['operand'])
                elif kind=='union_aggregate':
                    collapse(locations(owner,dst),'union_access')
                    for field in src:copy(owner,dst,field)
                else:losses.add((owner,kind))
            for site in row['calls']:
                current_span=site.get('source','unknown MIR source')
                is_box=(site.get('semantic_operation') or {}).get('kind') in ('box_new','box_storage_allocation')
                if is_box: allocate(owner,site)
                key=(owner,site['block'])
                if site['status'] in ('resolved_instance','drop_instance'):
                    targets={site['target']}
                elif site['status']=='unresolved_function_pointer':
                    targets={v[1] for v in operand(owner,site['callee_value']) if v[0]=='function'}
                    if 'place' in site['callee_value']:
                        for cell in locations(owner,site['callee_value']['place']):
                            if root(cell) in collapsed:
                                collapse_evidence[root(cell)]['affected_callsites'].add(owner+':bb'+str(site['block']))
                elif site['status']=='unresolved_dyn' and 'dyn_candidates' in site:
                    receiver=operand(owner,site['arguments'][0])
                    types={v[1] for v in receiver if v[0]=='type'}
                    objects={v[1] for v in receiver if v[0]=='address'}
                    types.update(v[1] for p in objects for v in values[p] if v[0]=='type')
                    candidates=[c for c in site['dyn_candidates'] if c['type_key'] in types]
                    targets={c['target'] for c in candidates}
                    receiver_reports[key]={'receiver_objects':sorted(objects),
                        'receiver_types':sorted({c['receiver_type'] for c in candidates}),
                        'trait_method':site['trait_method']}
                else:
                    targets=set(); losses.add((owner,site['status']))
                previous=sites.setdefault(key,set())
                old=len(previous); previous.update(targets); changed |= old!=len(previous)
                for target in targets:
                    if target not in active:
                        active.add(target); changed=True
                    if target not in functions or functions[target].get('body_availability') == 'missing MIR':
                        losses.add((owner,'external_or_unexported_body')); continue
                    contract=functions[target].get('intrinsic_contract')
                    if contract:
                        if contract=='identity':
                            copy(owner,site['destination'],site['arguments'][0])
                        elif contract=='select_value_union':
                            for arg in site['arguments'][1:3]:copy(owner,site['destination'],arg)
                        elif contract=='offset_pointer_union':
                            incoming=operand(owner,site['arguments'][0])
                            collapse({v[1] for v in incoming if v[0]=='address'},'unknown_index_or_offset')
                            store(locations(owner,site['destination']),incoming)
                        elif contract=='typed_pointee_swap':
                            left={v[1] for v in operand(owner,site['arguments'][0]) if v[0]=='address'}
                            right={v[1] for v in operand(owner,site['arguments'][1]) if v[0]=='address'}
                            # Flow-insensitive swap is the bidirectional union of
                            # corresponding typed fields, retaining each object.
                            for sources,destinations in ((left,right),(right,left)):
                                for src_cell in sources:
                                    for cell in list(cells_by_local[src_cell[:2]]):
                                        if cell[2][:len(src_cell[2])]==src_cell[2]:
                                            suffix=cell[2][len(src_cell[2]):]
                                            store({(i,l,p+suffix) for i,l,p in destinations},values[cell])
                        elif contract not in ('population_count_scalar','inhabited_type_assertion',
                                              'abort_nonreturning','immutable_caller_location','dynamic_layout_scalar',
                                              'saturating_sub_scalar','leading_zero_count_scalar',
                                              'pointer_distance_scalar','cold_path_leaf'):
                            losses.add((target,'unknown_intrinsic_contract'))
                        continue
                    if 'arguments' not in site:continue
                    for index,arg in enumerate(site['arguments'],1):
                        if site.get('rust_call') and functions[target].get('closure_body') and index==len(site['arguments']):
                            if 'place' not in arg:
                                if functions[target]['argument_count']>=index:
                                    losses.add((owner,'unsupported_rust_call_tuple_constant'))
                                continue
                            for parameter in range(index,functions[target]['argument_count']+1):
                                local,path=arg['place']
                                copy(target,[parameter,[]],{'place':[local,path+['field:'+str(parameter-index)]]},owner)
                        else:
                            copy(target,[index,[]],arg,owner)
                    # The standard Box::new value transfer is allocation-site
                    # summarized. Its call and all body edges remain present.
                    # A shared return slot must not merge distinct allocation sites.
                    if not is_box and site.get('destination') is not None:
                        copy(owner,site['destination'],{'place':[0,[]]},target)
        if not changed:
            converged=True;break
    if cast_audit is not None:
        for owner in sorted(active):
            for constraint in functions.get(owner,{}).get('constraints',[]):
                if constraint['kind']=='unsupported_cast':
                    cast_audit.append({'calling_instance':owner,**constraint,
                                       'current_abstract_value':sorted(operand(owner,constraint['source']))})
    return {'accepted_backend':False,'converged':converged,
            'required_body_ledger':ledger(functions,active),
            'unsupported_operation_inventory':[
                {'instance':owner,'kind':c['kind'],'operation':c.get('operation_detail'),
                 'source_span':c.get('source_span'),'classification':'D'}
                for owner,row in sorted(functions.items()) if owner in active
                for c in row['constraints'] if c['kind'].startswith('unsupported')],
            'active_instances':sorted(active),
            'allocations':[allocations[key] for key in sorted(allocations) if allocations[key]['established_by']=='box_new'],
            'constructor_storage_summaries':[allocations[key] for key in sorted(allocations) if allocations[key]['established_by']=='box_storage_allocation'],
            'body_inventory':[{'instance':i,'classification':functions[i].get('body_classification','unclassified')}
                              for i in sorted(active) if i in functions],
            'precision_losses':[{'kind':'byte_level_alias',
                'allocation':cell[0] if cell[0].startswith('heap:') else 'stack:'+hashlib.sha256(repr(cell[:2]).encode()).hexdigest(),
                'owner':cell[0],'local':cell[1],
                'source_span':sorted(info['source_spans'])[0],
                **{k:sorted(v) for k,v in info.items()}}
                for cell,info in sorted(collapse_evidence.items())
                if any(value[0]=='function' for value in values[cell]) or info['affected_callsites']],
            'memory_events_without_callable_flow':[{'owner':cell[0],'local':cell[1],
                'reasons':sorted(info['reasons']),'source_spans':sorted(info['source_spans'])}
                for cell,info in sorted(collapse_evidence.items())
                if not any(value[0]=='function' for value in values[cell]) and not info['affected_callsites']],
            'analysis_class':'flow-insensitive context-insensitive inclusion prototype',
            'sites':[{'owner':owner,'block':block,'targets':sorted(targets),**receiver_reports.get((owner,block),{})} for (owner,block),targets in sorted(sites.items())],
            'unsupported_operations':[{'instance':owner,'reason':reason} for owner,reason in sorted(losses)],
            'precision_policy':'Allocation-local collapse for exported byte/union/reinterpret/index operations; remaining unsupported operations reject acceptance'}
