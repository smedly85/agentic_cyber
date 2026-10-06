import argparse,datetime,os,sys,time,subprocess,pathlib
from common import ROOT,HERE,OUT,OLD,RESULTS,read,write,sha,digest
sys.path[:0]=[str(ROOT),str(ROOT/'security/semantic_callgraph/cross_language_calibration')]
from runtime_provenance import pre_measurement_gate
from security.semantic_callgraph.rust_mir_lightweight.graph import build
from mapping import definition_matches

def freeze():
    proof=read(OUT/'validation_summary.json');assert proof['status']=='PASS' and proof['deterministic']
    assert read(OUT/'validation_acceptance.json')['status']=='PASS'
    assert proof['implementation_sha256']==sha(HERE/'graph.py')
    p=OUT/'method_freeze.json';assert not p.exists()
    sources=[HERE/'graph.py',HERE/'mapping.py',HERE/'POLICY.md',HERE/'study.py',HERE/'publish.py',
        ROOT/'security/semantic_callgraph/backend.py',ROOT/'security/historical/rust/vulnerable_function_mappings.json',
        OLD/'observation_plan.json',OUT/'historical_input_inventory.json',OUT/'validation_summary.json',OUT/'validation_acceptance.json',HERE/'VALIDATION_REPORT.md',
        ROOT/'security/semantic_callgraph/cross_language_calibration/fixture_manifest.json',OLD/'complete_build_provenance.json']
    record={'method':'rust-only-lightweight-v1','scope':'retained compiler-resolved semantic graph',
        'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'frozen_before_historical_graph_processing':True,
        'no_points_to_solver':True,'no_cross_language_comparability_claim':True,'edition_policy':'original_manifest_declared_per_crate',
        'input_policy':'Reuse hash-verified frozen raw MIR; no source recompilation or dependency update',
        'files':{s.relative_to(ROOT).as_posix():sha(s) for s in sources}}
    record['fingerprint']=digest(record);write(p,record);print('METHOD FROZEN',record['fingerprint'],flush=True)

def verify():
    record=read(OUT/'method_freeze.json');h=record.pop('fingerprint');assert digest(record)==h
    for name,expected in record['files'].items():assert sha(ROOT/name)==expected,name
    return h

def graph_worker(source,root,directory):
    verify();raw=read(source);env=dict(os.environ)
    try:gate=pre_measurement_gate('Rust',env,[])
    except Exception as error:
        write(directory/'gate.json',{'status':'FAIL','error':str(error)});raise
    start=time.monotonic();graph=build(raw,root);elapsed=time.monotonic()-start
    write(directory/'gate.json',{'status':'PASS','rows':gate,'immediately_before_graph_invocation':True})
    write(directory/'graph.json',graph);write(directory/'timing.json',{'graph_seconds':elapsed})

