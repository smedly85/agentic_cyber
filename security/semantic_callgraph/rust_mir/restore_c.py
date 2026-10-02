"""Preserve the rejected Rust/SVF instrument before restoring canonical C.

This script never opens or builds a historical Rust source specimen.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from security.historical.rust.semantic_gate import verify_frozen


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserve():
    verify_frozen()
    original = ROOT/'build/semantic-toolchain/SVF'
    archive = ROOT/'build/semantic-toolchain/rust-svf-experimental'
    relative = Path('Release-build/bin/semantic-callgraph-svf')
    expected = 'd081531faa7a82254bf209c347249b94d422ad37f51e850a3b59cca76c2d87e1'
    if archive.exists():
        if digest(archive/relative) != expected:
            raise ValueError('Existing experimental archive does not match; refusing overwrite')
    else:
        if digest(original/relative) != expected:
            raise ValueError('Unexpected canonical helper; refusing archive')
        shutil.copytree(original, archive, symlinks=True)
    if digest(archive/relative) != expected:
        raise ValueError('Experimental preservation failed')
    print('Experimental build preserved:', archive, flush=True)


def build():
    preserve()
    cache=ROOT/'build/rust-mir/c-restoration'
    cache.mkdir(parents=True,exist_ok=True)
    argv=[str(ROOT/'build/semantic-toolchain/venv/bin/cmake'),'--build',
          str(ROOT/'build/semantic-toolchain/SVF/Release-build'),'--target','semantic-callgraph-svf','--parallel','2']
    with (cache/'build.log').open('w') as log:
        result=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT)
    path=ROOT/'build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf'
    actual=digest(path)
    expected='ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2'
    record={'canonical_helper':str(path.relative_to(ROOT)), 'expected_original_sha256':expected,
            'actual_sha256':actual,'build_exit':result.returncode,'restored_exactly':actual==expected,
            'experimental_helper':'build/semantic-toolchain/rust-svf-experimental/Release-build/bin/semantic-callgraph-svf',
            'experimental_sha256':'d081531faa7a82254bf209c347249b94d422ad37f51e850a3b59cca76c2d87e1',
            'canonical_role':'frozen C scientific instrument','experimental_role':'rejected Rust/SVF negative-result provenance'}
    (HERE/'c_restoration.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    print(json.dumps(record,indent=2))
    if result.returncode or actual!=expected:
        raise SystemExit('STOP: exact original C helper not restored; MIR work prohibited')


if __name__=='__main__':
    build() if '--build' in sys.argv else preserve()
