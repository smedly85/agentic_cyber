"""Audit diagnostic ledger completeness and numerical/path consistency."""
import csv
from .population_runner import ROOT, HERE, BASE, REPORT, read, write, sha, plan

def check_path(path, depth, scoped, raw):
    assert len(path['transitions'])==depth==len(path['functions'])-1
    included={n['identity'] for n in scoped['functions']}
    assert path['functions'][0]['identity']==scoped['entry']
    for a,b,t in zip(path['functions'],path['functions'][1:],path['transitions']):
        assert (t['caller'],t['callee'])==(a['identity'],b['identity'])
        assert t['witness_nodes'][0]==t['caller'] and t['witness_nodes'][-1]==t['callee']
        assert not (set(t['witness_nodes'][1:-1]) & included)
        assert t['full_call_edges']==[raw['call_edges'][i] for i in t['witness_edge_indices']]
        assert [(e['caller'],e['callee']) for e in t['full_call_edges']]==list(zip(t['witness_nodes'],t['witness_nodes'][1:]))

def main():
    result=read(REPORT/'historical_rupta_results.json'); records,planned,groups=plan()
    assert len(result['cves'])==45
    assert {c['cve_id'] for c in result['cves']}=={c['cve_id'] for c in records}
    assert {r['observation_id'] for r in result['observations']}=={r['observation_id'] for r in planned}
    assert len(result['observations'])==len(planned)
    assert result['summary']['collection_status']=='complete_diagnostic_attempts'
    assert all(not r['independently_verified'] and not r['accepted_historical_measurement'] for r in result['observations'])
    witnessed=0
    for p in result['programs']:
        observations=[r for r in result['observations'] if r['group']==p['key']]
        if p['analysis_status']!='completed':
            assert all(r['depth'] is None for r in observations);continue
        directory=ROOT/p['analysis_directory'];raw=read(directory/'normalized.json')
        assert sha(directory/'normalized.json')==p['graph_sha256']
        scoped=read(directory/'primary-graph.json')
        assert max(n['scoped_depth'] for n in scoped['functions'] if n['scoped_depth'] is not None)==p['maximum_depth']
        check_path(p['deepest_path'],p['maximum_depth'],scoped,raw)
        for r in observations:
            if r['platform']!='linux':
                assert r['depth'] is None and r['maximum_depth'] is None;continue
            if r['depth'] is not None:
                assert r['measurement_validity']=='provisional_graph_observed'
                assert r['maximum_depth']==p['maximum_depth']
                assert r['normalized_depth']==r['depth']/p['maximum_depth']
                assert len({i['compiler_definition']['def_path_hash'] for i in r['instances']})==1
                assert r['depth']==min(i['depth'] for i in r['instances'] if i['depth'] is not None)
                check_path(r['shortest_path'],r['depth'],scoped,raw);witnessed+=1
    csv.field_size_limit(100_000_000)
    counts={}
    for name,expected in (('historical_rupta_cves.csv',45),('historical_rupta_observations.csv',len(planned)),('historical_rupta_program_depths.csv',len(groups))):
        with (REPORT/name).open(newline='') as f: rows=list(csv.DictReader(f))
        assert len(rows)==expected;counts[name]=len(rows)
    assert sum(c['numerical_observations'] for c in result['cves'])==witnessed
    write(REPORT/'audit_checks.json',dict(status='PASS',population_cves=45,table_counts=counts,
        numerical_observations_with_checked_path_witnesses=witnessed,results_sha256=sha(REPORT/'historical_rupta_results.json'),
        checked='Exact frozen population and observation identities, one-definition instance aggregation, platform isolation, graph hashes, every reported vulnerability/deepest path witness, BFS maximum and normalized ratios. Not scientific completeness acceptance.'))
    print('AUDIT PASS',witnessed,'numerical observations',flush=True)

if __name__=='__main__':main()
