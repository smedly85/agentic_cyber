"""Publish a new instrument record; never rewrites any previous study artifact."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "security/historical/rust"))
from semantic_gate import verify_frozen, fingerprint
from validate import validate_directory


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable(value):
    if isinstance(value, str): return value.replace(str(ROOT), "$REPO")
    if isinstance(value, list): return [portable(v) for v in value]
    if isinstance(value, dict): return {k: portable(v) for k,v in value.items()}
    return value


def write(name, value):
    (HERE/name).write_text(json.dumps(portable(value), indent=2, sort_keys=True) + "\n")


def main():
    frozen = verify_frozen()
    protected = validate_directory()
    cache = ROOT / "build/rust-instrument-v2"
    rust = json.loads((cache/'rust/results.json').read_text())
    c = json.loads((cache/'c/results.json').read_text())
    if len(rust['cases']) != 31 or len(c['controlled']) != 11 or len(c['observations']) != 9:
        raise ValueError("Incomplete required accounting")
    files = [HERE/'svf-byte-offset.patch', ROOT/'security/semantic_callgraph/native/semantic_callgraph_svf.cpp',
        ROOT/'security/semantic_callgraph/backend.py', ROOT/'security/semantic_callgraph/rust_identity.py',
        HERE/'run_rust.py', HERE/'run_c_regressions.py', HERE/'build_instrument.py', HERE/'publish.py']
    fixtures = [ROOT/'tests/fixtures/rust_semantic'/name for name in ('instrument.rs','dependency.rs','expanded.rs')]
    fixture_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in fixtures}
    svf = ROOT/'build/semantic-toolchain/SVF'
    svf_revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=svf,text=True).strip()
    if svf_revision != '67efb7745ce47b2b6853fd5696fc22c83d701e6c':
        raise ValueError('SVF pinned revision mismatch')
    helper = svf/'Release-build/bin/semantic-callgraph-svf'
    compiler = ROOT/'build/historical-rust/semantic/toolchain/bin/rustc'
    provenance = {
        'schema_version': 1, 'instrument': 'rust-c-semantic-audit-v2-local-byte-gep',
        'frozen_rust_inputs': frozen, 'original_svf_revision': '67efb7745ce47b2b6853fd5696fc22c83d701e6c',
        'upstream_review_revision': json.loads((cache/'acquisition/svf-master.json').read_text())['sha'],
        'patch_origin': 'local; upstream byte-offset implementation remains a stub',
        'upstream_issue': 'https://github.com/SVF-tools/SVF/issues/524',
        'svf_version': '3.4', 'llvm_version': '21.1.8',
        'verified_svf_revision': svf_revision,
        'patched_svf_source_sha256': sha(svf/'svf-llvm/lib/SVFIRBuilder.cpp'),
        'rustc_vV': subprocess.check_output([str(compiler),'-vV'], text=True),
        'helper_sha256': sha(helper), 'svf_llvm_library_sha256': sha(svf/'Release-build/lib/libSvfLLVM.so'),
        'original_helper_sha256': (cache/'original-helper.sha256').read_text().strip(),
        'repository_base_commit': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT,text=True).strip(),
        'source_fingerprints': {p.relative_to(ROOT).as_posix(): sha(p) for p in files},
        'fixture_fingerprints': fixture_hashes, 'controlled_suite_fingerprint': fingerprint(fixture_hashes),
        'rust_flags': ['--edition=2021','--target=x86_64-unknown-linux-gnu','-C opt-level=0','-C debuginfo=2',
            '-C codegen-units=1','-C embed-bitcode=yes','--remap-path-prefix=$REPO=.',
            'panic=abort for original library fixtures; panic=unwind for expanded binary fixtures'],
        'dependency_flags': ['scopeguard 1.2.0','--edition=2015','--cfg=feature="use_std"'],
        'pointer_analysis': 'AndersenWaveDiff', 'svf_options': ['-stat=false','-ff-eq-base'],
        'acquisition': json.loads((cache/'acquisition/manifest.json').read_text()),
        'old_provenance_unchanged': True,
    }
    provenance = portable(provenance)
    provenance['instrument_fingerprint'] = fingerprint(provenance)
    failed = [r['case'] for r in rust['cases'] if r['status'] != 'passed']
    # Readiness also requires complete site adjudication and reviewed historical
    # scope preparation. This pass may publish STOP only, never run pilots.
    result = {'schema_version':1,'instrument_fingerprint':provenance['instrument_fingerprint'],
        'frozen_inputs':frozen,'verdict':'STOP','historical_rust_measurements':False,
        'rust_controlled':rust,'c_regression':c,'rust_failed_cases':failed,
        'protected_artifacts':protected,
        'reason':'Required boxed dispatch and exact stack-field target tests fail; residual runtime sites remain unadjudicated.',
        'go_permitted':False,'rust_pilots_permitted':False}
    # Keep hashes of all retained diagnostics, with paths relative to ignored cache.
    diagnostics = {p.relative_to(cache).as_posix(): sha(p) for sub in ('rust','c')
                   for p in sorted((cache/sub).rglob('*')) if p.is_file()}
    write('instrument.json', provenance)
    write('results.json', result)
    write('diagnostic_manifest.json', {'cache_root':'build/rust-instrument-v2', 'files':diagnostics})
    write('artifact_manifest.json', {'frozen_inputs':frozen, 'json_fingerprints':{
        name:fingerprint(json.loads((HERE/name).read_text())) for name in ('instrument.json','results.json','diagnostic_manifest.json')}})
    print(json.dumps({'verdict':'STOP','instrument_fingerprint':provenance['instrument_fingerprint'],
        'rust_passed':31-len(failed),'rust_failed':failed,'c_controlled_passed':sum(r['passed'] for r in c['controlled']),
        'c_observations_unchanged':sum(r['passed'] for r in c['observations'])},indent=2))


if __name__ == '__main__': main()
