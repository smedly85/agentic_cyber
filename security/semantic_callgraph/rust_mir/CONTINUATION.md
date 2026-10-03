# MIR-STOP-INCOMPLETE — controlled continuation

MIR remains a promising candidate. No backend graph is accepted. No historical Rust specimen was built or measured. The frozen Rust population/mappings and C instrument/results were not modified.

## 1. MIR stage

`TyCtxt::instance_mir` returns `Runtime(Optimized)`. Twelve checks pass for local and dependency MIR: direct calls, generic calls, closure calls, drops, non-generic dependency bodies/calls, and absence of inlined scopes. Two fresh runs of each stage variant are identical.

Candidate flags: `RUSTC_BOOTSTRAP=1 --edition=2021 --target=x86_64-unknown-linux-gnu -C opt-level=0 -C panic=unwind -C codegen-units=1 -Z mir-opt-level=0 -Z inline-mir=no -Z always-encode-mir`; explicit isolated sysroot and repository path remapping. Original controlled no_std library fixtures use panic=abort consistently with their dependency.

The optimized-dependency negative control removes dependency_direct -> dependency_leaf and dependency_non_generic -> dependency_direct despite local opt-level zero. The optimized-local control removes direct/generic/closure transitions. Phase labels alone do not establish equivalence across crates. Precompiled std is not approved by this contract. No alternate API was needed for the successful local/dependency experiment; a uniform whole-program stage is still unfinished.

## 2–5. Heap, dyn dispatch, function pointers, and closures

Allocation-site heap modeling and receiver-based dyn dispatch are unfinished. Heap storage and mixed stack/heap target checks fail. Values remain separate function/address tokens in typed local/subobject cells, but there is no accepted allocation object model.

The inclusion solver now accepts configured roots, avoids contamination from unreachable library entry points, and propagates typed struct/tuple/closure fields and enum variant fields. Direct calls into encoded dependency bodies are traversed. Missing bodies and empty inventories fail closed. Unsupported operations still prevent acceptance.

Direct closure, Option::map, Result::or_else, and Iterator::flat_map fixtures reach the designated target in partial graphs. This does not validate all closure captures or RustCall ABI adaptation. dyn Fn and Box<dyn FnMut> still fail. Compiler-generated instances remain in the graph; no shim contraction was added.

## 6. std/core MIR policy

Per-instance body availability is recorded in stage_validation.json and cargo_results.json. Generic std/core bodies are available selectively. The controlled Cargo graph exposes std bodies with inlined scopes and missing MIR for std::rt::lang_start_internal; compiler intrinsics are explicit unsupported boundaries. These are not treated as libc or successful leaves. A reproducible sysroot rebuild (build-std or equivalent) and intrinsic semantics remain necessary to test a common stage. build-std was not executed.

## 7. Cargo closure

Two fresh Cargo builds compiled one binary, two local libraries, and crates.io scopeguard 1.2.0. The registry archive was checked against its frozen checksum and vendored offline. Every crate ran under the driver with the same MIR flags. Package, crate, target, rustc invocation, features, dependency edges, edition, profile, panic strategy, and encoded MIR requests are retained. The callback through both local libraries resolves to exactly its assigned target.

Scope is `controlled_cargo_program_closure`, not linker_exact. Downstream compiler queries load encoded upstream bodies; separate crate-local display strings are not merged as global identities. Sysroot stage and full value semantics still block acceptance.

## 8. Unsafe memory

The byte-copy adversary fails: no conservative allocation-local merge or precision-loss marker is implemented. Raw pointer fields, unions, transmute, variable offsets/indexes, and complete byte-copy behavior remain unfinished. Unsupported-operation records are rejection evidence, not implemented conservative precision loss.

## 9. All 31 controlled cases

The old first 13 API-success records had zero instances because they requested metadata-only library compilation. These archived records remain intact; the new runner uses codegen-enabled collection and requires exactly one configured root. All 31 now have nonempty extraction inventories. The table reports only the executed reachability check; case-specific path, target-set, and trace validation remains incomplete. Unknown unexpected targets are not asserted empty.

| Case | Expected (partial check) | Actual | Missing designated target | Unexpected | Full semantic verdict |
|---|---|---|---|---|---|
| direct | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| recursion | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| function_pointer | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| multi_target | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| struct_pointer | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| closure | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| generic | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| static_trait | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| dynamic_trait | entry reaches designated target | not reached | yes | not fully adjudicated | INCOMPLETE |
| cross_crate_direct | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| cross_crate_indirect | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| duplicate_names | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| multiple_instances | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| nonfirst_reference | entry reaches designated target | not reached | yes | not fully adjudicated | INCOMPLETE |
| static_table | entry reaches designated target | not reached | yes | not fully adjudicated | INCOMPLETE |
| trait_drop | entry reaches designated target | not reached | yes | not fully adjudicated | INCOMPLETE |
| trait_one | entry reaches designated target | not reached | yes | not fully adjudicated | INCOMPLETE |
| trait_many | entry reaches designated target | not reached | yes | not fully adjudicated | INCOMPLETE |
| box_trait | entry reaches designated target | not reached | yes | not fully adjudicated | INCOMPLETE |
| dyn_fn | entry reaches designated target | not reached | yes | not fully adjudicated | INCOMPLETE |
| box_fnmut | entry reaches designated target | not reached | yes | not fully adjudicated | INCOMPLETE |
| option_map | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| result_or_else | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| iterator_flat_map | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| entry_wrappers | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| unwind | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| crates_io | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| static_and_dyn | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| platform | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| stack_bytes | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |
| same_method | entry reaches designated target | reached | none for this check | not fully adjudicated | INCOMPLETE |

