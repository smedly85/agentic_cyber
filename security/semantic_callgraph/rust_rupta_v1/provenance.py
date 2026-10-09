"""Record exact toolchain/CLI identity; no compiler defaults are changed."""
import hashlib
import json
import subprocess
from security.semantic_callgraph.rust_rupta_v1.probe import ROOT,BASE,SYSROOT,PTA,environment

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for data in iter(lambda:f.read(4*1024*1024),b''): h.update(data)
    return h.hexdigest()

if __name__=='__main__':
    result={'source_url':'https://github.com/rustanlys/rupta','commands':[]}
    commands=[['git','-C',str(BASE/'upstream'),'rev-parse','HEAD'],
              ['git','-C',str(BASE/'upstream'),'status','--porcelain'],
              [str(SYSROOT/'bin/rustc'),'-vV'],[str(SYSROOT/'bin/cargo'),'-V'],
              [str(BASE/'cargo/bin/rustup'),'component','list','--installed'],
              [str(PTA),'--help'],['uname','-a']]
    for cmd in commands:
        p=subprocess.run(cmd,env=environment(),cwd=BASE,text=True,capture_output=True)
        result['commands'].append({'argv':cmd,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
    files=[PTA,BASE/'target/debug/cargo-pta',BASE/'upstream/Cargo.lock',BASE/'upstream/Cargo.toml',BASE/'upstream/rust-toolchain.toml',
           SYSROOT/'bin/rustc',SYSROOT/'bin/cargo',BASE/'rustup-init',BASE/'rustup-init.sha256']
    files+=list((SYSROOT/'lib').glob('librustc_driver*.so'))+list((SYSROOT/'lib/rustlib').glob('multirust-channel-manifest.toml'))
    result['sha256']={str(p.relative_to(ROOT)):sha(p) for p in files}
    result['authentication']='HTTPS upstream Git checkout; rustup component manifest/checksum verification; rustup-init SHA256 checked. No claim of independently verified release signatures.'
    (BASE/'provenance.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
