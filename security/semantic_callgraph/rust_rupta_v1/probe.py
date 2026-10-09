"""Run only the six small RUPTA probes, with exact command/resource evidence."""
from pathlib import Path
import hashlib
import json
import os
import resource
import subprocess
import time
import sys

ROOT=Path.cwd()
HERE=ROOT/'security/semantic_callgraph/rust_rupta_v1'
BASE=ROOT/'build/rupta-v1'
SYSROOT=BASE/'rustup/toolchains/nightly-2024-02-03-x86_64-unknown-linux-gnu'
PTA=BASE/'target/debug/pta'

def environment():
    return dict(os.environ,RUSTUP_HOME=str(BASE/'rustup'),CARGO_HOME=str(BASE/'cargo'),
                PATH=str(BASE/'cargo/bin')+':'+os.environ['PATH'],
                LD_LIBRARY_PATH=str(SYSROOT/'lib'),PTA_LOG='info')

def limit():
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3))

def run(argv,out,timeout=180):
    out.mkdir(parents=True,exist_ok=False)
    cmd=['/usr/bin/time','-v','-o',str(out/'resources.txt'),*map(str,argv)]
    started=time.monotonic()
    with (out/'stdout.txt').open('w') as stdout,(out/'stderr.txt').open('w') as stderr:
        process=subprocess.Popen(cmd,cwd=ROOT,env=environment(),stdout=stdout,stderr=stderr,
                                 start_new_session=True,preexec_fn=limit)
        try:
            code=process.wait(timeout=timeout)
            status='completed' if code==0 else 'build_or_analysis_failure'
        except subprocess.TimeoutExpired:
            import signal
            os.killpg(process.pid,signal.SIGKILL)
            code=process.wait()
            status='timeout'
    result={'argv':cmd,'cwd':str(ROOT),'status':status,'returncode':code,
            'wall_seconds':time.monotonic()-started,'timeout_seconds':timeout,
            'address_space_limit_bytes':16*1024**3,
            'environment':{k:environment()[k] for k in ('RUSTUP_HOME','CARGO_HOME','PATH','LD_LIBRARY_PATH','PTA_LOG')}}
    (out/'command.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    assert PTA.is_file(), 'Build gate has not passed'
    for mode in ('ander','cs'):
        for fixture in ('direct','nested','recursion','pointer','two_fields','dynamic'):
            out=BASE/(sys.argv[1] if len(sys.argv)>1 else 'basic')/mode/fixture
            argv=[PTA,HERE/'fixtures'/f'{fixture}.rs','--pta-type',mode,
                  '--dump-call-graph',out/'graph.dot','--dump-dyn-calls',out/'dynamic.txt',
                  '--dump-mir',out/'mir.txt','--','--edition=2021','--crate-name',fixture,
                  '--sysroot',SYSROOT,'--emit=metadata','--out-dir',out,'-C','opt-level=0']
            result=run(argv,out)
            print(mode,fixture,result['status'],flush=True)
