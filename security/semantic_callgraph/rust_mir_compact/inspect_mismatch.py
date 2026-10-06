"""Inspect preserved state only, without executing any analysis."""
import json
from common import ROOT,OUT,read,write
assert read(OUT/'validation_stop.json')['status']=='STOP'
base=ROOT/'build/rust-mir/solver-v2-performance/equality-v1/reference/controlled/iterator_flat_map'
candidate=OUT/'equality-v1/candidate-1/controlled/iterator_flat_map'
a=read(base/'points_to_state.json');b=read(candidate/'points_to_state.json')
key=lambda x:json.dumps(x,sort_keys=True)
aa={key(cell):{key(v) for v in values} for cell,values in a['cells']}
bb={key(cell):{key(v) for v in values} for cell,values in b['cells']}
differences=[]
for cell in sorted(aa.keys()|bb.keys()):
    av=aa.get(cell,set());bv=bb.get(cell,set())
    if av!=bv or (cell in aa)!=(cell in bb):
        differences.append({'cell':json.loads(cell),'reference_present':cell in aa,'candidate_present':cell in bb,
            'reference_only_facts':[json.loads(v) for v in sorted(av-bv)],
            'candidate_only_facts':[json.loads(v) for v in sorted(bv-av)]})
summary={'case':'controlled/iterator_flat_map','reference_sweeps':a['completed_sweeps'],'candidate_sweeps':b['completed_sweeps'],
    'reference_cells':len(aa),'candidate_cells':len(bb),'different_cells':len(differences),
    'reference_only_facts':sum(len(r['reference_only_facts']) for r in differences),
    'candidate_only_facts':sum(len(r['candidate_only_facts']) for r in differences),
    'collapsed_groups_identical':a['collapsed']==b['collapsed'],'cell_membership_index_identical':a['cells_by_local']==b['cells_by_local']}
write(OUT/'state_mismatch_details.json',{'summary':summary,'differences':differences})
print(summary,flush=True)
