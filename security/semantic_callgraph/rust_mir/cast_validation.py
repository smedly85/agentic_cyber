"""Paired compiler-backed controls for casts, constants, arrays and intrinsics."""
import argparse
import hashlib
import json
import os
from prepare import ROOT,HERE,require_c
from probe import BASE,SYSROOT,command
from std_config import rebuilt_std_flags
from inclusion import analyze

CASES=['constant_item','constant_struct','static_struct','constant_helper','constant_dyn',
       'repeat_known','repeat_variable','mixed_known','mixed_variable','box_two',
       'box_fnmut_two','select_fields','swap_fields']

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--label',required=True);args=parser.parse_args()
    assert args.label.replace('-','').isalnum()
    require_c();out=BASE/'cast-validation'/args.label;out.mkdir(parents=True,exist_ok=False)
    env=os.environ.copy();env.update(RUSTC_BOOTSTRAP='1',MIR_PROBE_TRANSITIVE='1',LD_LIBRARY_PATH=str(SYSROOT/'lib')+':'+str(SYSROOT/'lib/rustlib/x86_64-unknown-linux-gnu/lib'))
    driver=out/'driver';rustc=SYSROOT/'bin/rustc'
    command([rustc,HERE/'driver.rs','--edition=2021','-C','prefer-dynamic','-L',SYSROOT/'lib','-o',driver],out,env)
    flags=['--sysroot',SYSROOT,'--edition=2021','--target=x86_64-unknown-linux-gnu','-C','opt-level=0','-C','panic=unwind',
           '-Z','mir-opt-level=0','-Z','inline-mir=no','-Z','always-encode-mir','--remap-path-prefix',str(ROOT)+'=.',*rebuilt_std_flags(out)]
    rows=[]
    for case in CASES:
        hashes=[]
        for run in ('run-1','run-2'):
            directory=out/case/run;directory.mkdir(parents=True)
            raw=json.loads(command([driver,ROOT/'tests/fixtures/rust_mir/cast_constants.rs',*flags,'--cfg=cast_case="'+case+'"','-A','warnings','--out-dir',directory],directory,env))
            root=next(r['instance_identity'] for r in raw['instances'] if r['instance_identity'].endswith('::crate::main'))
            flow=analyze(raw,roots=[root]);selected='dynamic_mut' if case=='box_fnmut_two' else 'dynamic' if case in ('box_two','constant_dyn') else 'invoke'
            sites=[s for s in flow['sites'] if s['owner'].endswith('::crate::'+selected)]
            actual=sorted({t.split('::',1)[1] for s in sites for t in s['targets']})
            if case=='box_fnmut_two':expected=['crate::boxed_a::{closure#0}','crate::boxed_b::{closure#0}']
            elif case=='box_two':expected=['<crate::First as crate::Action>::run','<crate::Second as crate::Action>::run']
            elif case=='constant_dyn':expected=['<crate::First as crate::Action>::run']
            else:expected=['crate::other','crate::target'] if case in ('mixed_variable','select_fields','swap_fields') else ['crate::target']
            unresolved=[s for s in flow['sites'] if not s['targets']]
            passed=actual==sorted(expected) and not flow['unsupported_operations'] and not unresolved and flow['converged']
            payload=json.dumps({'api':raw,'inclusion':flow},sort_keys=True,indent=2)+'\n'
            (directory/'graph.json').write_text(payload);hashes.append(hashlib.sha256(payload.encode()).hexdigest())
            if run=='run-1':row={'case':case,'expected':expected,'actual':actual,'passed':passed,'unsupported_operations':flow['unsupported_operations'],'unresolved':unresolved,'allocations':flow['allocations']}
        row['deterministic']=hashes[0]==hashes[1];rows.append(row)
        print(case,row['passed'],row['actual'],len(row['unsupported_operations']),flush=True)
    result={'cases':rows,'passed':sum(r['passed'] for r in rows),'total':len(rows),'deterministic':all(r['deterministic'] for r in rows)}
    (out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')

if __name__=='__main__':main()
