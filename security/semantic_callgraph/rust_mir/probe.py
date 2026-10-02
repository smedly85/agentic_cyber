"""Exact-version compiler API probe, not a historical measurement runner."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from inclusion import analyze

from prepare import ROOT, HERE, require_c

BASE=ROOT/'build/rust-mir'
SYSROOT=BASE/'toolchain'


def command(args, directory, env):
    result=subprocess.run([str(a) for a in args],cwd=ROOT,env=env,capture_output=True,text=True,timeout=180)
    with (directory/'commands.jsonl').open('a') as log:
        log.write(json.dumps({'argv':[str(a) for a in args],'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr})+'\n')
    if result.returncode: raise RuntimeError(result.stderr)
    return result.stdout


def main():
    require_c()
    directory=BASE/'probe-build'
    directory.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env['RUSTC_BOOTSTRAP']='1'
    env['LD_LIBRARY_PATH']=str(SYSROOT/'lib')+':'+str(SYSROOT/'lib/rustlib/x86_64-unknown-linux-gnu/lib')
    rustc=SYSROOT/'bin/rustc'
    version=command([rustc,'-vV'],directory,env)
    if 'rustc 1.93.0 ' not in version or '254b59607d4417e9dffbc307138ae5c86280fe4c' not in version:
        raise ValueError('Wrong compiler: no fallback permitted')
    help_text=command([rustc,'-Z','help'],directory,env)
    (directory/'unstable-options.txt').write_text(help_text)
    command([rustc,HERE/'driver.rs','--edition=2021','-C','prefer-dynamic',
             '-L',SYSROOT/'lib','-o',directory/'mir-probe'],directory,env)
    flags=['--sysroot',str(SYSROOT),'--edition=2021','--target=x86_64-unknown-linux-gnu',
           '-C','opt-level=0','-C','panic=unwind','-C','codegen-units=1',
           '-Z','mir-opt-level=0','-Z','inline-mir=no','-Z','always-encode-mir',
           '--remap-path-prefix',str(ROOT)+'=.','--crate-name=mir_probe',
           '--emit=metadata']
    runs=[]
    label=sys.argv[sys.argv.index('--label')+1] if '--label' in sys.argv else 'baseline'
    if not label.replace('-','').isalnum():raise ValueError('Invalid output label')
    for name in ('run-1','run-2'):
        out=BASE/'probe'/label/name
        # Fresh outputs, never recursively delete a user's directory.
        if out.exists():
            raise ValueError('Clean run directory already exists: '+str(out))
        out.mkdir(parents=True)
        raw=command([directory/'mir-probe',ROOT/'tests/fixtures/rust_mir/probe.rs',*flags,'--out-dir',out],out,env)
        obj=json.loads(raw)
        normalized=json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n'
        (out/'probe.json').write_text(normalized)
        runs.append({'run':name,'sha256':hashlib.sha256(normalized.encode()).hexdigest(),'data':obj})
    rows=runs[0]['data']['instances']
    result={'compiler':version,'flags':flags,'bootstrap':'RUSTC_BOOTSTRAP=1',
            'api_feasible':True,'instance_count':len(rows),
            'mir_phases':sorted({r['phase'] for r in rows}),
            'probe_deterministic':runs[0]['sha256']==runs[1]['sha256'],
            'run_fingerprints':[r['sha256'] for r in runs],
            'unresolved_sites':[{'instance':r['instance_identity'],**site} for r in rows for site in r['calls'] if site['status'].startswith('unresolved')],
            'accepted_backend':False,'historical_measurements':False,
            'instances':rows}
    # Provenance paths are remapped separately from scientific identities.
    result['flags']=[str(a).replace(str(ROOT),'$REPO') for a in result['flags']]
    (HERE/'feasibility.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    points=analyze(runs[0]['data'])
    (HERE/'inclusion_probe.json').write_text(json.dumps(points,indent=2,sort_keys=True)+'\n')
    print('API feasible; instances:',len(rows),'deterministic probe:',result['probe_deterministic'])
    print('Unresolved sites:',len(result['unresolved_sites']),'; backend NOT accepted')


if __name__=='__main__': main()
