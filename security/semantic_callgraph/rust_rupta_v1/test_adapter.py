import json
from pathlib import Path
import pytest
from security.semantic_callgraph.rust_rupta_v1.adapter import read_mir,parse,finalize,normalized

def fixture(tmp_path,dot,mir,dynamic='#Fnptr calls:\n'):
    for name,text in [('graph.dot',dot),('mir.txt',mir),('dynamic.txt',dynamic)]: (tmp_path/name).write_text(text)
    return parse(tmp_path,'ander')

def test_pointer_cast_is_not_call_and_ctfe_is_not_runtime():
    text='''[FuncId(0) - "crate::main"]
fn main() -> () {
    bb0: {
        _1 = target as fn(u32) -> u32 (PointerCoercion(ReifyFnPointer));
        _0 = move _1(const 1_u32) -> [return: bb1, unwind continue];
    }
}
// MIR FOR CTFE
fn main() -> () {
    bb0: {
        _0 = other() -> bb1;
    }
}
'''
    calls=read_mir(text)['crate::main']['calls']
    assert list(calls)==['bb0[1]']
    assert calls['bb0[1]']['operand_kind']=='pointer'

def test_diverging_static_call():
    text='[FuncId(0) - "crate::main"]\nfn main() -> () {\n    bb0: {\n        _0 = panic() -> bb1;\n    }\n}\n'
    assert read_mir(text)['crate::main']['calls']['bb0[0]']['operand_kind']=='static'

def test_unresolved_pointer_is_not_zero_complete(tmp_path):
    raw=fixture(tmp_path,'digraph {\n}\n','[FuncId(0) - "crate::main"]\nfn main() -> () {\n    bb0: {\n        _0 = move _1() -> [return: bb1, unwind continue];\n    }\n}\n')
    assert len(raw['unresolved_indirect_callsites'])==1
    assert not raw['unresolved_inventory_complete']
    assert raw['call_edges']==[]
    assert finalize(raw,'crate::main')['functions'][0]['raw_call_depth']==0

def test_duplicate_names_rejected(tmp_path):
    with pytest.raises(ValueError,match='colliding DOT'):
        fixture(tmp_path,'digraph {\n    0 [ label = "x" ]\n    1 [ label = "x" ]\n}\n','')

def test_unknown_edge_blocks_finalization(tmp_path):
    raw=fixture(tmp_path,'digraph {\n    0 [ label = "a" ]\n    1 [ label = "b" ]\n    0 -> 1 [ label = "bb0[0]" ]\n}\n','')
    with pytest.raises(ValueError,match='unknown edge'): finalize(raw,'a')

def test_bfs_recursion_and_shortcut():
    raw={'functions':[{'identity':x,'name':x} for x in 'abcd'],
         'call_edges':[{'caller':a,'callee':b,'edge_type':'direct','pointer_analysis_backend':'RUPTA'} for a,b in [('a','b'),('b','b'),('b','c'),('a','c'),('c','d')]],
         'unknown_edges':[],'analysis_mode':'ander','projection':'test'}
    graph=finalize(raw,'a')
    assert {f['identity']:f['raw_call_depth'] for f in graph['functions']}==dict(a=0,b=1,c=1,d=2)