No case is promoted to a full semantic pass from this partial check.

## 10. Twelve memory adversaries

Expected sets were fixed in tests/fixtures/rust_mir/memory_expectations.json before executing this matrix. Flow-insensitive overwrite deliberately retains both assignments.

| Case / site | Expected targets | Actual targets | Missing | Extra | Target/marker check |
|---|---|---|---|---|---|
| first_field / invoke_first | other | other | none | none | PASS |
| second_field / invoke_second | target | target | none | none | PASS |
| three_fields / invoke_first | other | other | none | none | PASS |
| three_fields / invoke_second | target | target | none | none | PASS |
| three_fields / invoke_third | third | third | none | none | PASS |
| reversed_writes / invoke_second | target | target | none | none | PASS |
| overwrite / invoke_second | other, target | other, target | none | none | PASS |
| conditional_same_field / invoke_second | other, target | other, target | none | none | PASS |
| distinct_fields / invoke_first | other | other | none | none | PASS |
| distinct_fields / invoke_second | target | target | none | none | PASS |
| stack_copy / invoke_second | target | target | none | none | PASS |
| heap_storage / invoke_second | target | none | target | none | FAIL |
| mixed_objects / invoke_second | other, target | other, target | none | none | PASS |
| stack_heap / invoke_second | other, target | target | other | none | FAIL |
| unsafe_bytes / invoke_second | target | none | target | none | FAIL |

Nine focused target checks pass. Heap storage, stack+heap, and unsafe byte copying fail. A passing target check is not full backend acceptance.

## 11. Dynamic traces

Not run. No claim that dynamic edges are a subset of static edges. Dynamic traces supplied no static edges.

## 12. Fifteen preregistered C/Rust pairs

Preregistration and expected semantics remain unchanged. These pairs were not executed; no calibration pass is inferred from separate C or Rust fixture tests.

| Pair | Result |
|---|---|
| direct_chain | NOT RUN |
| recursion | NOT RUN |
| single_pointer | NOT RUN |
| multi_pointer | NOT RUN |
| first_field | NOT RUN |
| non_first_field | NOT RUN |
| stack_copy | NOT RUN |
| heap_struct | NOT RUN |
| generic_specialization | NOT RUN |
| static_dispatch | NOT RUN |
| dyn_vtable | NOT RUN |
| closure_context | NOT RUN |
| library_callback | NOT RUN |
| mixed_stack_static | NOT RUN |
| mixed_stack_heap | NOT RUN |

## 13. Target-set precision

The memory table records actual/expected/missing/extra targets at every tested site. Actual set-size distribution across these Rust memory sites: 0 targets: 2 sites, 1 targets: 10 sites, 2 targets: 3 sites. Empty sets remain failures, not precise resolved calls.

C/Rust overlap and precision distributions remain unavailable. Calibration raw_edges/std_core_edges/compiler_shim_edges/user_application_edges are not computed; raw instance edges and shims were not contracted.

## 14. Deterministic reruns

Byte-identical scientific artifacts: 31/31 partial controlled graphs, 12/12 memory graphs, the Cargo application graph, and each stage experiment. All use fresh output directories; graph JSON is deterministically serialized. No session DefId, address, or temporary output path is used as an instance identity. This is reproducibility evidence for an incomplete implementation, not the required accepted-suite determinism gate.

## 15. Frozen C regression

C controlled 11/11 unchanged; C historical observations 9/9 unchanged; protected C artifacts 159/159 unchanged. The canonical helper remains `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2`. Validation outputs are in a fresh MIR-owned directory. No C expectations, backend semantics, or historical results were rewritten.

## 16. Files and tests

Changed driver.rs (transitive body queries, explicit unavailable boundaries, typed aggregates, stage metadata, Cargo continuation), inclusion.py (typed aggregates, root-scoped fixed point, fail-closed inventory/body handling), graph.py (unavailable-body boundaries), and verify_c_restoration.py (fresh outputs, protected hashes, nonzero failure). Added stage_validation.py, continuation_validation.py, memory_validation.py, cargo_validation.py, cargo_wrapper.py, publish_continuation.py, controlled fixtures, memory expectations, Cargo manifests/lockfile, and tests/test_rust_mir_stage.py. The old spike publisher now refuses to overwrite newer continuation evidence.

## 17. Decision

**MIR-STOP-INCOMPLETE.** Unfinished gates:

- allocation-site heap objects and Box value flow
- receiver-refined dyn Trait and dyn Fn/FnMut dispatch
- constant/static/promoted allocation contents
- complete closure environment and RustCall argument propagation
- allocation-local conservative unsafe/byte/union/index collapse and precision-loss markers
- uniform authenticated std/core stage and explicit required-body/intrinsic policy
- full semantic path and target-set adjudication of all 31 cases
- independent dynamic edge tracing and soundness validation
- execution of the 15 preregistered C/Rust calibration pairs and raw edge categorization
- cross-language target-set precision distribution and accepted full-suite reruns

There is no controlled evidence here establishing that MIR is unsuitable. Historical Rust work remains prohibited.
