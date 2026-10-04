# Controlled MIR bodies and tracing

**MIR-STOP-INCOMPLETE**. Implementation remains unfinished; this is not evidence that MIR is unsuitable. No historical Rust specimen, vulnerable-function measurement, or C/Rust calibration was run.

## Uniform std/core integration

The 31-case, focused, memory, Cargo, transitive and extra-adapter runners share `std_config.py`. It reuses the controlled build-std artifacts, records each rlib SHA-256, and uses rustc 1.93.0 / LLVM 21.1.8 with `RUSTC_BOOTSTRAP=1`, `-C opt-level=0`, `-C panic=unwind`, `-Z mir-opt-level=0`, `-Z inline-mir=no`, `-Z always-encode-mir`, and the same target triple. Analysis is `instance_mir`, Runtime(Optimized). The pinned distribution sysroot is not overwritten.

Every reached Instance has a required-body ledger with disposition, crate, DefPath, origin, generic status, source span, and compiler-generated status. Counts below sum per-fixture occurrences, not unique cross-program functions.

| Disposition | Count |
|---|---:|
| body_available | 511 |
| legitimate_external_boundary | 17 |
| intrinsic_with_contract | 44 |
| unsupported_required_body | 0 |
| missing_required_body | 0 |

| Available-body origin | Count |
|---|---:|
| local_crate | 124 |
| dependency | 8 |
| rebuilt_core | 356 |
| rebuilt_alloc | 23 |
| rebuilt_std | 0 |

Rebuilt body occurrences: {'nongeneric': 129, 'generic': 250}. Full per-fixture ledgers: `body_required_ledgers.json`.

## Intrinsic contracts

Compiler-registered intrinsic identities come from `tcx.intrinsic`, not source-text matching. Incoming raw Instance edges remain; contracts supply leaf/value behavior where ordinary MIR does not exist.

| Exact intrinsic | Contract | Callable/memory effect |
|---|---|---|
| core::intrinsics::assert_inhabited | inhabited_type_assertion | No callable flow or abstract-memory mutation; assertion leaf. |
| core::intrinsics::ctpop | population_count_scalar | Integer population count; no pointers or memory mutation. |
| core::intrinsics::abort | abort_nonreturning | Nonreturning leaf; no callback targets. |
| core::intrinsics::caller_location | immutable_caller_location | Immutable Location data (file string and integer coordinates), no callable payload. |
| core::intrinsics::black_box | identity | Copies the complete typed value and its subfields to the return destination. |
| core::intrinsics::size_of_val / align_of_val | dynamic_layout_scalar | Newly exposed by full Box bodies; metadata/layout query returns a scalar, does not invoke user methods or mutate memory. |

Unknown intrinsics remain `unsupported_required_body`. Foreign definitions alone may be legitimate external boundaries; ordinary missing Rust MIR is never classified as foreign.

## Unsupported-operation inventory

Before (Instance/reason occurrences): `{'unsupported_rvalue': 68, 'required_body_unavailable': 38, 'external_or_unexported_body': 40, 'unsupported_aggregate': 5, 'unsupported_cast': 12}`.
After: `{'unsupported_cast': 8}`.

A: arithmetic/comparisons, discriminants, runtime-check flags, numeric casts have no callable result. B: array construction retains element fields; subtype conversions preserve values. C: raw pointer construction and metadata transport preserve receiver type provenance; pointer representation roundtrips restore known allocation types without falsely collapsing typed fields. Unsafe reads still collapse allocation-local storage. D: remaining pointer/integer or representation casts stay blocking and are listed exactly in `body_operation_inventory.json`.

Uniform std exposed a Box precision regression. The fix models rustc lang-item `exchange_malloc` only in the compiler-recognized `box_new` constructor, retaining its body/call edges. Constructor storage summaries are distinct from caller allocation sites, preventing deallocation/allocator helper merges from contaminating typed Box payloads. Expected target sets were not changed.

## Transitive dyn and std callbacks

One combined whole-path adversary covers helper returns, multiple arguments, struct and Box fields, Option, closure capture, local libraries and the authenticated scopeguard dependency. Its two legitimate impl targets are checked exactly. Candidate inventory now reaches a fixed point over discovered bodies before emitting virtual callsites.

Transitive target checks: [True, True]; deterministic: True. Full gate still depends on its recorded operation blockers.
Cargo: both four-crate checks [True, True]; deterministic: True.
Option::map, Result::or_else and Iterator::flat_map retain their full std/core and shim paths in the 31-case graphs. Additional sort_by and boxed FnMut iterator-adapter checks are in `body_adapter_results.json`; target reachability alone does not clear their unresolved/operation gates.
The added sort adapter exposes uncontracted intrinsics: `saturating_sub`, `select_unpredictable`, `cold_path`, `arith_offset`, `ctlz_nonzero`, `ctlz`, `ptr_offset_from_unsigned`, and `typed_swap_nonoverlapping`. Pointer-capable select, offset and swap contracts must model value/memory effects. It also exposes constant-payload decoding, a repeated aggregate rvalue, and representation casts. These remain fail-closed, despite both callback paths being present.

