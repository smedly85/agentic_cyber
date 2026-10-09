"""One authenticated uutils 0.2.2 build-only trial; never computes depths."""
import hashlib
import json
import os
import subprocess
import tarfile
from .probe import ROOT
from .modern_trial import OUT, SYSROOT, env

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    frozen=ROOT/'build/historical-rust-measurement/method-v1/0.2.2/source_provenance.json'
    provenance=json.loads(frozen.read_text())
    archive=ROOT/provenance['archive']['cache_path']
    assert sha(archive)==provenance['archive']['sha256']
    folder=OUT/'historical-build'
    folder.mkdir(exist_ok=False)
    with tarfile.open(archive) as tf: tf.extractall(folder/'source',filter='data')
    checkout=next((folder/'source').iterdir())
    assert sha(checkout/'Cargo.toml')==provenance['cargo_toml_sha256']
    assert sha(checkout/'Cargo.lock')==provenance['cargo_lock_sha256']
    mappings=ROOT/'security/historical/rust/vulnerable_function_mappings.json'
    selected=next(r for r in json.loads(mappings.read_text())['records'] if r['cve_id']=='CVE-2026-35338')
    for f in selected['vulnerable_functions']:
        assert sha(checkout/f['source_file'])==f['source_sha256']
    command=[str(SYSROOT/'bin/cargo'),'build','--locked','--manifest-path',str(checkout/'Cargo.toml'),
             '-p','uu_chmod','--bin','chmod','--target=x86_64-unknown-linux-gnu','-j','2']
    environment=env()
    for key in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTUP_TOOLCHAIN'):
        environment.pop(key,None)
    environment.update(RUSTC=str(SYSROOT/'bin/rustc'),RUSTDOC=str(SYSROOT/'bin/rustdoc'),
        CARGO_HOME=str(folder/'cargo-home'),CARGO_TARGET_DIR=str(folder/'target'),
        CARGO_ENCODED_RUSTFLAGS='\x1f'.join(['-Copt-level=0','-Cpanic=unwind','-Zalways-encode-mir']))
    before={p.relative_to(checkout).as_posix():sha(p) for p in checkout.rglob('*') if p.is_file()}
    record={'kind':'build_only_no_analysis','argv':command,'cwd':str(checkout),
        'source_provenance_path':str(frozen.relative_to(ROOT)),'source_provenance_sha256':sha(frozen),
        'mapping_file_sha256':sha(mappings),'selected_mapping':selected,
        'source_manifest_before':before,
        'environment':{k:environment[k] for k in ('RUSTC','RUSTDOC','RUSTUP_HOME','CARGO_HOME','CARGO_TARGET_DIR','LD_LIBRARY_PATH','CARGO_ENCODED_RUSTFLAGS')},
        'features':'unchanged package/bin defaults, matching frozen build selection',
        'configuration_note':'candidate compiler; MIR encoding enabled; no historical measurements accepted or generated'}
    (folder/'launch.json').write_text(json.dumps(record,indent=2))
    with (folder/'stdout.log').open('w') as stdout,(folder/'stderr.log').open('w') as stderr:
        try:
            result=subprocess.run(command,cwd=checkout,env=environment,stdout=stdout,stderr=stderr,timeout=900)
            record.update(returncode=result.returncode,status='built' if result.returncode==0 else 'build_failure')
        except subprocess.TimeoutExpired: record.update(returncode=None,status='timeout')
    after={p.relative_to(checkout).as_posix():sha(p) for p in checkout.rglob('*') if p.is_file()}
    record['source_tree_unchanged']=before==after
    assert record['source_tree_unchanged'], 'candidate source or lock changed'
    (folder/'result.json').write_text(json.dumps(record,indent=2))
    print(record['status'],record['returncode'],flush=True)
    print((folder/'stderr.log').read_text()[-5000:],flush=True)

if __name__=='__main__': main()
