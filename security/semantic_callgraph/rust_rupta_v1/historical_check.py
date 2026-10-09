"""Read-only pinned-Cargo metadata checks; never build or analyze history."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time

root=Path.cwd()
base=root/'build/rupta-v1'
sysroot=base/'rustup/toolchains/nightly-2024-02-03-x86_64-unknown-linux-gnu'
env=dict(os.environ,CARGO_HOME=str(base/'cargo'),RUSTUP_HOME=str(base/'rustup'),
         CARGO_TARGET_DIR=str(base/'historical-build-unused'),RUSTC=str(sysroot/'bin/rustc'))
results=[]
for release in ('0.0.3','0.2.2'):
    provenance=json.loads((root/'build/historical-rust-measurement/method-v1'/release/'source_provenance.json').read_text())
    checkout=root/provenance['checkout']
    def hashes():
        return {name:hashlib.sha256((checkout/name).read_bytes()).hexdigest() for name in ('Cargo.toml','Cargo.lock')}
    before=hashes()
    assert before['Cargo.lock']==provenance['cargo_lock_sha256']
    assert before['Cargo.toml']==provenance['cargo_toml_sha256']
    cmd=[str(sysroot/'bin/cargo'),'metadata','--format-version','1','--no-deps','--frozen','--manifest-path',str(checkout/'Cargo.toml')]
    t=time.monotonic()
    p=subprocess.run(cmd,cwd=base,env=env,text=True,capture_output=True,timeout=120)
    results.append({'release':release,'argv':cmd,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,
                    'seconds':time.monotonic()-t,'before':before,'after':hashes(),
                    'interpretation':'metadata only; success does not establish build compatibility'})
    assert before==hashes()
    print(release,p.returncode,p.stderr[-1500:],flush=True)
(base/'historical_metadata.json').write_text(json.dumps(results,indent=2)+'\n')
