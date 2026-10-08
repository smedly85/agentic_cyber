"""Finalize source preregistration ONLY; no semantic graph or depth operations."""
import json
from validate_corpus import HERE,ROOT,read,sha,validate,require
from corpus_integrity import verify_instruments


def write(name,value):(HERE/name).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')


def main():
    provenance=read(HERE/'revision_provenance.json')
    old_state=read(HERE/'CORPUS_FROZEN.json')
    require(old_state['calibration_fixture_bundle_sha256']==provenance['prior_calibration_fixture_bundle_sha256'],
            'Only the explicitly superseded pre-measurement freeze may be replaced')
    require(sha(HERE/'CORPUS_FROZEN.json')==sha(HERE/provenance['archive']/'CORPUS_FROZEN.json'),'Prior freeze must be archived unchanged')
    frozen=validate();integrity=verify_instruments();manifest=read(HERE/'fixture_manifest.json')
    smoke_path=ROOT/'build/cross-language-calibration-corpus-smoke/corpus-r1-r5-v2/results.json'
    smoke=read(smoke_path);tests=read(HERE/'validator_test_results.json')
    require(smoke['passed'] and smoke['compilations_passed']==30 and smoke['runtime_configurations_passed']==34,'Smoke gate failed')
    require(smoke['calibration_fixture_bundle_sha256']==frozen['calibration_fixture_bundle_sha256'],'Smoke source freeze differs')
    require(tests['exit_code']==0 and tests['passed']==32 and tests['failed']==0,'Validator tests failed')
    require(tests['calibration_fixture_bundle_sha256']==frozen['calibration_fixture_bundle_sha256'],'Validator tests used a different freeze')
    require(not smoke['semantic_analyzers_invoked'] and not smoke['call_edges_traced'] and not smoke['depths_calculated'],'Unexpected scientific measurement')
    write('corpus_smoke_results.json',smoke)
    write('corpus_instrument_integrity.json',integrity)
    write('fixture_bundle_pointer.json',{'kind':'additive_pointer_only','fixture_manifest':'fixture_manifest.json',
          'fixture_hashes':'fixture_hashes.json','preregistration':'CALIBRATION_PREREGISTRATION.md',
          'calibration_fixture_bundle_sha256':frozen['calibration_fixture_bundle_sha256'],
          'preflight_snapshots_unchanged':True,'null_calibration_measurements_unchanged':True,
          'supersedes_only':'Prior source freeze superseded before measurement for independent preregistration audit corrections R1-R5.',
          'revision_provenance':'revision_provenance.json'})
    state={'status':'CALIBRATION-CORPUS-REFROZEN','meaning':'READY FOR RE-AUDIT',
           'pair_count':15,'source_count':30,'calibration_fixture_bundle_sha256':frozen['calibration_fixture_bundle_sha256'],
           'per_source_hashes':'fixture_hashes.json','source_entry_target_mappings':'fixture_manifest.json',
           'expectations_preregistered_before_measurement':True,'source_review':'source_review.json',
           'ordinary_compilations_passed':30,'ordinary_runtime_configurations_passed':34,'validator_tests_passed':32,
           'revision_provenance':read(HERE/'revision_provenance.json'),
           'semantic_analyzer_runs':0,'call_edges_traced':False,'depths_calculated':False,'analyzer_outputs_inspected':False,
           'independent_preregistration_audit':'pending','calibration_measurement_authorized':False,
           'historical_rust_measurement':False,'backends_modified':False,'preflight_artifacts_modified':False,
           'c_helper_sha256':integrity['c_helper_sha256'],'rust_calibration_start_sha256':integrity['rust_calibration_start_sha256'],
           'c_protected_artifacts_unchanged':159,
           'smoke_evidence':{'path':smoke_path.relative_to(ROOT).as_posix(),'sha256':sha(smoke_path)}}
    write('CORPUS_FROZEN.json',state)
    lines=['# Calibration corpus freeze report','',
        '**CALIBRATION-CORPUS-REFROZEN — READY FOR RE-AUDIT**','',
        'No semantic analyzer was run on this corpus, no analyzer graph output was inspected, no callback trace was collected, and no depth was calculated. This is not CALIBRATION-GO.',
        '', 'Bundle SHA-256: `'+frozen['calibration_fixture_bundle_sha256']+'`','',
        'The bundle hash binds every source byte plus the complete expectations/mappings/runtime/build manifest, JSON schema, preregistration and source review. All 15 pairs use `entry` as the source-level root; `main` is the excluded runtime harness.',
        '', '## Source paths and SHA-256 values','', '| Pair | C source / SHA-256 | Rust source / SHA-256 |','|---|---|---|']
    for p in manifest['pairs']:
        cells=[]
        for prefix in ('c','rust'):
            relative=(ROOT/p[prefix+'_source']).relative_to(HERE).as_posix()
            cells.append(f'[{relative}]({relative})<br>`'+p[prefix+'_source_sha256']+'`')
        lines.append('| '+p['pair_id']+' | '+' | '.join(cells)+' |')
    lines+=['','## Exact source entry and target mappings','',
            'Line spans are frozen review spans including function attributes where present; compiler source-definition spans must be matched by containment/overlap plus qualified identity and source file, not by a bare name. Closure identity refers to its literal, not a manufactured function.',
            '', '| Pair | C entry → source target(s) | Rust entry → source target(s) |','|---|---|---|']
    def label(identity):
        s=identity['source_span'];return '`'+identity.get('qualified_name',identity['function_name'])+'` L'+str(s['start_line'])+'–'+str(s['end_line'])
    for p in manifest['pairs']:
        cells=[label(p[prefix+'_entry_identity'])+' → '+', '.join(label(i) for i in p[prefix+'_target_identity']) for prefix in ('c','rust')]
        lines.append('| '+p['pair_id']+' | '+' | '.join(cells)+' |')
    lines+=['','## Expected targets and cross-language correspondence','',
            '| Pair | C exact application indirect targets | Rust exact application indirect targets | Cross-language expectation |','|---|---|---|---|']
    for p in manifest['pairs']:
        sets=[]
        for language,prefix in [('C','c'),('Rust','rust')]:
            sites=p['expected_'+prefix+'_indirect_targets']
            text='; '.join('`'+s['callsite_id']+'` → {'+', '.join(s['expected_targets'])+'}' for s in sites)
            if not text:
                binding=p['special_semantics'].get('library_callback_binding',{}).get(language)
                text='library callback binding: {'+', '.join(binding['targets'])+'}; internal site unmeasured' if binding else 'No application indirect site; direct/closure relations are in manifest'
            sets.append(text)
        lines.append('| '+p['pair_id']+' | '+' | '.join(sets)+' | `'+p['cross_language_expectation']+'` |')
    lines+=['','## Validation and review','',
        '- Ordinary source smoke tests: **30/30 compilations; 34/34 prescribed runtime configurations**. Results check exit code/stdout/stderr and return-value assertions only. Predicted callback identities were not traced or measured.',
        '- Source/schema/freeze validation: **15 pairs, 30 sources**. Validator/tamper-rejection tests: **32 passed**. Every requested scientific input is tested for aggregate change and rejection. See validator_test_results.json and tests/test_calibration_corpus.py.',
        '- C/Rust helper-layer, branch, callback, lifetime and storage review is recorded in source_review.json. Independent audit remains pending.',
        '- C helper SHA-256 unchanged: `'+integrity['c_helper_sha256']+'`.',
        '- Rust calibration-start fingerprint unchanged: `'+integrity['rust_calibration_start_sha256']+'`.',
        '- Backend/compiler/driver source and binary hashes were checked before and after smoke execution. Rebuilt Rust libraries were hash-verified before each compilation. All 159 protected C artifacts remain unchanged.',
        '- Existing preflight reports, fingerprints and null measurement files remain byte-identical. fixture_bundle_pointer.json is additive; it points to this corpus without turning null measurements into observations.',
        '- No scientific backend was modified. No historical uutils specimen was built; no historical Rust CVE measurement, frozen-population edit or mapping edit occurred.',
        '', '## Stop point','',
        'Stop here for independent preregistration audit. The first C/SVF or Rust/MIR semantic run on these fixtures must follow that audit and separate authorization.','']
    lines+=['','## Audit revisions R1-R5','',
        'Prior bundle `'+provenance['prior_calibration_fixture_bundle_sha256']+'` is `superseded_before_measurement`; reason: `independent preregistration audit corrections R1-R5`. No semantic analyzer output ever existed for it. Its full source freeze is preserved under '+provenance['archive']+'.','',
        'R1: dyn_vtable adds Third::operation / third_operation and a main-local live trait object / context-method object. R2: multi_pointer adds same-signature unrelated and a main-local live callback. R3: static_dispatch adds Second::operation / second_operation called directly in main. Each decoy call checks result 13; none is passed to entry or writes shared state. The original entry bodies and exact target sets remain unchanged. All six source spans were recomputed.','',
        'R4, expectation-only: '+next(p['registered_relationship'] for p in manifest['pairs'] if p['pair_id']=='generic_specialization')+' Prior wording is preserved verbatim in revision_provenance.json.','',
        'R5: Complete extraction configuration is frozen in fixture_manifest.json, independently of smoke flags. The accepted Rust canonical argv and rebuilt-std configuration are fingerprinted in semantic_extraction_canonical.json; canonical provider/build records, driver/compiler/library fingerprints and driver environment are also bound. C canonical backend flags/helper options are bound; its intentional host-default extraction target is explicitly documented.','',
        'Exact Rust settings: rustc 1.93.0; edition 2021; x86_64-unknown-linux-gnu; opt-level=0; codegen-units=1; panic=unwind; mir-opt-level=0; inline-mir=no; always-encode-mir; rebuilt-std noprelude extern/dependency flags; unstable-options; remap-path-prefix; -A dead_code; --emit=link. Compiler-internal rustc_driver Probe uses RUSTC_BOOTSTRAP=1, MIR_PROBE_TRANSITIVE=1 and stops after analysis. No semantic invocation occurred.','',
        manifest['exact_application_structure_definition'],'',manifest['external_boundary_definition'],'',
        'Runtime evidence: all separate harness decoy checks passed; both selector configurations passed in multi_pointer and dyn_vtable. Distinct return values and source non-flow establish the intended targets; no callback tracing or semantic graph inspection was performed.','',
        '## Changed source hashes','']
    old_manifest=read(HERE/provenance['archive']/'fixture_manifest.json')
    for pair,old in zip(manifest['pairs'],old_manifest['pairs']):
        for prefix in ('c','rust'):
            if pair[prefix+'_source_sha256']!=old[prefix+'_source_sha256']:
                lines.append('- '+pair[prefix+'_source']+': `'+pair[prefix+'_source_sha256']+'`')
    lines+=['','CALIBRATION-CORPUS-REFROZEN — READY FOR RE-AUDIT','']
    (HERE/'CORPUS_FREEZE_REPORT.md').write_text('\n'.join(lines))
    previous=set(read(HERE/'artifact_manifest.json'))|{'artifact_manifest.json'}
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='corpus_artifact_manifest.json' and p.relative_to(HERE).as_posix() not in previous]
    write('corpus_artifact_manifest.json',{p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)}|{'tests/test_calibration_corpus.py':sha(ROOT/'tests/test_calibration_corpus.py')})
    print(state['status']+' — '+state['meaning'])
    print('Bundle SHA-256: '+state['calibration_fixture_bundle_sha256'])


if __name__=='__main__':main()
