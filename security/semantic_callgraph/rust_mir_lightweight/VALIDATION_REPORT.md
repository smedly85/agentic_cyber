# Lightweight Rust MIR validation

103 existing extracted inputs passed compiler-evidence and BFS checks in two byte-identical graph runs. No inclusion or points-to solver ran. This validates the narrower known-edge method, not whole-program indirect completeness or C/Rust comparability.

Handled construct classes: direct calls and recursion, monomorphized generic calls, statically resolved trait calls, known concrete closure/Fn Instances, compiler-resolved drop calls, and direct cross-crate calls. Function pointers stored in locals/fields/heap objects and receiver-dependent dyn/Fn dispatch remain unresolved unless the MIR call itself has a concrete compiler-resolved target. Unsafe, copy, field and allocation constraints are not interpreted as target evidence. A candidate-implementation inventory never supplies guessed dyn edges.

Required concrete-call target paths were checked against the frozen controlled results; all retained call targets also match compiler operands and are subsets of the frozen full-method target sets where those oracles exist. Every unresolved site is retained. Body-unavailable callees are explicit boundary nodes. BFS path lengths and shortest-distance inequalities were checked.

| Case | Entry-reachable unresolved sites | Body boundaries | Controlled designated target paths |
|---|---:|---:|---|
| controlled/direct | 0 | 0 | retained at same depth |
| controlled/recursion | 0 | 0 | retained at same depth |
| controlled/function_pointer | 1 | 0 | some/all full-method paths unresolved |
| controlled/multi_target | 1 | 0 | some/all full-method paths unresolved |
| controlled/struct_pointer | 1 | 0 | some/all full-method paths unresolved |
| controlled/closure | 0 | 0 | retained at same depth |
| controlled/generic | 0 | 0 | retained at same depth |
| controlled/static_trait | 0 | 0 | retained at same depth |
| controlled/dynamic_trait | 1 | 0 | some/all full-method paths unresolved |
| controlled/cross_crate_direct | 0 | 0 | retained at same depth |
| controlled/cross_crate_indirect | 1 | 0 | some/all full-method paths unresolved |
| controlled/duplicate_names | 0 | 0 | retained at same depth |
| controlled/multiple_instances | 0 | 0 | retained at same depth |
| controlled/nonfirst_reference | 1 | 0 | some/all full-method paths unresolved |
| controlled/static_table | 1 | 0 | some/all full-method paths unresolved |
| controlled/trait_drop | 1 | 0 | some/all full-method paths unresolved |
| controlled/trait_one | 1 | 0 | some/all full-method paths unresolved |
| controlled/trait_many | 1 | 0 | some/all full-method paths unresolved |
| controlled/box_trait | 1 | 7 | some/all full-method paths unresolved |
| controlled/dyn_fn | 1 | 0 | some/all full-method paths unresolved |
| controlled/box_fnmut | 1 | 7 | some/all full-method paths unresolved |
| controlled/option_map | 0 | 0 | retained at same depth |
| controlled/result_or_else | 0 | 0 | retained at same depth |
| controlled/iterator_flat_map | 0 | 2 | retained at same depth |
| controlled/entry_wrappers | 0 | 0 | retained at same depth |
| controlled/unwind | 0 | 1 | retained at same depth |
| controlled/crates_io | 0 | 2 | retained at same depth |
| controlled/static_and_dyn | 1 | 0 | retained at same depth |
| controlled/platform | 0 | 0 | retained at same depth |
| controlled/stack_bytes | 1 | 0 | some/all full-method paths unresolved |
| controlled/same_method | 0 | 0 | retained at same depth |
| focused/closure_arg | 1 | 0 | callsite target evidence checked |
| focused/closure_box | 1 | 7 | callsite target evidence checked |
| focused/closure_capture | 1 | 0 | callsite target evidence checked |
| focused/closure_dyn | 1 | 0 | callsite target evidence checked |
| focused/closure_fnmut | 1 | 7 | callsite target evidence checked |
| focused/closure_object | 1 | 0 | callsite target evidence checked |
| focused/closure_once | 1 | 7 | callsite target evidence checked |
| focused/closure_return | 1 | 0 | callsite target evidence checked |
| focused/closure_struct | 1 | 0 | callsite target evidence checked |
| focused/closure_tuple_args | 1 | 0 | callsite target evidence checked |
| focused/dyn_box | 1 | 7 | callsite target evidence checked |
| focused/dyn_drop | 1 | 0 | callsite target evidence checked |
| focused/dyn_multiarg | 1 | 0 | callsite target evidence checked |
| focused/dyn_one | 1 | 0 | callsite target evidence checked |
| focused/dyn_static | 1 | 0 | callsite target evidence checked |
| focused/dyn_two | 1 | 0 | callsite target evidence checked |
| focused/heap_helpers | 1 | 7 | callsite target evidence checked |
| focused/heap_isolation | 2 | 7 | callsite target evidence checked |
| focused/heap_single | 1 | 7 | callsite target evidence checked |
| focused/heap_stack | 1 | 7 | callsite target evidence checked |
| focused/heap_two | 1 | 7 | callsite target evidence checked |
| focused/mixed_callable | 1 | 0 | callsite target evidence checked |
| focused/mixed_dyn_static | 1 | 0 | callsite target evidence checked |
| focused/mixed_safe_unsafe | 1 | 2 | callsite target evidence checked |
| focused/mixed_storage | 1 | 7 | callsite target evidence checked |
| focused/unsafe_byte | 1 | 2 | callsite target evidence checked |
| focused/unsafe_cast_read | 1 | 0 | callsite target evidence checked |
| focused/unsafe_offset | 1 | 1 | callsite target evidence checked |
| focused/unsafe_transmute | 1 | 0 | callsite target evidence checked |
| focused/unsafe_union | 1 | 0 | callsite target evidence checked |
| memory/conditional_same_field | 1 | 0 | callsite target evidence checked |
| memory/distinct_fields | 2 | 0 | callsite target evidence checked |
| memory/first_field | 1 | 0 | callsite target evidence checked |
| memory/heap_storage | 1 | 7 | callsite target evidence checked |
| memory/mixed_objects | 1 | 0 | callsite target evidence checked |
| memory/overwrite | 1 | 0 | callsite target evidence checked |
| memory/reversed_writes | 1 | 0 | callsite target evidence checked |
| memory/second_field | 1 | 0 | callsite target evidence checked |
| memory/stack_copy | 1 | 0 | callsite target evidence checked |
| memory/stack_heap | 1 | 7 | callsite target evidence checked |
| memory/three_fields | 3 | 0 | callsite target evidence checked |
| memory/unsafe_bytes | 1 | 2 | callsite target evidence checked |
| operations/box_fnmut_two | 1 | 7 | callsite target evidence checked |
| operations/box_two | 1 | 7 | callsite target evidence checked |
| operations/constant_dyn | 1 | 0 | callsite target evidence checked |
| operations/constant_helper | 1 | 0 | callsite target evidence checked |
| operations/constant_item | 1 | 0 | callsite target evidence checked |
| operations/constant_struct | 1 | 0 | callsite target evidence checked |
| operations/mixed_known | 1 | 0 | callsite target evidence checked |
| operations/mixed_variable | 1 | 0 | callsite target evidence checked |
| operations/repeat_known | 1 | 0 | callsite target evidence checked |
| operations/repeat_variable | 1 | 0 | callsite target evidence checked |
| operations/select_fields | 1 | 0 | callsite target evidence checked |
| operations/static_struct | 1 | 0 | callsite target evidence checked |
| operations/swap_fields | 1 | 0 | callsite target evidence checked |
| adapter/std_callbacks | 2 | 8 | callsite target evidence checked |
| transitive/graph | 1 | 8 | callsite target evidence checked |
| calibration/direct_chain | 0 | 0 | callsite target evidence checked |
| calibration/recursion | 0 | 0 | callsite target evidence checked |
| calibration/single_pointer | 1 | 0 | callsite target evidence checked |
| calibration/multi_pointer | 1 | 0 | callsite target evidence checked |
| calibration/first_field | 1 | 0 | callsite target evidence checked |
| calibration/non_first_field | 1 | 0 | callsite target evidence checked |
| calibration/stack_copy | 1 | 0 | callsite target evidence checked |
| calibration/heap_struct | 1 | 7 | callsite target evidence checked |
| calibration/generic_specialization | 0 | 0 | callsite target evidence checked |
| calibration/static_dispatch | 0 | 0 | callsite target evidence checked |
| calibration/dyn_vtable | 1 | 0 | callsite target evidence checked |
| calibration/closure_context | 0 | 0 | callsite target evidence checked |
| calibration/library_callback | 0 | 8 | callsite target evidence checked |
| calibration/mixed_stack_static | 1 | 0 | callsite target evidence checked |
| calibration/mixed_stack_heap | 1 | 7 | callsite target evidence checked |

The initial validation attempt is preserved separately. Its target lookup incorrectly assumed the cross-crate fixture used a function named target; the existing fixture oracle designates cross_target. Only the validation lookup was corrected before these clean reruns; graph implementation and acceptance criteria were unchanged.

Acceptance: PASS for the explicitly scoped Rust-only retained-call graph. The prior calibration verdict is unchanged. Unresolved cases are coverage limitations of this method and remain visible in historical statuses.
