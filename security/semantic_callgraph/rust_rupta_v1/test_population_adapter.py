import json
from pathlib import Path
import tempfile
import unittest
from security.semantic_callgraph.rust_rupta_v1.population_adapter import parse
from security.semantic_callgraph.rust_rupta_v1.utility_scope import project

class HistoricalExportTests(unittest.TestCase):
    def data(self):
        def fn(i,key,name):
            return dict(id=f'FuncId({i})',def_path_hash=key,generic_args='[]',promoted='None',shim='None',
                        name=name,source=None,body_available=True,special_model=False,drop_glue=False)
        fs=[fn(0,'main','utility::main'),fn(1,'same','dep::method<T>'),fn(2,'same','dep::method<T>')]
        return dict(functions=fs,nodes=[dict(id=f['id'],function=f['id']) for f in fs],entry=fs[0]['id'],
                    callsites=[dict(caller=fs[0]['id'],location='bb0[0]',kind='FnPtr',source=None,targets=[fs[1]['id'],fs[2]['id']])],
                    edges=[dict(caller=fs[0]['id'],callee=f['id'],location='bb0[0]') for f in fs[1:]])

    def test_equal_labels_and_export_text_never_merge_nodes_or_targets(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'graph.dot.depth.json').write_text(json.dumps(self.data()))
            raw,_,audit=parse(d,'ander')
        self.assertEqual(len(raw['functions']),3)
        self.assertEqual(len({f['identity'] for f in raw['functions']}),3)
        self.assertEqual(len({e['callee'] for e in raw['call_edges']}),2)
        self.assertEqual(len(audit['identity_text_collisions']),1)
        self.assertTrue(all(e['indirect_target_count']==2 for e in raw['call_edges']))

    def test_context_nodes_are_rejected_not_flattened(self):
        data=self.data();data['nodes'][0]['id']='CSFuncId(0, ContextId(0))'
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'graph.dot.depth.json').write_text(json.dumps(data))
            with self.assertRaises(AssertionError):parse(d,'ander')

    def test_collision_cannot_invent_dependency_mediated_callback(self):
        data=self.data();target=dict(data['functions'][0],id='FuncId(3)',def_path_hash='target',name='utility::target')
        data['functions'].append(target);data['nodes'].append(dict(id=target['id'],function=target['id']))
        data['callsites'][0]['targets']=['FuncId(1)']
        data['callsites'].append(dict(caller='FuncId(2)',location='bb0[0]',kind='StaticDispatch',source=None,targets=['FuncId(3)']))
        data['edges']=[data['edges'][0],dict(caller='FuncId(2)',callee='FuncId(3)',location='bb0[0]')]
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'graph.dot.depth.json').write_text(json.dumps(data));raw,_,_=parse(d,'ander')
        scoped=project(raw,{f['identity'] for f in raw['functions'] if f['name'].startswith('utility::')})
        self.assertEqual(scoped['scoped_edges'],[])
        self.assertIsNone(next(f for f in scoped['functions'] if f['name']=='utility::target')['scoped_depth'])

if __name__=='__main__':unittest.main()
