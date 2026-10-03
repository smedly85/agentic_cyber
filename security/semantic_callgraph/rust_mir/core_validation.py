"""Focused engineering gates for ordered core capability development."""
import argparse
import hashlib
import json
import os
import shutil
from prepare import ROOT,HERE,require_c
from probe import BASE,SYSROOT,command
from inclusion import analyze


def write(path,value):
    path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',required=True)
    parser.add_argument('--group',required=True)
    args=parser.parse_args()
    for label in (args.label,args.group):
        if not label.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c()
    out=BASE/'core-validation'/args.label
    out.mkdir(parents=True,exist_ok=False)
    fixture=ROOT/'tests/fixtures/rust_mir'
    manifest=fixture/'core_expectations.json'
    groups=json.loads(manifest.read_text())
    expected=[case for group in groups.values() for case in group] if args.group=='all' else groups[args.group]
    shutil.copy2(manifest,out/'expectations.json')
    for name in ('driver.rs','inclusion.py'):
        shutil.copy2(HERE/name,out/name)
    env=os.environ.copy()
    env.update(RUSTC_BOOTSTRAP='1',MIR_PROBE_TRANSITIVE='1',
               LD_LIBRARY_PATH=str(SYSROOT/'lib')+':'+str(SYSROOT/'lib/rustlib/x86_64-unknown-linux-gnu/lib'))
    rustc=SYSROOT/'bin/rustc'
    assert '254b59607d4417e9dffbc307138ae5c86280fe4c' in command([rustc,'-vV'],out,env)
    driver=out/'driver'
    command([rustc,HERE/'driver.rs','--edition=2021','-C','prefer-dynamic','-L',SYSROOT/'lib','-o',driver],out,env)
    rows=[]
    for case in expected:
        fingerprints=[]
        for run in ('run-1','run-2'):
            directory=out/case['case']/run
            directory.mkdir(parents=True)
            raw=json.loads(command([driver,fixture/'core_cases.rs','--crate-name=core_control',
                '--sysroot',SYSROOT,'--edition=2021','--target=x86_64-unknown-linux-gnu',
                '-C','opt-level=0','-C','panic=unwind','-C','codegen-units=1',
                '-Z','mir-opt-level=0','-Z','inline-mir=no','-Z','always-encode-mir',
                '--remap-path-prefix',str(ROOT)+'=.','--cfg=core_case="'+case['case']+'"',
                '-A','warnings','--emit=link','--out-dir',directory],directory,env))
            roots=[r['instance_identity'] for r in raw['instances'] if r['instance_identity'].endswith('::crate::main')]
            assert len(roots)==1
            result=analyze(raw,roots=roots)
            write(directory/'graph.json',{'api':raw,'inclusion':result})
            fingerprints.append(hashlib.sha256((directory/'graph.json').read_bytes()).hexdigest())
            checks=[]
            indirect={(r['instance_identity'],s['block']) for r in raw['instances'] for s in r['calls'] if s['status'].startswith('unresolved')}
            for owner,targets in case['sites'].items():
                sites=[s for s in result['sites'] if s['owner'].split('::',1)[1]==owner and (s['owner'],s['block']) in indirect]
                actual=sorted({t.split('::',1)[1] for s in sites for t in s['targets']})
                missing=sorted(set(targets)-set(actual));extra=sorted(set(actual)-set(targets))
                checks.append({'owner':owner,'expected_targets':targets,'actual_targets':actual,
                               'missing_targets':missing,'unexpected_targets':extra,
                               'receiver_types':sorted({t for s in sites for t in s.get('receiver_types',[])}),
                               'passed':len(sites)==1 and not missing and not extra})
        row={'case':case['case'],'sites':checks,'allocations':result.get('allocations',[]),
             'precision_losses':result.get('precision_losses',[]),
             'unsupported_operations':result['unsupported_operations'],
             'converged':result['converged'],'deterministic':len(set(fingerprints))==1,
             'fingerprints':fingerprints,'accepted_backend':False}
        row['focused_pass']=all(s['passed'] for s in checks) and row['converged'] and row['deterministic'] and bool(row['precision_losses'])==case.get('precision_loss',False)
        if 'allocations' in case:row['focused_pass'] &= len(row['allocations'])==case['allocations']
        if 'reachable_user_targets' in case:
            names={i.split('::',1)[1] for i in result['active_instances']}
            actual=sorted(names & {'crate::target','crate::other','crate::third','crate::unrelated'})
            dyn_sites=[s for s in result['sites'] if 'receiver_types' in s]
            row['reachable_user_targets']=actual
            row['dynamic_sites']=dyn_sites
            row['focused_pass'] &= actual==sorted(case['reachable_user_targets']) and len(dyn_sites)==1 and len(dyn_sites[0]['targets'])==case['dynamic_target_count']
        rows.append(row)
        print(case['case'],row['focused_pass'],checks,flush=True)
        write(out/'result.json',{'group':args.group,'cases':rows,'accepted_backend':False,
                               'expectations_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()})
    require_c()


if __name__=='__main__':main()
