"""Witness-preserving implementation projection; never fills analyzer edges."""
from collections import Counter, defaultdict, deque
import hashlib
import json
from pathlib import Path
import re
from .scoped_trial import HERE, WORK, OUT, ROOT


def bfs(entry, adjacency):
    distances={entry:0}; paths={entry:[entry]}; queue=deque([entry])
    while queue:
        u=queue.popleft()
        for v in sorted(adjacency.get(u, ())):
            if v not in distances:
                distances[v]=distances[u]+1; paths[v]=paths[u]+[v]; queue.append(v)
    return distances, paths


def project(raw, included):
    """Every projected relation has an actual path with excluded interiors."""
    nodes={f['identity']:f for f in raw['functions']}
    adjacency=defaultdict(list)
    for index,e in enumerate(raw['call_edges']):
        adjacency[e['caller']].append((e['callee'], index))
    for values in adjacency.values(): values.sort()
    relations=[]; frontiers={}
    for start in sorted(included):
        queue=deque([(start,[start],[])])
        seen={start}; found={}; excluded=set()
        while queue:
            u,path,edge_path=queue.popleft()
            for v,index in adjacency[u]:
                if v in included:
                    if v not in found:
                        found[v]={'caller':start,'callee':v,'relation':'implementation_transition',
                                  'dependency_mediated':len(path)>1,'witness_nodes':path+[v],
                                  'witness_edge_indices':edge_path+[index]}
                elif v not in seen:
                    seen.add(v); excluded.add(v)
                    queue.append((v,path+[v],edge_path+[index]))
        relations.extend(found.values()); frontiers[start]=excluded
    projected=defaultdict(set); induced=defaultdict(set)
    for e in relations: projected[e['caller']].add(e['callee'])
    for e in raw['call_edges']:
        if e['caller'] in included and e['callee'] in included: induced[e['caller']].add(e['callee'])
    distances, paths=bfs(raw['entry'],projected)
    induced_depths,_=bfs(raw['entry'],induced)
    full_distances,_=bfs(raw['entry'],{u:{v for v,_ in vs} for u,vs in adjacency.items()})
    assert set(distances)==(set(full_distances)&included), 'projection lost owned reachability'
    dmax=max(distances.values())
    deepest=min(k for k,d in distances.items() if d==dmax)
    coverage=[]
    for owner in sorted(included):
        interior=frontiers[owner]|{owner}
        unresolved=[i for i,s in enumerate(raw['unresolved_indirect_callsites']) if s['caller'] in interior]
        boundaries=sorted(k for k in interior if not nodes[k].get('body_available',True))
        if unresolved or boundaries:
            coverage.append({'owner':owner,'unresolved_site_indices':unresolved,'body_unavailable_nodes':boundaries})
    return dict(functions=[dict(nodes[k], scoped_depth=distances.get(k), scoped_path=paths.get(k)) for k in sorted(included)],
                scoped_edges=sorted(relations,key=lambda e:(e['caller'],e['callee'])),
                entry=raw['entry'],maximum_utility_depth=dmax,deepest_path=paths[deepest],
                deepest_endpoint_count=sum(d==dmax for d in distances.values()),
                direct_induced_reachable=len(induced_depths),projected_reachable=len(distances),
                recovered_owned_nodes=sorted(set(distances)-set(induced_depths)),
                coverage_frontiers=coverage,accepted_historical_measurement=False)


def ownership(raw, sidecar, include_shared, generated_sources=()):
    metadata={}
    for f in sidecar['functions']:
        key=json.dumps([f['def_path_hash'],f['generic_args'],f['promoted'],f['shim']],separators=(',',':'))
        metadata[key]=f
    included=set(); inventory=[]
    for f in raw['functions']:
        meta=metadata[f['function_identity']]
        # Older sidecars contain the actual crate name in the rustc DefId Debug.
        match=re.search(r'~ (\w+)\[',meta['def_id'])
        crate=meta.get('crate') or (match[1] if match else None)
        source=(f.get('source') or {}).get('file','').replace('\\','/')
        owned=crate in (('chmod','uu_chmod','uucore') if include_shared else ('chmod','uu_chmod'))
        project_span=source.startswith('src/') or '/coreutils-3a07ffc5a9bd4c283e75afa548ba1f1957bad242/src/' in source or source in generated_sources
        if meta['shim']!='None' or meta['drop_glue']: reason='compiler_glue_or_shim'
        elif meta['promoted']!='None' or meta.get('def_kind','').startswith(('Const','Static','AnonConst','InlineConst')): reason='constant_or_static_pseudo_body'
        elif not owned: reason='shared_uucore_sensitivity_exclusion' if crate=='uucore' else 'dependency_or_other_crate'
        elif not project_span: reason='unverified_project_source_span'
        elif not meta['body_available']: reason='owned_body_unavailable_boundary'
        else: reason='included'; included.add(f['identity'])
        inventory.append(dict(identity=f['identity'],name=f['name'],crate=crate,source=source,decision=reason))
    assert raw['entry'] in included
    return included,inventory


