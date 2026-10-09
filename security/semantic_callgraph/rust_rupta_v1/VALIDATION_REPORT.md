# RUPTA controlled validation

**STOP: canonical RUPTA is not accepted for historical depth measurement.**

Unmodified upstream builds with its pinned nightly. Both modes complete all 35 programs twice. Each matches 33/35 programs under the inherited required relations/path checks; this is not 33 complete semantic graphs. Drop and library scope gaps remain even in many matching programs.

| Mode | Required programs matching | Exact resolved sites | Expected unresolved site | False / missing adjudicated targets | Run-1 wall seconds | Peak RSS MiB | Deterministic |
|---|---|---|---|---|---|---|---|
| ander | 33/35 | 23/23 | 1, inferred from MIR | 0 / 0 | 53.28 | 85.7 | yes |
| cs | 33/35 | 23/23 | 1, inferred from MIR | 0 / 0 | 53.18 | 85.3 | yes |

Runtime includes compiler startup, analysis, dumps and metadata emission; excludes dependency builds. Peak RSS is GNU time process maximum, not RUPTA-only allocation. Each analysis had 180 seconds and 16 GiB address space available. No timeouts/OOMs/build failures occurred. cs uses default depth 1; depth 2 was not justified because resolved target sets already match, while remaining blockers concern drop/export/compiler support.

## Small probes

All six pass in both modes and repeat identically after normalization. Direct target depth 1; nested 3; recursion 2; pointer 2; two-field struct 1; dynamic dispatch 3. The struct site is exported as a Fnptr call to only `target`; `third` is absent. The MIR explicitly loads field index 1. Recursion retains the self-edge.

## All controlled programs

`match+gap` means required expectations match but drop/static-call omissions are detected. `match` means no such gap detected, not proof of complete unresolved coverage. Nodes include the MIR-exported inventory; no nodes are contracted. R is entry-reachable functions. Instrument/supplement have multiple BFS anchors, so R lists their distinct counts.

| Program | ander | cs | Nodes / edges (ander) | R (ander) | Run-1 seconds A / CS | Peak RSS MiB A / CS |
|---|---|---|---|---|---|---|
| instrument | match+gap | match+gap | 33 / 64 | 4, 5, 6, 7 | 1.68 / 1.53 | 68.8 / 68.5 |
| expanded/nonfirst_reference | match | match | 5 / 5 | 5 | 0.93 / 0.88 | 82.7 / 83.4 |
| expanded/static_table | match | match | 5 / 5 | 5 | 0.88 / 0.88 | 83.5 / 82.9 |
| expanded/trait_drop | match+gap | match+gap | 6 / 6 | 6 | 0.88 / 0.88 | 83.1 / 82.8 |
| expanded/trait_one | match+gap | match+gap | 6 / 6 | 6 | 0.88 / 0.88 | 83.5 / 83.2 |
| expanded/trait_many | match+gap | match+gap | 6 / 6 | 6 | 0.88 / 0.88 | 82.9 / 83.1 |
| expanded/box_trait | match+gap | match+gap | 8 / 8 | 8 | 1.33 / 1.33 | 84.2 / 83.9 |
| expanded/dyn_fn | match | match | 6 / 6 | 6 | 0.93 / 0.88 | 83.2 / 82.9 |
| expanded/box_fnmut | match+gap | match+gap | 9 / 9 | 9 | 1.38 / 1.38 | 83.7 / 84.1 |
| expanded/option_map | match+gap | match+gap | 8 / 8 | 8 | 0.98 / 1.03 | 82.7 / 82.8 |
| expanded/result_or_else | match+gap | match+gap | 8 / 8 | 8 | 1.03 / 1.03 | 82.9 / 83.3 |
| expanded/iterator_flat_map | match+gap | match+gap | 33 / 41 | 33 | 3.49 / 3.49 | 85.7 / 85.3 |
| expanded/entry_wrappers | match+gap | match+gap | 8 / 8 | 8 | 0.93 / 0.93 | 83.0 / 83.2 |
| expanded/unwind | match+gap | match+gap | 8 / 10 | 8 | 1.13 / 1.18 | 83.4 / 84.0 |
| expanded/crates_io | FAIL | FAIL | 9 / 8 | 9 | 0.98 / 0.98 | 83.1 / 83.4 |
| expanded/static_and_dyn | match+gap | match+gap | 7 / 8 | 7 | 0.93 / 0.93 | 83.3 / 83.5 |
| expanded/platform | match | match | 5 / 5 | 5 | 0.88 / 0.83 | 82.5 / 82.9 |
| expanded/stack_bytes | match | match | 6 / 6 | 6 | 0.88 / 0.88 | 83.1 / 83.1 |
| expanded/same_method | match+gap | match+gap | 8 / 9 | 8 | 0.98 / 0.98 | 82.5 / 82.7 |
| supplement | FAIL | FAIL | 14 / 12 | 2, 3, 5, 6 | 2.82 / 2.87 | 71.8 / 71.4 |
| calibration/direct_chain/Rust | match | match | 3 / 2 | 3 | 0.68 / 0.68 | 64.8 / 65.2 |
| calibration/recursion/Rust | match | match | 3 / 3 | 3 | 0.68 / 0.68 | 65.4 / 65.4 |
| calibration/single_pointer/Rust | match | match | 2 / 1 | 2 | 0.68 / 0.68 | 65.6 / 66.0 |
| calibration/multi_pointer/Rust | match | match | 3 / 2 | 3 | 0.73 / 0.73 | 68.2 / 68.8 |
| calibration/first_field/Rust | match | match | 2 / 1 | 2 | 0.68 / 0.68 | 72.6 / 72.6 |
| calibration/non_first_field/Rust | match | match | 2 / 1 | 2 | 0.68 / 0.68 | 72.8 / 72.9 |
| calibration/stack_copy/Rust | match | match | 2 / 1 | 2 | 0.68 / 0.73 | 72.8 / 72.9 |
| calibration/heap_struct/Rust | match+gap | match+gap | 4 / 3 | 4 | 1.23 / 1.18 | 80.3 / 80.8 |
| calibration/generic_specialization/Rust | match | match | 5 / 4 | 5 | 0.73 / 0.73 | 73.8 / 73.5 |
| calibration/static_dispatch/Rust | match | match | 3 / 2 | 3 | 0.68 / 0.68 | 67.0 / 66.9 |
| calibration/dyn_vtable/Rust | match | match | 3 / 2 | 3 | 0.73 / 0.73 | 68.4 / 69.2 |
| calibration/closure_context/Rust | match | match | 3 / 2 | 3 | 0.73 / 0.73 | 72.8 / 72.4 |
| calibration/library_callback/Rust | match+gap | match+gap | 48 / 78 | 48 | 17.47 / 17.52 | 81.9 / 81.6 |
| calibration/mixed_stack_static/Rust | match | match | 4 / 4 | 4 | 0.78 / 0.78 | 73.7 / 74.1 |
| calibration/mixed_stack_heap/Rust | match+gap | match+gap | 6 / 6 | 6 | 1.28 / 1.28 | 80.2 / 80.2 |

