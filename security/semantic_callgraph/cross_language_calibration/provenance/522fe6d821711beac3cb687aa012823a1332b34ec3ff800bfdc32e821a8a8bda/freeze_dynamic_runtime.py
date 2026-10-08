"""Final audit correction: provenance only, with all approved pairs immutable."""
import copy
import os
from pathlib import Path
import shutil
from validate_corpus import HERE,ROOT,read,sha,validate
from runtime_provenance import inspect,identity,expand,enforce_environment
from revise_preregistration import write

PRIOR='522fe6d821711beac3cb687aa012823a1332b34ec3ff800bfdc32e821a8a8bda'
ORIGINAL='065751bf5cfbd7233583fb123fc04fb5f22b2c02f035234a54ae12668ec5830a'

def main():
    require_old=read(HERE/'fixture_hashes.json')
    assert require_old['calibration_fixture_bundle_sha256']==PRIOR
    archive=HERE/'provenance'/PRIOR
    if not archive.exists():
        archive.mkdir(parents=True)
        for p in HERE.iterdir():
            if p.is_file():shutil.copy2(p,archive/p.name)
        shutil.copytree(HERE/'fixtures',archive/'fixtures')
    manifest=read(archive/'fixture_manifest.json');approved=copy.deepcopy(manifest['pairs'])
    frozen=read(HERE/'instrument_fingerprints.json')
    for language in ('C','Rust'):
        extraction=manifest['semantic_extraction_configuration'][language]
        required={} if language=='C' else extraction['driver']['environment']
        unset=['LD_PRELOAD','LD_AUDIT','SVF_DIR','LD_DEBUG','LD_PROFILE','LD_TRACE_LOADED_OBJECTS']
        unset+=['LD_LIBRARY_PATH'] if language=='C' else ['MIR_PROBE_CONTINUE','MIR_PROBE_OUTPUT','RUSTFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTUP_TOOLCHAIN']
        policy={'required':required,'unset':unset,'helper_options':extraction['helper_options'] if language=='C' else [],
            'working_directory':'$REPO','extapi_override':'Forbidden; no -extapi argument accepted',
            'substitution_policy':'Exact resolved paths, SHA-256, ELF metadata and complete dependency closure must match; no alternate SVF/library/model path or silent substitution.',
            'gate':'runtime_provenance.pre_measurement_gate(language, exact_launch_environment, exact_helper_options) must succeed immediately before every future authorized analyzer launch; no environment/options changes after gate.',
            'rustup_policy':'No rustup launcher: direct pinned rustc/driver and explicit sysroot; RUSTUP_TOOLCHAIN unset.' if language=='Rust' else 'Not applicable'}
        env=dict(os.environ)
        if language=='Rust':env.update({k:expand(v) for k,v in required.items()})
        enforce_environment(policy,env,policy['helper_options'])
        executable=ROOT/frozen[language]['helper_path' if language=='C' else 'driver_binary_path']
        compiler='/usr/lib/llvm-21/bin/clang' if language=='C' else ROOT/'build/rust-mir/toolchain/bin/rustc'
        seed={'executable':identity(executable),'compiler':identity(compiler)}
        found=inspect(language,seed,env)
        assert found['compiler']['sha256']==frozen[language]['compiler_sha256']
        assert found['executable']['sha256']==frozen[language]['helper_sha256' if language=='C' else 'driver_binary_sha256']
        extraction['dynamic_runtime']={'identities':found,'resolution_policy':policy,
            'inspection_method':'ldd/readelf under exact specified environment; canonical realpaths and SHA-256; no scientific entry point invoked',
            'scope':'Entire resolved ELF dependency closure of analyzer executable and compiler, including system libraries and loader. linux-vdso is kernel-provided, not a file.',
            'sysroot':'$REPO/build/rust-mir/toolchain' if language=='Rust' else None}
        if language=='C':extraction['link_policy']='Single translation unit: accepted backend copies its bitcode; llvm-link is not invoked or required for this corpus.'
    assert manifest['pairs']==approved
    for path,expected in require_old['sources'].items():assert sha(ROOT/path)==expected
    provenance={'status':'final_provenance_only_correction','superseded_bundles':[
        {'sha256':ORIGINAL,'status':'superseded_before_measurement','reason':'independent preregistration audit corrections R1-R5','analyzer_output_ever_existed':False},
        {'sha256':PRIOR,'status':'superseded_before_measurement','reason':'final independent preregistration audit identified incomplete dynamic analysis-runtime fingerprinting','analyzer_output_ever_existed':False}],
        'archive':archive.relative_to(HERE).as_posix(),'all_30_sources_unchanged':True,'all_approved_pairs_byte_equivalent_as_json':True,
        'archive_files_sha256':{p.relative_to(archive).as_posix():sha(p) for p in sorted(archive.rglob('*')) if p.is_file()}}
    write(HERE/'final_runtime_provenance.json',provenance)
    manifest['final_runtime_provenance']={'path':'final_runtime_provenance.json','sha256':sha(HERE/'final_runtime_provenance.json')}
    manifest['runtime_verification_gate']={'path':'runtime_provenance.py','sha256':sha(HERE/'runtime_provenance.py'),
        'instrument_verifier_path':'corpus_integrity.py','instrument_verifier_sha256':sha(HERE/'corpus_integrity.py')}
    write(HERE/'fixture_manifest.json',manifest)
    doc=HERE/'CALIBRATION_PREREGISTRATION.md'
    prior_doc=(archive/doc.name).read_text()
    doc.write_text(prior_doc+'\n## Final dynamic runtime provenance correction\n\n'
        +'R1-R4 and every pair/source/expectation/build/runtime field are unchanged. Full C and Rust analyzer/compiler dynamic dependency closures, canonical paths, SONAME/RPATH/RUNPATH metadata, SHA-256 values, exact Clang resolution and the selected SVF external model are bound in semantic_extraction_configuration.\n\n'
        +'C requires LD_LIBRARY_PATH and SVF_DIR unset, no extapi override, and no library substitution. The verifier repeats actual loader candidate resolution and external-model precedence from repository-root cwd. Rust uses the direct pinned toolchain/sysroot (no rustup selector), the existing exact two-directory LD_LIBRARY_PATH, RUSTC_BOOTSTRAP=1 and MIR_PROBE_TRANSITIVE=1. Both reject LD_PRELOAD/LD_AUDIT and verify the full dependency closure.\n\n'
        +'Before each future separately authorized calibration analyzer run, call runtime_provenance.pre_measurement_gate with the exact launch environment and helper options; abort on any error and do not change them after verification. This gate validates the bundle and resolved inputs, never launches an analyzer. verify_instruments now also reports expected/resolved paths and expected/actual hashes.\n\n'
        +'Both earlier bundles remain superseded_before_measurement, with no analyzer outputs. The latest supersession reason is: final independent preregistration audit identified incomplete dynamic analysis-runtime fingerprinting. See final_runtime_provenance.json.\n')
    result=validate(require_freeze=False)
    write(HERE/'fixture_hashes.json',result)
    print(result['calibration_fixture_bundle_sha256'])

if __name__=='__main__':main()
