import argparse,datetime,os,pathlib,subprocess,sys,time
from common import ROOT,HERE,OUT,read,write,sha,digest
sys.path[:0]=[str(ROOT),str(ROOT/'security/semantic_callgraph/cross_language_calibration')]
from runtime_provenance import pre_measurement_gate,expand
from security.semantic_callgraph.rust_mir_lightweight.graph import build
REQUIRED={'direct','recursion','generic','static_trait','closure','cross_crate_direct','multiple_instances',
    'option_map','result_or_else','iterator_flat_map','entry_wrappers','unwind','crates_io','platform','same_method'}

def worker(run,output):
    base=output/run;base.mkdir(parents=True,exist_ok=False);results=[]
    frozen={r['id']:r for r in read(OUT/'validation_summary.json')['results']}
    for case in read(OUT/'input_inventory.json'):
        p=ROOT/case['input_path'];assert sha(p)==case['input_sha256'];data=read(p);raw=data['api'] if case['wrapped'] else data
        folder=base/case['id'];folder.mkdir(parents=True)
        env=dict(os.environ);write(folder/'launch.json',{'environment':env,'input':case,'entry':case['root'],
            'implementation_sha256':sha(HERE/'graph.py'),'points_to_solver_used':False})
        gate=pre_measurement_gate('Rust',env,[])
        graph=build(raw,case['root'])
        write(folder/'gate.json',{'status':'PASS','rows':gate,'immediately_before_graph_invocation':True})
        write(folder/'graph.json',graph)
        sites={(owner['instance_identity'],s['block']):s for owner in raw['instances'] for s in owner['calls']}
        for edge in graph['call_edges']:
            source=sites[edge['caller'],edge['callsite']['mir_block']]
            assert (source['status'] in ('resolved_instance','drop_instance') and source['target']==edge['callee']) or (
                source['status']=='unresolved_function_pointer' and source.get('callee_value')=={'function':edge['callee']})
        nodes={r['identity']:r for r in graph['functions']}
        for node in nodes.values():
            if node['reachable_from_entry']:assert len(node['shortest_call_path']['edges'])==node['raw_call_depth']
        for e in graph['call_edges']:
            if nodes[e['caller']]['reachable_from_entry']:assert nodes[e['callee']]['raw_call_depth']<=nodes[e['caller']]['raw_call_depth']+1
        golden=read(ROOT/case['frozen_flow_path']) if case['frozen_flow_path'] else data.get('inclusion') if case['wrapped'] else None
        comparison=[]
        if golden:
            actual={(s['caller'],s['callsite']['mir_block']):s for s in graph['callsites']}
            for site in golden['sites']:
                got=actual[site['owner'],site['block']];expected=set(site['targets']);observed=set(got['targets'])
                assert observed<=expected,('Target not supported by frozen reference',case['id'],site,got)
                comparison.append({'owner':site['owner'],'block':site['block'],'frozen_full_method_targets':sorted(expected),
                    'lightweight_targets':sorted(observed),'status':'exact' if observed==expected else 'explicitly_unresolved',
                    'mir_status':got['mir_status']})
        expected_target_depths={};actual_target_depths={}
        if case['group']=='controlled':
            expected_target_depths=frozen[case['id']]['controlled_full_method_target_depths']
            actual_target_depths={i:nodes[i]['raw_call_depth'] for i in expected_target_depths}
            if case['name'] in REQUIRED:
                assert expected_target_depths,(case['name'],'missing controlled target oracle')
                assert actual_target_depths==expected_target_depths,(case['name'],'required concrete call path failed')
        result={'id':case['id'],'group':case['group'],'graph_sha256':sha(folder/'graph.json'),
            'no_invented_targets':True,'compiler_evidence_valid':True,'shortest_path_checks_pass':True,
            'reachable_unresolved_sites':len(graph['reachable_unresolved_callsites']),
            'reachable_body_boundaries':len(graph['reachable_body_boundaries']),
            'target_set_comparison':comparison,'controlled_full_method_target_depths':expected_target_depths,
            'lightweight_target_depths':actual_target_depths,'coverage':graph['coverage']}
        assert result==frozen[case['id']],('Canonical lightweight result changed',case['id'])
        results.append(result);write(base/'results.json',results);print(run,case['id'],'PASS',result['reachable_unresolved_sites'],'unresolved',flush=True)
    write(base/'complete.json',{'status':'PASS','cases':len(results)})

def main(output):
    from study import verify
    verify()
    output=output.resolve();assert output.is_relative_to(ROOT) and not output.exists()
    output.mkdir(parents=True)
    manifest=read(ROOT/'security/semantic_callgraph/cross_language_calibration/fixture_manifest.json')
    env=dict(os.environ);env.update({k:expand(v) for k,v in manifest['semantic_extraction_configuration']['Rust']['driver']['environment'].items()})
    write(output/'validation_protocol.json',{'required_controlled_cases':sorted(REQUIRED),'acceptance':'Exact equality to frozen lightweight validation, including concrete-path oracles; compiler evidence and deterministic replicas.',
        'oracle':'Canonical lightweight validation_summary.json, retaining the original controlled reference expectations without a failed-solver directory dependency.',
        'implementation_sha256':sha(HERE/'graph.py'),'policy_sha256':sha(HERE/'POLICY.md'),'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    workers=[subprocess.Popen([sys.executable,str(HERE/'validate.py'),'--run',run,'--output',str(output)],cwd=ROOT,env=env) for run in ('run-1','run-2')]
    try:
        while any(p.poll() is None for p in workers):
            assert all(p.poll() in (None,0) for p in workers),'Validation failed; stop before history'
            time.sleep(1)
        assert all(p.returncode==0 for p in workers)
    finally:
        for p in workers:
            if p.poll() is None:p.terminate();p.wait()
    a=read(output/'run-1/results.json');b=read(output/'run-2/results.json');assert a==b
    write(output/'validation_summary.json',{'status':'PASS','cases':len(a),'deterministic':True,
        'required_cases':sorted(REQUIRED),'implementation_sha256':sha(HERE/'graph.py'),'results':a})
    print('LIGHTWEIGHT VALIDATION PASS',len(a),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run');p.add_argument('--output',type=pathlib.Path,required=True)
    args=p.parse_args();worker(args.run,args.output) if args.run else main(args.output)
