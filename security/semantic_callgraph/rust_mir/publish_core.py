"""Publish the core engineering milestone without bypassing remaining gates."""
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
    if (HERE/'body_controlled_results.json').exists():
        raise SystemExit('Refusing to overwrite the newer controlled body/trace milestone')
    parser=argparse.ArgumentParser()
    parser.add_argument('--focused',required=True)
    parser.add_argument('--memory',required=True)
    parser.add_argument('--controlled',required=True)
    parser.add_argument('--std',required=True)
    parser.add_argument('--c',required=True)
    args=parser.parse_args()
    for value in vars(args).values():
        if not value.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c()
    paths={'focused':BASE/'core-validation'/args.focused/'result.json',
           'memory':BASE/'memory-validation'/args.memory/'result.json',
           'controlled':BASE/'continuation'/args.controlled/'semantic_adjudication.json',
           'std':BASE/'built-std-inspection'/args.std/'result.json',
           'c':BASE/'c-validation'/args.c/'results.json'}
    focused,memory,controlled,std,c=(read(paths[k]) for k in paths)
    assert len(focused['cases'])==30 and len(memory['cases'])==12 and controlled['total']==31
    assert c['passed'] and len(c['controlled'])==11 and len(c['observations'])==9 and c['protected_c_files_unchanged']==159
    write('core_results.json',focused)
    write('core_memory_results.json',memory)
    write('core_semantic_results.json',controlled)
    write('core_std_results.json',std)
    write('core_c_regression.json',c)
    write('core_dynamic_trace_results.json',{'status':'not_run','accepted':False,'missing_dynamic_edges':None,
        'reason':'Required-body/unsupported-operation gates remain open. Per requested order, runtime tracing follows complete controlled static validation.'})
    blocks=[
        'Integrate the successfully rebuilt std/core libraries into every controlled standalone and Cargo run; the rebuilt-std experiment currently covers one separate program.',
        'Implement explicit contracts for compiler intrinsics and adjudicate remaining unsupported rvalues, aggregates, and casts; retain fail-closed behavior for every genuinely missing required body.',
        'Complete body/operation closure for all 31 cases. Their explicit node/edge/target assertions pass, but all 31 still fail the strict complete-semantic gate.',
        'Extend dyn candidate discovery to a fixed point over newly reached dependency bodies and cover supertraits/generic trait methods beyond the present controlled receiver cases.',
        'Add independent runtime edge tracing only after static gates close, and compare every observed edge against the unchanged static graph.',
        'Repeat the complete accepted semantic/trace suite twice under the uniform rebuilt-std stage; existing graph reruns are deterministic but do not satisfy unfinished acceptance gates.',
    ]
    if not (HERE/'continuation_instrument.json').exists():shutil.copy2(HERE/'instrument.json',HERE/'continuation_instrument.json')
    record={'status':'MIR-STOP-INCOMPLETE','accepted_backend':False,'historical_measurement':False,
        'milestone':'controlled core implementation; required-body and trace gates incomplete',
        'driver_sha256':sha(HERE/'driver.rs'),'inclusion_sha256':sha(HERE/'inclusion.py'),
        'core_focused_passed':sum(r['focused_pass'] for r in focused['cases']),'core_focused_total':30,
        'memory_adversaries_passed':sum(r['target_checks_pass'] for r in memory['cases']),'memory_total':12,
        'controlled_static_assertions_passed':controlled['static_assertions_passed'],
        'complete_semantic_passed':controlled['complete_semantic_passed'],'semantic_total':31,
        'dynamic_soundness':'not_run','calibration':'not_run_this_pass',
        'preregistration_sha256':sha(HERE/'PREREGISTRATION.md'),
        'build_std':'compiled and inspected for controlled probe','uniform_full_suite_std':'not_yet_integrated',
        'focused_deterministic':all(r['deterministic'] for r in focused['cases']),
        'memory_deterministic':all(r['deterministic'] for r in memory['cases']),
        'controlled_deterministic':read(paths['controlled'].parent/'result.json')['all_identical'] and controlled['deterministic'],
        'full_suite_determinism':'incomplete acceptance gate',
        'c_controlled':'11/11 unchanged','c_historical':'9/9 unchanged','protected_c_artifacts':159,
        'c_helper_sha256':sha(ROOT/'build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf'),
        'blockers':blocks,'evidence':{key:{'path':path.relative_to(ROOT).as_posix(),'sha256':sha(path)} for key,path in paths.items()}}
    write('instrument.json',record)
    text=[
        '# Controlled MIR core — MIR-STOP-INCOMPLETE','',
        'This is an implementation-incomplete verdict, not evidence that MIR is unsuitable. No historical Rust specimen was built or measured. No cross-language calibration was executed. Frozen Rust inputs and C artifacts remain unchanged.','',
        '## 1. Heap model','',
        'Five focused heap tests pass: one boxed callback, two allocation sites at one callsite, stack+heap union, helper argument/return/move transfer, and isolation between separate sites. Allocation IDs hash the calling stable Instance, source span, MIR block ordinal, allocated type/type fingerprint, and DefPathHash. Runtime addresses and session AllocIds are not persisted. Abstract objects and their field cells are separate from function-instance tokens.','',
        '## 2. Box behavior','',
        'The allocation is established by `tcx.is_diagnostic_item("box_new", def)` at a MIR Call, not by LLVM allocation names. Typed Box/Unique/NonNull pointer paths are obtained recursively from rustc ADT fields. The source value is copied into the heap object; ownership moves, references, argument/return copies, and dereferences retain its address.','',
        'The Box::new value transfer has an explicit allocation-site summary. Its call edge, body, allocator calls, and drop nodes remain in the primary graph. The shared constructor return local is not used to merge all allocation sites. Pure pointer-representation conversions are distinguished from field-erasing memory operations.','',
        '## 3. Dyn dispatch','',
        'Six focused tests pass: one receiver, two receivers with an unrelated impl present, boxed receiver, static+dynamic calls, Drop-bearing receiver, and multiple method arguments. Candidate concrete types come from compiler-observed unsizing casts. The full trait arguments are checked before rustc Instance::try_resolve. The inclusion solver selects only candidates justified by receiver object/type flow. There is no source-name-based target resolution and no all-impl fallback.','',
        'Static and dynamic callsites can legitimately target the same impl Instance; the edges/callsites remain distinct. Candidate discovery over later-discovered upstream bodies and general supertrait/generic-method handling still require further work.','',
        '## 4. Closures and Fn-family','',
        'Ten focused checks pass: captured callback, closure argument, returned closure, captured object, closure field, boxed closure, dyn Fn, boxed dyn FnMut, function-pointer tuple argument, and consuming FnOnce. The compiler RustCall tuple is unpacked when the resolved callee is a closure body; shim MIR retains its own arguments. Compiler-generated shims are not contracted.','',
        '| Focused case/site | Receiver types (dynamic sites) | Expected targets | Actual targets | Check |',
        '|---|---|---|---|---|']
    for row in focused['cases']:
        if row['case'].startswith('closure_'):
            for site in row['sites']:
                text.append('| '+' | '.join([row['case']+'/'+site['owner'],', '.join(site.get('receiver_types',[])) or 'statically typed',', '.join(site['expected_targets']),', '.join(site['actual_targets']) or 'none','PASS' if site['passed'] else 'FAIL'])+' |')
    text += ['', 'Option::map, Result::or_else, Iterator::flat_map, dyn Fn, and Box<dyn FnMut> also pass their explicit node/target assertions in the 31-case suite, subject to the remaining required-body gate.','',
        '## 5. Unsafe precision loss','',
        'Byte-copy intrinsics, union aggregates/access, reinterpretation, and unknown pointer offsets collapse only affected object storage. Whole-value copies propagate collapse conservatively. Pointer casts carry erased-address provenance; dereferencing such an address triggers collapse. Function values from collapsed fields are unioned, so plausible targets are retained.','',
        'Records contain allocation, source spans, reasons, affected fields, and affected callsites. Scalar-only library memory events remain in `memory_events_without_callable_flow`; they are not labeled lost callable precision. Safe typed memory cases have no callable precision-loss marker. Five expanded unsafe checks pass, including the union initializer whose first run correctly failed before it was implemented.','',
        '## 6. std/core body policy','',
        'Every exported/reached instance is classified using compiler availability and foreign-item information. A missing body is not silently treated as an external leaf. Original controlled suite outputs still use the precompiled sysroot; their full required-body gate is not accepted.','',
        'An isolated build-std build of std, core, and panic_unwind succeeded with rustc 1.93.0, opt-level=0, mir-opt-level=0, inline-mir=no, and always-encode-mir. A new program exercises Option/Result/flat_map. Its compiler-recorded Cargo argv was replayed as an argv list, not shell code. The rebuilt relevant bodies have zero inlined scopes. The pinned sysroot was not replaced.','',
        '| Classification | Reached instances in rebuilt-std probe |','|---|---|']
    for category in ('local_body_available','dependency_body_available','std_generic_body_available','std_nongeneric_body_available','external_boundary','missing_required_body'):
        text.append(f"| {category} | {std['body_counts'].get(category,0)} |")
    text += ['', 'The remaining required boundaries in that probe are compiler intrinsics needing explicit contracts:', '']
    text += ['- `'+name+'`' for name in std['missing_required_bodies']]
    text += ['', 'This experiment demonstrates that rebuilt std MIR can expose previously unavailable bodies at the controlled stage. Full-suite migration and boundary/operation validation remain unfinished.','',
        '## 7. All 31 controlled semantic cases','',
        f"**{controlled['static_assertions_passed']}/31 explicit static node/edge/target assertions pass. {controlled['complete_semantic_passed']}/31 pass the complete semantic gate.** Each assertion specification is retained in tests/fixtures/rust_mir/semantic_expectations.json. This is more than target reachability, but is not acceptance: required intrinsics/bodies and unsupported operations still block every complete result.",'',
        '| Fixture | Node/edge/target assertions | Missing expected | Unexpected | Complete semantic result |','|---|---|---|---|---|']
    for row in controlled['cases']:
        text.append('| '+' | '.join([row['case'],'PASS' if row['semantic_assertions_pass'] else 'FAIL',', '.join(row['missing']) or 'none',', '.join(row['unexpected']) or 'none','PASS' if row['complete_semantic_pass'] else 'BLOCKED: body/operation gate'])+' |')
    text += ['', 'Expected and actual node inventories, callsite target sets, unavailable instances, and operation blockers are recorded per case in core_semantic_results.json. No empty target set is reported as resolved.','',
        '## 8. Twelve memory adversaries','',
        f"**{record['memory_adversaries_passed']}/12 memory target/precision-marker checks pass.** The unsafe case permits documented conservative extras. All safe cases retain typed-field precision.",'',
        '| Case/site | Expected | Actual | Missing | Extra | Result |','|---|---|---|---|---|---|']
    for row in memory['cases']:
        for site in row['sites']:
            text.append('| '+' | '.join([row['case']+'/'+site['owner'],', '.join(site['expected_targets']),', '.join(site['actual_targets']) or 'none',', '.join(site['missing_targets']) or 'none',', '.join(site['unexpected_targets']) or 'none','PASS' if row['target_checks_pass'] else 'FAIL'])+' |')
    text += ['', '## 9. Mixed adversaries','', '| Case | Result |','|---|---|']
    for row in focused['cases']:
        if row['case'].startswith('mixed_'):text.append(f"| {row['case']} | {'PASS' if row['focused_pass'] else 'FAIL'} |")
    text += ['', 'These cover static+stack+heap at one site; closure+plain fn pointer through dyn Fn; two dyn receiver types plus a static method call; and safe plus unsafe-collapsed objects. The safe object’s unrelated first-field callback stays excluded.','',
        '## 10. Dynamic trace validation','',
        'NOT RUN. The requested development order places independent tracing after complete controlled static validation. That gate remains open. No dynamic edges were used to fill static edges; missing dynamic edges are unknown, not zero.','',
        '## 11. Determinism','',
        'Two fresh output directories per case produce byte-identical normalized scientific graphs for all 31 original cases, all 12 memory adversaries, and all 30 focused core cases. Semantic adjudication also matches byte for byte. Full acceptance-suite determinism remains incomplete until uniform rebuilt std and dynamic validation are integrated.','',
        '## 12. Frozen C regression','',
        'Fresh replay: C controlled 11/11 unchanged; C historical observations 9/9 unchanged; protected artifacts 159/159 unchanged. The canonical helper remains `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2`. No C backend semantics, expected results, or finalized historical artifacts changed.','',
        '## 13. Implementation and tests','',
        'Changed driver.rs, inclusion.py, graph.py, precision_loss.schema.json, and memory_validation.py. Added core_validation.py, adjudicate_core.py, build_std_probe.py, inspect_built_std.py, publish_core.py, core_cases.rs, core_expectations.json, semantic_expectations.json, and tests/test_rust_mir_core.py. Existing continuation/stage evidence is retained. The core unit regressions cover allocation isolation, receiver filtering, local unsafe collapse, RustCall tuple transfer, static fields, and unresolved receiver handling.','',
        '## 14. Decision and remaining engineering','',
        '**MIR-STOP-INCOMPLETE.** Not ready for cross-language calibration or historical measurement. Remaining tasks:','']
    text += ['- '+block for block in blocks]
    text += ['', 'The calibration preregistration is untouched. No historical CVE measurement or historical uutils build occurred.','']
    (HERE/'CORE_REPORT.md').write_text('\n'.join(text))
    evidence={}
    for p in paths.values():
        for f in sorted(p.parent.rglob('*.json')):
            if not {'target','cargo-home'} & set(f.relative_to(p.parent).parts):evidence[f.relative_to(ROOT).as_posix()]=sha(f)
    write('core_evidence_manifest.json',evidence)
    write('artifact_manifest.json',{p.relative_to(HERE).as_posix():sha(p) for p in sorted(HERE.rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts and p.name!='artifact_manifest.json'})
    print('MIR-STOP-INCOMPLETE: core milestone published; no calibration/historical authorization')


if __name__=='__main__':main()
