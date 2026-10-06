"""Conditional method-v2 orchestration; never changes frozen scientific policy."""
import argparse,datetime,json,os,pathlib,subprocess,sys,time
from common import ROOT,HERE,OUT,read,write,sha,digest
sys.path[:0]=[str(ROOT),str(ROOT/'security/historical/rust'),str(ROOT/'security/semantic_callgraph/cross_language_calibration')]
from runtime_provenance import pre_measurement_gate
from inspect_frozen_builds import verify_phase_a
import measure_historical as frozen
from security.semantic_callgraph.rust_mir_compact.inclusion import analyze
OLD=ROOT/'build/historical-rust-measurement/method-v1'
BASE=ROOT/'build/historical-rust-measurement/method-v2-compact'

def amendment():
    pointer=read(OUT/'frozen_amendment_pointer.json');path=ROOT/pointer['path'];assert sha(path)==pointer['sha256']
    policy=read(path);aggregate=policy.pop('aggregate_solver_amendment_sha256');assert digest(policy)==aggregate
    assert sha(HERE/'inclusion.py')==policy['candidate_sha256']
    assert verify_phase_a()['aggregate_classifier_sha256']==policy['classifier_fingerprint']
    for name,expected in policy['evidence'].items():assert sha(ROOT/name)==expected,name
    return pointer

def worker(directory,release,utility):
    amendment()
    statistics={}
    def candidate(raw,**kwargs):return analyze(raw,statistics=statistics,**kwargs)
    frozen.analyze=candidate  # In-memory orchestration alias only; no frozen file changes.
    frozen.solve(directory,release,utility)
    write(directory/'operation_counts.json',statistics)

def bounded(command,environment,directory,label):
    write(directory/(label+'_launch.json'),{'argv':command,'environment':environment,'cwd':str(ROOT),
        'amendment':read(OUT/'frozen_amendment_pointer.json'),'wall_budget_seconds':900})
    with (directory/(label+'.stdout')).open('w') as stdout,(directory/(label+'.stderr')).open('w') as stderr:
        try:gate=pre_measurement_gate('Rust',environment,[])
        except Exception as error:
            write(directory/(label+'_gate.json'),{'status':'FAIL','error':str(error)});raise
        process=subprocess.Popen(command,cwd=ROOT,env=environment,stdout=stdout,stderr=stderr)
        write(directory/(label+'_gate.json'),{'status':'PASS','rows':gate,'immediately_before_invocation':True})
        start=time.monotonic();peak=0;reason=None
        while process.poll() is None:
            try:
                status={k:v.strip() for k,v in (s.split(':',1) for s in (pathlib.Path('/proc')/str(process.pid)/'status').read_text().splitlines() if ':' in s)}
                info={k:v.strip() for k,v in (s.split(':',1) for s in pathlib.Path('/proc/meminfo').read_text().splitlines())}
                peak=max(peak,int(status.get('VmHWM','0 kB').split()[0]))
                if peak>24*1024*1024 or int(info['MemAvailable'].split()[0])<2*1024*1024:reason='memory_safety_stop'
            except FileNotFoundError:pass
            if time.monotonic()-start>=900:reason='wall_timeout'
            if reason:process.kill();process.wait();break
            time.sleep(2)
        code=process.wait()
    result={'status':reason or ('completed' if code==0 else 'worker_failed'),'returncode':code,
        'wall_seconds':time.monotonic()-start,'peak_RSS_KiB':peak}
    write(directory/(label+'_result.json'),result);return result

def main():
    pointer=amendment();assert not BASE.exists();BASE.mkdir(parents=True)
    write(BASE/'start.json',{'amendment':pointer,'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    plan=read(OLD/'observation_plan.json');contexts=sorted({(r['release'],r['utility']) for r in plan['function_contexts']})
    builds={}
    for release in sorted({r for r,u in contexts}):
        path=OLD/release/('build-attempts-2' if (OLD/release/'build-attempts-2').exists() else 'build-attempts')
        builds.update({(release,r['utility']):r for r in read(path/'results.json')})
    completed=[]
    for release,utility in contexts:
        folder=BASE/release/'semantic'/utility;folder.mkdir(parents=True)
        build=builds.get((release,utility),{})
        if build.get('status')!='built':
            result={'status':'build_unresolved','frozen_build_evidence':build}
        else:
            old=OLD/release/'semantic'/utility/'run-1';launch=read(old/'launch.json');runs=[]
            for run in ('run-1','run-2'):
                directory=folder/run;directory.mkdir()
                argv=[];removed=[];i=0
                while i<len(launch['argv']):
                    arg=launch['argv'][i]
                    if arg=='-C' and i+1<len(launch['argv']) and launch['argv'][i+1].startswith('incremental='):
                        removed+=launch['argv'][i:i+2];i+=2;continue
                    if arg.startswith('-Cincremental='):removed.append(arg);i+=1;continue
                    argv.append(arg);i+=1
                argv[argv.index('--out-dir')+1]=str(directory)
                env={**launch['environment'],'CARGO_INCREMENTAL':'0'}
                write(directory/'edition_and_build_provenance.json',{'frozen_launch_sha256':sha(old/'launch.json'),
                    'observed_edition':launch['observed_edition'],'edition_verified':launch['edition_verified'],
                    'removed_incremental_arguments':removed,'complete_build_provenance_sha256':sha(OLD/'complete_build_provenance.json')})
                print(release,utility,run,'extracting',flush=True)
                extraction=bounded(argv,env,directory,'extraction')
                if extraction['status']!='completed':runs.append({'status':'extraction_failed','detail':extraction});continue
                write(directory/'raw.json',read(directory/'extraction.stdout'))
                # An operational cache change is not permission to change MIR.
                if sha(directory/'raw.json')!=sha(old/'raw.json'):
                    write(directory/'extraction_mismatch.json',{'status':'STOP','frozen_sha256':sha(old/'raw.json'),'actual_sha256':sha(directory/'raw.json')})
                    raise RuntimeError('STOP: normalized historical extraction changed')
                print(release,utility,run,'solving',flush=True)
                command=[sys.executable,str(HERE/'measure_study.py'),'--worker','--directory',str(directory),'--release',release,'--utility',utility]
                solved=bounded(command,env,directory,'solver')
                runs.append({'status':'measured' if solved['status']=='completed' else 'solver_failure','detail':solved})
            checks={}
            for name in ('raw.json','inclusion.json','exported.json','scientific_graph.json','program_context.json','function_observations.json'):
                paths=[folder/run/name for run in ('run-1','run-2')]
                if all(p.exists() for p in paths):
                    texts=[p.read_text().replace('/run-1/','/$RUN/').replace('/run-2/','/$RUN/') for p in paths]
                    checks[name]=texts[0]==texts[1]
            result={'status':'measured' if all(r['status']=='measured' for r in runs) and len(checks)==6 and all(checks.values()) else 'semantic_failure',
                'runs':runs,'deterministic_artifacts':checks}
            if checks and not all(checks.values()):
                write(folder/'result.json',result);raise RuntimeError('STOP: historical scientific nondeterminism')
        write(folder/'result.json',result);completed.append({'release':release,'utility':utility,**result})
        write(BASE/'context_results.json',completed);print('CONTEXT',release,utility,result['status'],flush=True)
    write(BASE/'complete.json',{'status':'complete','contexts':len(completed),'amendment':pointer})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--directory',type=pathlib.Path)
    p.add_argument('--release');p.add_argument('--utility');a=p.parse_args()
    worker(a.directory,a.release,a.utility) if a.worker else main()
