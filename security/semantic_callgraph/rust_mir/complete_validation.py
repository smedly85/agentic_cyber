"""Controlled-only graph serialization, shortest paths, and raw edge provenance."""
import argparse
from collections import Counter, deque
import hashlib
import json
import sys
from prepare import ROOT, HERE, require_c
from probe import BASE
sys.path.insert(0,str(ROOT))
from security.semantic_callgraph.rust_mir.graph import export_partial


def write(path, value):
    content=json.dumps(value,sort_keys=True,indent=2)+'\n'
    path.write_text(content)
    assert json.loads(content)==value
    return hashlib.sha256(content.encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--label',required=True)
    args=parser.parse_args()
    if not args.label.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c();directory=BASE/'continuation'/args.label
    runs=[]
    for run in ('run-1','run-2'):
        cases=[]
        records=json.loads((directory/run/'results.json').read_text())
        adjudicated=json.loads((directory/run/'semantic_adjudication.json').read_text())
        for original,decision in zip(records,adjudicated):
            # Adjudicator orders by preregistered JSON keys; match by case explicitly.
            case=original['case'];decision=next(d for d in adjudicated if d['case']==case)
            path=directory/run/case
            raw=json.loads((path/'api.json').read_text());flow=json.loads((path/'inclusion.json').read_text())
            active=set(flow['active_instances'])
            functions={r['instance_identity']:r for r in raw['instances'] if r['instance_identity'] in active}
            scientific=export_partial({'instances':list(functions.values())},flow)
            fingerprint=write(path/'scientific_graph.json',scientific)
            adjacency={i:[] for i in active}
            for s in flow['sites']:adjacency[s['owner']].extend(s['targets'])
            root=original['root'];previous={root:None};queue=deque([root]);distance={root:0}
            while queue:
                owner=queue.popleft()
                for target in sorted(set(adjacency[owner])):
                    if target not in previous:
                        previous[target]=owner;distance[target]=distance[owner]+1;queue.append(target)
            paths=[]
            for target in sorted(i for i in active if i.split('::',1)[1] in decision['expected_targets']):
                nodes=[target]
                while nodes[-1]!=root and nodes[-1] in previous:nodes.append(previous[nodes[-1]])
                nodes.reverse()
                valid=nodes[0]==root and len(nodes)-1==distance[target] and all(b in adjacency[a] for a,b in zip(nodes,nodes[1:]))
                counts=Counter()
                for node in nodes[1:]:
                    row=functions[node];kind=row.get('instance_kind')
                    category=('drop_glue_edges' if kind=='drop_glue' else
                              'compiler_shim_edges' if row.get('compiler_generated') and kind is not None else
                              'std_core_edges' if row.get('defining_crate') in ('std','core','alloc') else
                              'user_application_edges')
                    counts[category]+=1
                paths.append({'target':target,'instances':nodes,'shortest_path_valid':valid,
                              'raw_edges':len(nodes)-1,**{k:counts[k] for k in ('drop_glue_edges','compiler_shim_edges','std_core_edges','user_application_edges')}})
            ledger=flow['required_body_ledger']
            blockers=[r for r in ledger if r['disposition'] in ('missing_required_body','unsupported_required_body')]
            complete=decision['complete_semantic_pass'] and bool(paths) and all(p['shortest_path_valid'] for p in paths) and not blockers
            cases.append({'case':case,'complete_semantic_pass':complete,'static_assertions_pass':decision['semantic_assertions_pass'],
                          'paths':paths,'body_counts':dict(Counter(r['disposition'] for r in ledger)),
                          'origin_counts':dict(Counter(r['origin'] for r in ledger if r['origin'])),
                          'required_body_blockers':blockers,'unsupported_operations':flow['unsupported_operations'],
                          'unsupported_operation_inventory':flow['unsupported_operation_inventory'],
                          'unresolved_callsites':decision['unresolved_callsites'],'graph_sha256':fingerprint})
        fingerprint=write(directory/run/'complete_validation.json',cases);runs.append((cases,fingerprint))
    write(directory/'complete_validation.json',{'cases':runs[0][0],'passed':sum(c['complete_semantic_pass'] for c in runs[0][0]),
          'total':31,'deterministic':runs[0][1]==runs[1][1],'fingerprints':[r[1] for r in runs],
          'primary_metric':'raw semantic Instance edges','accepted_backend':False})
    print(sum(c['complete_semantic_pass'] for c in runs[0][0]),'/31 complete static gate',flush=True)


if __name__=='__main__':main()
