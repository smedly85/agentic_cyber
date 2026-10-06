"""Diagnostic incremental-off replay; dependencies remain frozen read-only."""
import pathlib, subprocess, sys, datetime
from common import ROOT,OUT,read,write,sha
BASE=ROOT/'build/historical-rust-measurement/method-v1'
sys.path.insert(0,str(ROOT/'security/semantic_callgraph/cross_language_calibration'))
from runtime_provenance import pre_measurement_gate
def main():
    equality=read(OUT/'equality_summary.json');assert equality['status']=='PASS'
    selection=read(ROOT/'build/historical-rust-diagnostics/solver-v1/experiment_preregistration.json')['selection']
    write(OUT/'cold_extraction_protocol.json',{'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'diagnostic_only':True,
        'selection':selection,'change':'Remove only Cargo -C incremental argument, set CARGO_INCREMENTAL=0, redirect output to independent empty directories.',
        'scope':'Checks extracted MIR for final utility compilation using unchanged prebuilt dependencies. Does not establish whole-dependency cold rebuild equivalence.',
        'no_solver_or_finalizer':True})
    results=[]
    for utility in selection.values():
        old=BASE/'0.2.2/semantic'/utility/'run-1';launch=read(old/'launch.json');hashes=[]
        for run in ('a','b'):
            folder=OUT/'cold-extraction'/utility/run;folder.mkdir(parents=True,exist_ok=False)
            before=launch['argv'];argv=[];removed=[];i=0
            while i<len(before):
                if before[i]=='-C' and i+1<len(before) and before[i+1].startswith('incremental='):
                    removed+=before[i:i+2];i+=2;continue
                if before[i].startswith('-Cincremental='):removed.append(before[i]);i+=1;continue
                argv.append(before[i]);i+=1
            argv[argv.index('--out-dir')+1]=str(folder)
            env={**launch['environment'],'CARGO_INCREMENTAL':'0'}
            write(folder/'launch.json',{'argv':argv,'environment':env,'cwd':str(ROOT),'removed_incremental_arguments':removed,'diagnostic_only':True})
            with (folder/'raw.stdout').open('w') as stdout,(folder/'stderr').open('w') as stderr:
                try:gate=pre_measurement_gate('Rust',env,[])
                except Exception as error:
                    write(folder/'gate.json',{'status':'FAIL','error':str(error)});raise
                p=subprocess.run(argv,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,timeout=900)
            write(folder/'gate.json',{'status':'PASS','rows':gate,'immediately_before_invocation':True})
            assert p.returncode==0,(utility,run,p.returncode)
            write(folder/'raw.diagnostic.json',read(folder/'raw.stdout'))
            hashes.append(sha(folder/'raw.diagnostic.json'))
        results.append({'utility':utility,'baseline_raw_sha256':sha(old/'raw.json'),'cold_hashes':hashes,
                        'matches_frozen_extraction':all(h==sha(old/'raw.json') for h in hashes),'cold_reruns_match':len(set(hashes))==1})
        assert results[-1]['matches_frozen_extraction'] and results[-1]['cold_reruns_match']
        write(OUT/'cold_extraction_results.json',results);print(results[-1],flush=True)
if __name__=='__main__':main()
