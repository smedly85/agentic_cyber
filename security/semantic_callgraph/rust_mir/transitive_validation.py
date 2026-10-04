"""Whole-path dyn propagation across two local libraries and scopeguard."""
import argparse
import hashlib
import json
import os
from prepare import ROOT,HERE,require_c
from probe import BASE,SYSROOT,command
from std_config import rebuilt_std_flags
from inclusion import analyze


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--label',required=True)
    args=parser.parse_args()
    if not args.label.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c();out=BASE/'transitive-validation'/args.label;out.mkdir(parents=True,exist_ok=False)
    env=os.environ.copy();env.update(RUSTC_BOOTSTRAP='1',MIR_PROBE_TRANSITIVE='1',LD_LIBRARY_PATH=str(SYSROOT/'lib')+':'+str(SYSROOT/'lib/rustlib/x86_64-unknown-linux-gnu/lib'))
    rustc=SYSROOT/'bin/rustc';driver=out/'driver'
    command([rustc,HERE/'driver.rs','--edition=2021','-C','prefer-dynamic','-L',SYSROOT/'lib','-o',driver],out,env)
    flags=['--sysroot',SYSROOT,'--edition=2021','--target=x86_64-unknown-linux-gnu','-C','opt-level=0','-C','panic=unwind',
           '-Z','mir-opt-level=0','-Z','inline-mir=no','-Z','always-encode-mir','--remap-path-prefix',str(ROOT)+'=.',*rebuilt_std_flags(out)]
    fixture=ROOT/'tests/fixtures/rust_mir';runs=[]
    expected=['<transitive_dependency::First as transitive_dependency::Action>::operation',
              '<transitive_dependency::Second as transitive_dependency::Action>::operation']
    for run in ('run-1','run-2'):
        directory=out/run;directory.mkdir()
        command([rustc,fixture/'transitive_dependency.rs','--crate-type=rlib',*flags,'--out-dir',directory],directory,env)
        dependency=['--extern','transitive_dependency='+str(directory/'libtransitive_dependency.rlib')]
        command([rustc,fixture/'transitive_bridge.rs','--crate-type=rlib',*flags,*dependency,'--out-dir',directory],directory,env)
        scopeguard=ROOT/'build/rust-instrument-v2/acquisition/scopeguard-1.2.0/src/lib.rs'
        command([rustc,scopeguard,'--crate-name=scopeguard','--crate-type=rlib','--cfg=feature="use_std"',*flags,'--out-dir',directory],directory,env)
        raw=json.loads(command([driver,fixture/'transitive_main.rs',*flags,*dependency,
             '--extern','transitive_bridge='+str(directory/'libtransitive_bridge.rlib'),
             '--extern','scopeguard='+str(directory/'libscopeguard.rlib'),'-L','dependency='+str(directory),
             '--out-dir',directory],directory,env))
        roots=[r['instance_identity'] for r in raw['instances'] if r['instance_identity'].endswith('::crate::main')]
        assert len(roots)==1
        graph=analyze(raw,roots=roots)
        sites=[s for s in graph['sites'] if s['owner'].endswith('::crate::dynamic')]
        actual=sorted({t.split('::',1)[1] for s in sites for t in s['targets']})
        payload=json.dumps({'api':raw,'inclusion':graph},sort_keys=True,indent=2)+'\n'
        (directory/'graph.json').write_text(payload)
        runs.append({'expected_targets':expected,'actual_targets':actual,'missing':sorted(set(expected)-set(actual)),
                     'unexpected':sorted(set(actual)-set(expected)),'passed':len(sites)==1 and actual==expected,
                     'sha256':hashlib.sha256(payload.encode()).hexdigest(),'unsupported_operations':graph['unsupported_operations']})
    result={'runs':runs,'deterministic':runs[0]['sha256']==runs[1]['sha256'],
            'routes':['helper_return','multiple_arguments','struct_field','box_field','option','closure_capture','local_library','crates_io_scopeguard'],
            'accepted_backend':False}
    (out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(result,flush=True);require_c()


if __name__=='__main__':main()
