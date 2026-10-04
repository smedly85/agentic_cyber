"""Controlled Cargo closure prototype with a hash-authenticated crates.io input."""
import argparse
import hashlib
import json
import os
import shutil
import tarfile
from prepare import ROOT, HERE, require_c
from probe import BASE, SYSROOT, command
from inclusion import analyze
from std_config import rebuilt_std_flags


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    if not args.label.replace('-', '').isalnum():
        raise ValueError('Invalid label')
    require_c()
    out = BASE / 'cargo-validation' / args.label
    out.mkdir(parents=True, exist_ok=False)
    archive = ROOT / 'build/rust-instrument-v2/acquisition/scopeguard-1.2.0.crate'
    checksum = '94143f37725109f92c262ed2cf5e59bce7498c01bcc1502d7b9afe439a4e9f49'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == checksum
    vendor = out / 'vendor'
    vendor.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(vendor, filter='data')
    package = vendor / 'scopeguard-1.2.0'
    files = {p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(package.rglob('*')) if p.is_file() and p.name != '.cargo-checksum.json'}
    (package / '.cargo-checksum.json').write_text(json.dumps({'files': files, 'package': checksum}))
    env = os.environ.copy()
    env.update(RUSTC_BOOTSTRAP='1', RUSTC=str(SYSROOT / 'bin/rustc'),
               LD_LIBRARY_PATH=str(SYSROOT / 'lib') + ':' + str(SYSROOT / 'lib/rustlib/x86_64-unknown-linux-gnu/lib'),
               CARGO_HOME=str(out / 'cargo-home'))
    rustc = SYSROOT / 'bin/rustc'
    version = command([rustc, '-vV'], out, env)
    assert '254b59607d4417e9dffbc307138ae5c86280fe4c' in version
    driver = out / 'driver'
    shutil.copy2(HERE / 'driver.rs', out / 'driver.rs')
    command([rustc, HERE / 'driver.rs', '--edition=2021', '-C', 'prefer-dynamic',
             '-L', SYSROOT / 'lib', '-o', driver], out, env)
    wrapper = out / 'wrapper.py'
    shutil.copy2(HERE / 'cargo_wrapper.py', wrapper)
    wrapper.chmod(0o755)
    env.update(RUSTC_WRAPPER=str(wrapper), MIR_CARGO_DRIVER=str(driver))
    # Encoded flags retain the repository path as one argument despite spaces.
    flags = ['--sysroot', str(SYSROOT), '-C', 'opt-level=0', '-C', 'panic=unwind', '-C', 'codegen-units=1',
             '-Z', 'mir-opt-level=0', '-Z', 'inline-mir=no', '-Z', 'always-encode-mir',
             '--remap-path-prefix', str(ROOT) + '=.']
    flags.extend(rebuilt_std_flags(out))
    env['CARGO_ENCODED_RUSTFLAGS'] = '\x1f'.join(flags)
    manifest = ROOT / 'tests/fixtures/rust_mir/cargo/Cargo.toml'
    cargo = SYSROOT / 'bin/cargo'
    config = ['--offline', '--config', 'source.crates-io.replace-with="controlled-vendor"',
              '--config', 'source.controlled-vendor.directory=' + json.dumps(str(vendor))]
    metadata = json.loads(command([cargo, 'metadata', '--format-version=1', '--manifest-path', manifest, *config], out, env))
    (out / 'metadata.json').write_text(json.dumps(metadata, sort_keys=True, indent=2) + '\n')
    runs = []
    for run in ('run-1', 'run-2'):
        directory = out / run
        directory.mkdir()
        evidence = directory / 'crates'
        evidence.mkdir()
        env.update(CARGO_TARGET_DIR=str(directory / 'target'), MIR_CARGO_EVIDENCE=str(evidence))
        command([cargo, 'build', '--manifest-path', manifest, '--workspace', '--target=x86_64-unknown-linux-gnu',
                 *config], directory, env)
        invocations = [json.loads(p.read_text()) for p in sorted(evidence.glob('*.invocation.json'))]
        graphs = [json.loads(p.read_text()) for p in sorted(evidence.glob('*.api.json'))]
        binary = next(g for g in graphs if any(r['instance_identity'].endswith('::crate::main') for r in g['instances']))
        roots = [r['instance_identity'] for r in binary['instances'] if r['instance_identity'].endswith('::crate::main')]
        inclusion = analyze(binary, roots=roots)
        calls = [s for s in inclusion['sites'] if s['owner'].endswith('::mir_controlled_second::invoke')]
        # The downstream instance_mir query reads dependency bodies from their
        # encoded MIR; do not merge crate-local display strings as global IDs.
        bodies = [{k: r[k] for k in ('instance_identity', 'body_availability', 'defining_crate', 'phase',
                   'inlined_scopes') if k in r} for r in binary['instances']]
        normalized = json.dumps({'graph': binary, 'inclusion': inclusion}, sort_keys=True, indent=2) + '\n'
        (directory / 'graph.json').write_text(normalized)
        summary = {'invocations': invocations, 'bodies': bodies, 'cross_crate_indirect_sites': calls,
                   'cross_crate_callback_pass': len(calls) == 1 and len(calls[0]['targets']) == 1 and
                       calls[0]['targets'][0].endswith('::mir_controlled_second::target'),
                   'all_four_crates_analyzed': {r['crate'] for r in invocations} ==
                       {'mir_controlled_application', 'mir_controlled_first', 'mir_controlled_second', 'scopeguard'},
                   'scientific_sha256': hashlib.sha256(normalized.encode()).hexdigest()}
        runs.append(summary)
        print(run, 'four crates', summary['all_four_crates_analyzed'], 'callback', summary['cross_crate_callback_pass'], flush=True)
    result = {'scope': 'controlled_cargo_program_closure', 'accepted_backend': False,
              'status': 'MIR-STOP-INCOMPLETE', 'compiler': version, 'runs': runs,
              'scientific_rerun_identical': runs[0]['scientific_sha256'] == runs[1]['scientific_sha256'],
              'std_stage_verified': all(not r.get('inlined_scopes',0) for r in binary['instances']), 'build_std_used': True,
              'crates_io_input': {'package': 'scopeguard', 'version': '1.2.0', 'sha256': checksum,
                                  'transport': 'offline vendor of authenticated crates.io archive'},
              'dependency_edges': metadata['resolve']['nodes'],
              'packages': metadata['packages'],
              'blockers': ['remaining unsupported pointer/integer operations', 'Cargo runtime tracing not yet validated']}
    (out / 'result.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    require_c()


if __name__ == '__main__':
    main()
