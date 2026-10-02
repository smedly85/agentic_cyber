"""Acquire exact compiler components into an isolated controlled-only sysroot."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from security.historical.rust.semantic_gate import verify_frozen


def require_c(*, regression=True):
    verify_frozen()
    record=json.loads((HERE/'c_restoration.json').read_text())
    helper=ROOT/record['canonical_helper']
    if hashlib.sha256(helper.read_bytes()).hexdigest()!=record['expected_original_sha256']:
        raise ValueError('Canonical C instrument must be restored first')
    if regression:
        result=json.loads((ROOT/'build/rust-mir/c-restoration/regression/results.json').read_text())
        if not result['passed'] or len(result['controlled'])!=11 or len(result['observations'])!=9:
            raise ValueError('C regression gate has not passed')


def main():
    # Acquisition is not analysis; analysis must also await the C replay gate.
    require_c(regression=False)
    base=ROOT/'build/rust-mir'
    downloads=base/'downloads'
    downloads.mkdir(parents=True,exist_ok=True)
    rows=[]
    for component in ('rustc','rust-std','cargo','rustc-dev','rust-src'):
        name=component+'-1.93.0'+('' if component=='rust-src' else '-x86_64-unknown-linux-gnu')
        url='https://static.rust-lang.org/dist/'+name+'.tar.xz'
        archive=downloads/(name+'.tar.xz')
        checksum=downloads/(name+'.tar.xz.sha256')
        for path in (archive,checksum):
            cached=ROOT/'build/historical-rust/semantic/downloads'/path.name
            if not path.exists() and cached.exists(): shutil.copy2(cached,path)
        if not checksum.exists():
            checksum.write_bytes(urllib.request.urlopen(url+'.sha256',timeout=60).read())
        expected=checksum.read_text().split()[0]
        if not archive.exists():
            print('Downloading',component,flush=True)
            with urllib.request.urlopen(url,timeout=60) as src, archive.open('wb') as dst:
                shutil.copyfileobj(src,dst)
        actual=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
        if actual!=expected: raise ValueError('Official checksum mismatch: '+component)
        marker=downloads/(name+'.installed')
        if not marker.exists():
            with tarfile.open(archive) as tar: tar.extractall(downloads,filter='data')
            with (downloads/(name+'.install.log')).open('w') as log:
                subprocess.run(['bash','./install.sh','--prefix=../../toolchain','--disable-ldconfig'],cwd=downloads/name,
                               stdout=log,stderr=subprocess.STDOUT,check=True)
            marker.write_text(expected+'\n')
        rows.append({'component':component,'url':url,'sha256':actual})
        print(component,'verified and installed',flush=True)
    (HERE/'toolchain_acquisition.json').write_text(json.dumps(rows,indent=2,sort_keys=True)+'\n')
    subprocess.run([str(base/'toolchain/bin/rustc'),'-vV'],check=True)


if __name__=='__main__': main()
