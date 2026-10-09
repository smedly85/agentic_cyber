"""Adjudicate unchanged expectations; fixture labels never supply graph edges."""
import hashlib
import json
import re
from pathlib import Path
from collections import Counter
from security.semantic_callgraph.rust_identity import strip_generic_arguments
from security.semantic_callgraph.rust_llvm_svf_v1.validate import adjudicate,evaluate_case
from security.semantic_callgraph.rust_rupta_v1.adapter import parse,finalize,normalized
from security.semantic_callgraph.rust_rupta_v1.validate import inventory
from security.semantic_callgraph.rust_rupta_v1.probe import ROOT,BASE,HERE

def base_name(name):
    return strip_generic_arguments(name)

def scope_at(source,line):
    """Fixture-only lexical scope mapping, backed by frozen declaration lines.

    These fixtures contain no braces in the relevant impl/module headers.
    Never used to analyze calls or to map historical functions.
    """
    scopes=[]
    impl_index=0
    for m in re.finditer(r'\b(impl\s+[^\n{]+|(?:pub\s+)?mod\s+\w+)\s*\{',source):
        is_impl=m[1].startswith('impl')
        name='{impl#'+str(impl_index)+'}' if is_impl else m[1].split()[-1]
        if is_impl: impl_index+=1
        depth=1; end=m.end()
        while end<len(source) and depth:
            depth+=(source[end]=='{')-(source[end]=='}'); end+=1
        start_line=source[:m.start()].count('\n')+1
        end_line=source[:end].count('\n')+1
        if start_line<=line<=end_line: scopes.append(name)
    return scopes

def mapping(program,raw):
    if program['kind']=='controlled': specs=program['functions']
    else:
        specs={label:{'file':s['source_file'],'line':s['source_span']['start_line'],
                      'name':s.get('qualified_name',s['function_name']).split('::')[-1],
                      'qualified':s.get('qualified_name',s['function_name'])}
               for label,s in program['pair']['rust_functions'].items()}
    crates={c.source:c.name for c in program['crates']}
    by_label={}; evidence={}
    for label,spec in specs.items():
        source=(ROOT/spec['file']).read_text()
        scope=scope_at(source,spec['line'])
        suffix='::'.join([*scope,spec['name']])
        if '{closure#' in spec['name']: suffix=spec.get('qualified',label)
        if label=='uumain(outer)': suffix='uumain'
        if label=='uumain(inner)': suffix='uumain::uumain'
        prefix=crates[spec['file']]+'::'+suffix
        ids=[r['identity'] for r in raw['functions'] if base_name(r['identity'])==prefix]
        by_label[label]=ids
        evidence[label]={'frozen_spec':spec,'rupta_base_name':prefix,'instances':ids}
    label_of={i:k for k,v in by_label.items() for i in v}
    if len(label_of)!=sum(map(len,by_label.values())): raise ValueError('ambiguous fixture labels')
    for f in raw['functions']:
        crate=f['identity'].split('::')[0]
        f['source_file']=next((src for src,c in crates.items() if c==crate),
                              'rust_std/'+crate if crate in ('core','std','alloc') else '')
        f['source_file_basis']='controlled crate/source inventory; not exported source span'
    return by_label,label_of,evidence

def sites(program,raw,by_label,label_of):
    specs=program.get('indirect_sites',[]) if program['kind']=='controlled' else [
        {'id':s['callsite_id'],'caller':s['owner'],'line':s['source_identity']['line'],
         'expected':s['expected_targets']} for s in program['pair']['expected_rust_indirect_targets']]
    result=[]
    for spec in specs:
        caller=spec['caller']
        if isinstance(caller,str): callers=by_label.get(caller,[])
        else:
            # The one frozen library selector is alloc::boxed::call_mut.
            assert caller=={'file':'rust_std/library/alloc/src/boxed.rs','name':'call_mut'}
            callers=[f['identity'] for f in raw['functions'] if base_name(f['identity']).startswith('alloc::boxed::') and base_name(f['identity']).endswith('::call_mut')]
        resolved=[e for e in raw['call_edges'] if e['caller'] in callers and e['edge_type']=='indirect_resolved']
        unresolved=[u for u in raw['unresolved_indirect_callsites'] if u['caller'] in callers]
        locs={(e['caller'],e['callsite']['mir_location']) for e in resolved+unresolved}
        # No source-line spans in export: accept only the unique indirect site
        # in the independently mapped owner, never select by expected target.
        if len(locs)!=1:
            row={'status':'site_mapping_unavailable','passed':False,'actual':None,'missing':None,'unexpected':None,'expected':spec['expected']}
        else:
            row=adjudicate(spec['expected'],resolved,unresolved,label_of,expect_unresolved=spec.get('expect_unresolved',False))
        row.update(id=spec['id'],source_line=spec.get('line'),mir_sites=sorted(locs),mapping_policy='unique indirect MIR site in source-mapped owner')
        if spec.get('expect_unresolved'):
            row['explicit_upstream_unresolved_record']=False
            row['evidence_origin']='pointer call in dumped MIR without DOT target'
        result.append(row)
    return result

