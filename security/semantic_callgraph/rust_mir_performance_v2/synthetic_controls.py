"""Extra exactness controls for cache invalidation and the unchanged sweep cap."""
from common import ROOT,OUT,write,sha

def copy(dst,src):return {'kind':'copy','destination':dst,'source':src,'source_span':'synthetic:1:1'}
def fixture(constraints,calls=()):
    return {'instances':[{'instance_identity':'entry','constraints':constraints,'calls':list(calls)}]}

cases={
    'delta_fanout':fixture([copy([3,[]],{'place':[2,[]]}),copy([2,[]],{'place':[1,[]]}),
                           copy([4,[]],{'place':[1,[]]}),copy([1,[]],{'function':'a'}),copy([1,[]],{'function':'b'})]),
    'prefix_membership_growth':fixture([copy([2,[]],{'place':[1,[]]}),copy([3,['field:0']],{'place':[1,[]]}),
                                        copy([1,['field:1']],{'function':'a'}),copy([1,['variant:1','field:0']],{'function':'b'})]),
    'collapsed_destination_transfer':fixture([copy([2,['field:0']],{'place':[1,[]]}),
        {'kind':'reinterpret','destination':[3,[]],'source':{'place':[2,[]]},'source_span':'synthetic:2:1'},
        copy([1,[]],{'function':'late'})]),
    'late_empty_collapse_member':fixture([
        {'kind':'reference','destination':[2,[]],'source':{'place':[1,['field:late']]},'source_span':'synthetic:3:1'},
        {'kind':'reinterpret','destination':[3,[]],'source':{'place':[1,[]]},'source_span':'synthetic:4:1'}],
        [{'block':0,'status':'unresolved_dyn','dyn_candidates':[],'trait_method':'trait::method',
          'arguments':[{'place':[2,[]]}],'destination':[0,[]],'source':'synthetic:5:1'}]),
    'sweep_cap_300_step_chain':fixture([copy([i,[]],{'place':[i-1,[]]}) for i in range(300,0,-1)]+
                                      [copy([0,[]],{'function':'terminal'})])}
rows=[]
for name,raw in cases.items():
    path=OUT/'synthetic-inputs'/f'{name}.json';assert not path.exists();write(path,raw)
    rows.append({'id':'synthetic/'+name,'group':'synthetic','name':name,'input_path':path.relative_to(ROOT).as_posix(),
                 'input_sha256':sha(path),'wrapped':False,'root':'entry','frozen_flow_path':None})
write(OUT/'synthetic_input_inventory.json',rows)
print('Prepared',len(rows),'synthetic cache/cap controls')
