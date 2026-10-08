"""Inventory all existing controlled fixtures; report unsupported graph semantics.

API extraction success is deliberately separate from semantic acceptance.
"""
import json
import os
from pathlib import Path
import hashlib
from prepare import ROOT,HERE,require_c
from probe import BASE,SYSROOT,command
from inclusion import analyze
from dependency_inputs import scopeguard as verified_scopeguard


def main():
    verified_scopeguard()
    require_c()
    out=BASE/'controlled-probe'
    if out.exists():raise ValueError('Fresh controlled output directory required')
    out.mkdir(parents=True)
    env=os.environ.copy()
    env['RUSTC_BOOTSTRAP']='1'
    env['LD_LIBRARY_PATH']=str(SYSROOT/'lib')+':'+str(SYSROOT/'lib/rustlib/x86_64-unknown-linux-gnu/lib')
    rustc=SYSROOT/'bin/rustc'
    driver=BASE/'probe-build/mir-probe'
    fixtures=ROOT/'tests/fixtures/rust_semantic'
    flags=['--sysroot',SYSROOT,'-C','opt-level=0','-C','codegen-units=1','-Z','mir-opt-level=0',
           '-Z','inline-mir=no','-Z','always-encode-mir','--remap-path-prefix',str(ROOT)+'=.',
           '--target=x86_64-unknown-linux-gnu']
    command([rustc,fixtures/'dependency.rs','--edition=2021','--crate-type=rlib','--crate-name=semantic_dependency',
             '-C','panic=abort',*flags,'--out-dir',out],out,env)
    command([driver,fixtures/'dependency.rs','--edition=2021','--crate-type=rlib','--crate-name=semantic_dependency',
             '-C','panic=abort',*flags,'--emit=metadata','--out-dir',out],out,env)
    acquisition=ROOT/'build/rust-mir/dependencies'
    archive=acquisition/'scopeguard-1.2.0.crate'
    if hashlib.sha256(archive.read_bytes()).hexdigest()!='94143f37725109f92c262ed2cf5e59bce7498c01bcc1502d7b9afe439a4e9f49':
        raise ValueError('Dependency archive fingerprint mismatch')
    command([rustc,acquisition/'scopeguard-1.2.0/src/lib.rs','--edition=2015','--crate-type=rlib',
             '--crate-name=scopeguard','--cfg=feature="use_std"',*flags,'--out-dir',out],out,env)
    baseline=json.loads((HERE/'controlled_results.json').read_text())['cases']
    rows=[]
    for index,old in enumerate(baseline):
        case=old['case']; directory=out/case; directory.mkdir()
        source=fixtures/('instrument.rs' if index<13 else 'expanded.rs')
        extra=(['--crate-type=rlib','--crate-name=semantic_instrument','-C','panic=abort','--extern',
                'semantic_dependency='+str(out/'libsemantic_dependency.rlib')] if index<13 else
               ['--crate-name=expanded','-C','panic=unwind','--cfg=audit_case="'+case+'"','--extern',
                'scopeguard='+str(out/'libscopeguard.rlib')])
        try:
            raw=json.loads(command([driver,source,'--edition=2021',*flags,*extra,'-A','dead_code','--emit=metadata','--out-dir',directory],directory,env))
            result=analyze(raw)
            (directory/'api.json').write_text(json.dumps(raw,sort_keys=True,indent=2)+'\n')
            (directory/'inclusion.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
            row={'case':case,'api_status':'success','instances':len(raw['instances']),
                 'unsupported_reasons':sorted({r['reason'] for r in result['unsupported_operations']}),
                 'api_sha256':hashlib.sha256((directory/'api.json').read_bytes()).hexdigest(),
                 'semantic_status':'not_accepted','converged':result['converged']}
        except Exception as error:
            row={'case':case,'api_status':'failed','error':str(error),'semantic_status':'not_accepted'}
        rows.append(row);print(case,row['api_status'],row['semantic_status'],flush=True)
        (HERE/'controlled_results.json').write_text(json.dumps({'cases':rows,'accepted_backend':False,
            'historical_measurement':False,'stage':'API and incomplete inclusion probe; not semantic validation'},sort_keys=True,indent=2)+'\n')


if __name__=='__main__':main()
