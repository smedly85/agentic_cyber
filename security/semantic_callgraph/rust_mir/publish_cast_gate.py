"""Publish the controlled MIR core gate; never authorize historical measurement."""
from collections import Counter
import hashlib
import json
from prepare import ROOT,HERE,require_c
from probe import BASE


def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name,value):(HERE/name).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')


def main():
    require_c()
    paths={
        'controlled':BASE/'continuation/cast-final-v2/complete_validation.json',
        'frozen':BASE/'continuation/cast-final-v2/frozen_comparison.json',
        'extraction':BASE/'continuation/cast-final-v2/result.json',
        'dynamic':BASE/'dynamic-validation/cast-final-v2/result.json',
        'focused':BASE/'core-validation/cast-v1/result.json',
        'memory':BASE/'memory-validation/cast-v1/result.json',
        'operations':BASE/'cast-validation/cast-v3/result.json',
        'adapter':BASE/'adapter-validation/cast-final-v1/result.json',
        'c':BASE/'c-validation/casts-v1/results.json'}
    data={k:read(p) for k,p in paths.items()}
    assert data['controlled']['passed']==31
    assert all(c['static_assertions_pass'] and not c['unsupported_operations'] and not c['required_body_blockers'] and not c['unresolved_callsites'] for c in data['controlled']['cases'])
    assert data['frozen']['unchanged']==27 and data['extraction']['all_identical']
    assert data['controlled']['deterministic'] and data['dynamic']['passed']==31 and data['dynamic']['deterministic']
    assert len(data['focused']['cases'])==30 and all(c['focused_pass'] for c in data['focused']['cases'])
    assert len(data['memory']['cases'])==12 and all(c['target_checks_pass'] and c['deterministic'] for c in data['memory']['cases'])
    assert data['operations']['passed']==data['operations']['total']==13 and data['operations']['deterministic']
    assert data['adapter']['deterministic'] and all(not r['unsupported_operations'] and not r['unresolved_sites'] and all(c['passed'] for c in r['checks']) for r in data['adapter']['runs'])
    assert data['c']['passed'] and data['c']['protected_c_files_unchanged']==159
    assert sha(ROOT/'build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf')=='ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2'
    for name,value in data.items():write('cast_'+name+'_results.json',value)
    base=paths['controlled'].parent
    prior=BASE/'continuation/body-v5'
    changes=[];contracts=[];traces={};bodies=Counter()
    for case in data['controlled']['cases']:
        name=case['case'];flow=read(base/'run-1'/name/'inclusion.json');raw=read(base/'run-1'/name/'api.json')
        old=read(prior/'run-1'/name/'inclusion.json')
        edges=lambda f:{(s['owner'],s['block'],t) for s in f['sites'] for t in s['targets']}
        changes.append({'fixture':name,'new_static_targets':sorted(edges(flow)-edges(old)), 'removed_static_targets':sorted(edges(old)-edges(flow))})
        bodies.update(r['disposition'] for r in flow['required_body_ledger'])
        if name in ('box_trait','box_fnmut','iterator_flat_map','crates_io'):
            active=set(flow['active_instances'])
            casts=[{'instance':r['instance_identity'],**c} for r in raw['instances'] if r['instance_identity'] in active for c in r['constraints'] if 'cast_evidence' in c]
            traces[name]={'raw_shortest_paths':case['paths'],'allocations':flow['allocations'],
                          'indirect_sites':[s for s in flow['sites'] if any(r['instance_identity']==s['owner'] and any(c['block']==s['block'] and c['status'].startswith('unresolved') for c in r['calls']) for r in raw['instances'])],
                          'casts':casts,'required_body_ledger':flow['required_body_ledger']}
    adapter=read(paths['adapter'].parent/'run-1/graph.json')
    active=set(adapter['inclusion']['active_instances'])
    for r in adapter['api']['instances']:
        if r['instance_identity'] in active and r.get('intrinsic_contract'):
            contracts.append({'instance':r['instance_identity'],'def_path':r['def_path'],'contract':r['intrinsic_contract'],
                              'body_exists':False,'disposition':r['disposition'],'fixture':'std_callbacks.rs: sort_by / boxed FnMut Map'})
    write('cast_trace_evidence.json',traces)
    write('cast_target_changes.json',changes)
    write('cast_intrinsic_ledger.json',contracts)
    assert not any(r['new_static_targets'] or r['removed_static_targets'] for r in changes)
    # Preserve the previous milestone rather than rewriting its archived reports.
    if not (HERE/'body_instrument.json').exists():write('body_instrument.json',read(HERE/'instrument.json'))
    record={'status':'MIR-CORE-GO','meaning':'READY FOR CROSS-LANGUAGE CALIBRATION',
            'accepted_backend':False,'historical_measurement':False,'calibration':'not_run',
            'complete_semantic_passed':31,'semantic_total':31,'controlled_static_assertions_passed':31,
            'core_focused_passed':30,'memory_adversaries_passed':12,'new_operation_controls_passed':13,
            'dynamic_soundness_passed':31,'dynamic_total':31,'controlled_deterministic':True,'dynamic_deterministic':True,
            'frozen_passing_fixtures_unchanged':27,'new_static_targets_in_original_suite':0,
            'body_disposition_occurrences':dict(bodies),'protected_c_artifacts':159,
            'c_controlled':'11/11 unchanged','c_historical':'9/9 unchanged',
            'canonical_c_helper_sha256':'ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2',
            'driver_sha256':sha(HERE/'driver.rs'),'inclusion_sha256':sha(HERE/'inclusion.py'),
            'scope':'Controlled core gate only. Historical measurements still prohibited; final reporting gate unchanged.',
            'evidence':{k:{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for k,p in paths.items()}}
    write('instrument.json',record)
    write('cast_evidence_manifest.json',{p.relative_to(ROOT).as_posix():sha(p) for p in paths.values()})
    write('artifact_manifest.json',{p.relative_to(HERE).as_posix():sha(p) for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name!='artifact_manifest.json'})
    print('MIR-CORE-GO: complete static 31/31; frozen 27/27; dynamic 31/31; C frozen',flush=True)


if __name__=='__main__':main()
