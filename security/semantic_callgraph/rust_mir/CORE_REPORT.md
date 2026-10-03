# Controlled MIR core — MIR-STOP-INCOMPLETE

This is an implementation-incomplete verdict, not evidence that MIR is unsuitable. No historical Rust specimen was built or measured. No cross-language calibration was executed. Frozen Rust inputs and C artifacts remain unchanged.

## 1. Heap model

Five focused heap tests pass: one boxed callback, two allocation sites at one callsite, stack+heap union, helper argument/return/move transfer, and isolation between separate sites. Allocation IDs hash the calling stable Instance, source span, MIR block ordinal, allocated type/type fingerprint, and DefPathHash. Runtime addresses and session AllocIds are not persisted. Abstract objects and their field cells are separate from function-instance tokens.

## 2. Box behavior

The allocation is established by `tcx.is_diagnostic_item("box_new", def)` at a MIR Call, not by LLVM allocation names. Typed Box/Unique/NonNull pointer paths are obtained recursively from rustc ADT fields. The source value is copied into the heap object; ownership moves, references, argument/return copies, and dereferences retain its address.

The Box::new value transfer has an explicit allocation-site summary. Its call edge, body, allocator calls, and drop nodes remain in the primary graph. The shared constructor return local is not used to merge all allocation sites. Pure pointer-representation conversions are distinguished from field-erasing memory operations.

## 3. Dyn dispatch

Six focused tests pass: one receiver, two receivers with an unrelated impl present, boxed receiver, static+dynamic calls, Drop-bearing receiver, and multiple method arguments. Candidate concrete types come from compiler-observed unsizing casts. The full trait arguments are checked before rustc Instance::try_resolve. The inclusion solver selects only candidates justified by receiver object/type flow. There is no source-name-based target resolution and no all-impl fallback.

Static and dynamic callsites can legitimately target the same impl Instance; the edges/callsites remain distinct. Candidate discovery over later-discovered upstream bodies and general supertrait/generic-method handling still require further work.

## 4. Closures and Fn-family

Ten focused checks pass: captured callback, closure argument, returned closure, captured object, closure field, boxed closure, dyn Fn, boxed dyn FnMut, function-pointer tuple argument, and consuming FnOnce. The compiler RustCall tuple is unpacked when the resolved callee is a closure body; shim MIR retains its own arguments. Compiler-generated shims are not contracted.

