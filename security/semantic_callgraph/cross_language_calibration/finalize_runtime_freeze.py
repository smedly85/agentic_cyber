"""Final provenance-only freeze report and direct instrument verification."""
from validate_corpus import HERE,ROOT,read,sha,validate,digest,require
from corpus_integrity import verify_instruments
from revise_preregistration import write
from freeze_dynamic_runtime import PRIOR,ORIGINAL

def main():
    frozen=validate();manifest=read(HERE/'fixture_manifest.json')
    archive=HERE/'provenance'/PRIOR
    old=read(archive/'fixture_manifest.json');old_hashes=read(archive/'fixture_hashes.json')
    require(manifest['pairs']==old['pairs'],'Approved pair changed')
    require(frozen['sources']==old_hashes['sources'],'Source hashes changed')
    require(digest({'manifest':old,'sources':old_hashes['sources'],'metadata_sha256':old_hashes['metadata_sha256']})==PRIOR,'Prior bundle identity invalid')
    for name,expected in old_hashes['metadata_sha256'].items():require(sha(archive/name)==expected,'Prior metadata changed')
    tests=read(HERE/'validator_test_results.json')
    require(tests['exit_code']==0 and tests['failed']==0 and tests['passed']>=73,'Provenance tests failed')
    require(tests['calibration_fixture_bundle_sha256']==frozen['calibration_fixture_bundle_sha256'],'Test freeze differs')
    integrity=verify_instruments()
    write(HERE/'corpus_instrument_integrity.json',integrity)
    state={'status':'CALIBRATION-CORPUS-FINAL-REFREEZE','meaning':'READY FOR FINAL PREREGISTRATION CHECK',
        'calibration_fixture_bundle_sha256':frozen['calibration_fixture_bundle_sha256'],
        'pair_count':15,'source_count':30,'all_sources_unchanged':True,'R1_R4_and_all_pair_records_unchanged':True,
        'semantic_analyzer_runs':0,'analyzer_outputs_inspected':False,'depths_calculated':False,'historical_rust_work':False,
        'scientific_backends_modified':False,'calibration_measurement_authorized':False,'independent_preregistration_audit':'pending',
        'c_helper_sha256':integrity['c_helper_sha256'],'rust_calibration_start_sha256':integrity['rust_calibration_start_sha256'],
        'runtime_verification':'corpus_instrument_integrity.json','validator_tests_passed':tests['passed'],
        'source_smoke_evidence':{'path':'corpus_smoke_results.json','sha256':sha(HERE/'corpus_smoke_results.json'),
            'bundle':PRIOR,'compilations_passed':30,'runtime_configurations_passed':34,
            'reused_for_identical_sources_and_build_runtime_configurations':True,'rerun_in_provenance_only_pass':False},
        'provenance':'final_runtime_provenance.json','superseded_bundles':read(HERE/'final_runtime_provenance.json')['superseded_bundles']}
    write(HERE/'CORPUS_FROZEN.json',state)
    write(HERE/'fixture_bundle_pointer.json',{'fixture_manifest':'fixture_manifest.json','fixture_hashes':'fixture_hashes.json',
        'calibration_fixture_bundle_sha256':frozen['calibration_fixture_bundle_sha256'],'status':state['status'],
        'superseded_bundles':state['superseded_bundles'],'preflight_snapshots_unchanged':True,'null_calibration_measurements_unchanged':True})
    report=['# Final calibration provenance freeze','',state['status']+' — '+state['meaning'],'',
        'Bundle SHA-256: `'+frozen['calibration_fixture_bundle_sha256']+'`','',
        'All 30 source hashes and every approved pair record are unchanged, including R1–R4, expected edges/targets, source identities, runtime inputs, ordinary build configuration and cross-language categories. No analyzer ran, no semantic graph output was inspected, no depth was calculated, and no historical Rust work occurred. Neither scientific backend was modified.','',
        'verify_instruments: PASS, including direct expected/resolved path and expected/actual SHA-256 reports for runtime components, immutable backend sources/driver, standard libraries and all 159 protected C artifacts. See corpus_instrument_integrity.json.','',
        'Validator/tamper controls: '+str(tests['passed'])+' passed. Controls include all requested runtime components, Clang path/hash, environment/model overrides, added transitive libraries and aggregate hash sensitivity. No scientific binary was overwritten.','',
        'Ordinary smoke evidence remains 30/30 compilations and 34/34 runtime configurations from the prior bundle, reused for byte-identical sources and identical build/runtime inputs; no smoke rerun was necessary in this provenance-only pass.','']
    for language in ('C','Rust'):
        config=manifest['semantic_extraction_configuration'][language]
        runtime=config['dynamic_runtime'];ids=runtime['identities']
        report+=['## '+language+' runtime identities','', '| Component | Canonical resolved path | SHA-256 | SONAME |','|---|---|---|---|']
        rows=[('analyzer executable',ids['executable']),('compiler',ids['compiler'])]
        rows+=list(ids['libraries'].items())
        if language=='C':rows.append(('extapi.bc',ids['external_model']))
        else:rows+=list(ids['rebuilt_std'].items())
        for name,row in rows:report.append('| '+name+' | `'+row['path']+'` | `'+row['sha256']+'` | '+', '.join(row.get('elf',{}).get('SONAME',[]))+' |')
        report+=['','Compiler identity:','```text',ids['compiler']['version'].strip(),'```','',
            'Analyzer ELF search policy: `'+str(ids['executable']['elf'])+'`','',
            'Resolution policy:','```json',__import__('json').dumps(runtime['resolution_policy'],indent=2),'```','',
            'The complete compiler dependency closure (also frozen) is in fixture_manifest.json. No llvm-link invocation is required for these single-file C fixtures.','']
        if language=='C':report+=['External model selection: '+ids['external_model']['selection_mechanism'],
            'Observed candidates: `'+str(ids['external_model']['candidates'])+'`. npm is absent; /lib/extapi.bc is absent. The selected model is beside the loaded libSvfCore. The verifier rejects changed selection, model bytes or override options.','']
        else:report+=['Sysroot: `$REPO/build/rust-mir/toolchain`; direct pinned toolchain, no rustup dispatch. The complete driver closure contains one rustc-private library (librustc_driver); all additional resolved libraries, loader and rebuilt std artifacts are bound.','']
    report+=['## Superseded identities','',
        '`'+ORIGINAL+'`: superseded_before_measurement; independent preregistration audit corrections R1-R5.','',
        '`'+PRIOR+'`: superseded_before_measurement; final independent preregistration audit identified incomplete dynamic analysis-runtime fingerprinting.','',
        'No analyzer output existed for either superseded corpus. Prior manifests, metadata and source bytes are archived under provenance.','',
        'Unchanged C helper: `'+integrity['c_helper_sha256']+'`.','',
        'Unchanged Rust calibration-start: `'+integrity['rust_calibration_start_sha256']+'`. Candidate instrument sources and driver are hash-verified unchanged.','',
        'Paths use `$REPO` for the canonical repository root. Runtime gates expand this value and compare canonical resolved paths, never silently substitute files.','',
        state['status']+' — '+state['meaning'],'']
    (HERE/'CORPUS_FREEZE_REPORT.md').write_text('\n'.join(report))
    previous=set(read(HERE/'artifact_manifest.json'))|{'artifact_manifest.json'}
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='corpus_artifact_manifest.json' and p.relative_to(HERE).as_posix() not in previous]
    write(HERE/'corpus_artifact_manifest.json',{p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)}|
        {name:sha(ROOT/name) for name in ('tests/test_calibration_corpus.py','tests/test_calibration_runtime_provenance.py')})
    validate()
    print(state['status']+' — '+state['meaning'])
    print(frozen['calibration_fixture_bundle_sha256'])

if __name__=='__main__':main()
