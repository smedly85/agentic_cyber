import json
from security.semantic_callgraph.rust_rupta_v1.utility_scope import project, ownership


def test_projection_retains_callbacks_and_stops_at_owned_nodes():
    # Dependency cycle, two callbacks, a further owned call, an unavailable sink.
    nodes=['main','dep','cycle','callback','other','leaf','sink']
    edges=[('main','dep'),('dep','cycle'),('cycle','dep'),('dep','callback'),
           ('dep','other'),('callback','leaf'),('dep','sink')]
    raw=dict(entry='main',functions=[dict(identity=n,name=n,body_available=n!='sink') for n in nodes],
             call_edges=[dict(caller=a,callee=b) for a,b in edges],
             unresolved_indirect_callsites=[dict(caller='cycle')])
    owned={'main','callback','other','leaf'}
    graph=project(raw,owned)
    relations={(e['caller'],e['callee']) for e in graph['scoped_edges']}
    assert relations=={('main','callback'),('main','other'),('callback','leaf')}
    assert graph['maximum_utility_depth']==2
    assert graph['direct_induced_reachable']==1 and graph['projected_reachable']==4
    assert graph['deepest_path']==['main','callback','leaf']
    main=next(f for f in graph['coverage_frontiers'] if f['owner']=='main')
    assert main['unresolved_site_indices']==[0] and main['body_unavailable_nodes']==['sink']
    for e in graph['scoped_edges']:
        assert not (set(e['witness_nodes'][1:-1])&owned)
        assert all(raw['call_edges'][i]==dict(caller=a,callee=b)
                   for i,a,b in zip(e['witness_edge_indices'],e['witness_nodes'],e['witness_nodes'][1:]))


def test_ownership_uses_defining_crate_and_preserves_contexts():
    metadata=[]; functions=[]
    def add(number,crate,name,source,shim='None',contexts=('',)):
        key=json.dumps([str(number),'[]','None',shim],separators=(',',':'))
        metadata.append(dict(def_path_hash=str(number),generic_args='[]',promoted='None',shim=shim,
            def_id='unused',crate=crate,drop_glue=shim!='None',body_available=True,def_kind='Fn'))
        for context in contexts:
            functions.append(dict(identity=key+context,function_identity=key,name=name,source={'file':source}))
        return key
    root=add(0,'chmod','chmod::main','src/uucore/src/lib/lib.rs')
    helper=add(1,'uucore','uucore::generated','generated.rs')
    callback=add(2,'uu_chmod','uu_chmod::callback','src/uu/chmod/src/chmod.rs',contexts=(' @ A',' @ B'))
    add(3,'core','core::adapter<uu_chmod::Type>','src/uu/chmod/src/chmod.rs')
    add(4,'uu_chmod','glue','src/uu/chmod/src/chmod.rs',shim='Some(DropGlue)')
    raw=dict(entry=root,functions=functions); sidecar=dict(functions=metadata)
    included,_=ownership(raw,sidecar,True,{'generated.rs'})
    assert included=={root,helper,callback+' @ A',callback+' @ B'}
    narrow,_=ownership(raw,sidecar,False,{'generated.rs'})
    assert narrow==included-{helper}
