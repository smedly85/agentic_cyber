"""Rust-only compiler-evidenced MIR calls. No inclusion/points-to solver."""
from security.semantic_callgraph.backend import finalize_semantic_graph
IDENTITY='rust_mir_compiler_resolved_only_v1'

def target_of(site):
    if site['status'] in ('resolved_instance','drop_instance'):
        target=site.get('target')
        if not isinstance(target,str) or not target:raise ValueError('Resolved MIR call lacks concrete Instance')
        return target,'rustc_resolved_instance'
    value=site.get('callee_value',{})
    if site['status']=='unresolved_function_pointer' and set(value)=={'function'}:
        return value['function'],'concrete_function_constant_operand'
    return None,None

def build(raw,entry):
    rows={r['instance_identity']:r for r in raw['instances']}
    if len(rows)!=len(raw['instances']):raise ValueError('Duplicate compiler Instance identity')
    if entry not in rows:raise ValueError('Entry missing from compiler inventory')
    nodes={i:{'identity':i,'name':i,'instance_identity':i,'source_identity':r.get('source_identity',r.get('def_path',i)),
        'definition':{'source_span':r.get('source')},'crate':r.get('defining_crate'),'instance_kind':r.get('instance_kind'),
        'compiler_generated':r.get('compiler_generated',False),'body_availability':r.get('body_availability'),
        'compiler_inventory_present':True} for i,r in rows.items()}
    edges=[];calls=[];unresolved=[];boundaries=[]
    for owner,row in sorted(rows.items()):
        for site in row['calls']:
            target,evidence=target_of(site)
            location={'source_span':site.get('source',row.get('source')),'mir_block':site['block']}
            call={'caller':owner,'callsite':location,'mir_status':site['status'],'targets':[target] if target else [],
                'resolution_evidence':evidence}
            calls.append(call)
            if target is None:
                unresolved.append({**call,'reason':'No compiler-resolved concrete call target; no points-to inference',
                    'compiler_candidate_count_not_used':len(site.get('dyn_candidates',[]))})
                continue
            if target not in nodes:
                nodes[target]={'identity':target,'name':target,'instance_identity':target,'compiler_inventory_present':False,
                    'body_availability':'body not exported','definition':{'source_span':None},'crate':None}
            if nodes[target].get('body_availability') in ('missing MIR','external body','body not exported'):
                boundaries.append({**call,'callee':target,'body_availability':nodes[target]['body_availability']})
            indirect=evidence=='concrete_function_constant_operand'
            edges.append({'caller':owner,'callee':target,'callsite':location,'edge_type':'indirect_resolved' if indirect else 'direct',
                'indirect_target_set':[target] if indirect else None,'indirect_target_count':1 if indirect else None,
                'mir_kind':site['status'],'resolution_evidence':evidence,'pointer_analysis_backend':IDENTITY,'pointer_analysis':'none'})
    graph=finalize_semantic_graph({'functions':list(nodes.values()),'call_edges':edges,
        'unresolved_indirect_callsites':unresolved,'external_calls':boundaries},entry_point=entry,
        provenance={'backend':IDENTITY,'scope':'Rust-only retained compiler-resolved graph; not whole-program may-call completeness',
                    'points_to_analysis_used':False,'cross_language_comparability_claimed':False})
    graph['analysis_backend']=IDENTITY;graph['pointer_analysis']='none'
    reached={f['identity'] for f in graph['functions'] if f['reachable_from_entry']}
    graph['callsites']=calls
    graph['reachable_unresolved_callsites']=[s for s in unresolved if s['caller'] in reached]
    graph['reachable_body_boundaries']=[s for s in boundaries if s['caller'] in reached]
    graph['coverage']='incomplete_known_edge_graph' if graph['reachable_unresolved_callsites'] or graph['reachable_body_boundaries'] else 'no_observed_reachable_boundary'
    graph['metric_scope']='Shortest distances in retained known-edge graph; missing edges can change reachability, distances and maximum in either direction.'
    return graph
