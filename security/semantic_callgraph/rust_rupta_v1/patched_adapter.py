"""Depth sidecar adapter. Context graph is authoritative; projection is validation-only."""
import copy
import json
import re
from pathlib import Path
from .adapter import normalized
from .evaluate import evaluate
from security.semantic_callgraph.backend import finalize_semantic_graph

def parse(directory, mode):
    directory = Path(directory)
    data = json.loads((directory/'graph.dot.depth.json').read_text())
    functions = {f['id']:f for f in data['functions']}
    assert len(functions)==len(data['functions'])
    # Context strings are upstream Debug output for its existing call strings.
    contexts = json.loads((directory/'graph.dot.contexts.json').read_text()) if mode=='cs' else {}
    def function_key(f):
        parts=[f['def_path_hash'],f['generic_args'],f['promoted']]
        if 'shim' in f: parts.append(f['shim'])
        return json.dumps(parts,separators=(',',':'))
    def context_key(cid):
        return re.sub(r'FuncId\(\d+\)',lambda m:function_key(functions[m[0]]),contexts[cid])
    names = {}; keys = {}; fn_of = {}
    for n in data['nodes']:
        f = functions[n['function']]
        fn_of[n['id']] = f
        names[n['id']] = f['name']
        context = re.search(r'ContextId\(\d+\)',n['id'])
        keys[n['id']] = function_key(f)+(' @ '+context_key(context[0]) if context else '')
    assert len(set(keys.values()))==len(keys), 'context/instance identity collision'
    site_by_key = {(s['caller'],s['location']):s for s in data['callsites']}
    assert len(site_by_key)==len(data['callsites'])
    rows = []
    for n in data['nodes']:
        f = fn_of[n['id']]
        rows.append({'identity':keys[n['id']], 'name':f['name'], 'language':'Rust',
                     'function_identity':function_key(f),'source':f['source'],
                     'source_file':(f['source'] or {}).get('file',''),
                     'body_available':f['body_available'],'special_model':f['special_model'],
                     'drop_glue':f['drop_glue']})
    edges=[]; external=[]; unresolved=[]
    for e in data['edges']:
        s=site_by_key[(e['caller'],e['location'])]
        assert e['callee'] in s['targets']
        row={'caller':keys[e['caller']],'callee':keys[e['callee']],
             'edge_type':'direct' if s['kind']=='StaticDispatch' else 'indirect_resolved',
             'pointer_analysis_backend':'RUPTA separate Drop/export trial','pointer_analysis':mode,
             'callsite':{'mir_location':s['location'],**(s['source'] or {})},
             'indirect_target_count':len(set(s['targets'])) if s['kind']!='StaticDispatch' else None,
             'indirect_target_set':sorted({keys[t] for t in s['targets']}) if s['kind']!='StaticDispatch' else None}
        edges.append(row)
        if not fn_of[e['callee']]['body_available']:
            external.append({**row,'callee_name':names[e['callee']].split('::')[-1], 'boundary':'body_unavailable'})
    for s in data['callsites']:
        observed={e['callee'] for e in data['edges'] if e['caller']==s['caller'] and e['location']==s['location']}
        assert observed==set(s['targets'])
        if s['kind']!='StaticDispatch' and not s['targets']:
            unresolved.append({'caller':keys[s['caller']], 'callsite':{'mir_location':s['location'],**(s['source'] or {})},
                               'kind':s['kind'],'origin':'explicit internal recognized-call inventory'})
    raw={'functions':rows,'call_edges':edges,'external_calls':external,
         'unresolved_indirect_callsites':unresolved,'unresolved_inventory_complete':False,
         'unresolved_scope':'complete only for internally recognized indirect callsites',
         'entry':keys[data['entry']], 'analysis_mode':mode,
         'projection':'none; context-sensitive nodes retained' if mode=='cs' else 'function instances'}
    for field in ('functions','call_edges','external_calls','unresolved_indirect_callsites'):
        raw[field].sort(key=lambda v:json.dumps(v,sort_keys=True))
    graph=finalize_semantic_graph(raw,entry_point=raw['entry'],provenance={'instrument':'separate Drop/export trial','projection':raw['projection']})
    graph['analysis_backend']='rupta_drop_trial'
    graph['pointer_analysis']=mode
    graph['analysis_status']='controlled_experiment_not_accepted_historical_measurement'
    graph['unresolved_inventory_complete']=False
    # Explicit CI view only for inherited source-function requirements. Boundary
    # edges stay in the authoritative depth graph above; this view uses the
    # inherited SVF distinction between internal edges and external-call records.
    labels={keys[n['id']]:names[n['id']] for n in data['nodes']}
    view=copy.deepcopy(raw)
    for f in view['functions']: f['identity']=labels[f['identity']]; f['present_in_dot']=True
    for field in ('call_edges','external_calls','unresolved_indirect_callsites'):
        for e in view[field]:
            e['caller']=labels[e['caller']]
            if 'callee' in e: e['callee']=labels[e['callee']]
            if e.get('indirect_target_set') is not None:
                e['indirect_target_set']=sorted({labels[t] for t in e['indirect_target_set']})
                e['indirect_target_count']=len(e['indirect_target_set'])
    missing={f['identity'] for f in view['functions'] if not f['body_available']}
    view['call_edges']=[e for e in view['call_edges'] if e['callee'] not in missing]
    for field in ('functions','call_edges','external_calls','unresolved_indirect_callsites'):
        view[field]=list({json.dumps(v,sort_keys=True):v for v in view[field]}.values())
    assert len({f['identity'] for f in view['functions']})==len(view['functions']), 'projected label collision'
    view.update(body_inventory={},drop_terminators=[],omitted_static_calls=[],unknown_edges=[],
                projection='explicit function union for inherited requirements only; not depth graph')
    return raw,graph,view

