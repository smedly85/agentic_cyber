"""Bounded read-only RUPTA upstream/fork toolchain inventory (no other frameworks)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import urllib.request
import sys

OUT=Path('build/rupta-v1/drop-trial/compatibility')

def fetch(url):
    request=urllib.request.Request(url,headers={'User-Agent':'agentic-cyber-rupta-compatibility-check'})
    try:
        with urllib.request.urlopen(request,timeout=45) as response:
            data=response.read()
            return {'url':url,'status':response.status,'sha256':hashlib.sha256(data).hexdigest(),'text':data.decode()}
    except Exception as exc:
        return {'url':url,'error':str(exc)}

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    endpoints={'repo':'','branches':'/branches?per_page=100','forks':'/forks?per_page=100&sort=newest','pulls':'/pulls?state=all&per_page=100','tags':'/tags?per_page=100'}
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses=dict(zip(endpoints,pool.map(fetch,['https://api.github.com/repos/rustanlys/rupta'+suffix for suffix in endpoints.values()])))
    (OUT/'github-api.json').write_text(json.dumps(responses,indent=2))
    assert all('text' in r for r in responses.values()), responses
    branches=json.loads(responses['branches']['text'])
    forks=json.loads(responses['forks']['text'])
    assert len(forks)<100 and len(branches)<100, 'pagination required'
    candidates=[{'repo':'rustanlys/rupta','branch':b['name'],'commit':b['commit']['sha']} for b in branches]
    candidates += [{'repo':f['full_name'],'branch':f['default_branch'],'pushed_at':f['pushed_at'],'archived':f['archived']} for f in forks]
    def inspect(c):
        r=fetch(f"https://raw.githubusercontent.com/{c['repo']}/{c.get('commit',c['branch'])}/rust-toolchain.toml")
        return {**c,'toolchain':r}
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(inspect,candidates))
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'all exposed upstream branches and direct forks default branches; no claim about private/unindexed forks','candidates':rows}
    (OUT/'toolchains.json').write_text(json.dumps(result,indent=2))
    for r in rows:
        print(r['repo'],r['branch'],r['toolchain'].get('text',r['toolchain'].get('error')).strip().replace('\n',' '),flush=True)
    for p in json.loads(responses['pulls']['text']):
        print('PR',p['number'],p['state'],p['title'],p['head']['sha'],flush=True)

def fork_branches():
    saved=json.loads((OUT/'github-api.json').read_text())
    forks=json.loads(saved['forks']['text'])
    def inspect(f):
        response=fetch(f"https://api.github.com/repos/{f['full_name']}/branches?per_page=100")
        if 'text' not in response: return {'repo':f['full_name'],'response':response}
        branches=json.loads(response['text'])
        assert len(branches)<100
        return {'repo':f['full_name'],'response':response,'branches':[
            {'name':b['name'],'sha':b['commit']['sha'],'toolchain':fetch(f"https://raw.githubusercontent.com/{f['full_name']}/{b['commit']['sha']}/rust-toolchain.toml")}
            for b in branches]}
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(inspect,forks))
    (OUT/'fork-branches.json').write_text(json.dumps(rows,indent=2))
    for r in rows:
        for b in r.get('branches',[]):
            print(r['repo'],b['name'],b['sha'],b['toolchain'].get('text',b['toolchain'].get('error')).replace('\n',' '),flush=True)

def compiler_check():
    import io
    import os
    import subprocess
    import tarfile
    from .probe import ROOT, BASE
    from .patched_trial import SHA
    source=(ROOT/OUT/'canonical-1.93-check').resolve()
    source.mkdir(exist_ok=False)
    archive=subprocess.check_output(['git','-C',str(BASE/'upstream'),'archive',SHA])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf: tf.extractall(source,filter='data')
    compiler=ROOT/'build/rust-mir/toolchain'
    env=dict(os.environ,RUSTC=str(compiler/'bin/rustc'),RUSTDOC=str(compiler/'bin/rustdoc'),
             RUSTC_BOOTSTRAP='1',RUST_SYSROOT=str(compiler),CARGO_HOME=str(BASE/'cargo'),
             CARGO_TARGET_DIR=str((ROOT/OUT/'target-1.93').resolve()),
             LD_LIBRARY_PATH=str(compiler/'lib')+':'+str(compiler/'lib/rustlib/x86_64-unknown-linux-gnu/lib'))
    cmd=[str(compiler/'bin/cargo'),'check','--locked','--offline','--lib','--message-format=json','-j','4']
    versions={name:subprocess.check_output([str(compiler/'bin'/name),'-vV'],env=env,text=True) for name in ('rustc','cargo')}
    lock_hash=hashlib.sha256((source/'Cargo.lock').read_bytes()).hexdigest()
    with (OUT/'compiler-check.jsonl').open('w') as stdout,(OUT/'compiler-check.stderr').open('w') as stderr:
        result=subprocess.run(cmd,cwd=source,env=env,stdout=stdout,stderr=stderr,timeout=600)
    messages=[]
    for line in (OUT/'compiler-check.jsonl').read_text().splitlines():
        try: row=json.loads(line)
        except ValueError: continue
        if row.get('reason')=='compiler-message' and row['message']['level']=='error': messages.append(row['message'])
    record={'argv':cmd,'cwd':str(source),'returncode':result.returncode,'versions':versions,
            'configuration':'diagnostic compile check only; RUSTC_BOOTSTRAP=1 allows rustc-private feature gates, not API compatibility',
            'environment':{k:env[k] for k in ('RUSTC','RUSTDOC','RUSTC_BOOTSTRAP','RUST_SYSROOT','CARGO_HOME','CARGO_TARGET_DIR','LD_LIBRARY_PATH')},
            'errors':messages,'lock_unchanged':lock_hash==hashlib.sha256((source/'Cargo.lock').read_bytes()).hexdigest()}
    (OUT/'compiler-check.json').write_text(json.dumps(record,indent=2))
    print('Compiler check exit',result.returncode,'errors',len(messages),flush=True)
    for m in messages[:20]: print(m.get('code'),m['message'],flush=True)

if __name__=='__main__':
    if len(sys.argv)==1: main()
    elif sys.argv[1]=='fork-branches': fork_branches()
    elif sys.argv[1]=='compiler-check': compiler_check()
