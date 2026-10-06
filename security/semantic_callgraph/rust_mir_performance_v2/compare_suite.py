"""Gated, immutable-input reference/candidate equality; never historical depths."""
import argparse, datetime, json, os, pathlib, resource, subprocess, sys, time
from common import ROOT,HERE,OUT,REFERENCE,REFERENCE_SHA,read,sha,write,digest
sys.path[:0]=[str(ROOT),str(ROOT/'security/semantic_callgraph/cross_language_calibration')]
from runtime_provenance import pre_measurement_gate, expand
from security.semantic_callgraph.rust_mir.inclusion import analyze as reference
from security.semantic_callgraph.rust_mir_performance_v2.inclusion import analyze as candidate
from security.semantic_callgraph.rust_mir.graph import export_partial
from security.semantic_callgraph.backend import finalize_semantic_graph
EQUALITY=OUT/'equality-v1'

def worker(mode,run):
    cases=read(OUT/'input_inventory.json')
    extra=OUT/'synthetic_input_inventory.json'
    if extra.exists():cases+=read(extra)
    base=EQUALITY/run
    base.mkdir(parents=True,exist_ok=False)
    function=reference if mode=='reference' else candidate
    source=REFERENCE if mode=='reference' else HERE/'inclusion.py'
    records=[]
    for case in cases:
        folder=base/case['id'];folder.mkdir(parents=True)
        path=ROOT/case['input_path'];assert sha(path)==case['input_sha256']
        wrapped=read(path);raw=wrapped['api'] if case['wrapped'] else wrapped
        state={}
        def capture(frame,event,arg):
            if event=='return' and frame.f_code is function.__code__:
                local=frame.f_locals
                state.update(cells=[[k,sorted(v)] for k,v in sorted(local['values'].items())],
                             collapsed=sorted(local['collapsed']),
                             cells_by_local=[[k,sorted(v)] for k,v in sorted(local['cells_by_local'].items())],
                             completed_sweeps=local.get('_',-1)+1)
        stats={};cast_audit=[]
        kwargs={'roots':[case['root']],'cast_audit':cast_audit}
        if mode!='reference':kwargs['statistics']=stats
        write(folder/'launch.json',{'mode':mode,'run':run,'environment':dict(os.environ),'cwd':str(ROOT),
              'reference_sha256':sha(REFERENCE),'candidate_sha256':sha(HERE/'inclusion.py'),
              'executed_solver_sha256':sha(source),'input':case,'options':{'roots':[case['root']],'cast_audit':True},
              'purpose':'Controlled/calibration equality only; not historical measurement.'})
        sys.setprofile(capture)
        try:
            gate=pre_measurement_gate('Rust',dict(os.environ),[])
            start=time.monotonic();cpu=time.process_time()
            flow=function(raw,**kwargs)
            wall=time.monotonic()-start;cpu=time.process_time()-cpu
        except Exception as error:
            write(folder/'failure.json',{'error':str(error),'stage':'gate_or_solver'});raise
        finally:sys.setprofile(None)
        write(folder/'gate.json',{'status':'PASS','rows':gate,'immediately_before_call':True})
        write(folder/'inclusion.json',flow);write(folder/'points_to_state.json',state)
        write(folder/'cast_audit.json',cast_audit)
        assert state
        if case['group']!='synthetic':
            active=set(flow['active_instances'])
            exported=export_partial({'instances':[r for r in raw['instances'] if r['instance_identity'] in active]},flow)
            graph=finalize_semantic_graph(exported,entry_point=case['root'],provenance={'backend':'accepted_controlled_MIR_CORE','acceptance_evaluated_separately':True})
            write(folder/'exported.json',exported);write(folder/'normalized_graph.json',graph)
        write(folder/'observer_metrics.json',{'wall_seconds':wall,'cpu_seconds':cpu,'process_cumulative_peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              'operation_counts':stats,'timing_scope':'Equality run with read-only return-state profiler; not primary performance timing.'})
        reference_match=None
        if case['frozen_flow_path']:
            reference_match=digest(flow)==digest(read(ROOT/case['frozen_flow_path']))
            assert reference_match,('frozen inclusion mismatch',mode,case['id'])
        frozen_graph_match=None
        if case['group']=='calibration':
            frozen_graph_match=digest(graph)==digest(read(path.parent/'normalized_graph.json'))
            assert frozen_graph_match,('frozen calibration graph mismatch',mode,case['id'])
        scientific=['inclusion.json','points_to_state.json','cast_audit.json']
        if case['group']!='synthetic':scientific+=['exported.json','normalized_graph.json']
        record={'id':case['id'],'group':case['group'],'converged':flow['converged'],
                'scientific_hashes':{name:sha(folder/name) for name in scientific},
                'frozen_flow_matches':reference_match,'frozen_graph_matches':frozen_graph_match}
        if mode!='reference':
            original=next(r for r in read(EQUALITY/'reference/summary.json') if r['id']==case['id'])
            record['exact_reference_equality']=record['scientific_hashes']==original['scientific_hashes']
            write(folder/'comparison.json',record)
            assert record['exact_reference_equality'],('SCIENTIFIC MISMATCH',run,case['id'])
        records.append(record);write(base/'summary.json',records)
        print(run,case['id'],'PASS',flush=True)
    write(base/'complete.json',{'status':'PASS','cases':len(records),'mode':mode,'solver_sha256':sha(source)})

def launch_all():
    assert sha(REFERENCE)==REFERENCE_SHA
    assert (OUT/'preservation_before.json').exists()
    manifest=read(ROOT/'security/semantic_callgraph/cross_language_calibration/fixture_manifest.json')
    env=dict(os.environ);env.update({k:expand(v) for k,v in manifest['semantic_extraction_configuration']['Rust']['driver']['environment'].items()})
    for mode,run in [('reference','reference'),('candidate','candidate-1'),('candidate','candidate-2')]:
        subprocess.run([sys.executable,str(pathlib.Path(__file__).resolve()),'--worker',mode,'--run',run],cwd=ROOT,env=env,check=True)
    first=read(EQUALITY/'candidate-1/summary.json');second=read(EQUALITY/'candidate-2/summary.json')
    assert first==second,'Candidate nondeterminism'
    counts={g:sum(r['group']==g for r in first) for g in sorted({r['group'] for r in first})}
    assert counts['controlled']==31 and counts['memory']==12 and counts['calibration']==15
    frozen_pairs=ROOT/'security/semantic_callgraph/cross_language_calibration/pair_results.json'
    dynamic=ROOT/'security/semantic_callgraph/cross_language_calibration/dynamic_soundness.json'
    write(OUT/'equality_summary.json',{'status':'PASS','case_counts':counts,'cases':len(first),
          'candidate_sha256':sha(HERE/'inclusion.py'),'reference_sha256':REFERENCE_SHA,
          'all_internal_points_to_states_identical':True,'all_serialized_scientific_outputs_identical':True,
          'deterministic_candidate_replicas':True,
          'calibration_pair_statuses_and_dynamic_inputs':{'pair_results_sha256':sha(frozen_pairs),'dynamic_soundness_sha256':sha(dynamic),
              'proof':'Every Rust normalized graph and inclusion result matches the frozen artifact exactly. Raw MIR input, C evidence, expectations, statuses and dynamic traces are unchanged; no calibration result is republished.'},
          'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'historical_depths_accepted':0})
    print('COMPLETE EQUALITY PASS',counts,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',choices=['reference','candidate']);p.add_argument('--run');a=p.parse_args()
    worker(a.worker,a.run) if a.worker else launch_all()