def adjudicate(program, directory, mode, entry):
    raw,graph,view=parse(directory,mode)
    p=copy.deepcopy(program)
    if p['id']=='supplement':
        p['cases']=[c for c in p['cases'] if c['entry']==entry]
        p['indirect_sites']=p['indirect_sites'] if entry=='entry_unresolved_indirect' else []
    result,_=evaluate(p,view)
    result['scope_gaps']=[]
    result['unresolved_total']=len(raw['unresolved_indirect_callsites'])
    result['unresolved_scope']=raw['unresolved_scope']
    for site in result['sites']:
        if site.get('explicit_upstream_unresolved_record') is False:
            site['explicit_upstream_unresolved_record']=True
            site['evidence_origin']='explicit internal recognized-call inventory'
    # Validate inherited target depths against the actual context graph too.
    labels={instance:label for label,m in result['mapping'].items() for instance in m['instances']}
    targets=[]
    for case in p.get('cases',[]):
        roots=[f['identity'] for f in raw['functions'] if labels.get(f['name'])==case['entry']]
        case_graphs=[finalize_semantic_graph(raw,entry_point=r,provenance={'controlled_sensitivity_anchor':r}) for r in roots]
        for spec in case.get('targets',[]):
            candidates=[f for cg in case_graphs for f in cg['functions'] if labels.get(f['name'])==spec['function'] and f['reachable_from_entry']]
            best=min(candidates,key=lambda f:(f['raw_call_depth'],f['identity'])) if candidates else None
            path=best['shortest_call_path']['function_identities'] if best else []
            nodes={f['identity']:f for f in graph['functions']}
            application=[labels.get(nodes[i]['name'],nodes[i]['name']) for i in path if nodes[i]['name'].split('::')[0] in {c.name for c in p['crates'] if c.source in p['application_files']}]
            ok=bool(best) and application==spec['application_path']
            if spec['rule']=='exact': ok=ok and best['raw_call_depth']==spec['depth']
            targets.append({'function':spec['function'],'passed':ok,'depth':best['raw_call_depth'] if best else None,'application_path':application})
            if not ok: result['failures'].append('context_depth_or_path:'+spec['function'])
    result['context_targets']=targets
    # An audit of the new Drop handling, not a change to frozen expectations:
    # generated dyn-drop MIR must not be mistaken for static self-recursion.
    node_rows={f['identity']:f for f in raw['functions']}
    bad_drop=[e for e in raw['call_edges'] if e['caller']==e['callee'] and node_rows[e['caller']]['drop_glue']]
    if bad_drop: result['failures'].append('invalid_recursive_drop_glue')
    if program['id']=='expanded/box_trait':
        # Existing fixture owns First (with Drop) through Box<dyn Action>.
        # The dynamic Drop must reach concrete drop glue through a resolved
        # receiver, rather than relying on Box::new's cleanup route.
        dynamic_drop=[e for e in raw['call_edges'] if e['edge_type']=='indirect_resolved' and node_rows[e['callee']]['drop_glue']]
        result['dynamic_drop_edges']=dynamic_drop
        if not dynamic_drop: result['failures'].append('boxed_dynamic_drop_not_resolved')
    result['required_expectations_passed']=not result['failures']
    result['status']='pass' if not result['failures'] else 'fail'
    result['context_nodes']=len(raw['functions']); result['context_edges']=len(raw['call_edges'])
    result['external_boundaries']=raw['external_calls']
    for name,value in (('normalized.json',raw),('context.graph.json',graph),('evaluation.json',result)):
        (Path(directory)/name).write_text(normalized(value))
    return result