def derive(directory, label):
    raw=json.loads((directory/'normalized.json').read_text())
    sidecar=json.loads((directory/'graph.dot.depth.json').read_text())
    frozen=json.loads((OUT/'historical-pilot/result.json').read_text())
    result={'input':str(directory),'full_graph_sha256':hashlib.sha256((directory/'normalized.json').read_bytes()).hexdigest(),
            'mapping':frozen['frozen_mapping'],'policies':{}}
    # Authenticated build-generated project source has the same inclusion role
    # as generated C translation units; it is not historical release source.
    build=json.loads((OUT/'historical-build/result.json').read_text())
    generator=Path(build['cwd'])/'src/uucore/build.rs'
    assert hashlib.sha256(generator.read_bytes()).hexdigest()==build['source_manifest_before']['src/uucore/build.rs']
    generated={}
    for f in sidecar['functions']:
        path=Path((f.get('source') or {}).get('file',''))
        if path.name=='embedded_locales.rs' and path.is_relative_to(OUT/'historical-pilot/target'):
            generated[str(path)]={'kind':'configured_build_generated','crate':'uucore',
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'generator':'src/uucore/build.rs','generator_sha256':hashlib.sha256(generator.read_bytes()).hexdigest(),
                'include_site':'src/uucore/src/lib/mods/locale.rs:62',
                'build_record':str((OUT/'historical-pilot/launch.json').relative_to(ROOT))}
    result['generated_source_provenance']=generated
    for shared in (True,False):
        policy='project_implementation' if shared else 'utility_crates_only_sensitivity'
        included,inventory=ownership(raw,sidecar,shared,generated)
        graph=project(raw,included)
        matches=[f for f in graph['functions'] if f['name'].startswith('uu_chmod::') and f['name'].endswith('::chmod')
                 and (f['source'] or {}).get('file','').endswith(frozen['frozen_mapping']['source_file'])
                 and (f['source'] or {}).get('line')==269]
        # Source query ambiguity fails closed; no shallowest-match preference.
        assert len(matches)==1, 'frozen vulnerable source query is absent or ambiguous'
        vulnerable=matches[0]; depth=vulnerable['scoped_depth']
        graph.update(vulnerability_depth=depth,normalized_vulnerability_depth=depth/graph['maximum_utility_depth'] if depth is not None and graph['maximum_utility_depth'] else None,
                     vulnerable_identity=vulnerable['identity'],vulnerable_path=vulnerable['scoped_path'],
                     ownership_inventory=inventory,ownership_counts=dict(Counter(f['decision'] for f in inventory)))
        names={f['identity']:f['name'] for f in raw['functions']}
        graph['vulnerable_path_names']=[names[k] for k in graph['vulnerable_path']] if graph['vulnerable_path'] else None
        graph['deepest_path_names']=[names[k] for k in graph['deepest_path']]
        result['policies'][policy]=graph
        print(label,policy,'depth',depth,'Dmax',graph['maximum_utility_depth'],'nodes',len(included),
              'induced',graph['direct_induced_reachable'],'projected',graph['projected_reachable'],flush=True)
        print('deepest',graph['deepest_path_names'],flush=True)
    destination=WORK/f'{label}-scoped.json'
    previous=WORK/f'{label}-scoped-pre-generated-audit.json'
    if destination.exists() and not previous.exists(): previous.write_bytes(destination.read_bytes())
    destination.write_text(json.dumps(result,indent=2,sort_keys=True))
    return result


if __name__=='__main__':
    import sys
    label=sys.argv[1]
    derive(OUT/'historical-pilot' if label=='baseline' else WORK/'pilot',label)