def evaluate(program,raw):
    by_label,label_of,evidence=mapping(program,raw)
    site_results=sites(program,raw,by_label,label_of)
    failures=[f"site:{s['id']}:{s['status']}" for s in site_results if not s['passed']]
    cases=[]; graphs={}
    if program['kind']=='controlled':
        for label,count in program.get('instance_counts',{}).items():
            if len(by_label[label])!=count: failures.append(f'instance_count:{label}')
        rows={f['identity']:f for f in raw['functions']}
        for case in program['cases']:
            # Reuse the prior exact-depth, path, unreachability and edge validator.
            r=evaluate_case(case,raw,by_label,label_of,rows,set(program['application_files']),{'instrument':'RUPTA','mode':raw['analysis_mode']})
            g=r.pop('graph',None)
            if g:
                g.update(analysis_backend='rupta_mir',pointer_analysis=raw['analysis_mode'],analysis_status='partial_export',unresolved_inventory_complete=False)
                graphs[case['id']]=g
            cases.append(r)
            failures += [f"case:{case['id']}:{f}" for f in r['failures']]
    else:
        pair=program['pair']; entries=by_label['entry']
        if len(entries)!=1: failures.append('entry_not_unique')
        else:
            g=finalize(raw,entries[0]); graphs['entry']=g
            nodes={f['identity']:f for f in g['functions']}
            scope={p['Rust'] for p in pair['application_correspondence'] if p['inside_entry_scope']}
            expected={(e['caller'],e['callee']) for e in pair['expected_rust_edges']}
            for s in pair['expected_rust_indirect_targets']: expected|={(s['owner'],t) for t in s['expected_targets']}
            actual={(label_of.get(e['caller']),label_of.get(e['callee'])) for e in raw['call_edges']
                    if label_of.get(e['caller']) in scope and label_of.get(e['callee']) in scope and nodes[e['caller']]['reachable_from_entry']}
            failures += [f'missing_relation:{a}->{b}' for a,b in sorted(expected-actual)]
            failures += [f'extra_relation:{a}->{b}' for a,b in sorted(actual-expected)]
            targets=[]
            for spec in pair['rust_target_identity']:
                label=spec['function_name']; reachable=[nodes[i] for i in by_label[label] if nodes[i]['reachable_from_entry']]
                depth=min((n['raw_call_depth'] for n in reachable),default=None)
                targets.append({'function':label,'observed_depth':depth,'expected_depth':None})
                if depth is None: failures.append('target_unreachable:'+label)
            cases=[{'id':'entry','targets':targets,'expected_relations':sorted(expected),'observed_relations':sorted(actual),
                    'reachable_functions':sum(n['reachable_from_entry'] for n in nodes.values()),
                    'maximum_finite_shortest_path_depth':max(n['raw_call_depth'] for n in nodes.values() if n['raw_call_depth'] is not None)}]
    gaps=[]
    if raw['drop_terminators']: gaps.append('drop_terminators_not_exported_as_calls')
    if raw['omitted_static_calls']: gaps.append('static_MIR_calls_without_exported_edge')
    if raw['unresolved_indirect_callsites']: gaps.append('unresolved_inventory_requires_MIR_inference')
    return {'program':program['id'],'required_expectations_passed':not failures,'failures':failures,
            'status':'expectation_failure' if failures else ('required_expectations_match_with_scope_gaps' if gaps else 'required_expectations_match'),
            'scope_gaps':gaps,'whole_graph_accepted':False,'sites':site_results,'cases':cases,
            'nodes':len(raw['functions']),'dot_nodes':sum(f['present_in_dot'] for f in raw['functions']),
            'edges':len(raw['call_edges']),'unresolved_observed':len(raw['unresolved_indirect_callsites']),
            'unresolved_total':None,'omitted_static_calls':raw['omitted_static_calls'],
            'drop_terminators':raw['drop_terminators'],'missing_body_nodes':[f['identity'] for f in raw['functions'] if f['body_available'] is False],
            'mapping':evidence},graphs