| Focused case/site | Receiver types (dynamic sites) | Expected targets | Actual targets | Check |
|---|---|---|---|---|
| closure_capture/crate::closure_capture::{closure#0} | statically typed | crate::target | crate::target | PASS |
| closure_arg/crate::closure_arg::{closure#0} | statically typed | crate::target | crate::target | PASS |
| closure_return/crate::make_closure::{closure#0} | statically typed | crate::target | crate::target | PASS |
| closure_object/crate::invoke | statically typed | crate::target | crate::target | PASS |
| closure_struct/crate::closure_struct::{closure#0} | statically typed | crate::target | crate::target | PASS |
| closure_box/crate::closure_box::{closure#0} | statically typed | crate::target | crate::target | PASS |
| closure_dyn/crate::dyn_fn_site | {closure@./tests/fixtures/rust_mir/core_cases.rs:33:75: 33:83} | crate::closure_dyn::{closure#0} | crate::closure_dyn::{closure#0} | PASS |
| closure_dyn/crate::closure_dyn::{closure#0} | statically typed | crate::target | crate::target | PASS |
| closure_fnmut/crate::dyn_fnmut_site | {closure@./tests/fixtures/rust_mir/core_cases.rs:37:49: 37:57} | crate::closure_fnmut::{closure#0} | crate::closure_fnmut::{closure#0} | PASS |
| closure_fnmut/crate::closure_fnmut::{closure#0} | statically typed | crate::target | crate::target | PASS |
| closure_tuple_args/crate::closure_tuple_args::{closure#0} | statically typed | crate::target | crate::target | PASS |
| closure_once/crate::invoke | statically typed | crate::target | crate::target | PASS |

Option::map, Result::or_else, Iterator::flat_map, dyn Fn, and Box<dyn FnMut> also pass their explicit node/target assertions in the 31-case suite, subject to the remaining required-body gate.

## 5. Unsafe precision loss

Byte-copy intrinsics, union aggregates/access, reinterpretation, and unknown pointer offsets collapse only affected object storage. Whole-value copies propagate collapse conservatively. Pointer casts carry erased-address provenance; dereferencing such an address triggers collapse. Function values from collapsed fields are unioned, so plausible targets are retained.

Records contain allocation, source spans, reasons, affected fields, and affected callsites. Scalar-only library memory events remain in `memory_events_without_callable_flow`; they are not labeled lost callable precision. Safe typed memory cases have no callable precision-loss marker. Five expanded unsafe checks pass, including the union initializer whose first run correctly failed before it was implemented.

## 6. std/core body policy

Every exported/reached instance is classified using compiler availability and foreign-item information. A missing body is not silently treated as an external leaf. Original controlled suite outputs still use the precompiled sysroot; their full required-body gate is not accepted.

An isolated build-std build of std, core, and panic_unwind succeeded with rustc 1.93.0, opt-level=0, mir-opt-level=0, inline-mir=no, and always-encode-mir. A new program exercises Option/Result/flat_map. Its compiler-recorded Cargo argv was replayed as an argv list, not shell code. The rebuilt relevant bodies have zero inlined scopes. The pinned sysroot was not replaced.

| Classification | Reached instances in rebuilt-std probe |
|---|---|
| local_body_available | 5 |
| dependency_body_available | 0 |
| std_generic_body_available | 89 |
| std_nongeneric_body_available | 33 |
| external_boundary | 2 |
| missing_required_body | 5 |

The remaining required boundaries in that probe are compiler intrinsics needing explicit contracts:

- `Fingerprint(15477247933503382533, 4788954941611434124)::core::intrinsics::assert_inhabited::<u64> - intrinsic`
- `Fingerprint(16951378105085547131, 4076379297307518836)::core::intrinsics::ctpop::<usize> - intrinsic`
- `Fingerprint(3213976792411881718, 7527236295839443165)::core::intrinsics::abort - intrinsic`
- `Fingerprint(6367143862653226491, 12359808221508533503)::core::intrinsics::caller_location - intrinsic`
- `Fingerprint(6955890307906202306, 11718777334893196647)::core::intrinsics::black_box::<u64> - intrinsic`

This experiment demonstrates that rebuilt std MIR can expose previously unavailable bodies at the controlled stage. Full-suite migration and boundary/operation validation remain unfinished.

## 7. All 31 controlled semantic cases

**31/31 explicit static node/edge/target assertions pass. 0/31 pass the complete semantic gate.** Each assertion specification is retained in tests/fixtures/rust_mir/semantic_expectations.json. This is more than target reachability, but is not acceptance: required intrinsics/bodies and unsupported operations still block every complete result.

| Fixture | Node/edge/target assertions | Missing expected | Unexpected | Complete semantic result |
|---|---|---|---|---|
| direct | PASS | none | none | BLOCKED: body/operation gate |
| recursion | PASS | none | none | BLOCKED: body/operation gate |
| function_pointer | PASS | none | none | BLOCKED: body/operation gate |
| multi_target | PASS | none | none | BLOCKED: body/operation gate |
| struct_pointer | PASS | none | none | BLOCKED: body/operation gate |
| closure | PASS | none | none | BLOCKED: body/operation gate |
| generic | PASS | none | none | BLOCKED: body/operation gate |
| static_trait | PASS | none | none | BLOCKED: body/operation gate |
| dynamic_trait | PASS | none | none | BLOCKED: body/operation gate |
| cross_crate_direct | PASS | none | none | BLOCKED: body/operation gate |
| cross_crate_indirect | PASS | none | none | BLOCKED: body/operation gate |
| duplicate_names | PASS | none | none | BLOCKED: body/operation gate |
| multiple_instances | PASS | none | none | BLOCKED: body/operation gate |
| nonfirst_reference | PASS | none | none | BLOCKED: body/operation gate |
| static_table | PASS | none | none | BLOCKED: body/operation gate |
| trait_drop | PASS | none | none | BLOCKED: body/operation gate |
| trait_one | PASS | none | none | BLOCKED: body/operation gate |
| trait_many | PASS | none | none | BLOCKED: body/operation gate |
| box_trait | PASS | none | none | BLOCKED: body/operation gate |
| dyn_fn | PASS | none | none | BLOCKED: body/operation gate |
| box_fnmut | PASS | none | none | BLOCKED: body/operation gate |
| option_map | PASS | none | none | BLOCKED: body/operation gate |
| result_or_else | PASS | none | none | BLOCKED: body/operation gate |
| iterator_flat_map | PASS | none | none | BLOCKED: body/operation gate |
| entry_wrappers | PASS | none | none | BLOCKED: body/operation gate |
| unwind | PASS | none | none | BLOCKED: body/operation gate |
| crates_io | PASS | none | none | BLOCKED: body/operation gate |
| static_and_dyn | PASS | none | none | BLOCKED: body/operation gate |
| platform | PASS | none | none | BLOCKED: body/operation gate |
| stack_bytes | PASS | none | none | BLOCKED: body/operation gate |
| same_method | PASS | none | none | BLOCKED: body/operation gate |

Expected and actual node inventories, callsite target sets, unavailable instances, and operation blockers are recorded per case in core_semantic_results.json. No empty target set is reported as resolved.

## 8. Twelve memory adversaries

**12/12 memory target/precision-marker checks pass.** The unsafe case permits documented conservative extras. All safe cases retain typed-field precision.

| Case/site | Expected | Actual | Missing | Extra | Result |
|---|---|---|---|---|---|
| first_field/invoke_first | other | other | none | none | PASS |
| second_field/invoke_second | target | target | none | none | PASS |
| three_fields/invoke_first | other | other | none | none | PASS |
| three_fields/invoke_second | target | target | none | none | PASS |
| three_fields/invoke_third | third | third | none | none | PASS |
| reversed_writes/invoke_second | target | target | none | none | PASS |
| overwrite/invoke_second | other, target | other, target | none | none | PASS |
| conditional_same_field/invoke_second | other, target | other, target | none | none | PASS |
| distinct_fields/invoke_first | other | other | none | none | PASS |
| distinct_fields/invoke_second | target | target | none | none | PASS |
| stack_copy/invoke_second | target | target | none | none | PASS |
| heap_storage/invoke_second | target | target | none | none | PASS |
| mixed_objects/invoke_second | other, target | other, target | none | none | PASS |
| stack_heap/invoke_second | other, target | other, target | none | none | PASS |
| unsafe_bytes/invoke_second | target | other, target, third | none | other, third | PASS |

## 9. Mixed adversaries

| Case | Result |
|---|---|
| mixed_storage | PASS |
| mixed_callable | PASS |
| mixed_dyn_static | PASS |
| mixed_safe_unsafe | PASS |

These cover static+stack+heap at one site; closure+plain fn pointer through dyn Fn; two dyn receiver types plus a static method call; and safe plus unsafe-collapsed objects. The safe object’s unrelated first-field callback stays excluded.

## 10. Dynamic trace validation

NOT RUN. The requested development order places independent tracing after complete controlled static validation. That gate remains open. No dynamic edges were used to fill static edges; missing dynamic edges are unknown, not zero.

## 11. Determinism

Two fresh output directories per case produce byte-identical normalized scientific graphs for all 31 original cases, all 12 memory adversaries, and all 30 focused core cases. Semantic adjudication also matches byte for byte. Full acceptance-suite determinism remains incomplete until uniform rebuilt std and dynamic validation are integrated.

## 12. Frozen C regression

Fresh replay: C controlled 11/11 unchanged; C historical observations 9/9 unchanged; protected artifacts 159/159 unchanged. The canonical helper remains `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2`. No C backend semantics, expected results, or finalized historical artifacts changed.

## 13. Implementation and tests

Changed driver.rs, inclusion.py, graph.py, precision_loss.schema.json, and memory_validation.py. Added core_validation.py, adjudicate_core.py, build_std_probe.py, inspect_built_std.py, publish_core.py, core_cases.rs, core_expectations.json, semantic_expectations.json, and tests/test_rust_mir_core.py. Existing continuation/stage evidence is retained. The core unit regressions cover allocation isolation, receiver filtering, local unsafe collapse, RustCall tuple transfer, static fields, and unresolved receiver handling.

## 14. Decision and remaining engineering

**MIR-STOP-INCOMPLETE.** Not ready for cross-language calibration or historical measurement. Remaining tasks:

- Integrate the successfully rebuilt std/core libraries into every controlled standalone and Cargo run; the rebuilt-std experiment currently covers one separate program.
- Implement explicit contracts for compiler intrinsics and adjudicate remaining unsupported rvalues, aggregates, and casts; retain fail-closed behavior for every genuinely missing required body.
- Complete body/operation closure for all 31 cases. Their explicit node/edge/target assertions pass, but all 31 still fail the strict complete-semantic gate.
- Extend dyn candidate discovery to a fixed point over newly reached dependency bodies and cover supertraits/generic trait methods beyond the present controlled receiver cases.
- Add independent runtime edge tracing only after static gates close, and compare every observed edge against the unchanged static graph.
- Repeat the complete accepted semantic/trace suite twice under the uniform rebuilt-std stage; existing graph reruns are deterministic but do not satisfy unfinished acceptance gates.

The calibration preregistration is untouched. No historical CVE measurement or historical uutils build occurred.
