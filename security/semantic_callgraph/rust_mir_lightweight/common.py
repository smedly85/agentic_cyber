import hashlib,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[3]
HERE=pathlib.Path(__file__).parent
OUT=ROOT/'build/rust-mir/lightweight-v1'
OLD=ROOT/'build/historical-rust-measurement/method-v1'
RESULTS=ROOT/'security/historical/rust/results/rust-only-lightweight-v1'
REFERENCE=ROOT/'security/semantic_callgraph/rust_mir/inclusion.py'
REFERENCE_SHA='12ba550d3f52f20f989ff596d292bc4ebdb2608ccc5fcd47beef16ad4d40d871'
def read(p):return json.loads(pathlib.Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with pathlib.Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
def write(p,x):
    p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,sort_keys=True,indent=2)+'\n')
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
