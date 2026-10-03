"""Publish controlled continuation evidence without upgrading incomplete gates."""
import argparse
from collections import Counter
import hashlib
import json
import shutil
from prepare import ROOT, HERE, require_c


def read(path):
    return json.loads(path.read_text())


def write(name, value):
    (HERE / name).write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if (HERE / 'core_results.json').exists():
        raise RuntimeError('Prior continuation publisher cannot overwrite core evidence; use publish_core.py')
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True)
    parser.add_argument('--controlled', required=True)
    parser.add_argument('--memory', required=True)
    parser.add_argument('--cargo', required=True)
    parser.add_argument('--c', required=True)
    args = parser.parse_args()
    for value in vars(args).values():
        if not value.replace('-', '').isalnum():
            raise ValueError('Invalid evidence label')
    require_c()
    base = ROOT / 'build/rust-mir'
    paths = {'stage': base / 'stage-validation' / args.stage / 'result.json',
             'controlled': base / 'continuation' / args.controlled / 'result.json',
             'memory': base / 'memory-validation' / args.memory / 'result.json',
             'cargo': base / 'cargo-validation' / args.cargo / 'result.json',
             'c': base / 'c-validation' / args.c / 'results.json'}
    stage, controlled, memory, cargo, c = (read(paths[key]) for key in paths)
    assert len(controlled['cases']) == 31 and len(memory['cases']) == 12
    assert c['passed'] and len(c['controlled']) == 11 and len(c['observations']) == 9
    assert c['protected_c_files_unchanged'] == 159
    write('stage_validation.json', stage)
    write('continuation_results.json', controlled)
    write('memory_results.json', memory)
    write('cargo_results.json', cargo)
    write('continuation_c_regression.json', c)
    unfinished = [
        'allocation-site heap objects and Box value flow',
        'receiver-refined dyn Trait and dyn Fn/FnMut dispatch',
        'constant/static/promoted allocation contents',
        'complete closure environment and RustCall argument propagation',
        'allocation-local conservative unsafe/byte/union/index collapse and precision-loss markers',
        'uniform authenticated std/core stage and explicit required-body/intrinsic policy',
        'full semantic path and target-set adjudication of all 31 cases',
        'independent dynamic edge tracing and soundness validation',
        'execution of the 15 preregistered C/Rust calibration pairs and raw edge categorization',
        'cross-language target-set precision distribution and accepted full-suite reruns',
    ]
    status = {'status': 'MIR-STOP-INCOMPLETE', 'accepted_backend': False,
              'historical_measurement': False, 'compiler': stage['compiler'],
              'mir_stage': 'instance_mir / Runtime(Optimized)',
              'local_dependency_flags': stage['candidate_flags'],
              'common_flags': stage['common_flags'],
              'driver_sha256': sha(HERE / 'driver.rs'), 'inclusion_sha256': sha(HERE / 'inclusion.py'),
              'stage_local_dependency_checks_pass': stage['candidate_local_dependency_stage_pass'],
              'std_stage_verified': False, 'full_semantic_cases_passed': 0,
              'partial_target_reachable': sum(r.get('actual_semantic_result') == 'target_reachable' for r in controlled['cases']),
              'memory_target_checks_passed': sum(r['target_checks_pass'] for r in memory['cases']),
              'memory_cases': 12, 'full_memory_semantic_gate': False,
              'cargo_scope': cargo['scope'], 'cargo_four_crates_analyzed': all(r['all_four_crates_analyzed'] for r in cargo['runs']),
              'partial_31_graph_reruns_identical': controlled['all_identical'],
              'partial_memory_graph_reruns_identical': all(r['deterministic'] for r in memory['cases']),
              'partial_cargo_graph_reruns_identical': cargo['scientific_rerun_identical'],
              'full_suite_determinism': 'not established for an accepted implementation',
              'dynamic_soundness': 'not_run', 'calibration': 'not_run', 'blockers': unfinished,
              'c_controlled': '11/11 unchanged', 'c_historical': '9/9 unchanged', 'protected_c_artifacts': 159,
              'c_helper_sha256': sha(ROOT / 'build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf'),
              'evidence': {k: {'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)} for k, p in paths.items()}}
    if not (HERE / 'spike_instrument.json').exists():
        shutil.copy2(HERE / 'instrument.json', HERE / 'spike_instrument.json')
    write('instrument.json', status)
    rows = [
        '# MIR-STOP-INCOMPLETE — controlled continuation', '',
        'MIR remains a promising candidate. No backend graph is accepted. No historical Rust specimen was built or measured. The frozen Rust population/mappings and C instrument/results were not modified.', '',
        '## 1. MIR stage', '',
        '`TyCtxt::instance_mir` returns `Runtime(Optimized)`. Twelve checks pass for local and dependency MIR: direct calls, generic calls, closure calls, drops, non-generic dependency bodies/calls, and absence of inlined scopes. Two fresh runs of each stage variant are identical.', '',
        'Candidate flags: `RUSTC_BOOTSTRAP=1 --edition=2021 --target=x86_64-unknown-linux-gnu -C opt-level=0 -C panic=unwind -C codegen-units=1 -Z mir-opt-level=0 -Z inline-mir=no -Z always-encode-mir`; explicit isolated sysroot and repository path remapping. Original controlled no_std library fixtures use panic=abort consistently with their dependency.', '',
        'The optimized-dependency negative control removes dependency_direct -> dependency_leaf and dependency_non_generic -> dependency_direct despite local opt-level zero. The optimized-local control removes direct/generic/closure transitions. Phase labels alone do not establish equivalence across crates. Precompiled std is not approved by this contract. No alternate API was needed for the successful local/dependency experiment; a uniform whole-program stage is still unfinished.', '',
        '## 2–5. Heap, dyn dispatch, function pointers, and closures', '',
        'Allocation-site heap modeling and receiver-based dyn dispatch are unfinished. Heap storage and mixed stack/heap target checks fail. Values remain separate function/address tokens in typed local/subobject cells, but there is no accepted allocation object model.', '',
        'The inclusion solver now accepts configured roots, avoids contamination from unreachable library entry points, and propagates typed struct/tuple/closure fields and enum variant fields. Direct calls into encoded dependency bodies are traversed. Missing bodies and empty inventories fail closed. Unsupported operations still prevent acceptance.', '',
        'Direct closure, Option::map, Result::or_else, and Iterator::flat_map fixtures reach the designated target in partial graphs. This does not validate all closure captures or RustCall ABI adaptation. dyn Fn and Box<dyn FnMut> still fail. Compiler-generated instances remain in the graph; no shim contraction was added.', '',
        '## 6. std/core MIR policy', '',
        'Per-instance body availability is recorded in stage_validation.json and cargo_results.json. Generic std/core bodies are available selectively. The controlled Cargo graph exposes std bodies with inlined scopes and missing MIR for std::rt::lang_start_internal; compiler intrinsics are explicit unsupported boundaries. These are not treated as libc or successful leaves. A reproducible sysroot rebuild (build-std or equivalent) and intrinsic semantics remain necessary to test a common stage. build-std was not executed.', '',
        '## 7. Cargo closure', '',
        'Two fresh Cargo builds compiled one binary, two local libraries, and crates.io scopeguard 1.2.0. The registry archive was checked against its frozen checksum and vendored offline. Every crate ran under the driver with the same MIR flags. Package, crate, target, rustc invocation, features, dependency edges, edition, profile, panic strategy, and encoded MIR requests are retained. The callback through both local libraries resolves to exactly its assigned target.', '',
        'Scope is `controlled_cargo_program_closure`, not linker_exact. Downstream compiler queries load encoded upstream bodies; separate crate-local display strings are not merged as global identities. Sysroot stage and full value semantics still block acceptance.', '',
        '## 8. Unsafe memory', '',
        'The byte-copy adversary fails: no conservative allocation-local merge or precision-loss marker is implemented. Raw pointer fields, unions, transmute, variable offsets/indexes, and complete byte-copy behavior remain unfinished. Unsupported-operation records are rejection evidence, not implemented conservative precision loss.', '',
        '## 9. All 31 controlled cases', '',
        'The old first 13 API-success records had zero instances because they requested metadata-only library compilation. These archived records remain intact; the new runner uses codegen-enabled collection and requires exactly one configured root. All 31 now have nonempty extraction inventories. The table reports only the executed reachability check; case-specific path, target-set, and trace validation remains incomplete. Unknown unexpected targets are not asserted empty.', '',
        '| Case | Expected (partial check) | Actual | Missing designated target | Unexpected | Full semantic verdict |',
        '|---|---|---|---|---|---|',
    ]
    for case in controlled['cases']:
        reached = case.get('actual_semantic_result') == 'target_reachable'
        rows.append(f"| {case['case']} | entry reaches designated target | {'reached' if reached else 'not reached'} | {'none for this check' if reached else 'yes'} | not fully adjudicated | INCOMPLETE |")
    rows += ['', 'No case is promoted to a full semantic pass from this partial check.', '',
             '## 10. Twelve memory adversaries', '',
             'Expected sets were fixed in tests/fixtures/rust_mir/memory_expectations.json before executing this matrix. Flow-insensitive overwrite deliberately retains both assignments.', '',
             '| Case / site | Expected targets | Actual targets | Missing | Extra | Target/marker check |',
             '|---|---|---|---|---|---|']
    for case in memory['cases']:
        for site in case['sites']:
            rows.append('| ' + ' | '.join([case['case'] + ' / ' + site['owner'], ', '.join(site['expected_targets']) or 'none',
                ', '.join(site['actual_targets']) or 'none', ', '.join(site['missing_targets']) or 'none',
                ', '.join(site['unexpected_targets']) or 'none', 'PASS' if case['target_checks_pass'] else 'FAIL']) + ' |')
    rows += ['', 'Nine focused target checks pass. Heap storage, stack+heap, and unsafe byte copying fail. A passing target check is not full backend acceptance.', '',
             '## 11. Dynamic traces', '',
             'Not run. No claim that dynamic edges are a subset of static edges. Dynamic traces supplied no static edges.', '',
             '## 12. Fifteen preregistered C/Rust pairs', '',
             'Preregistration and expected semantics remain unchanged. These pairs were not executed; no calibration pass is inferred from separate C or Rust fixture tests.', '',
             '| Pair | Result |', '|---|---|']
    for pair in read(HERE / 'calibration_results.json')['pairs']:
        rows.append(f"| {pair['pair']} | NOT RUN |")
    sizes = Counter(len(site['actual_targets']) for case in memory['cases'] for site in case['sites'])
    rows += ['', '## 13. Target-set precision', '',
             'The memory table records actual/expected/missing/extra targets at every tested site. Actual set-size distribution across these Rust memory sites: ' + ', '.join(f'{k} targets: {v} sites' for k, v in sorted(sizes.items())) + '. Empty sets remain failures, not precise resolved calls.', '',
             'C/Rust overlap and precision distributions remain unavailable. Calibration raw_edges/std_core_edges/compiler_shim_edges/user_application_edges are not computed; raw instance edges and shims were not contracted.', '',
             '## 14. Deterministic reruns', '',
             'Byte-identical scientific artifacts: 31/31 partial controlled graphs, 12/12 memory graphs, the Cargo application graph, and each stage experiment. All use fresh output directories; graph JSON is deterministically serialized. No session DefId, address, or temporary output path is used as an instance identity. This is reproducibility evidence for an incomplete implementation, not the required accepted-suite determinism gate.', '',
             '## 15. Frozen C regression', '',
             'C controlled 11/11 unchanged; C historical observations 9/9 unchanged; protected C artifacts 159/159 unchanged. The canonical helper remains `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2`. Validation outputs are in a fresh MIR-owned directory. No C expectations, backend semantics, or historical results were rewritten.', '',
             '## 16. Files and tests', '',
             'Changed driver.rs (transitive body queries, explicit unavailable boundaries, typed aggregates, stage metadata, Cargo continuation), inclusion.py (typed aggregates, root-scoped fixed point, fail-closed inventory/body handling), graph.py (unavailable-body boundaries), and verify_c_restoration.py (fresh outputs, protected hashes, nonzero failure). Added stage_validation.py, continuation_validation.py, memory_validation.py, cargo_validation.py, cargo_wrapper.py, publish_continuation.py, controlled fixtures, memory expectations, Cargo manifests/lockfile, and tests/test_rust_mir_stage.py. The old spike publisher now refuses to overwrite newer continuation evidence.', '',
             '## 17. Decision', '',
             '**MIR-STOP-INCOMPLETE.** Unfinished gates:', '']
    rows += ['- ' + item for item in unfinished]
    rows += ['', 'There is no controlled evidence here establishing that MIR is unsuitable. Historical Rust work remains prohibited.', '']
    (HERE / 'CONTINUATION.md').write_text('\n'.join(rows))
    evidence = {}
    for path in paths.values():
        for artifact in sorted(path.parent.rglob('*.json')):
            if 'target' not in artifact.relative_to(path.parent).parts:
                evidence[artifact.relative_to(ROOT).as_posix()] = sha(artifact)
    write('continuation_evidence_manifest.json', evidence)
    write('artifact_manifest.json', {p.relative_to(HERE).as_posix(): sha(p) for p in sorted(HERE.rglob('*'))
                                   if p.is_file() and '__pycache__' not in p.parts and p.name != 'artifact_manifest.json'})
    print('MIR-STOP-INCOMPLETE: evidence published; no historical authorization')


if __name__ == '__main__':
    main()
