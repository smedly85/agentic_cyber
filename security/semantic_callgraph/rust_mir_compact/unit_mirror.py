"""Run existing Rust unit contracts with a gated reference/candidate mirror."""
import copy, os, sys
from common import ROOT,HERE,OUT,REFERENCE,REFERENCE_SHA,sha,write,digest
sys.path[:0]=[str(ROOT),str(ROOT/'security/semantic_callgraph/cross_language_calibration')]
import pytest
from runtime_provenance import pre_measurement_gate,expand
from common import read
from security.semantic_callgraph.rust_mir.inclusion import analyze as reference
from security.semantic_callgraph.rust_mir_compact.inclusion import analyze as candidate

calls=[];reports=[]
def invoke(function,probe,kwargs):
    state={}
    def capture(frame,event,arg):
        if event=='return' and frame.f_code is function.__code__:
            local=frame.f_locals
            state.update(cells=[[k,sorted(v)] for k,v in sorted(local['values'].items())],
                         collapsed=sorted(local['collapsed']),
                         cells_by_local=[[k,sorted(v)] for k,v in sorted(local['cells_by_local'].items())],
                         completed_sweeps=local.get('_',-1)+1)
    sys.setprofile(capture)
    try:
        gate=pre_measurement_gate('Rust',dict(os.environ),[])
        result=function(probe,**kwargs)
    finally:sys.setprofile(None)
    return result,state,gate

def mirror(probe,**kwargs):
    index=len(calls);folder=OUT/'unit-mirror'/str(index);folder.mkdir(parents=True,exist_ok=False)
    write(folder/'input.json',probe)
    before=copy.deepcopy(kwargs)
    a,sa,ga=invoke(reference,probe,before)
    b,sb,gb=invoke(candidate,probe,kwargs)
    write(folder/'reference.json',{'result':a,'state':sa,'options_after':before})
    write(folder/'candidate.json',{'result':b,'state':sb,'options_after':kwargs})
    write(folder/'gates.json',{'status':'PASS','reference':ga,'candidate':gb})
    exact=digest([a,sa,before])==digest([b,sb,kwargs])
    calls.append({'index':index,'exact':exact,'input_sha256':sha(folder/'input.json')})
    write(OUT/'unit_mirror_calls.json',calls)
    assert exact,('SCIENTIFIC MISMATCH in existing unit contract',index)
    return b

class Mirror:
    def pytest_collection_modifyitems(self,items):
        for item in items:
            module=item.module
            if getattr(module,'analyze',None) is reference:module.analyze=mirror
    def pytest_runtest_logreport(self,report):
        if report.when=='call' or report.failed:reports.append({'test':report.nodeid,'when':report.when,'outcome':report.outcome})

def main():
    assert sha(REFERENCE)==REFERENCE_SHA
    policy=read(ROOT/'security/semantic_callgraph/cross_language_calibration/fixture_manifest.json')['semantic_extraction_configuration']['Rust']['driver']['environment']
    os.environ.update({k:expand(v) for k,v in policy.items()})
    tests=['tests/test_rust_mir'+suffix+'.py' for suffix in ('','_bodies','_cast_contracts','_core','_stage')]
    code=pytest.main(['-q',*tests,'-o','cache_dir='+str(OUT/'pytest-cache'),'--basetemp='+str(OUT/'pytest-temp'),
                     '--junitxml='+str(OUT/'unit_mirror.junit.xml')],plugins=[Mirror()])
    write(OUT/'unit_mirror_summary.json',{'status':'PASS' if code==0 and all(r['exact'] for r in calls) else 'FAIL',
          'pytest_exit_code':int(code),'mirrored_analyzer_calls':len(calls),'reports':reports,
          'candidate_sha256':sha(HERE/'inclusion.py'),'reference_sha256':REFERENCE_SHA,
          'scope':'Existing unit-test module aliases use the mirror in memory; frozen source files and backend module are unchanged.'})
    raise SystemExit(code)

if __name__=='__main__':main()
