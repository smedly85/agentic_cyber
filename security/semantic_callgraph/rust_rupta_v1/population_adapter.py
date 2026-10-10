"""Ander sidecar reader without the fixture-only source-label union view.

The general fixture adapter requires that optional view to have unique labels.
Historical graphs can contain equal display names for distinct compiler items.
Pretty-printed generic arguments also omit crate-version disambiguators. Retain
upstream FuncIds when exported identity text collides; never merge their edges.
This reader does not infer targets or alter any analyzer output.
"""
from collections import Counter, defaultdict
import json
from pathlib import Path

def base_key(f):
    return json.dumps([f['def_path_hash'],f['generic_args'],f['promoted'],f['shim']],separators=(',',':'))

def identity_keys(functions):
    counts=Counter(base_key(f) for f in functions)
    return {f['id']:base_key(f)+((' @ exported '+f['id']) if counts[base_key(f)]>1 else '') for f in functions}

def parse(directory, mode):
    assert mode=='ander', 'Historical reader must not collapse context-sensitive nodes'
    data=json.loads((Path(directory)/'graph.dot.depth.json').read_text())
    functions={f['id']:f for f in data['functions']}
    assert len(functions)==len(data['functions'])
    ids=identity_keys(data['functions'])
    assert all(n['id']==n['function'] for n in data['nodes']), 'Unexpected contexts in ander graph'
    assert len({ids[n['id']] for n in data['nodes']})==len(data['nodes'])
    site_by_key={(s['caller'],s['location']):s for s in data['callsites']}
    assert len(site_by_key)==len(data['callsites'])
    rows=[]
    for n in data['nodes']:
        f=functions[n['function']]
        rows.append(dict(identity=ids[n['id']],name=f['name'],language='Rust',function_identity=ids[f['id']],
                         source=f['source'],source_file=(f['source'] or {}).get('file',''),body_available=f['body_available'],
                         special_model=f['special_model'],drop_glue=f['drop_glue']))
    edges=[];external=[];unresolved=[];observed=defaultdict(set)
    for e in data['edges']:
        s=site_by_key[(e['caller'],e['location'])]
        assert e['callee'] in s['targets']
        observed[(e['caller'],e['location'])].add(e['callee'])
        row=dict(caller=ids[e['caller']],callee=ids[e['callee']],
                 edge_type='direct' if s['kind']=='StaticDispatch' else 'indirect_resolved',
                 pointer_analysis_backend='RUPTA separate Drop/export trial',pointer_analysis=mode,
                 callsite=dict(mir_location=s['location'],**(s['source'] or {})),
                 indirect_target_count=len(set(s['targets'])) if s['kind']!='StaticDispatch' else None,
                 indirect_target_set=sorted({ids[t] for t in s['targets']}) if s['kind']!='StaticDispatch' else None)
        edges.append(row)
        if not functions[e['callee']]['body_available']:
            external.append(dict(row,callee_name=functions[e['callee']]['name'].split('::')[-1],boundary='body_unavailable'))
    for s in data['callsites']:
        assert observed[(s['caller'],s['location'])]==set(s['targets'])
        if s['kind']!='StaticDispatch' and not s['targets']:
            unresolved.append(dict(caller=ids[s['caller']],callsite=dict(mir_location=s['location'],**(s['source'] or {})),
                                   kind=s['kind'],origin='explicit internal recognized-call inventory'))
    raw=dict(functions=rows,call_edges=edges,external_calls=external,unresolved_indirect_callsites=unresolved,
             unresolved_inventory_complete=False,unresolved_scope='complete only for internally recognized indirect callsites',
             entry=ids[data['entry']],analysis_mode=mode,projection='function instances')
    for field in ('functions','call_edges','external_calls','unresolved_indirect_callsites'):
        raw[field].sort(key=lambda v:json.dumps(v,sort_keys=True))
    collisions=defaultdict(list)
    for f in data['functions']:collisions[base_key(f)].append(f)
    audit=dict(display_label_collisions=sum(n>1 for n in Counter(f['name'] for f in data['functions']).values()),
               identity_text_collisions=[v for v in collisions.values() if len(v)>1],
               policy='Keep upstream function nodes distinct; append exported FuncId only when identity text collides. No cross-run stability claim for the suffix. No source-level union graph is used.')
    return raw,None,audit
