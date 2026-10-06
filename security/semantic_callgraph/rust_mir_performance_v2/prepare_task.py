"""Record protected before hashes and immutable validation input inventory."""
import datetime, pathlib
from common import ROOT,HERE,OUT,REFERENCE,REFERENCE_SHA,read,sha,write

def main():
    assert sha(REFERENCE)==REFERENCE_SHA
    assert not (OUT/'preservation_before.json').exists()
    OUT.mkdir(parents=True,exist_ok=True)
    baseline=read(ROOT/'build/historical-rust-diagnostics/solver-v1/preservation_before.json')['files']
    files={}
    for i,(name,expected) in enumerate(baseline.items(),1):
        actual=sha(ROOT/name);assert actual==expected,name;files[name]=actual
        if i%5000==0:print('Before hashes',i,'/',len(baseline),flush=True)
    for folder in ('security/historical/rust/diagnostics/solver-v1','build/historical-rust-diagnostics/solver-v1',
                   'tests/fixtures/rust_mir','tests/fixtures/rust_semantic'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:files[p.relative_to(ROOT).as_posix()]=sha(p)
    write(OUT/'preservation_before.json',{'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':files,'reference_sha256':REFERENCE_SHA,'engineering_note_sha256':sha(HERE/'ENGINEERING_NOTE.md')})
    cases=[]
    def add(group,name,path,wrapped=False,root=None,frozen_flow=None):
        data=read(path);raw=data['api'] if wrapped else data
        if root is None:
            roots=[r['instance_identity'] for r in raw['instances'] if r['instance_identity'].endswith('::crate::main')]
            assert len(roots)==1,(group,name,roots);root=roots[0]
        cases.append({'id':group+'/'+name,'group':group,'name':name,'input_path':path.relative_to(ROOT).as_posix(),
                      'input_sha256':sha(path),'wrapped':wrapped,'root':root,
                      'frozen_flow_path':frozen_flow.relative_to(ROOT).as_posix() if frozen_flow else None})
    base=ROOT/'build/rust-mir'
    folder=base/'continuation/cast-final-v2/run-1'
    controlled=read(folder/'results.json');assert len(controlled)==31
    for c in controlled:add('controlled',c['case'],folder/c['case']/'api.json',root=c['root'],frozen_flow=folder/c['case']/'inclusion.json')
    for group,sub,total in [('focused','core-validation/cast-v1',30),('memory','memory-validation/cast-v1',12),('operations','cast-validation/cast-v3',13)]:
        paths=sorted((base/sub).glob('*/run-1/graph.json'));assert len(paths)==total,(group,len(paths))
        for p in paths:add(group,p.parent.parent.name,p,True)
    add('adapter','std_callbacks',base/'adapter-validation/cast-final-v1/run-1/graph.json',True)
    paths=sorted((base/'transitive-validation/dyn-v1/run-1').glob('*.json'))
    for p in paths:
        data=read(p)
        if isinstance(data,dict) and 'api' in data and 'inclusion' in data:add('transitive',p.stem,p,True)
    manifest=read(ROOT/'security/semantic_callgraph/cross_language_calibration/fixture_manifest.json')
    for pair in manifest['pairs']:
        folder=ROOT/'build/cross-language-calibration-measured/approved-v1/run-1'/pair['pair_id']/'Rust'
        raw=read(folder/'raw.json');roots=[r['instance_identity'] for r in raw['instances'] if r.get('def_path','').split('::')[-1]=='entry' and pair['rust_source'] in r.get('source','')]
        assert len(roots)==1
        add('calibration',pair['pair_id'],folder/'raw.json',root=roots[0],frozen_flow=folder/'inclusion.json')
    assert len([c for c in cases if c['group']=='calibration'])==15
    write(OUT/'input_inventory.json',cases)
    print('Prepared',len(cases),'immutable solver inputs',flush=True)

if __name__=='__main__':main()
