"""Isolated controlled build-std experiment; never modifies the pinned sysroot."""
import argparse
import json
import os
import subprocess
from prepare import ROOT,HERE,require_c
from probe import BASE,SYSROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',required=True)
    args=parser.parse_args()
    if not args.label.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c()
    out=BASE/'build-std-probe'/args.label
    out.mkdir(parents=True,exist_ok=False)
    project=out/'application'
    (project/'src').mkdir(parents=True)
    (project/'Cargo.toml').write_text('[package]\nname="controlled-std-probe"\nversion="0.0.0"\nedition="2021"\n[workspace]\n[profile.dev]\nopt-level=0\npanic="unwind"\ncodegen-units=1\n')
    (project/'src/main.rs').write_text('fn target(x:u64)->u64{x}\nfn main(){let x=std::hint::black_box(1);let f=|v|target(v);let _=Some(x).map(f);let _=Err::<u64,u64>(x).or_else(|v|Ok::<u64,u64>(target(v)));let _:u64=[x].into_iter().flat_map(|v|[target(v)]).sum();}\n')
    env=os.environ.copy()
    flags=['-C','opt-level=0','-C','codegen-units=1','-C','panic=unwind','-Z','mir-opt-level=0','-Z','inline-mir=no','-Z','always-encode-mir','--remap-path-prefix',str(ROOT)+'=.']
    env.update(RUSTC_BOOTSTRAP='1',RUSTC=str(SYSROOT/'bin/rustc'),CARGO_HOME=str(out/'cargo-home'),
               CARGO_TARGET_DIR=str(out/'target'),CARGO_ENCODED_RUSTFLAGS='\x1f'.join(flags))
    argv=[str(SYSROOT/'bin/cargo'),'build','-vv','-Z','build-std=std,panic_unwind','--target=x86_64-unknown-linux-gnu','--manifest-path',str(project/'Cargo.toml')]
    record={'argv':argv,'flags':flags,'accepted_backend':False,'historical_measurement':False}
    with (out/'build.log').open('w') as log:
        try:
            run=subprocess.run(argv,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600)
            record['exit_code']=run.returncode
            record['status']='compiled' if run.returncode==0 else 'build_failed'
        except subprocess.TimeoutExpired:
            record['status']='timeout';record['exit_code']=None
    record['std_stage_semantically_validated']=False
    (out/'result.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
    print(record['status'],out/'build.log',flush=True)
    require_c()


if __name__=='__main__':main()
