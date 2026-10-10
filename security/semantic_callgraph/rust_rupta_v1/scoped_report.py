"""Package the scoped pilot's saved evidence; no analyzer invocation."""
import hashlib
import json
from pathlib import Path
import re
from .scoped_trial import WORK, HERE, OUT, ROOT


def main():
    result={'accepted_historical_measurement':False,'policy_file':'SCOPED_POLICY.md',
            'provenance':json.loads((HERE/'scoped_provenance.json').read_text()),
            'mechanisms':json.loads((HERE/'scoped_mechanism_results.json').read_text()),
            'variants':{},'regression':{},
            'remaining_blocker':'Missing initializer and formatting callbacks can change implementation reachability and depths.'}
    rows=json.loads((WORK/'regression-results.json').read_text())
    for mode in ('ander','cs'):
        subset=[r for r in rows if r['mode']==mode]
        sites=[s for r in subset for s in r['evaluation']['sites'] if s['expected']]
        assert len(subset)==38 and len({r['program'] for r in subset})==35
        assert all(r['evaluation']['required_expectations_passed'] for r in subset)
        assert len(sites)==23 and all(s['passed'] for s in sites)
        result['regression'][mode]=dict(programs_passed=35,programs_total=35,exact_designated_target_sets=23)
    repeats=json.loads((WORK/'repeat-results.json').read_text())
    assert len(repeats)==8 and all(r['identical'] for r in repeats)
    result['mechanism_repeat_determinism']=dict(identical=8,total=8)
    for label in ('baseline','patched'):
        scoped=json.loads((WORK/f'{label}-scoped.json').read_text())
        directory=OUT/'historical-pilot' if label=='baseline' else WORK/'pilot'
        raw=json.loads((directory/'normalized.json').read_text())
        full=json.loads((directory/'graph.json').read_text())
        names={f['identity']:f['name'] for f in raw['functions']}
        entry={'policies':{},'full_graph_evidence_only':dict(nodes=len(raw['functions']),edges=len(raw['call_edges']),
                maximum_finite_shortest_depth=max(f['raw_call_depth'] for f in full['functions'] if f['reachable_from_entry']),
                unresolved_calls=len(raw['unresolved_indirect_callsites']),body_unavailable=sum(not f['body_available'] for f in raw['functions'])),
                'scoped_artifact':str((WORK/f'{label}-scoped.json').relative_to(ROOT)),
                'scoped_artifact_sha256':hashlib.sha256((WORK/f'{label}-scoped.json').read_bytes()).hexdigest()}
        entry['generated_source_provenance']=scoped['generated_source_provenance']
        for policy,graph in scoped['policies'].items():
            info={k:graph[k] for k in ('vulnerability_depth','maximum_utility_depth','normalized_vulnerability_depth',
                'vulnerable_path_names','deepest_path_names','direct_induced_reachable','projected_reachable',
                'ownership_counts','deepest_endpoint_count')}
            info['projected_edges']=len(graph['scoped_edges'])
            info['mediated_edges']=sum(e['dependency_mediated'] for e in graph['scoped_edges'])
            info['owned_nodes']=len(graph['functions'])
            info['frontiers_with_coverage_gaps']=len(graph['coverage_frontiers'])
            info['included_functions']=[dict(identity=f['identity'],name=f['name'],source=f['source'],depth=f['scoped_depth']) for f in graph['functions']]
            by_pair={(e['caller'],e['callee']):e for e in graph['scoped_edges']}
            for field in ('vulnerable_path','deepest_path'):
                expanded=[]
                for u,v in zip(graph[field],graph[field][1:]):
                    edge=by_pair[u,v]
                    expanded.append(dict(caller=names[u],callee=names[v],dependency_mediated=edge['dependency_mediated'],
                        full_witness=[names[k] for k in edge['witness_nodes']],
                        full_edges=[raw['call_edges'][i] for i in edge['witness_edge_indices']]))
                info[field+'_evidence']=expanded
            if label=='patched':
                # A separate scoped graph is retained locally; omit the enormous
                # excluded-node ledger here, which remains in the build artifact.
                compact={k:v for k,v in graph.items() if k!='ownership_inventory'}
                (HERE/(policy+'_graph.json')).write_text(json.dumps(compact,indent=2,sort_keys=True)+'\n')
            entry['policies'][policy]=info
        result['variants'][label]=entry
    pilot=json.loads((WORK/'pilot/result.json').read_text())
    result['pilot_invocation']=pilot
    resource=(WORK/'pilot/resources.txt').read_text()
    result['pilot_peak_rss_kib']=int(re.search(r'Maximum resident set size \(kbytes\): (\d+)',resource)[1])
    build=json.loads((OUT/'historical-build/result.json').read_text())
    checkout=Path(build['cwd'])
    changed=[p for p,h in build['source_manifest_before'].items() if hashlib.sha256((checkout/p).read_bytes()).hexdigest()!=h]
    assert not changed
    result['historical_source_preservation']={'files_checked':len(build['source_manifest_before']),'changed':changed}
    (HERE/'scoped_pilot_results.json').write_text(json.dumps(result,indent=2)+'\n')
    for label,v in result['variants'].items():
        print(label,v['full_graph_evidence_only'],flush=True)
        for name,g in v['policies'].items():
            print(name,{k:g[k] for k in ('owned_nodes','projected_edges','mediated_edges','frontiers_with_coverage_gaps','ownership_counts')},flush=True)
    print('source preservation',result['historical_source_preservation'],flush=True)


if __name__=='__main__': main()
