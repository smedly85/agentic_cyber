# Controlled method comparison

These are distinct instruments and compiler configurations. MIR means the existing compiler-resolved lightweight method; its own successful validation concerns retained compiler-proven edges, not exact whole-program may-call coverage. No new MIR/SVF analysis was run to generate this comparison. Their committed/frozen results are read-only. S3 is the best tested three-patch SVF configuration (30/35), tied with S and S-noffeq; canonical P matches 20/35.

| Program | Compiler-resolved MIR | Canonical SVF P | Patched SVF S3 | RUPTA ander | RUPTA cs(1) |
|---|---|---|---|---|---|
| instrument | partial_known_edge_method; 5 unresolved | fail | pass | match+gap | match+gap |
| expanded/nonfirst_reference | partial_known_edge_method; 1 unresolved | fail | pass | match | match |
| expanded/static_table | partial_known_edge_method; 1 unresolved | fail | pass | match | match |
| expanded/trait_drop | partial_known_edge_method; 1 unresolved | fail | pass | match+gap | match+gap |
| expanded/trait_one | partial_known_edge_method; 1 unresolved | fail | pass | match+gap | match+gap |
| expanded/trait_many | partial_known_edge_method; 1 unresolved | fail | pass | match+gap | match+gap |
| expanded/box_trait | partial_known_edge_method; 1 unresolved | fail | pass | match+gap | match+gap |
| expanded/dyn_fn | partial_known_edge_method; 1 unresolved | fail | pass | match | match |
| expanded/box_fnmut | partial_known_edge_method; 1 unresolved | fail | fail | match+gap | match+gap |
| expanded/option_map | compiler_evidence_valid; 0 unresolved | pass | pass | match+gap | match+gap |
| expanded/result_or_else | compiler_evidence_valid; 0 unresolved | pass | pass | match+gap | match+gap |
| expanded/iterator_flat_map | compiler_evidence_valid; 0 unresolved | pass | pass | match+gap | match+gap |
| expanded/entry_wrappers | compiler_evidence_valid; 0 unresolved | pass | pass | match+gap | match+gap |
| expanded/unwind | compiler_evidence_valid; 0 unresolved | pass | pass | match+gap | match+gap |
| expanded/crates_io | compiler_evidence_valid; 0 unresolved | pass | pass | FAIL | FAIL |
| expanded/static_and_dyn | partial_known_edge_method; 1 unresolved | fail | pass | match+gap | match+gap |
| expanded/platform | compiler_evidence_valid; 0 unresolved | pass | pass | match | match |
| expanded/stack_bytes | partial_known_edge_method; 1 unresolved | fail | fail | match | match |
| expanded/same_method | compiler_evidence_valid; 0 unresolved | pass | pass | match+gap | match+gap |
| supplement | not_previously_measured | pass | pass | FAIL | FAIL |
| calibration/direct_chain/Rust | compiler_evidence_valid; 0 unresolved | pass | pass | match | match |
| calibration/recursion/Rust | compiler_evidence_valid; 0 unresolved | pass | pass | match | match |
| calibration/single_pointer/Rust | partial_known_edge_method; 1 unresolved | pass | pass | match | match |
| calibration/multi_pointer/Rust | partial_known_edge_method; 1 unresolved | pass | pass | match | match |
| calibration/first_field/Rust | partial_known_edge_method; 1 unresolved | pass | pass | match | match |
| calibration/non_first_field/Rust | partial_known_edge_method; 1 unresolved | pass | pass | match | match |
| calibration/stack_copy/Rust | partial_known_edge_method; 1 unresolved | pass | pass | match | match |
| calibration/heap_struct/Rust | partial_known_edge_method; 1 unresolved | fail | fail | match+gap | match+gap |
| calibration/generic_specialization/Rust | compiler_evidence_valid; 0 unresolved | pass | pass | match | match |
| calibration/static_dispatch/Rust | compiler_evidence_valid; 0 unresolved | pass | pass | match | match |
| calibration/dyn_vtable/Rust | partial_known_edge_method; 1 unresolved | fail | pass | match | match |
| calibration/closure_context/Rust | compiler_evidence_valid; 0 unresolved | pass | pass | match | match |
| calibration/library_callback/Rust | compiler_evidence_valid; 0 unresolved | pass | pass | match+gap | match+gap |
| calibration/mixed_stack_static/Rust | partial_known_edge_method; 1 unresolved | fail | fail | match | match |
| calibration/mixed_stack_heap/Rust | partial_known_edge_method; 1 unresolved | fail | fail | match+gap | match+gap |

