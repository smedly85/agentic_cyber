"""Read-only comparison of existing failed validation; no analyzer invocation."""
from common import ROOT,HERE,OUT,read,write,sha
assert read(OUT/'validation_stop.json')['status']=='STOP'
reference=ROOT/'build/rust-mir/solver-v2-performance/equality-v1/reference/controlled/iterator_flat_map'
records=[]
for run in ('candidate-1','candidate-2'):
    folder=OUT/'equality-v1'/run/'controlled/iterator_flat_map'
    if not (folder/'inclusion.json').exists():continue
    original=read(reference/'inclusion.json');candidate=read(folder/'inclusion.json')
    fields=[]
    for name in sorted(set(original)|set(candidate)):
        a=original.get(name);b=candidate.get(name)
        if a==b:continue
        row={'field':name}
        if isinstance(a,list) and isinstance(b,list):
            import json
            def keyed(xs):return {json.dumps(x,sort_keys=True):x for x in xs}
            aa=keyed(a);bb=keyed(b)
            row.update(reference_count=len(a),candidate_count=len(b),
                reference_only=[aa[k] for k in sorted(aa.keys()-bb.keys())],
                candidate_only=[bb[k] for k in sorted(bb.keys()-aa.keys())])
        else:row.update(reference=a,candidate=b)
        fields.append(row)
    files={name:{'reference_sha256':sha(reference/name),'candidate_sha256':sha(folder/name),
                'identical':sha(reference/name)==sha(folder/name)}
           for name in ('inclusion.json','points_to_state.json','cast_audit.json','exported.json','normalized_graph.json')
           if (folder/name).exists()}
    records.append({'run':run,'case':'controlled/iterator_flat_map','reference_converged':original['converged'],
        'candidate_converged':candidate['converged'],'fields':fields,'files':files})
assert records and any(r['fields'] for r in records)
write(OUT/'equality_failure_evidence.json',{'status':'STOP','candidate_sha256':sha(HERE/'inclusion.py'),
    'case':'controlled/iterator_flat_map','comparisons':records,'historical_analyzer_invocations':0,
    'historical_depths_accepted':0,'amendment_frozen':False,'further_optimization_started':False})
for row in records:
    print(row['run'],'converged',row['reference_converged'],row['candidate_converged'],flush=True)
    print('Different fields:',[r['field'] for r in row['fields']],flush=True)
    print('Scientific files:',{k:v['identical'] for k,v in row['files'].items()},flush=True)
