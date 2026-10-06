"""Runs only after complete equality and practical diagnostic convergence."""
import datetime,sys
from common import ROOT,HERE,OUT,REFERENCE,REFERENCE_SHA,read,write,sha,digest
sys.path.insert(0,str(ROOT/'security/historical/rust'))
from inspect_frozen_builds import verify_phase_a
def main():
    phase=verify_phase_a();proof=read(OUT/'validation_complete.json');practical=read(OUT/'practical_convergence.json')
    assert proof['status']=='PASS' and practical['status']=='PASS'
    assert proof['candidate_sha256']==practical['candidate_sha256']==sha(HERE/'inclusion.py')
    assert sha(REFERENCE)==REFERENCE_SHA
    target=ROOT/'security/historical/rust/methodology/solver_compact_performance_amendment.json'
    assert not target.exists()
    record={'version':'method-v2-compact','kind':'performance_only_exact_storage_and_propagation',
        'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'frozen_before_method_v2_historical_measurement':True,'method_v1_accepted_depths':0,
        'reference_solver_sha256':REFERENCE_SHA,'candidate_path':(HERE/'inclusion.py').relative_to(ROOT).as_posix(),
        'candidate_sha256':sha(HERE/'inclusion.py'),'classifier_fingerprint':phase['aggregate_classifier_sha256'],
        'edition_policy':'manifest_declared_per_crate','CARGO_INCREMENTAL':'0',
        'replication':'Independent extraction directories/processes and independent solver processes; frozen compiled dependencies reused read-only.',
        'limits':{'post_extraction_worker_wall_seconds':900,'extraction_wall_seconds':900,'solver_sweeps':256,
                  'parallel_executable_contexts':1,'RSS_safety_GiB':24,'host_available_memory_floor_GiB':2},
        'unchanged':['MIR extraction semantics','constraint system','body policy','mappings','population','classifier','BFS','target aggregation','depth definitions','C results'],
        'evidence':{p.relative_to(ROOT).as_posix():sha(p) for p in [OUT/'equality_summary.json',OUT/'unit_mirror_summary.json',
            OUT/'historical_diagnostic_results.json',OUT/'practical_convergence.json',OUT/'validation_protocol.json',
            ROOT/'build/rust-mir/solver-v2-performance/cold_extraction_results.json',
            ROOT/'security/historical/rust/methodology/edition_policy_amendment.json',
            ROOT/'security/semantic_callgraph/cross_language_calibration/fixture_manifest.json']}}
    record['aggregate_solver_amendment_sha256']=digest(record)
    write(target,record);write(OUT/'frozen_amendment_pointer.json',{'path':target.relative_to(ROOT).as_posix(),'sha256':sha(target),
        'aggregate_solver_amendment_sha256':record['aggregate_solver_amendment_sha256']})
    print('PERFORMANCE AMENDMENT FROZEN',record['aggregate_solver_amendment_sha256'],flush=True)
if __name__=='__main__':main()
