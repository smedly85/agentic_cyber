"""Read-only integrity checks using the frozen post-calibration preservation policy."""
import argparse, datetime, hashlib, pathlib, sys
from common import ROOT,HERE,OUT,RESULTS,REFERENCE,REFERENCE_SHA,read,sha,write
sys.path[:0]=[str(ROOT),str(ROOT/'security/semantic_callgraph/cross_language_calibration'),str(ROOT/'security/historical/rust')]
from runtime_provenance import verify_all_runtimes
from corpus_integrity import verify_std,C_HELPER,RUST_START
from inspect_frozen_builds import verify_phase_a

def instruments():
    calibration=ROOT/'security/semantic_callgraph/cross_language_calibration'
    phase=verify_phase_a()
    runtime=verify_all_runtimes()
    frozen=read(calibration/'instrument_fingerprints.json');checks={}
    assert frozen['C']['helper_sha256']==C_HELPER and frozen['Rust']['calibration_start_sha256']==RUST_START
    for language in ('C','Rust'):
        for name,expected in frozen[language]['sources'].items():checks[name]=sha(ROOT/name)==expected
    checks['C helper']=sha(ROOT/frozen['C']['helper_path'])==C_HELPER
    checks['Rust driver']=sha(ROOT/frozen['Rust']['driver_binary_path'])==frozen['Rust']['driver_binary_sha256']
    checks['reference solver']=sha(REFERENCE)==REFERENCE_SHA
    configuration=read(calibration/'fixture_manifest.json')['semantic_extraction_configuration']
    canonical=read(calibration/'semantic_extraction_canonical.json')
    for ref in (configuration['C']['canonical_provider'],configuration['Rust']['std_flag_provider'],
                configuration['Rust']['rebuilt_std_build_record'],configuration['Rust']['driver']['source'],canonical['source_log']):
        checks[ref['path']]=sha(ROOT/ref['path'])==ref['sha256']
    verify_std(configuration['Rust'])
    cfiles={}
    for name,expected in read(ROOT/'security/historical/rust/protected_c_artifacts.json')['files'].items():
        data=(ROOT/name).read_bytes();checks['protected C:'+name]=hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()==expected
        cfiles[name]=hashlib.sha256(data).hexdigest()
    assert len(cfiles)==159 and all(checks.values()),[k for k,v in checks.items() if not v]
    return {'status':'PASS','checks':checks,'dynamic_runtime':runtime,'protected_c_byte_hashes':cfiles,
            'c_helper_sha256':C_HELPER,'rust_calibration_start_sha256':RUST_START,
            'classifier_fingerprint':phase['aggregate_classifier_sha256'],
            'calibration_guard':'Frozen Phase-A post-publication inventory; historical null-result placeholders are not used as current measured-output identities.',
            'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}

def main(output):
    from study import verify
    from security.historical.rust.validate import validate_directory
    fingerprint=verify();population=validate_directory()
    failures=[];cleanup=ROOT/'build/rust-depth-cleanup/rust_audit_preserve_manifest.json'
    if not cleanup.exists():cleanup=ROOT/'build/rust-depth-cleanup/preserve_manifest.json'
    baseline=read(cleanup)['files'] if cleanup.exists() else {
        (RESULTS/name).relative_to(ROOT).as_posix():h for name,h in read(RESULTS/'artifact_hashes.json')['files'].items()}
    for i,(name,expected) in enumerate(baseline.items(),1):
        p=ROOT/name
        if not p.is_file() or sha(p)!=expected:failures.append(name)
        if i%5000==0:print('After hashes',i,'/',len(baseline),flush=True)
    for row in read(OUT/'input_inventory.json'):
        if sha(ROOT/row['input_path'])!=row['input_sha256']:failures.append(row['input_path'])
    current=instruments();before=read(OUT/'instrument_before_performance.json')
    assert current['protected_c_byte_hashes']==before['protected_c_byte_hashes']
    write(output,{'status':'FAIL' if failures else 'PASS','protected_files_verified':len(baseline),
          'changed_or_missing':failures,'instruments':current,'population_validation':population,
          'method_fingerprint':fingerprint,'cleanup_preservation_manifest':str(cleanup) if cleanup.exists() else None})
    assert not failures,failures
    print('Final integrity PASS',len(baseline),'protected files',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();main(a.output)
