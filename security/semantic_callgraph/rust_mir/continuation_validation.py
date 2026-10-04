"""Re-extract all 31 fixtures with codegen enabled and explicit root selection.

This runner checks target reachability and reports indirect sets, but deliberately
does not call these partial checks full semantic validation. It preserves the
original spike artifacts and never reads historical Rust specimen source.
"""
import argparse
import hashlib
import json
import os
import shutil
from prepare import ROOT, HERE, require_c
from probe import BASE, SYSROOT, command
from inclusion import analyze
from std_config import rebuilt_std_flags


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    options = parser.parse_args()
    if not options.label.replace('-', '').isalnum():
        raise ValueError('Invalid label')
    require_c()
    out = BASE / 'continuation' / options.label
    out.mkdir(parents=True, exist_ok=False)
    for name in ('driver.rs','inclusion.py','body_ledger.py','std_config.py'):
        shutil.copy2(HERE / name, out / name)
    env = os.environ.copy()
    env.update(RUSTC_BOOTSTRAP='1', MIR_PROBE_TRANSITIVE='1',
               LD_LIBRARY_PATH=str(SYSROOT / 'lib') + ':' + str(SYSROOT / 'lib/rustlib/x86_64-unknown-linux-gnu/lib'))
    rustc = SYSROOT / 'bin/rustc'
    assert '254b59607d4417e9dffbc307138ae5c86280fe4c' in command([rustc, '-vV'], out, env)
    driver = out / 'driver'
    command([rustc, HERE / 'driver.rs', '--edition=2021', '-C', 'prefer-dynamic',
             '-L', SYSROOT / 'lib', '-o', driver], out, env)
    flags = ['--sysroot', SYSROOT, '-C', 'opt-level=0', '-C', 'codegen-units=1',
             '-Z', 'mir-opt-level=0', '-Z', 'inline-mir=no', '-Z', 'always-encode-mir',
             '--remap-path-prefix', str(ROOT) + '=.', '--target=x86_64-unknown-linux-gnu']
    flags.extend(rebuilt_std_flags(out))
    fixtures = ROOT / 'tests/fixtures/rust_semantic'
    cases = [r['case'] for r in json.loads((HERE / 'controlled_results.json').read_text())['cases']]
    all_runs = []
    for run in ('run-1', 'run-2'):
        directory = out / run
        directory.mkdir()
        command([rustc, fixtures / 'dependency.rs', '--edition=2021', '--crate-type=rlib',
                 '--crate-name=semantic_dependency', '-C', 'panic=unwind', *flags, '--out-dir', directory], directory, env)
        acquisition = ROOT / 'build/rust-instrument-v2/acquisition'
        archive = acquisition / 'scopeguard-1.2.0.crate'
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == '94143f37725109f92c262ed2cf5e59bce7498c01bcc1502d7b9afe439a4e9f49'
        command([rustc, acquisition / 'scopeguard-1.2.0/src/lib.rs', '--edition=2015', '--crate-type=rlib',
                 '--crate-name=scopeguard', '--cfg=feature="use_std"', *flags, '--out-dir', directory], directory, env)
        results = []
        for index, case in enumerate(cases):
            case_dir = directory / case
            case_dir.mkdir()
            source = fixtures / ('instrument.rs' if index < 13 else 'expanded.rs')
            extra = (['--crate-type=rlib', '--crate-name=semantic_instrument', '-C', 'panic=unwind', '--extern',
                      'semantic_dependency=' + str(directory / 'libsemantic_dependency.rlib')] if index < 13 else
                     ['--crate-name=expanded', '-C', 'panic=unwind', '--cfg=audit_case="' + case + '"', '--extern',
                      'scopeguard=' + str(directory / 'libscopeguard.rlib')])
            try:
                # Metadata-only collection yielded zero instances for library fixtures.
                raw = json.loads(command([driver, source, '--edition=2021', *flags, *extra,
                                          '-A', 'dead_code', '--emit=link', '--out-dir', case_dir], case_dir, env))
                roots = [r['instance_identity'] for r in raw['instances'] if r['instance_identity'].endswith(
                    '::crate::entry_' + case if index < 13 else '::crate::main')]
                if len(roots) != 1:
                    raise ValueError('Expected one configured root, got ' + repr(roots))
                result = analyze(raw, roots=roots)
                target_suffix = ('::semantic_dependency::cross_target' if case.startswith('cross_crate_') else '::crate::target')
                expected = sorted(r['instance_identity'] for r in raw['instances'] if r['instance_identity'].endswith(target_suffix))
                actual = sorted(set(expected) & set(result['active_instances']))
                indirect = []
                sites = {(s['owner'], s['block']): s for s in result['sites']}
                for owner in raw['instances']:
                    for site in owner['calls']:
                        key = owner['instance_identity'], site['block']
                        if key in sites and site['status'].startswith('unresolved'):
                            indirect.append({**sites[key], 'extraction_status': site['status'],
                                'expected_targets': None, 'actual_targets': sites[key]['targets'],
                                'missing_targets': None, 'unexpected_targets': None,
                                'validation_status': 'not_adjudicated'})
                write(case_dir / 'api.json', raw)
                write(case_dir / 'inclusion.json', result)
                write(case_dir / 'required_body_ledger.json', result['required_body_ledger'])
                record = {'case': case, 'instances': len(raw['instances']), 'root': roots[0],
                          'expected_semantic_result': 'Configured entry reaches the designated target; full case-specific paths and target sets also require validation.',
                          'actual_semantic_result': 'target_reachable' if actual else 'target_not_reached',
                          'missing': sorted(set(expected) - set(actual)), 'unexpected': None,
                          'target_inventory_present': bool(expected), 'indirect_callsites': indirect,
                          'unsupported_operations': result['unsupported_operations'],
                          'converged': result['converged'], 'semantic_status': 'incomplete',
                          'api_sha256': hashlib.sha256((case_dir / 'api.json').read_bytes()).hexdigest(),
                          'inclusion_sha256': hashlib.sha256((case_dir / 'inclusion.json').read_bytes()).hexdigest()}
            except Exception as error:
                record = {'case': case, 'semantic_status': 'failed', 'error': str(error)}
            results.append(record)
            print(run, case, record['semantic_status'], record.get('actual_semantic_result', ''), flush=True)
            write(directory / 'results.json', results)
        all_runs.append(results)
    determinism = [{'case': a['case'], 'identical': all(a.get(k) is not None and a[k] == b.get(k)
                    for k in ('api_sha256', 'inclusion_sha256'))} for a, b in zip(*all_runs)]
    write(out / 'result.json', {'accepted_backend': False, 'cases': all_runs[0],
                              'determinism': determinism, 'all_identical': all(r['identical'] for r in determinism),
                              'status': 'MIR-STOP-INCOMPLETE',
                              'driver_sha256': hashlib.sha256((out / 'driver.rs').read_bytes()).hexdigest(),
                              'inclusion_sha256': hashlib.sha256((out / 'inclusion.py').read_bytes()).hexdigest()})
    require_c()


if __name__ == '__main__':
    main()
