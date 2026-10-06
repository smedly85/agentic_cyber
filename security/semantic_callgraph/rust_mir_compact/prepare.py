import datetime
from common import ROOT,HERE,OUT,read,write,sha,REFERENCE,REFERENCE_SHA
assert sha(REFERENCE)==REFERENCE_SHA
assert not (OUT/'preservation_before.json').exists()
previous=ROOT/'build/rust-mir/solver-v2-performance'
files=read(previous/'preservation_before.json')['files']
for i,(name,expected) in enumerate(files.items(),1):
    assert sha(ROOT/name)==expected,name
    if i%5000==0:print('Protected before',i,flush=True)
for name,expected in read(previous/'repair_evidence_manifest.json')['files'].items():assert sha(ROOT/name)==expected,name
for folder in (previous,ROOT/'security/semantic_callgraph/rust_mir_performance_v2'):
    for p in folder.rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:files[p.relative_to(ROOT).as_posix()]=sha(p)
write(OUT/'preservation_before.json',{'files':files,'reference_sha256':REFERENCE_SHA,
    'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'engineering_note_sha256':sha(HERE/'ENGINEERING_NOTE.md')})
print('Preservation baseline PASS',len(files),flush=True)
