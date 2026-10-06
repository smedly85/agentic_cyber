"""Separate candidate tooling; never changes reference or accepted results."""
import hashlib, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).parent
OUT = ROOT / 'build/rust-mir/solver-compact'
REFERENCE = ROOT / 'security/semantic_callgraph/rust_mir/inclusion.py'
REFERENCE_SHA = '12ba550d3f52f20f989ff596d292bc4ebdb2608ccc5fcd47beef16ad4d40d871'

def read(p): return json.loads(pathlib.Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with pathlib.Path(p).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def write(p,value):
    p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
