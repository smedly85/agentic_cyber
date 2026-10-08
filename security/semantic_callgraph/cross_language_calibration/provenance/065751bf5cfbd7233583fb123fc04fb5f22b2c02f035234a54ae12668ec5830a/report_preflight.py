"""Report missing calibration inputs without fabricating empirical observations."""
import json
from preflight import HERE,ROOT,MIR,BASE,read,sha,write


def main():
    frozen=read(HERE/'instrument_fingerprints.json')
    checks={name:sha(ROOT/name)==expected for language in ('C','Rust') for name,expected in frozen[language]['sources'].items()}
    checks['canonical_c_helper']=sha(ROOT/frozen['C']['helper_path'])==frozen['C']['helper_sha256']
    checks['rust_driver_binary']=sha(ROOT/frozen['Rust']['driver_binary_path'])==frozen['Rust']['driver_binary_sha256']
    checks['rust_compiler']=sha(BASE/'toolchain/bin/rustc')==frozen['Rust']['compiler_sha256']
    from pathlib import Path
    checks['clang_compiler']=sha(Path('/usr/lib/llvm-21/bin/clang'))==frozen['C']['compiler_sha256']
    argv=read(BASE/'built-std-inspection/core-v2/result.json')['rustc_argv']
    libraries=frozen['Rust']['std_configuration']['libraries']
    for index,arg in enumerate(argv[:-1]):
        if arg=='--extern' and argv[index+1].startswith('noprelude:'):
            name,filename=argv[index+1].split('=',1)
            checks['rust_rebuilt_'+name]=sha(Path(filename))==libraries[name.removeprefix('noprelude:')]['sha256']
    assert all(checks.values()), 'Candidate instrument changed after freeze'
    static_path=BASE/'continuation/calibration-preflight-v1/complete_validation.json'
    dynamic_path=BASE/'dynamic-validation/calibration-preflight-v1/result.json'
    c_path=BASE/'c-validation/calibration-preflight-v1/results.json'
    static=read(static_path);dynamic=read(dynamic_path);c=read(c_path)
    assert static['passed']==31 and static['deterministic']
    assert dynamic['passed']==31 and dynamic['deterministic']
    assert c['passed'] and c['protected_c_files_unchanged']==159
    regression={'phase':'fresh_preflight_regression_not_post_calibration','rust_complete_static':31,
                'rust_semantic_assertions':sum(r['static_assertions_pass'] for r in static['cases']),
                'rust_dynamic':31,'rust_paired_determinism':static['deterministic'] and dynamic['deterministic'],
                'c_controlled':sum(r['passed'] for r in c['controlled']),
                'c_historical_replay':sum(r['passed'] for r in c['observations']),
                'protected_c_artifacts_unchanged':159,'instrument_unchanged_checks':checks,
                'evidence':{str(p.relative_to(ROOT)):sha(p) for p in (static_path,dynamic_path,c_path)}}
    write('frozen_regression.json',regression)
    expectations=read(HERE/'preregistered_expectations.json')
    reason='Frozen 15-pair C/Rust source manifest and source hashes were not located. Categories/relationships alone do not uniquely identify executable pairs.'
    roots=['security/calibration/semantic_callgraph','tests/fixtures/rust_semantic','tests/fixtures/rust_mir']
    write('available_fixture_inventory.json',{'purpose':'Existing controlled sources only; no inferred pairing or registration',
          'searched_roots':roots,'sources':{str(p.relative_to(ROOT)):sha(p) for root in roots
          for p in sorted((ROOT/root).rglob('*')) if p.is_file() and p.suffix in ('.c','.rs')},
          'existing_c_manifest':{'path':'security/calibration/semantic_callgraph/fixtures.json',
          'sha256':sha(ROOT/'security/calibration/semantic_callgraph/fixtures.json'),
          'fixture_count':len(read(ROOT/'security/calibration/semantic_callgraph/fixtures.json')['fixtures'])},
          'paired_source_manifest':None})
    write('pair_results.json',{'execution_status':'not_run','reason':reason,'pairs':[
        {'pair':p['pair'],'status':None,'execution_status':'not_run','prerequisite':'frozen_paired_sources_missing'} for p in expectations['pairs']]})
    write('target_set_comparison.json',{'execution_status':'not_run','pairs':[
        {'pair':p['pair'],'registered_relationship':p['verbatim_expectation'],
         'C':{'expected_targets':None,'actual_targets':None,'cardinality':None,'missing':None,'unexpected':None},
         'Rust':{'expected_targets':None,'actual_targets':None,'cardinality':None,'missing':None,'unexpected':None},
         'edge_semantics_comparable':None} for p in expectations['pairs']]})
    write('depth_comparison.json',{'execution_status':'not_run','primary_metric':'shortest number of static semantic may-call edges',
          'diagnostic_user_app_depth_only':True,'correction_factor':None,'pairs':[
              {'pair':p['pair'],'C':None,'Rust':None,'raw_edges':None,'user_application_edges':None,
               'std_core_edges':None,'compiler_shim_edges':None,'drop_glue_edges':None} for p in expectations['pairs']]})
    write('dynamic_soundness.json',{'calibration_execution_status':'not_run','C':None,'Rust':None,
          'controlled_rust_preflight':{'passed':31,'total':31,'deterministic':True},
          'controlled_results_are_not_calibration_evidence':True})
    write('precision_summary.json',{'execution_status':'not_run','comparison_supported':False,
          'mean_target_set_size':None,'median_target_set_size':None,'maximum_target_set_size':None,
          'exact_matches':None,'conservative_supersets':None,'missing_target_failures':None,
          'configured_common_class':['context-insensitive','flow-insensitive inclusion','field-sensitive where represented'],
          'empirical_precision_equivalence':None,
          'registered_library_boundary_expectation':'C external qsort versus compiled Rust generic sort_by; not measured',
          'remaining_unassessed':['heap abstraction correspondence','target-set inflation','external callback coverage','raw/app graph structure']})
    write('final_verdict.json',{'decision':'CALIBRATION-STOP-REVIEW','reason':reason,
          'calibration_executed':False,'calibration_pairs_executed':0,'total_preregistered_categories':15,
          'pair_statuses_unassigned':True,'calibration_determinism':'not_run',
          'scientific_backend_failure_demonstrated':False,'backend_modifications':[],
          'ready_for_independent_audit_before_historical_pilots':False,'historical_rust_measurement':False,
          'required_input':'Path to the frozen 15-pair source/entry/target manifest and authenticated fixture sources, or an explicit preregistration amendment before observing new pairs.',
          'rust_calibration_start_sha256':frozen['Rust']['calibration_start_sha256'],
          'canonical_c_helper_sha256':frozen['C']['helper_sha256'],
          'frozen_regression':regression})
    write('artifact_manifest.json',{p.name:sha(p) for p in sorted(HERE.iterdir()) if p.is_file() and p.name!='artifact_manifest.json'})
    print('CALIBRATION-STOP-REVIEW: missing frozen paired source manifest; instruments unchanged; fresh controlled regressions pass.')


if __name__=='__main__':main()
