"""Exact target-set checks for the 12 controlled Rust memory adversaries."""
import argparse
import hashlib
import json
import os
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
    out = BASE / 'memory-validation' / args.label
    out.mkdir(parents=True, exist_ok=False)
    fixture = ROOT / 'tests/fixtures/rust_mir'
    expected_path = fixture / 'memory_expectations.json'
    expected = json.loads(expected_path.read_text())
    env = os.environ.copy()
    env.update(RUSTC_BOOTSTRAP='1', MIR_PROBE_TRANSITIVE='1',
               LD_LIBRARY_PATH=str(SYSROOT / 'lib') + ':' + str(SYSROOT / 'lib/rustlib/x86_64-unknown-linux-gnu/lib'))
    rustc = SYSROOT / 'bin/rustc'
    assert '254b59607d4417e9dffbc307138ae5c86280fe4c' in command([rustc, '-vV'], out, env)
    driver = out / 'driver'
    command([rustc, HERE / 'driver.rs', '--edition=2021', '-C', 'prefer-dynamic',
             '-L', SYSROOT / 'lib', '-o', driver], out, env)
    std_flags = rebuilt_std_flags(out)
    rows = []
    for case in expected['cases']:
        hashes = []
        for run in ('run-1', 'run-2'):
            directory = out / case['case'] / run
            directory.mkdir(parents=True)
            raw = json.loads(command([driver, fixture / 'memory.rs', '--crate-name=memory_control',
                '--sysroot', SYSROOT, '--edition=2021', '--target=x86_64-unknown-linux-gnu',
                '-C', 'opt-level=0', '-C', 'panic=unwind', '-C', 'codegen-units=1',
                '-Z', 'mir-opt-level=0', '-Z', 'inline-mir=no', '-Z', 'always-encode-mir',
                '--remap-path-prefix', str(ROOT) + '=.', '--cfg=memory_case="' + case['case'] + '"',
                *std_flags, '-A', 'warnings', '--emit=link', '--out-dir', directory], directory, env))
            roots = [r['instance_identity'] for r in raw['instances'] if r['instance_identity'].endswith('::crate::main')]
            assert len(roots) == 1
            result = analyze(raw, roots=roots)
            reports = []
            for owner, targets in case['sites'].items():
                sites = [s for s in result['sites'] if s['owner'].endswith('::crate::' + owner)]
                # Selectors identify known test functions only; they never resolve backend edges.
                actual = sorted({t.split('::crate::')[-1] for s in sites for t in s['targets']})
                extra = sorted(set(actual) - set(targets))
                missing = sorted(set(targets) - set(actual))
                reports.append({'owner': owner, 'expected_targets': targets, 'actual_targets': actual,
                    'missing_targets': missing, 'unexpected_targets': extra, 'site_count': len(sites),
                    'target_set_pass': len(sites) == 1 and not missing and
                        set(extra) <= set(case.get('allowed_conservative_extras', []))})
            scientific = json.dumps({'api': raw, 'inclusion': result}, sort_keys=True, indent=2) + '\n'
            (directory / 'graph.json').write_text(scientific)
            hashes.append(hashlib.sha256(scientific.encode()).hexdigest())
        marker = not case.get('requires_precision_loss_marker', False) or bool(result.get('precision_losses'))
        if not case.get('requires_precision_loss_marker', False):
            marker = not result.get('precision_losses')
        row = {'case': case['case'], 'sites': reports, 'precision_loss_requirement_met': marker,
               'target_checks_pass': all(r['target_set_pass'] for r in reports) and marker,
               'deterministic': len(set(hashes)) == 1, 'fingerprints': hashes,
               'unsupported_operations': result['unsupported_operations'],
               'precision_losses': result.get('precision_losses', []),
               'allocations': result.get('allocations', []),
               'accepted_backend': False, 'full_semantic_status': 'incomplete'}
        rows.append(row)
        print(case['case'], 'target checks', row['target_checks_pass'], 'deterministic', row['deterministic'], flush=True)
        (out / 'result.json').write_text(json.dumps({'cases': rows,
            'expectations_sha256': hashlib.sha256(expected_path.read_bytes()).hexdigest(),
            'status': 'MIR-STOP-INCOMPLETE'}, sort_keys=True, indent=2) + '\n')
    require_c()


if __name__ == '__main__':
    main()
