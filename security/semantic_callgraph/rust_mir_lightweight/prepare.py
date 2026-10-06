import ast,datetime
from common import ROOT,HERE,OUT,OLD,read,write,sha
assert not (OUT/'preservation_before.json').exists()
prior=ROOT/'build/rust-mir/solver-compact'
files=read(prior/'preservation_before.json')['files']
for i,(name,h) in enumerate(files.items(),1):
    assert sha(ROOT/name)==h,name
    if i%5000==0:print('Protected before',i,flush=True)
for name,h in read(prior/'stop_evidence_manifest.json')['files'].items():assert sha(ROOT/name)==h,name
for folder in (prior,ROOT/'security/semantic_callgraph/rust_mir_compact'):
    for p in folder.rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:files[p.relative_to(ROOT).as_posix()]=sha(p)
write(OUT/'preservation_before.json',{'files':files,'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
source=(ROOT/'security/historical/rust/measure_historical.py').read_text();tree=ast.parse(source)
definitions=[ast.get_source_segment(source,n) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('source_line','definition_matches')]
assert len(definitions)==2
(HERE/'mapping.py').write_text('"""Exact source/DefPath/span resolver copied from frozen historical orchestration. No solver import."""\nimport re\n\n'+'\n\n'.join(definitions)+'\n')
write(OUT/'input_inventory.json',read(ROOT/'build/rust-mir/solver-v2-performance/input_inventory.json'))
contexts=[]
for release,utility in sorted({(r['release'],r['utility']) for r in read(OLD/'observation_plan.json')['function_contexts']}):
    directory=OLD/release/'semantic'/utility/'run-1'
    if not (directory/'raw.json').exists():
        contexts.append({'release':release,'utility':utility,'available':False});continue
    context={'release':release,'utility':utility,'available':True,'files':{}}
    for name in ('raw.json','entry_resolution.json','launch.json'):
        p=directory/name;context['files'][name]={'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)}
    contexts.append(context)
write(OUT/'historical_input_inventory.json',contexts)
print('PREPARATION PASS',len(files),'protected files;',len(contexts),'historical contexts',flush=True)