def merge(raws):
    # Supplemental library has four independent entries; preserve per-entry
    # graphs for BFS below. Union is used only for program-wide site inventory.
    raw=dict(raws[0])
    for key in ('functions','call_edges','unresolved_indirect_callsites','omitted_static_calls','drop_terminators','unknown_edges'):
        vals={json.dumps(v,sort_keys=True):v for r in raws for v in r[key]}
        raw[key]=[vals[k] for k in sorted(vals)]
    raw['body_inventory']={k:v for r in raws for k,v in r['body_inventory'].items()}
    return raw

def main():
    results={}; determinism={}; graph_determinism={}
    for p in inventory():
        for mode in ('ander','cs'):
            norms=[]
            for repeat in (1,2):
                folder=BASE/'validation'/f'run-{repeat}'/p['id']/mode
                outputs=sorted(folder.glob('*/graph.dot'))
                raws=[]; resources=[]
                for output in outputs:
                    command=json.loads((output.parent/'command.json').read_text())
                    if command['status']!='completed': raise ValueError('incomplete run')
                    raw=parse(output.parent,mode)
                    if raw['unknown_edges']: raise ValueError('unknown edge kinds')
                    raws.append(raw)
                    text=(output.parent/'resources.txt').read_text()
                    rss=re.search(r'Maximum resident set size \(kbytes\): (\d+)',text)
                    resources.append({'entry':output.parent.name,'wall_seconds':command['wall_seconds'],
                                      'peak_rss_kib':int(rss[1]) if rss else None,'command_record':str((output.parent/'command.json').relative_to(ROOT))})
                    (output.parent/'normalized.json').write_text(normalized(raw))
                expected=4 if p['id']=='supplement' else 1
                if len(raws)!=expected: raise ValueError('missing analysis outputs: '+p['id'])
                raw=merge(raws) if len(raws)>1 else raws[0]
                norms.append(normalized(raw))
                result,graphs=evaluate(p,raw)
                if p['id']=='supplement':
                    # Each supplemental root was analyzed independently. Never
                    # use another entry's edges to supply a BFS path.
                    separate_cases=[]; separate_graphs={}; case_failures=[]
                    for output,one_raw in zip(outputs,raws):
                        sub={**p,'cases':[c for c in p['cases'] if c['entry']==output.parent.name],
                             'indirect_sites':[s for s in p['indirect_sites'] if output.parent.name=='entry_unresolved_indirect']}
                        r,g=evaluate(sub,one_raw)
                        separate_cases+=r['cases']; separate_graphs.update(g)
                        case_failures+=r['failures']
                    result['cases']=separate_cases
                    result['failures']=case_failures
                    result['required_expectations_passed']=not case_failures
                    graphs=separate_graphs
                result.update(mode=mode,repeat=repeat,resources=resources)
                for name,g in graphs.items(): (folder/(name+'.graph.json')).write_text(json.dumps(g,sort_keys=True,indent=2)+'\n')
                results[f'{repeat}|{mode}|{p["id"]}']=result
                (folder/'evaluation.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
            determinism[f'{mode}|{p["id"]}']=norms[0]==norms[1]
            first=BASE/'validation/run-1'/p['id']/mode
            second=BASE/'validation/run-2'/p['id']/mode
            graph_determinism[f'{mode}|{p["id"]}']=all((second/g.name).read_bytes()==g.read_bytes() for g in first.glob('*.graph.json'))
            print(p['id'],mode,results[f'1|{mode}|{p["id"]}']['status'],determinism[f'{mode}|{p["id"]}'],flush=True)
    data={'schema_version':1,'decision':'STOP','historical_measurement_authorized':False,'results':results,'determinism':determinism,'finalized_graph_determinism':graph_determinism}
    (BASE/'evaluated.json').write_text(json.dumps(data,sort_keys=True,indent=2)+'\n')

if __name__=='__main__': main()
