"""Case-specific static semantic assertions plus uncompromised required-body gates."""
import argparse
from collections import defaultdict, deque
import hashlib
import json
from prepare import ROOT,HERE,require_c
from probe import BASE


def label(identity):return identity.split('::',1)[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',required=True)
    args=parser.parse_args()
    if not args.label.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c()
    directory=BASE/'continuation'/args.label
    specs_path=ROOT/'tests/fixtures/rust_mir/semantic_expectations.json'
    specs=json.loads(specs_path.read_text())
    runs=[]
    for run in ('run-1','run-2'):
        cases=[]
        for case,spec in specs.items():
            raw=json.loads((directory/run/case/'api.json').read_text())
            graph=json.loads((directory/run/case/'inclusion.json').read_text())
            records={r['instance_identity']:r for r in raw['instances']}
            active=set(graph['active_instances']); names={label(i) for i in active}
            user_targets={'crate::target','crate::alternate','crate::third','semantic_dependency::cross_target'}
            expected_targets=spec.get('user_targets',['crate::target'])
            actual_targets=sorted(names & user_targets)
            missing=sorted(set(spec.get('nodes',[]))-names)
            missing.extend('target:'+v for v in set(expected_targets)-set(actual_targets))
            extra=['target:'+v for v in set(actual_targets)-set(expected_targets)]
            edges={(label(s['owner']),label(t)) for s in graph['sites'] for t in s['targets']}
            for edge in spec.get('edges',[]):
                if tuple(edge) not in edges:missing.append('edge:'+repr(edge))
            adapters=sorted(n for n in names if all(f in n for f in spec.get('adapter_fragments',[]))) if 'adapter_fragments' in spec else []
            if 'adapter_fragments' in spec and not adapters:missing.append('adapter:'+repr(spec['adapter_fragments']))
            indirect={(r['instance_identity'],s['block']) for r in raw['instances'] for s in r['calls'] if s['status'].startswith('unresolved')}
            sites=[]
            for owner,targets in spec.get('sites',{}).items():
                found=[s for s in graph['sites'] if label(s['owner'])==owner and (s['owner'],s['block']) in indirect]
                actual=sorted({label(t) for s in found for t in s['targets']})
                site_missing=sorted(set(targets)-set(actual));site_extra=sorted(set(actual)-set(targets))
                if len(found)!=1:site_missing.append('expected exactly one callsite')
                sites.append({'owner':owner,'expected_targets':targets,'actual_targets':actual,'missing':site_missing,'unexpected':site_extra})
                missing.extend(owner+':'+v for v in site_missing);extra.extend(owner+':'+v for v in site_extra)
            if 'indirect_target_union' in spec:
                actual={label(t) for s in graph['sites'] if (s['owner'],s['block']) in indirect for t in s['targets']}
                missing.extend('indirect:'+v for v in set(spec['indirect_target_union'])-actual)
                extra.extend('indirect:'+v for v in actual-set(spec['indirect_target_union']))
            unresolved=[s for s in graph['sites'] if not s['targets']]
            unavailable=[i for i in sorted(active) if i not in records or records[i].get('body_classification')=='missing_required_body']
            body_gate=not unavailable and not graph['unsupported_operations'] and not unresolved
            assertion_pass=not missing and not extra and graph['converged']
            cases.append({'case':case,'expected_nodes':spec.get('nodes',[]),'actual_nodes':sorted(names),
                          'expected_targets':expected_targets,'actual_targets':actual_targets,
                          'missing':sorted(missing),'unexpected':sorted(extra),'indirect_sites':sites,
                          'adapter_nodes':adapters,'semantic_assertions_pass':assertion_pass,
                          'required_body_gate_pass':body_gate,'unavailable_required_instances':unavailable,
                          'unsupported_operations':graph['unsupported_operations'],'unresolved_callsites':unresolved,
                          'complete_semantic_pass':assertion_pass and body_gate,
                          'body_inventory':graph.get('body_inventory',[])})
        document=json.dumps(cases,sort_keys=True,indent=2)+'\n'
        (directory/run/'semantic_adjudication.json').write_text(document)
        runs.append({'cases':cases,'sha256':hashlib.sha256(document.encode()).hexdigest()})
    result={'cases':runs[0]['cases'],'static_assertions_passed':sum(r['semantic_assertions_pass'] for r in runs[0]['cases']),
            'complete_semantic_passed':sum(r['complete_semantic_pass'] for r in runs[0]['cases']),
            'total':31,'deterministic':runs[0]['sha256']==runs[1]['sha256'],
            'fingerprints':[r['sha256'] for r in runs], 'accepted_backend':False,
            'expectations_sha256':hashlib.sha256(specs_path.read_bytes()).hexdigest()}
    (directory/'semantic_adjudication.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print('Static assertions:',result['static_assertions_passed'],'/31; complete semantic gate:',result['complete_semantic_passed'],'/31',flush=True)


if __name__=='__main__':main()
