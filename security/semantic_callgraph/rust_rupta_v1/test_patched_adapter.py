"""Small reporting checks; no additional Rust fixture corpus."""
import json
from security.semantic_callgraph.rust_rupta_v1.patched_adapter import parse

def test_contexts_unresolved_and_boundary(tmp_path):
    fs=[{'id':f'FuncId({i})','name':name,'def_id':str(i),'def_path_hash':str(i),
         'generic_args':'[]','promoted':'None','source':{'file':'input.rs','line':i+1},
         'body_available':i!=2,'special_model':False,'drop_glue':False}
        for i,name in enumerate(('input::main','input::callback_owner','input::foreign'))]
    nodes=[{'id':f'CSFuncId {{ cid: ContextId({ctx}), func_id: FuncId({f}) }}','function':f'FuncId({f})'}
           for ctx,f in ((0,0),(1,1),(2,1),(1,2))]
    a,b,c,d=[n['id'] for n in nodes]
    sites=[{'caller':a,'location':'bb0[0]','kind':'StaticDispatch','source':{'line':10},'targets':[b]},
           {'caller':b,'location':'bb1[0]','kind':'StaticDispatch','source':{'line':11},'targets':[d]},
           {'caller':b,'location':'bb2[0]','kind':'FnPtr','source':{'line':37},'targets':[]},
           {'caller':c,'location':'bb2[0]','kind':'FnPtr','source':{'line':37},'targets':[]}]
    data={'entry':a,'functions':fs,'nodes':nodes,'callsites':sites,
          'edges':[{'caller':a,'callee':b,'location':'bb0[0]'},{'caller':b,'callee':d,'location':'bb1[0]'}]}
    (tmp_path/'graph.dot.depth.json').write_text(json.dumps(data))
    (tmp_path/'graph.dot.contexts.json').write_text(json.dumps({'ContextId(0)':'[]','ContextId(1)':'[FuncId(0), bb0[0]]','ContextId(2)':'[FuncId(0), bb3[0]]'}))
    raw,graph,view=parse(tmp_path,'cs')
    assert len(raw['functions'])==4 and len(view['functions'])==3
    assert len(raw['unresolved_indirect_callsites'])==2
    assert all(s['callsite']['line']==37 for s in raw['unresolved_indirect_callsites'])
    assert len(raw['call_edges'])==2 and len(view['call_edges'])==1
    assert raw['external_calls'][0]['callee_name']=='foreign'
    assert max(n['raw_call_depth'] for n in graph['functions'] if n['reachable_from_entry'])==2
    assert sum(not n['reachable_from_entry'] for n in graph['functions'])==1
