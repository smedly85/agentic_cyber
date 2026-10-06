"""Solver-only performance passes, permitted only after complete exact equality."""
import argparse, os, pathlib, resource, subprocess, sys, time
from common import ROOT,HERE,OUT,REFERENCE,REFERENCE_SHA,read,sha,write,digest
sys.path[:0]=[str(ROOT),str(ROOT/'security/semantic_callgraph/cross_language_calibration')]
from runtime_provenance import pre_measurement_gate,expand
from security.semantic_callgraph.rust_mir.inclusion import analyze as reference
from security.semantic_callgraph.rust_mir_performance_v2.inclusion import analyze as candidate
from reference_counters import make_reference

def worker(mode):
    passed=read(OUT/'equality_summary.json')
    assert passed['status']=='PASS' and passed['candidate_sha256']==sha(HERE/'inclusion.py')
    units=read(OUT/'unit_mirror_summary.json');assert units['status']=='PASS' and units['candidate_sha256']==sha(HERE/'inclusion.py')
    assert sha(REFERENCE)==REFERENCE_SHA
    folder=OUT/'performance'/mode;folder.mkdir(parents=True,exist_ok=False)
    rows=[]
    for case in read(OUT/'input_inventory.json')+read(OUT/'synthetic_input_inventory.json'):
        p=ROOT/case['input_path'];assert sha(p)==case['input_sha256'];data=read(p)
        raw=data['api'] if case['wrapped'] else data
        statistics={};capture={}
        if mode=='reference-counted':
            function,statistics=make_reference()
            def sample(frame,event,arg):
                if event=='return' and frame.f_code is function.__code__:
                    capture.update(points_to_cells=len(frame.f_locals['values']),
                                   points_to_facts=sum(map(len,frame.f_locals['values'].values())))
            sys.setprofile(sample)
        else:function=reference if mode=='reference' else candidate
        kwargs={'roots':[case['root']]}
        if mode=='candidate':kwargs['statistics']=statistics
        directory=folder/case['id'];directory.mkdir(parents=True)
        write(directory/'launch.json',{'mode':mode,'input':case,'environment':dict(os.environ),
              'options':{'roots':[case['root']]},'reference_sha256':REFERENCE_SHA,'candidate_sha256':sha(HERE/'inclusion.py'),
              'observer_source_sha256':sha(HERE/'reference_counters.py') if mode=='reference-counted' else None})
        try:
            gate=pre_measurement_gate('Rust',dict(os.environ),[])
            start=time.monotonic();cpu=time.process_time()
            flow=function(raw,**kwargs)
            elapsed=time.monotonic()-start;cpu=time.process_time()-cpu
        finally:sys.setprofile(None)
        write(directory/'gate.json',{'status':'PASS','rows':gate,'immediately_before_call':True})
        write(directory/'inclusion.json',flow)
        scientific_hash=sha(directory/'inclusion.json')
        if mode!='reference':
            expected=sha(OUT/'performance/reference'/case['id']/'inclusion.json')
            assert scientific_hash==expected,('Performance pass scientific mismatch',mode,case['id'])
        row={'id':case['id'],'wall_seconds':elapsed,'cpu_seconds':cpu,
             'process_cumulative_peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
             'scientific_sha256':scientific_hash,'converged':flow['converged'],
             'operation_counts':dict(statistics),'reference_return_state_counts':capture,
             'timing_scope':'Observed counter pass; excluded from baseline speed comparison' if mode=='reference-counted' else 'Solver only; excludes input loading, gate, serialization and extraction'}
        rows.append(row);write(folder/'results.json',rows)
        print(mode,case['id'],round(elapsed,4),'seconds',flush=True)
    write(folder/'complete.json',{'status':'PASS','cases':len(rows),'wall_seconds':sum(r['wall_seconds'] for r in rows),
          'cpu_seconds':sum(r['cpu_seconds'] for r in rows),'peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})

def main():
    policy=read(ROOT/'security/semantic_callgraph/cross_language_calibration/fixture_manifest.json')['semantic_extraction_configuration']['Rust']['driver']['environment']
    env=dict(os.environ);env.update({k:expand(v) for k,v in policy.items()})
    for mode in ('reference','candidate','reference-counted'):
        subprocess.run([sys.executable,str(pathlib.Path(__file__).resolve()),'--worker',mode],cwd=ROOT,env=env,check=True)
    ref=read(OUT/'performance/reference/complete.json');opt=read(OUT/'performance/candidate/complete.json')
    write(OUT/'performance_summary.json',{'status':'PASS','reference':ref,'candidate':opt,
          'wall_speedup':ref['wall_seconds']/opt['wall_seconds'],'cpu_speedup':ref['cpu_seconds']/opt['cpu_seconds'],
          'candidate_to_reference_peak_RSS_ratio':opt['peak_RSS_KiB']/ref['peak_RSS_KiB'],
          'operation_counter_pass_scientific_equality':True,
          'memory_scope':'Independent worker peak across the complete controlled/calibration suite, not per-case peak. Historical contexts use independent per-context workers.',
          'reference_counter_overhead_excluded_from_speedup':True,'historical_depths_accepted':0})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',choices=['reference','candidate','reference-counted']);a=p.parse_args()
    worker(a.worker) if a.worker else main()