## Failures and representation differences

- `expanded/crates_io`: `main → dependency_path → drop(guard)` is exported, but the destructor/callback transition is absent. The designated closure and `target` are unreachable in both modes. This is a missing legitimate route, not zero depth.
- `supplement`: RUPTA retains `external_work` and `external_callback` as body-unavailable graph nodes. The old SVF contract instead demands external-call records and no internal edge. The strict inherited check fails; its `invented_internal_edges` diagnostic describes a representation mismatch, not a fabricated call target. The callback pointer has no target in DOT/dynamic output; the adapter records its unresolved MIR operand. There is no explicit upstream unresolved/source-line ledger, so the inherited line-based unresolved check fails.
- All five S3 failures are resolved at the designated sites: heap_struct, mixed_stack_heap, mixed_stack_static, box_fnmut and stack_bytes. Their exact sets are in METHOD_COMPARISON.md. This does not repair omitted drop/library scope.

## Depth and entry interpretation

BFS uses the unchanged shared finalizer. Full per-anchor target depths, raw paths, reachability and finite shortest-distance maxima are in validation_results.json and build/.../*.graph.json. No historical metric was generated. Supplement mutual-recursion target depth is 2 and nested-chain depth is 4. The library comparator is reached at depth 6 with raw maximum finite shortest distance 7, but no equal C/Rust depth was preregistered.

The default root is rustc's source-level main, before an LLVM/native entry wrapper exists. Instrument uses explicit main (rlib); calibration uses its frozen entry anchor; the supplemental library is analyzed separately from its four entry functions. Supplemental BFS never fills a root graph from another root. Source main remains a reasonable primary utility entry, with uumain only as a separately identified sensitivity anchor. The controlled wrappers retain distinct outer and inner uumain nodes. An invalid name silently falls back to main; an isolated main disappears from DOT but remains in the MIR dump. Neither behavior permits name-only historical entry selection.

Post-hoc main-root sensitivity repeats dyn_vtable, mixed_stack_static and mixed_stack_heap twice in both modes. All six program/mode combinations retain the exact designated target sets with harness decoys included, and normalize identically. Primary calibration analysis begins at entry whereas prior SVF analyzes the main-rooted module; this sensitivity checks that the observed improvements in these cases are not merely caused by excluding those decoys from the analysis root.

## Evidence and preservation

All 70 program/mode normalized comparisons are identical across fresh compilations; all 12 small probe comparisons also match. DOT node numbering and ordering vary and are excluded from semantic identity. All generic argument strings and MIR locations remain. Analyzer binaries/source are unpatched. Export/parser amendments, not scientific algorithm changes, are documented in README.md.

Existing checks: frozen population gate, published MIR result verification, integrity checks, and four existing pytest tests. Six new adapter tests plus those four existing tests pass. The broader `pytest tests` command collects no tests (exit 5); it is not counted as a passing suite. All 39,276 snapshotted pre-existing files are byte-identical. Both before/after result verification and integrity checks pass. Final byte-preservation results and exact command records are in validation_results.json.