## Complete static semantic gate

**27 / 31 complete static semantic fixtures passed.** All 31 preregistered node/edge/target assertions pass. Serialization, BFS shortest paths, required-body disposition and unresolved-site checks are included.

| Fixture | Complete static gate | Remaining blocking Instances |
|---|---|---|
| direct | PASS | none |
| recursion | PASS | none |
| function_pointer | PASS | none |
| multi_target | PASS | none |
| struct_pointer | PASS | none |
| closure | PASS | none |
| generic | PASS | none |
| static_trait | PASS | none |
| dynamic_trait | PASS | none |
| cross_crate_direct | PASS | none |
| cross_crate_indirect | PASS | none |
| duplicate_names | PASS | none |
| multiple_instances | PASS | none |
| nonfirst_reference | PASS | none |
| static_table | PASS | none |
| trait_drop | PASS | none |
| trait_one | PASS | none |
| trait_many | PASS | none |
| box_trait | FAIL | core::num::nonzero::NonZero::<usize>::get; core::ptr::const_ptr::<impl *const u8>::addr |
| dyn_fn | PASS | none |
| box_fnmut | FAIL | core::num::nonzero::NonZero::<usize>::get; core::ptr::const_ptr::<impl *const u8>::addr |
| option_map | PASS | none |
| result_or_else | PASS | none |
| iterator_flat_map | FAIL | core::ptr::const_ptr::<impl *const ()>::addr; core::ptr::const_ptr::<impl *const u8>::addr |
| entry_wrappers | PASS | none |
| unwind | PASS | none |
| crates_io | FAIL | core::ptr::const_ptr::<impl *const ()>::addr; core::ptr::const_ptr::<impl *const u8>::addr |
| static_and_dyn | PASS | none |
| platform | PASS | none |
| stack_bytes | PASS | none |
| same_method | PASS | none |

Focused core checks: 30/30. Memory adversaries: 12/12. These are exact-target/precision checks, not substitutes for the full body/operation gate.

## Independent dynamic validation

Native x86_64 entry instrumentation (`-Z instrument-mcount`, frame pointers, no PIE) writes address pairs. `nm` and executable DWARF map them to compiler symbols. DWARF inline frames independently reconstruct LLVM-inlined semantic transitions, including Box::new; the static graph is never used to invent or repair a runtime edge. Incoming runtime/harness-to-configured-root edges are explicitly reported as entry boundaries outside the selected-root graph. Unknown mappings fail validation.

**31/31 runtime comparisons pass.** Per-fixture observed edges, static edges, missing dynamic edges, static-only edges, inline evidence and unresolved static sites are in `body_dynamic_results.json`.
This validates executed user/application transitions and their observed adapter frames, not exhaustive execution coverage or all std internals. Dynamic comparison never repairs static results.

## Edge provenance and determinism

The primary metric remains raw semantic Instance edges. Each successful shortest controlled target path includes raw, application, std/core, compiler-shim and drop-glue counts in `body_controlled_results.json`; no shim or adapter is made transparent.

Paired static serialization/ledger/path output identical: True. Paired dynamic comparisons identical: True. Focused and memory scientific outputs also match their fresh paired roots. Acceptance remains closed while any static blocker remains.

An abstract-cell index improves the larger adapter analysis. Two fresh solver replays reproduce all 73 original/focused/memory outputs byte-for-byte, including precision-loss evidence (`body_solver_replay_results.json`). Empty read cells remain indexed to preserve affected-field records.

## Frozen C regression

C controlled 11/11; historical replay 9/9; protected artifacts 159/159 unchanged. Canonical helper SHA-256: `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2`. Only the established replay checks ran.

## Files, tests and remaining work

Changed driver.rs, inclusion.py, graph.py and the controlled/focused/memory/Cargo runners. Added std_config.py, body_ledger.py, complete_validation.py, dynamic_validation.py, trace_compare.py, runtime_mcount.S, runtime_trace.c, transitive_validation.py, adapter_validation.py, publish_bodies.py, the transitive/std callback fixtures and tests/test_rust_mir_bodies.py. The C recorder is new support code for Rust tracing, not a change to the frozen C semantic instrument.

Remaining engineering: justify and implement the listed pointer/integer and representation casts; implement the eight additional adapter intrinsic families with value/memory effects where needed; decode its constant payloads and repeated aggregates; complete general operation/constant/projection coverage audit; rerun the complete gate after those changes. No calibration or historical measurement is authorized by this result.