def execute():
    fingerprint=verify();contexts=read(OUT/'historical_input_inventory.json');plan=read(OLD/'observation_plan.json')['function_contexts']
    base=OUT/'historical';base.mkdir(exist_ok=False);context_results=[];observations=[]
    for context in contexts:
        release=context['release'];utility=context['utility'];folder=base/release/utility;folder.mkdir(parents=True)
        targets=[t for t in plan if t['release']==release and t['utility']==utility]
        if not context['available']:
            rows=[{**t,'status':'build_unresolved','vulnerability_depth':None,'max_depth':None} for t in targets]
            observations+=rows;write(folder/'observations.json',rows)
            context_results.append({'release':release,'utility':utility,'status':'build_unresolved','max_depth':None})
            continue
        for ref in context['files'].values():assert sha(ROOT/ref['path'])==ref['sha256']
        raw=read(ROOT/context['files']['raw.json']['path']);raw_by_id={r['instance_identity']:r for r in raw['instances']}
        entry=read(ROOT/context['files']['entry_resolution.json']['path']);assert len(entry['candidates'])==1
        root=entry['candidates'][0]['instance_identity'];assert root in raw_by_id
        checkout=ROOT/read(OLD/release/'source_provenance.json')['checkout']
        assert definition_matches(raw_by_id[root],checkout,entry['source'],'uumain','uu_'+utility)
        original=read(ROOT/context['files']['launch.json']['path']);env=original['environment'];hashes=[]
        for run in ('run-1','run-2'):
            directory=folder/run;directory.mkdir()
            command=[sys.executable,str(HERE/'study.py'),'--graph-input',str(ROOT/context['files']['raw.json']['path']),'--root',root,'--output',str(directory)]
            write(directory/'launch.json',{'argv':command,'method_fingerprint':fingerprint,'environment':env,'entry':root,'raw_input':context['files']['raw.json'],
                'original_extraction_launch':context['files']['launch.json'],'original_compilation_reused':True,
                'edition_policy':'manifest_declared_per_crate','observed_edition':original.get('observed_edition'),
                'replication':'Independent graph processes over identical immutable compiler extraction'})
            with (directory/'stdout').open('w') as stdout,(directory/'stderr').open('w') as stderr:
                subprocess.run(command,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,check=True,timeout=900)
            hashes.append(sha(directory/'graph.json'))
            print(release,utility,run,'graph complete',round(read(directory/'timing.json')['graph_seconds'],3),'seconds',flush=True)
        assert hashes[0]==hashes[1],('Historical graph nondeterminism',release,utility)
        graph=read(folder/'run-1/graph.json')
        nodes={r['identity']:r for r in graph['functions']};reachable=[r for r in nodes.values() if r['reachable_from_entry']]
        maximum=max(r['raw_call_depth'] for r in reachable)
        info={'release':release,'utility':utility,'revision':targets[0]['revision'],'entry':root,'status':'measured_known_edge_graph',
            'max_depth':maximum,'reachable_instances':len(reachable),'inventory_instances':len(nodes),
            'maximum_instances':[r for r in reachable if r['raw_call_depth']==maximum],
            'reachable_unresolved_indirect_calls':len(graph['reachable_unresolved_callsites']),
            'reachable_body_boundaries':len(graph['reachable_body_boundaries']),'coverage':graph['coverage'],
            'graph_sha256':hashes[0],'deterministic':True,'graph_artifact':(folder/'run-1/graph.json').relative_to(ROOT).as_posix()}
        write(folder/'program_max_depth.json',info);context_results.append(info);rows=[]
        for target in targets:
            assert sha(checkout/target['source_file'])==target['source_sha256']
            ids=sorted(r['instance_identity'] for r in raw['instances'] if definition_matches(r,checkout,target['source_file'],target['function'],target['crate_or_package']))
            definitions={(raw_by_id[i]['def_path'],raw_by_id[i]['source']) for i in ids}
            instances=[{'instance':i,'depth':nodes[i]['raw_call_depth'],'path':nodes[i]['shortest_call_path']} for i in ids]
            valid=[r for r in instances if r['depth'] is not None]
            selected=min(valid,key=lambda r:(r['depth'],r['instance'])) if valid else None
            if '/windows.rs' in target['source_file']:status='platform_not_built';selected=None
            elif len(definitions)>1:status='ambiguous_source_mapping';selected=None
            elif not ids:status='target_unresolved'
            elif selected:status='measured_partial_graph' if graph['coverage']=='incomplete_known_edge_graph' else 'measured_no_observed_boundary'
            elif graph['reachable_unresolved_callsites']:status='unresolved_with_indirect_boundary'
            elif graph['reachable_body_boundaries']:status='unresolved_with_body_boundary'
            else:status='unreachable_in_retained_graph'
            row={**target,'status':status,'vulnerability_depth':selected['depth'] if selected else None,
                'max_depth':None if status=='platform_not_built' else maximum,'entry':root,'target_instance_count':len(ids),
                'instances':instances,'selected':selected,'coverage':graph['coverage'],
                'reachable_unresolved_indirect_calls':info['reachable_unresolved_indirect_calls'],
                'reachable_body_boundaries':info['reachable_body_boundaries'],'graph_artifact':info['graph_artifact'],
                'comparability':'Rust-only; not validated for direct C/Rust comparison'}
            rows.append(row)
        observations+=rows;write(folder/'observations.json',rows)
        write(OUT/'historical_observations.json',observations);write(OUT/'historical_contexts.json',context_results)
    write(OUT/'historical_observations.json',observations);write(OUT/'historical_contexts.json',context_results)
    write(OUT/'historical_complete.json',{'status':'PASS','contexts':len(context_results),'verified_function_contexts':len(observations),
        'method_fingerprint':fingerprint,'all_graph_replicas_identical':True})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--graph-input',type=pathlib.Path)
    p.add_argument('--root');p.add_argument('--output',type=pathlib.Path);a=p.parse_args()
    graph_worker(a.graph_input,a.root,a.output) if a.graph_input else freeze() if a.freeze else execute()
