"""Selected historical solver diagnostics only. No mappings, finalizer or BFS."""
import argparse, datetime, json, os, pathlib, resource, signal, subprocess, sys, time
from common import ROOT,HERE,OUT,REFERENCE,REFERENCE_SHA,read,sha,write,digest
sys.path[:0]=[str(ROOT),str(ROOT/'security/semantic_callgraph/cross_language_calibration')]
from runtime_provenance import pre_measurement_gate
from security.semantic_callgraph.rust_mir_compact.inclusion import analyze
from security.semantic_callgraph.rust_mir.graph import export_partial
BASE=ROOT/'build/historical-rust-measurement/method-v1/0.2.2/semantic'

def worker(utility,directory):
    record=read(OUT/'equality_summary.json')
    assert record['status']=='PASS' and record['candidate_sha256']==sha(HERE/'inclusion.py')
    old=BASE/utility/'run-1';raw=read(old/'raw.json')
    root=read(old/'entry_resolution.json')['candidates'];assert len(root)==1
    stats={};start=time.monotonic();cpu=time.process_time()
    stream=(directory/'progress.jsonl').open('w',buffering=1)
    def sample(signum,frame):
        cursor=frame
        while cursor and cursor.f_code is not analyze.__code__:cursor=cursor.f_back
        counts=dict(cursor.f_locals.get('stats',{})) if cursor else dict(stats)
        stream.write(json.dumps({'elapsed_seconds':time.monotonic()-start,'cpu_seconds':time.process_time()-cpu,
             'peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'operation_counts':counts,
             'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()},sort_keys=True)+'\n')
    signal.signal(signal.SIGALRM,sample);signal.setitimer(signal.ITIMER_REAL,10,10)
    result=analyze(raw,roots=[root[0]['instance_identity']],statistics=stats)
    solve_wall=time.monotonic()-start;solve_cpu=time.process_time()-cpu
    signal.setitimer(signal.ITIMER_REAL,0);sample(0,None);stream.close()
    write(directory/'inclusion.diagnostic.json',result)
    graph_hash=None
    if result['converged']:
        active=set(result['active_instances'])
        exported=export_partial({'instances':[r for r in raw['instances'] if r['instance_identity'] in active]},result)
        write(directory/'graph.diagnostic.json',exported);graph_hash=sha(directory/'graph.diagnostic.json')
    write(directory/'completion.json',{'diagnostic_only':True,'converged':result['converged'],
          'solver_wall_seconds':solve_wall,'solver_cpu_seconds':solve_cpu,
          'peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
          'operation_counts':stats,'inclusion_sha256':sha(directory/'inclusion.diagnostic.json'),
          'graph_sha256':graph_hash,'graph_hash_scope':'Unchanged export_partial nodes/edges; no BFS, depth or mapped-target resolution.',
          'required_body_dispositions':{k:sum(r['disposition']==k for r in result['required_body_ledger']) for k in sorted({r['disposition'] for r in result['required_body_ledger']})},
          'historical_depths_accepted':0})

def run(utility,replica):
    folder=OUT/'historical-diagnostic'/utility/replica;folder.mkdir(parents=True,exist_ok=False)
    old=BASE/utility/'run-1';environment=read(old/'launch.json')['environment']
    command=[sys.executable,str(pathlib.Path(__file__).resolve()),'--worker',utility,'--directory',str(folder)]
    write(folder/'launch.json',{'command':command,'environment':environment,'cwd':str(ROOT),
          'candidate_sha256':sha(HERE/'inclusion.py'),'reference_sha256':sha(REFERENCE),
          'raw_sha256':sha(old/'raw.json'),'wall_budget_seconds':900,'RSS_safety_limit_GiB':24,
          'host_available_memory_floor_GiB':2,'purpose':'Diagnostic only, no vulnerability targets or depths.'})
    with (folder/'stdout').open('w') as stdout,(folder/'stderr').open('w') as stderr:
        try:gate=pre_measurement_gate('Rust',environment,[])
        except Exception as error:write(folder/'gate.json',{'status':'FAIL','error':str(error)});raise
        p=subprocess.Popen(command,cwd=ROOT,env=environment,stdout=stdout,stderr=stderr)
        write(folder/'gate.json',{'status':'PASS','rows':gate,'immediately_before_invocation':True})
        start=time.monotonic();peak=0;reason=None
        with (folder/'memory.jsonl').open('w',buffering=1) as log:
            while p.poll() is None:
                try:
                    status={k:v.strip() for k,v in (s.split(':',1) for s in (pathlib.Path('/proc')/str(p.pid)/'status').read_text().splitlines() if ':' in s)}
                    info={k:v.strip() for k,v in (s.split(':',1) for s in pathlib.Path('/proc/meminfo').read_text().splitlines())}
                    rss=int(status.get('VmHWM','0 kB').split()[0]);peak=max(peak,rss)
                    log.write(json.dumps({'elapsed_seconds':time.monotonic()-start,'peak_RSS_KiB':rss,'RSS':status.get('VmRSS'),
                              'swap':status.get('VmSwap'),'host_MemAvailable':info['MemAvailable']})+'\n')
                    if rss>24*1024*1024 or int(info['MemAvailable'].split()[0])<2*1024*1024:reason='memory_safety_stop'
                except FileNotFoundError:pass
                if time.monotonic()-start>=900:reason='wall_timeout'
                if reason:p.kill();p.wait();break
                time.sleep(2)
        code=p.wait()
    row={'utility':utility,'replica':replica,'returncode':code,'outcome':reason or ('completed' if code==0 else 'worker_error'),
         'process_elapsed_seconds':time.monotonic()-start,'observed_peak_RSS_KiB':peak,'diagnostic_only':True}
    write(folder/'result.json',row);print(row,flush=True)
    assert row['outcome']!='worker_error',(utility,(folder/'stderr').read_text())
    return read(folder/'completion.json') if (folder/'completion.json').exists() else None

def main():
    assert read(OUT/'validation_complete.json')['status']=='PASS'
    proof=read(OUT/'equality_summary.json');assert proof['status']=='PASS' and proof['candidate_sha256']==sha(HERE/'inclusion.py')
    assert sha(REFERENCE)==REFERENCE_SHA
    original=read(ROOT/'build/historical-rust-diagnostics/solver-v1/experiment_preregistration.json')
    order=[original['selection'][s] for s in ('small','median','large')]
    policy={'diagnostic_only':True,'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'selection':order,'selection_source_sha256':sha(ROOT/'build/historical-rust-diagnostics/solver-v1/experiment_preregistration.json'),
            'wall_budget_seconds_per_process':900,'scheduling':'Serial, independent processes and output directories',
            'RSS_safety_limit_GiB':24,'host_available_memory_floor_GiB':2,
            'reference_comparison':'Preserve and bind the prior same-input reference 900-second trials (and printenv 1800-second trial). No new prolonged reference attempt unless candidate convergence makes one computationally reasonable. Lack of a converged reference prevents historical-scale exact-equality claims.',
            'replication':'Repeat each converged candidate from a fresh process; compare full inclusion and exported graph hashes.',
            'no_vulnerable_mapping_or_BFS':True,'candidate_sha256':proof['candidate_sha256'],
            'python_version':sys.version,'python_executable_sha256':sha(pathlib.Path(sys.executable).resolve())}
    write(OUT/'historical_diagnostic_protocol.json',policy)
    records=[]
    for utility in order:
        old=BASE/utility/'run-1'
        prior=[]
        for p in (ROOT/'build/historical-rust-diagnostics/solver-v1/ladder'/utility).glob('*/launch.json'):
            launch=read(p);assert launch['raw_sha256']==sha(old/'raw.json') and launch['solver_sha256']==REFERENCE_SHA
            assert launch['python_executable_sha256']==policy['python_executable_sha256']
            prior.append({'path':p.parent.relative_to(ROOT).as_posix(),'launch_sha256':sha(p),'result':read(p.parent/'result.json')})
        first=run(utility,'candidate-a');second=None
        if first and first['converged']:
            second=run(utility,'candidate-b')
            assert second and second['converged'] and all(first[k]==second[k] for k in ('inclusion_sha256','graph_sha256')),('Historical diagnostic nondeterminism',utility)
        records.append({'utility':utility,'first':first,'second':second,'prior_reference_trials':prior,
                        'historical_reference_equality_established':False,'historical_depths_accepted':0})
        write(OUT/'historical_diagnostic_results.json',records)
    practical=all(r['first'] and r['first']['converged'] and r['second'] and r['second']['converged']
                  and max(r['first']['peak_RSS_KiB'],r['second']['peak_RSS_KiB'])<=12*1024*1024 for r in records)
    write(OUT/'practical_convergence.json',{'status':'PASS' if practical else 'STOP',
        'candidate_sha256':proof['candidate_sha256'],'all_three_deterministically_converged_within_budget':practical,
        'peak_RSS_limit_GiB':12,'wall_budget_seconds':900,'historical_depths_accepted':0,
        'failure_action':'Stop this optimization cycle; do not run historical measurement.'})
    print('PRACTICAL CONVERGENCE', 'PASS' if practical else 'STOP',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--directory',type=pathlib.Path);a=p.parse_args()
    worker(a.worker,a.directory) if a.worker else main()
