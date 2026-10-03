"""Controlled stage experiments. No historical inputs and no graph acceptance.

Keep the old spike records intact. Each execution requires a fresh --label.
The optimized dependency is a negative control, never a candidate stage.
"""
import argparse
import hashlib
import json
import os
from prepare import ROOT, HERE, require_c
from probe import BASE, SYSROOT, command


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    if not args.label.replace('-', '').isalnum():
        raise ValueError('Invalid label')
    require_c()
    out = BASE / 'stage-validation' / args.label
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(RUSTC_BOOTSTRAP='1', MIR_PROBE_TRANSITIVE='1',
               LD_LIBRARY_PATH=str(SYSROOT / 'lib') + ':' + str(SYSROOT / 'lib/rustlib/x86_64-unknown-linux-gnu/lib'))
    rustc = SYSROOT / 'bin/rustc'
    version = command([rustc, '-vV'], out, env)
    assert '254b59607d4417e9dffbc307138ae5c86280fe4c' in version
    driver = out / 'driver'
    command([rustc, HERE / 'driver.rs', '--edition=2021', '-C', 'prefer-dynamic',
             '-L', SYSROOT / 'lib', '-o', driver], out, env)
    common = ['--sysroot', SYSROOT, '--edition=2021', '--target=x86_64-unknown-linux-gnu',
              '-C', 'panic=unwind', '-C', 'codegen-units=1', '-Z', 'always-encode-mir',
              '--remap-path-prefix', str(ROOT) + '=.']
    frozen = ['-C', 'opt-level=0', '-Z', 'mir-opt-level=0', '-Z', 'inline-mir=no']
    optimized = ['-C', 'opt-level=3', '-Z', 'mir-opt-level=4', '-Z', 'inline-mir=yes']
    fixture = ROOT / 'tests/fixtures/rust_mir'
    results = []
    for variant in ('consistent', 'optimized_dependency', 'optimized_local'):
        hashes = []
        for run in ('run-1', 'run-2'):
            directory = out / variant / run
            directory.mkdir(parents=True)
            depflags = optimized if variant == 'optimized_dependency' else frozen
            localflags = optimized if variant == 'optimized_local' else frozen
            command([rustc, fixture / 'stage_dependency.rs', '--crate-name=stage_dependency',
                     '--crate-type=rlib', *common, *depflags, '--out-dir', directory], directory, env)
            raw = command([driver, fixture / 'stage.rs', '--crate-name=stage_control',
                           *common, *localflags, '--extern',
                           'stage_dependency=' + str(directory / 'libstage_dependency.rlib'),
                           '--emit=metadata', '--out-dir', directory], directory, env)
            graph = json.loads(raw)
            scientific = json.dumps(graph, sort_keys=True, separators=(',', ':')) + '\n'
            (directory / 'api.json').write_text(scientific)
            hashes.append(hashlib.sha256(scientific.encode()).hexdigest())
            rows = graph['instances']
            def select(suffix):
                found = [r for r in rows if r['instance_identity'].endswith(suffix)]
                return found[0] if len(found) == 1 else None
            def edge(caller, callee):
                row = select(caller)
                return bool(row and any(c.get('target', '').endswith(callee)
                                       for c in row['calls'] if c.get('target')))
            checks = {
                'main_direct': edge('::crate::main', '::crate::direct'),
                'direct_leaf': edge('::crate::direct', '::crate::leaf'),
                'generic_call': edge('::crate::main', '::crate::generic::<u64>'),
                'closure_call': bool(select('::crate::main') and any(
                    '{closure' in (c.get('target') or '') for c in select('::crate::main')['calls'])),
                'drop_call': bool(select('::crate::main') and any(
                    c['status'] == 'drop_instance' for c in select('::crate::main')['calls'])),
                'dependency_direct': edge('::crate::main', '::stage_dependency::dependency_direct'),
                'dependency_leaf': edge('::stage_dependency::dependency_direct', '::stage_dependency::dependency_leaf'),
                'dependency_generic': edge('::crate::main', '::stage_dependency::dependency_generic::<u64>'),
                'dependency_non_generic_body': bool(select('::stage_dependency::dependency_non_generic') and
                    select('::stage_dependency::dependency_non_generic').get('body_availability') == 'available body'),
                'dependency_non_generic_call': edge('::stage_dependency::dependency_non_generic', '::stage_dependency::dependency_direct'),
                'local_no_inlined_scopes': all(r.get('inlined_scopes', 0) == 0 for r in rows if r.get('local_definition')),
                'dependency_no_inlined_scopes': all(r.get('inlined_scopes', 0) == 0 for r in rows if r.get('defining_crate') == 'stage_dependency'),
            }
            body_inventory = [{k: r[k] for k in ('instance_identity', 'body_availability', 'defining_crate',
                               'local_definition', 'phase', 'inlined_scopes') if k in r} for r in rows]
        results.append({'variant': variant, 'checks': checks, 'fingerprints': hashes,
                        'deterministic': len(set(hashes)) == 1, 'bodies': body_inventory})
        print(variant, checks, 'deterministic', len(set(hashes)) == 1, flush=True)
    result = {'accepted_backend': False, 'compiler': version, 'api': 'TyCtxt::instance_mir',
              'common_flags': [str(a).replace(str(ROOT), '$REPO') for a in common],
              'candidate_flags': frozen, 'negative_control_flags': optimized, 'experiments': results,
              'driver_sha256': digest(HERE / 'driver.rs'),
              'candidate_local_dependency_stage_pass': all(results[0]['checks'].values()),
              'std_stage_verified': False,
              'policy': 'Precompiled sysroot stage is unauthenticated; required std/core bodies block acceptance.'}
    (out / 'result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print('Evidence:', out / 'result.json', flush=True)
    require_c()


if __name__ == '__main__':
    main()
