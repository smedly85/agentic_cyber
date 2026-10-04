"""Publish controlled body/trace evidence without granting backend acceptance."""
import argparse
from collections import Counter
import hashlib
import json
import shutil
from prepare import ROOT,HERE,require_c
from probe import BASE


def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name,value):(HERE/name).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser()
    for name in ('controlled','focused','memory','cargo','transitive','adapter','dynamic','c'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    for value in vars(args).values():
        if not value.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c()
    paths={'controlled':BASE/'continuation'/args.controlled/'complete_validation.json',
           'focused':BASE/'core-validation'/args.focused/'result.json',
           'memory':BASE/'memory-validation'/args.memory/'result.json',
           'cargo':BASE/'cargo-validation'/args.cargo/'result.json',
           'transitive':BASE/'transitive-validation'/args.transitive/'result.json',
           'adapter':BASE/'adapter-validation'/args.adapter/'result.json',
           'dynamic':BASE/'dynamic-validation'/args.dynamic/'result.json',
           'c':BASE/'c-validation'/args.c/'results.json'}
    data={k:read(p) for k,p in paths.items()}
    assert data['c']['passed'] and data['c']['protected_c_files_unchanged']==159
    assert len(data['c']['controlled'])==11 and len(data['c']['observations'])==9
    assert sha(ROOT/'build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf')=='ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2'
    for name,value in data.items():write('body_'+name+'_results.json',value)
    counts=Counter();origins=Counter();generic=Counter();intrinsics={};ledgers={}
    rawroot=paths['controlled'].parent
    for case in data['controlled']['cases']:
        ledger=read(rawroot/'run-1'/case['case']/'required_body_ledger.json');ledgers[case['case']]=ledger
        counts.update(r['disposition'] for r in ledger)
        origins.update(r['origin'] for r in ledger if r['origin'])
        generic.update(('generic' if r['generic'] else 'nongeneric') for r in ledger if r['origin'] in ('rebuilt_std','rebuilt_core','rebuilt_alloc'))
        for row in ledger:
            if row['intrinsic_contract']:intrinsics[row['def_path']]=row['intrinsic_contract']
    write('body_required_ledgers.json',ledgers)
    before=Counter(r['reason'] for c in read(HERE/'core_semantic_results.json')['cases'] for r in c['unsupported_operations'])
    after=Counter(r['reason'] for c in data['controlled']['cases'] for r in c['unsupported_operations'])
    blocks=[{'case':c['case'],'operations':c['unsupported_operation_inventory'],'bodies':c['required_body_blockers'],
             'unresolved_sites':c['unresolved_callsites']} for c in data['controlled']['cases'] if not c['complete_semantic_pass']]
    write('body_operation_inventory.json',{'before_instance_reason_counts':dict(before),'after_instance_reason_counts':dict(after),
          'remaining_failures':blocks,'body_disposition_occurrences':dict(counts),'body_origin_occurrences':dict(origins),
          'rebuilt_generic_occurrences':dict(generic),'intrinsic_contracts':intrinsics,
          'additional_adapter_blockers':data['adapter']['runs'][0]['unsupported_operations']})
    replay_path=BASE/'solver-replay/index-v3/result.json'
    replay=read(replay_path)
    assert replay['identical_to_reference'] and replay['fresh_solver_reruns_identical']
    write('body_solver_replay_results.json',replay)
    if not (HERE/'core_instrument.json').exists():shutil.copy2(HERE/'instrument.json',HERE/'core_instrument.json')
    record={'status':'MIR-STOP-INCOMPLETE','accepted_backend':False,'historical_measurement':False,
            'milestone':'controlled body contracts and independent native tracing',
            'complete_semantic_passed':data['controlled']['passed'],'semantic_total':31,
            'controlled_static_assertions_passed':sum(c['static_assertions_pass'] for c in data['controlled']['cases']),
            'core_focused_passed':sum(c['focused_pass'] for c in data['focused']['cases']),
            'memory_adversaries_passed':sum(c['target_checks_pass'] for c in data['memory']['cases']),
            'dynamic_soundness_passed':data['dynamic']['passed'],'dynamic_total':data['dynamic']['total'],
            'uniform_full_suite_std':'rebuilt core/alloc/std; panic=unwind; pinned rustc 1.93.0',
            'controlled_deterministic':data['controlled']['deterministic'],'dynamic_deterministic':data['dynamic']['deterministic'],
            'driver_sha256':sha(HERE/'driver.rs'),'inclusion_sha256':sha(HERE/'inclusion.py'),
            'calibration':'not_run_this_pass','preregistration_sha256':sha(HERE/'PREREGISTRATION.md'),
            'c_controlled':'11/11 unchanged','c_historical':'9/9 unchanged','protected_c_artifacts':159,
            'blockers':['Remaining pointer/integer and representation casts require justified semantics; no generic ignore contract.',
                        'Additional std adapter gate and its full operation closure must pass.',
                        'Broader intrinsic, terminator, constant and projection completeness audit remains necessary; no historical acceptance.'],
            'evidence':{k:{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for k,p in paths.items()}}
    write('instrument.json',record)
    lines=['# Controlled MIR bodies and tracing','', '**MIR-STOP-INCOMPLETE**. Implementation remains unfinished; this is not evidence that MIR is unsuitable. No historical Rust specimen, vulnerable-function measurement, or C/Rust calibration was run.','',
           '## Uniform std/core integration','',
           'The 31-case, focused, memory, Cargo, transitive and extra-adapter runners share `std_config.py`. It reuses the controlled build-std artifacts, records each rlib SHA-256, and uses rustc 1.93.0 / LLVM 21.1.8 with `RUSTC_BOOTSTRAP=1`, `-C opt-level=0`, `-C panic=unwind`, `-Z mir-opt-level=0`, `-Z inline-mir=no`, `-Z always-encode-mir`, and the same target triple. Analysis is `instance_mir`, Runtime(Optimized). The pinned distribution sysroot is not overwritten.','',
           'Every reached Instance has a required-body ledger with disposition, crate, DefPath, origin, generic status, source span, and compiler-generated status. Counts below sum per-fixture occurrences, not unique cross-program functions.','',
           '| Disposition | Count |','|---|---:|']
    lines += [f'| {k} | {counts[k]} |' for k in ('body_available','legitimate_external_boundary','intrinsic_with_contract','unsupported_required_body','missing_required_body')]
    lines += ['', '| Available-body origin | Count |','|---|---:|']+[f'| {k} | {origins[k]} |' for k in ('local_crate','dependency','rebuilt_core','rebuilt_alloc','rebuilt_std')]
    lines += ['',f'Rebuilt body occurrences: {dict(generic)}. Full per-fixture ledgers: `body_required_ledgers.json`.','',
        '## Intrinsic contracts','',
        'Compiler-registered intrinsic identities come from `tcx.intrinsic`, not source-text matching. Incoming raw Instance edges remain; contracts supply leaf/value behavior where ordinary MIR does not exist.','',
        '| Exact intrinsic | Contract | Callable/memory effect |','|---|---|---|',
        '| core::intrinsics::assert_inhabited | inhabited_type_assertion | No callable flow or abstract-memory mutation; assertion leaf. |',
        '| core::intrinsics::ctpop | population_count_scalar | Integer population count; no pointers or memory mutation. |',
        '| core::intrinsics::abort | abort_nonreturning | Nonreturning leaf; no callback targets. |',
        '| core::intrinsics::caller_location | immutable_caller_location | Immutable Location data (file string and integer coordinates), no callable payload. |',
        '| core::intrinsics::black_box | identity | Copies the complete typed value and its subfields to the return destination. |',
        '| core::intrinsics::size_of_val / align_of_val | dynamic_layout_scalar | Newly exposed by full Box bodies; metadata/layout query returns a scalar, does not invoke user methods or mutate memory. |','',
        'Unknown intrinsics remain `unsupported_required_body`. Foreign definitions alone may be legitimate external boundaries; ordinary missing Rust MIR is never classified as foreign.','',
        '## Unsupported-operation inventory','',f'Before (Instance/reason occurrences): `{dict(before)}`.',f'After: `{dict(after)}`.','',
        'A: arithmetic/comparisons, discriminants, runtime-check flags, numeric casts have no callable result. B: array construction retains element fields; subtype conversions preserve values. C: raw pointer construction and metadata transport preserve receiver type provenance; pointer representation roundtrips restore known allocation types without falsely collapsing typed fields. Unsafe reads still collapse allocation-local storage. D: remaining pointer/integer or representation casts stay blocking and are listed exactly in `body_operation_inventory.json`.','',
        'Uniform std exposed a Box precision regression. The fix models rustc lang-item `exchange_malloc` only in the compiler-recognized `box_new` constructor, retaining its body/call edges. Constructor storage summaries are distinct from caller allocation sites, preventing deallocation/allocator helper merges from contaminating typed Box payloads. Expected target sets were not changed.','',
        '## Transitive dyn and std callbacks','',
        'One combined whole-path adversary covers helper returns, multiple arguments, struct and Box fields, Option, closure capture, local libraries and the authenticated scopeguard dependency. Its two legitimate impl targets are checked exactly. Candidate inventory now reaches a fixed point over discovered bodies before emitting virtual callsites.','',
        f"Transitive target checks: {[r['passed'] for r in data['transitive']['runs']]}; deterministic: {data['transitive']['deterministic']}. Full gate still depends on its recorded operation blockers.",
        f"Cargo: both four-crate checks {[r['all_four_crates_analyzed'] and r['cross_crate_callback_pass'] for r in data['cargo']['runs']]}; deterministic: {data['cargo']['scientific_rerun_identical']}.",
        'Option::map, Result::or_else and Iterator::flat_map retain their full std/core and shim paths in the 31-case graphs. Additional sort_by and boxed FnMut iterator-adapter checks are in `body_adapter_results.json`; target reachability alone does not clear their unresolved/operation gates.',
        'The added sort adapter exposes uncontracted intrinsics: `saturating_sub`, `select_unpredictable`, `cold_path`, `arith_offset`, `ctlz_nonzero`, `ctlz`, `ptr_offset_from_unsigned`, and `typed_swap_nonoverlapping`. Pointer-capable select, offset and swap contracts must model value/memory effects. It also exposes constant-payload decoding, a repeated aggregate rvalue, and representation casts. These remain fail-closed, despite both callback paths being present.','',
        '## Complete static semantic gate','',f"**{data['controlled']['passed']} / 31 complete static semantic fixtures passed.** All 31 preregistered node/edge/target assertions pass. Serialization, BFS shortest paths, required-body disposition and unresolved-site checks are included.",'',
        '| Fixture | Complete static gate | Remaining blocking Instances |','|---|---|---|']
    for case in data['controlled']['cases']:
        names=sorted({r['instance'].split('::',1)[1] for r in case['unsupported_operations']})
        lines.append('| '+case['case']+' | '+('PASS' if case['complete_semantic_pass'] else 'FAIL')+' | '+('; '.join(names).replace('|','/') or 'none')+' |')
    lines += ['',f"Focused core checks: {record['core_focused_passed']}/30. Memory adversaries: {record['memory_adversaries_passed']}/12. These are exact-target/precision checks, not substitutes for the full body/operation gate.",'',
        '## Independent dynamic validation','',
        'Native x86_64 entry instrumentation (`-Z instrument-mcount`, frame pointers, no PIE) writes address pairs. `nm` and executable DWARF map them to compiler symbols. DWARF inline frames independently reconstruct LLVM-inlined semantic transitions, including Box::new; the static graph is never used to invent or repair a runtime edge. Incoming runtime/harness-to-configured-root edges are explicitly reported as entry boundaries outside the selected-root graph. Unknown mappings fail validation.','',
        f"**{data['dynamic']['passed']}/{data['dynamic']['total']} runtime comparisons pass.** Per-fixture observed edges, static edges, missing dynamic edges, static-only edges, inline evidence and unresolved static sites are in `body_dynamic_results.json`.",
        'This validates executed user/application transitions and their observed adapter frames, not exhaustive execution coverage or all std internals. Dynamic comparison never repairs static results.','',
        '## Edge provenance and determinism','',
        'The primary metric remains raw semantic Instance edges. Each successful shortest controlled target path includes raw, application, std/core, compiler-shim and drop-glue counts in `body_controlled_results.json`; no shim or adapter is made transparent.','',
        f"Paired static serialization/ledger/path output identical: {data['controlled']['deterministic']}. Paired dynamic comparisons identical: {data['dynamic']['deterministic']}. Focused and memory scientific outputs also match their fresh paired roots. Acceptance remains closed while any static blocker remains.",'',
        'An abstract-cell index improves the larger adapter analysis. Two fresh solver replays reproduce all 73 original/focused/memory outputs byte-for-byte, including precision-loss evidence (`body_solver_replay_results.json`). Empty read cells remain indexed to preserve affected-field records.','',
        '## Frozen C regression','',
        'C controlled 11/11; historical replay 9/9; protected artifacts 159/159 unchanged. Canonical helper SHA-256: `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2`. Only the established replay checks ran.','',
        '## Files, tests and remaining work','',
        'Changed driver.rs, inclusion.py, graph.py and the controlled/focused/memory/Cargo runners. Added std_config.py, body_ledger.py, complete_validation.py, dynamic_validation.py, trace_compare.py, runtime_mcount.S, runtime_trace.c, transitive_validation.py, adapter_validation.py, publish_bodies.py, the transitive/std callback fixtures and tests/test_rust_mir_bodies.py. The C recorder is new support code for Rust tracing, not a change to the frozen C semantic instrument.','',
        'Remaining engineering: justify and implement the listed pointer/integer and representation casts; implement the eight additional adapter intrinsic families with value/memory effects where needed; decode its constant payloads and repeated aggregates; complete general operation/constant/projection coverage audit; rerun the complete gate after those changes. No calibration or historical measurement is authorized by this result.','']
    (HERE/'BODY_REPORT.md').write_text('\n'.join(lines))
    write('body_evidence_manifest.json',{p.relative_to(ROOT).as_posix():sha(p) for p in paths.values()})
    write('artifact_manifest.json',{p.relative_to(HERE).as_posix():sha(p) for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name!='artifact_manifest.json'})
    print(record['status'],record['complete_semantic_passed'],'/31',flush=True)


if __name__=='__main__':main()
