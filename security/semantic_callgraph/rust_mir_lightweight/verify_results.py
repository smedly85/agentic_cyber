"""Read-only consistency checks on published lightweight results."""
from collections import deque
from common import ROOT,OUT,OLD,RESULTS,read,write,sha
from study import verify
import argparse,pathlib

parser=argparse.ArgumentParser();parser.add_argument('--output',type=pathlib.Path,required=True)
output=parser.parse_args().output
assert not output.exists(),'Choose a fresh verification output path'

fingerprint=verify()
result=read(RESULTS/'semantic_results.json')
assert result['method_fingerprint']==fingerprint
plan=read(OLD/'observation_plan.json')['function_contexts']
rows=result['observations']
verified=[r for r in rows if r.get('context_observation_id')]
assert len(verified)==len(plan)==51
assert {r['context_observation_id'] for r in verified}=={r['context_observation_id'] for r in plan}
mappings=read(ROOT/'security/historical/rust/vulnerable_function_mappings.json')['records']
assert {r['cve'] for r in rows}=={m['cve_id'] for m in mappings}
assert len({r['cve'] for r in rows})==45
for m in mappings:
    if m['mapping_status']!='verified':
        expected='not_applicable' if m['mapping_status']=='not_applicable' else 'unresolved_mapping'
        assert all(r['status']==expected and r['vulnerability_depth'] is None for r in rows if r['cve']==m['cve_id'])
graphs={};gates=0
for context in result['program_contexts']:
    if context['max_depth'] is None:continue
    path=ROOT/context['graph_artifact'];graph=read(path)
    assert sha(path)==context['graph_sha256']==sha(path.parent.parent/'run-2/graph.json')
    for run in ('run-1','run-2'):
        assert read(path.parent.parent/run/'gate.json')['status']=='PASS';gates+=1
    edges={}
    for edge in graph['call_edges']:edges.setdefault(edge['caller'],set()).add(edge['callee'])
    distances={context['entry']:0};queue=deque(distances)
    while queue:
        caller=queue.popleft()
        for callee in edges.get(caller,()):
            if callee not in distances:distances[callee]=distances[caller]+1;queue.append(callee)
    assert max(distances.values())==context['max_depth']
    assert len(distances)==context['reachable_instances']
    for node in graph['functions']:
        assert node['raw_call_depth']==distances.get(node['identity'])
        if node['raw_call_depth'] is not None:
            assert len(node['shortest_call_path']['edges'])==node['raw_call_depth']
    graphs[context['graph_artifact']]=distances
for row in verified:
    if row['vulnerability_depth'] is None:continue
    assert row['status'].startswith('measured_')
    selected=row['selected'];distance=graphs[row['graph_artifact']][selected['instance']]
    assert row['vulnerability_depth']==distance==min(i['depth'] for i in row['instances'] if i['depth'] is not None)
    assert len(selected['path']['edges'])==distance
    if distance==0:assert row['entry']==selected['instance']
for name,expected in read(RESULTS/'artifact_hashes.json')['files'].items():assert sha(RESULTS/name)==expected
write(output,{'status':'PASS','population_CVEs':45,'verified_function_contexts':51,
    'graphs_independently_BFS_checked':len(graphs),'passing_historical_gates':gates,
    'method_fingerprint':fingerprint,'published_artifact_hashes_verified':True})
print('RESULT VERIFICATION PASS',len(graphs),'graphs;',gates,'gates; 51 function contexts; 45 CVEs')
