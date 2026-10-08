"""Read-only hash guards. No backend execution or graph-output inspection."""
from pathlib import Path
from validate_corpus import HERE,ROOT,read,sha,require

C_HELPER='ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2'
RUST_START='514e397d83f9fd2be32e42b69970861036c7251dd2a2dbf38591a6ad7ec76e20'


def verify_instruments():
    from runtime_provenance import verify_all_runtimes
    runtime_report=verify_all_runtimes()
    frozen=read(HERE/'instrument_fingerprints.json');checks={}
    require(frozen['Rust']['calibration_start_sha256']==RUST_START,'Rust start fingerprint differs')
    require(frozen['C']['helper_sha256']==C_HELPER,'C start fingerprint differs')
    for language in ('C','Rust'):
        for name,expected in frozen[language]['sources'].items():checks[name]=sha(ROOT/name)==expected
    checks['C helper']=sha(ROOT/frozen['C']['helper_path'])==C_HELPER
    checks['Rust driver binary']=sha(ROOT/frozen['Rust']['driver_binary_path'])==frozen['Rust']['driver_binary_sha256']
    checks['Rust compiler']=sha(ROOT/'build/rust-mir/toolchain/bin/rustc')==frozen['Rust']['compiler_sha256']
    checks['C compiler']=sha(Path('/usr/lib/llvm-21/bin/clang'))==frozen['C']['compiler_sha256']
    extraction=read(HERE/'fixture_manifest.json')['semantic_extraction_configuration']
    canonical=read(HERE/'semantic_extraction_canonical.json')
    for ref in (extraction['C']['canonical_provider'],extraction['Rust']['std_flag_provider'],
                extraction['Rust']['rebuilt_std_build_record'],extraction['Rust']['driver']['source'],canonical['source_log']):
        checks['extraction configuration:'+ref['path']]=sha(ROOT/ref['path'])==ref['sha256']
    verify_std(extraction['Rust'])
    # Preserve the preflight report, null results and fingerprint files byte for byte.
    previous=read(HERE/'artifact_manifest.json')
    for name,expected in previous.items():checks['preflight:'+name]=sha(HERE/name)==expected
    protected=read(ROOT/'security/historical/rust/protected_c_artifacts.json')['files']
    import hashlib
    for name,expected in protected.items():
        checks['protected C:'+name]=hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==expected
    require(len(protected)==159,'Protected C inventory differs')
    require(all(checks.values()),'Frozen artifacts changed: '+str([k for k,v in checks.items() if not v]))
    return {'c_helper_sha256':C_HELPER,'rust_calibration_start_sha256':RUST_START,
            'all_unchanged':True,'protected_c_artifacts_unchanged':159,
            'preflight_artifacts_unchanged':len(previous),'checked_hashes':checks,
            'dynamic_runtime_verification':runtime_report}


def verify_std(configuration):
    libraries=configuration['std_policy']['libraries'];found={}
    flags=configuration['flags']
    for i,arg in enumerate(flags[:-1]):
        if arg=='--extern' and flags[i+1].startswith('noprelude:'):
            name,path=flags[i+1].split('=',1);name=name.removeprefix('noprelude:')
            actual=sha(Path(path.replace('$REPO',str(ROOT))))
            require(actual==libraries[name]['sha256'],'Rebuilt standard library changed: '+name)
            found[name]=actual
    require(set(found)==set(libraries),'Rebuilt std configuration incomplete')
    return found