MIR instrument row aggregates 13 separately rooted cases; no directly comparable 35-program pass count is asserted. The supplemental source has no prior lightweight run. `match+gap` and `match` have the restricted meanings in VALIDATION_REPORT.md.

## Exact adjudicated target sets

All rows below use the unchanged prior site expectations. ∅ unresolved is not a successful empty target set unless the fixture explicitly expects an external-origin unresolved pointer. Source-to-MIR mapping uses the unique indirect site in the independently mapped owner; absent/ambiguous mappings cannot pass.

| Program / site | Expected | Compiler-resolved MIR observed | SVF P observed | SVF S3 observed | RUPTA ander observed | RUPTA cs observed |
|---|---|---|---|---|---|---|
| calibration/dyn_vtable/Rust / entry.dispatch | First::operation, Second::operation | ∅ (unresolved) | ∅ (missing_targets) | First::operation, Second::operation (exact) | First::operation, Second::operation (exact) | First::operation, Second::operation (exact) |
| calibration/first_field/Rust / entry.callback | target | ∅ (unresolved) | target (lowered_to_direct_call_exact) | target (lowered_to_direct_call_exact) | target (exact) | target (exact) |
| calibration/heap_struct/Rust / entry.callback | target | ∅ (unresolved) | ∅ (missing_targets) | ∅ (missing_targets) | target (exact) | target (exact) |
| calibration/mixed_stack_heap/Rust / invoke.callback | target_a, target_b | ∅ (unresolved) | target_a, unrelated (missing_and_unexpected_targets) | target_a, unrelated (missing_and_unexpected_targets) | target_a, target_b (exact) | target_a, target_b (exact) |
| calibration/mixed_stack_static/Rust / invoke.callback | target_a, target_b | ∅ (unresolved) | target_a, unrelated (missing_and_unexpected_targets) | target_a, target_b, unrelated (unexpected_targets) | target_a, target_b (exact) | target_a, target_b (exact) |
| calibration/multi_pointer/Rust / entry.callback | target_a, target_b | ∅ (unresolved) | target_a, target_b (exact) | target_a, target_b (exact) | target_a, target_b (exact) | target_a, target_b (exact) |
| calibration/non_first_field/Rust / entry.callback | target | ∅ (unresolved) | target (lowered_to_direct_call_exact) | target (lowered_to_direct_call_exact) | target (exact) | target (exact) |
| calibration/single_pointer/Rust / entry.callback | target | ∅ (unresolved) | target (lowered_to_direct_call_exact) | target (lowered_to_direct_call_exact) | target (exact) | target (exact) |
| calibration/stack_copy/Rust / entry.callback | target | ∅ (unresolved) | target (lowered_to_direct_call_exact) | target (lowered_to_direct_call_exact) | target (exact) | target (exact) |
| expanded/box_fnmut / box_call_mut.box_dyn_fnmut_shim | boxed_mut::{closure#0} | ∅ (unresolved) | ∅ (missing_targets) | boxed_mut::{closure#0}, rust_std/library/core/src/ops/function.rs::call_once<expanded::boxed_mut::{closure_env#0}, (usize)>#llvm=_ZN4core3ops8function6FnOnce40call_once$u7b$$u7b$vtable.shim$u7d$$u7d$17h91528eb295cbc937E (unexpected_targets) | boxed_mut::{closure#0} (exact) | boxed_mut::{closure#0} (exact) |
| expanded/box_trait / boxed.box_dyn_trait | <First as Action>::operation | ∅ (unresolved) | ∅ (missing_targets) | <First as Action>::operation (exact) | <First as Action>::operation (exact) | <First as Action>::operation (exact) |
| expanded/dyn_fn / dyn_fn.dyn_fn_object | main::{closure#0} | ∅ (unresolved) | ∅ (missing_targets) | main::{closure#0} (exact) | main::{closure#0} (exact) | main::{closure#0} (exact) |
| expanded/nonfirst_reference / by_reference.static_nonfirst_field | target | ∅ (unresolved) | third (missing_and_unexpected_targets) | target (exact) | target (exact) | target (exact) |
| expanded/stack_bytes / by_reference.stack_nonfirst_field | target | ∅ (unresolved) | target, third (unexpected_targets) | target, third (unexpected_targets) | target (exact) | target (exact) |
| expanded/static_and_dyn / dyn_one.trait_object | <First as Action>::operation | ∅ (unresolved) | ∅ (missing_targets) | <First as Action>::operation (exact) | <First as Action>::operation (exact) | <First as Action>::operation (exact) |
| expanded/static_table / static_table.static_nonfirst_field | target | ∅ (unresolved) | third (missing_and_unexpected_targets) | target (exact) | target (exact) | target (exact) |
| expanded/trait_drop / dyn_one.trait_object | <First as Action>::operation | ∅ (unresolved) | ∅ (missing_targets) | <First as Action>::operation (exact) | <First as Action>::operation (exact) | <First as Action>::operation (exact) |
| expanded/trait_many / dyn_many.trait_object_second_method | <First as Action>::multiple | ∅ (unresolved) | ∅ (missing_targets) | <First as Action>::multiple (exact) | <First as Action>::multiple (exact) | <First as Action>::multiple (exact) |
| expanded/trait_one / dyn_one.trait_object | <First as Action>::operation | ∅ (unresolved) | ∅ (missing_targets) | <First as Action>::operation (exact) | <First as Action>::operation (exact) | <First as Action>::operation (exact) |
| instrument / cross_indirect.function_pointer | dep::cross_target | ∅ (unresolved) | dep::cross_target (exact) | dep::cross_target (exact) | dep::cross_target (exact) | dep::cross_target (exact) |
| instrument / dynamic_dispatch.trait_object | <First as Operation>::operation, <Second as Operation>::operation | ∅ (unresolved) | ∅ (missing_targets) | <First as Operation>::operation, <Second as Operation>::operation (exact) | <First as Operation>::operation, <Second as Operation>::operation (exact) | <First as Operation>::operation, <Second as Operation>::operation (exact) |
| instrument / invoke.function_pointer | alternate, target | ∅ (unresolved) | alternate, target (exact) | alternate, target (exact) | alternate, target (exact) | alternate, target (exact) |
| instrument / invoke_holder.struct_field | target | ∅ (unresolved) | target (exact) | target (exact) | target (exact) | target (exact) |
| supplement / call_unknown.external_origin_pointer | ∅ | not previously matched | ∅ (exact_unresolved) | ∅ (exact_unresolved) | ∅ (exact_unresolved) | ∅ (exact_unresolved) |

## Interpretation

RUPTA improves designated indirect-call precision over canonical and patched SVF on this corpus: all 23 resolved target sets are exact, including the five persistent S3 failures. Both modes give the same sets; context sensitivity adds no demonstrated precision here. The unresolved external-origin site is recoverable only as a MIR observation, not from a complete upstream unresolved ledger.

RUPTA also loses a valid scopeguard route that the existing compiler-resolved MIR method retains. Its omitted Drop transitions, allocator special models, boundary nodes and direct Fn/closure resolution change the raw graph and path layering. Better field precision is not equivalent to a more complete instrument.

C SVF analyzes LLVM memory objects and emitted definitions; RUPTA analyzes MIR function references, generic substitutions and special-function models. RUPTA exports the context-unioned graph even for cs. Compiler versions, source roots, bodies available from libraries, drop/shim nodes, and unavailable externals differ. The same BFS computes distances in these different graphs; it does not make the numbers directly comparable. A common-scope, entry- and identity-audited calibration would be necessary before any numerical C/Rust claim.
