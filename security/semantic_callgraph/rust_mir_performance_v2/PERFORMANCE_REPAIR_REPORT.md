# Rust MIR performance-only repair

PERFORMANCE-REPAIR-INSUFFICIENT

Exact controlled, calibration and adversarial equality passed, with deterministic replicas and unchanged protected artifacts. Controlled aggregate speedup was 1.104x and historical propagation advanced faster, but printenv, mktemp and sort all timed out at the original 900-second budget with peak RSS above 10 GiB. Practical historical convergence is not established; the candidate is not approved for historical remeasurement.

This is a separate diagnostic candidate. The original solver remains the reference/default backend. Method-v1 remains frozen with zero accepted historical depths. No historical vulnerability depth was calculated or accepted by these diagnostics.

## Hot paths and repair

`analyze.collapse` repeatedly unions all sets belonging to the same local, even after collapse. `copy`/`store` repeatedly transfer complete sets and scan field projections. `locations`, pointer metadata and dyn-receiver handling repeatedly filter token sets. The preimplementation engineering note records the exact scans and proof obligations.

The candidate performs the original union on first collapse and retains all provenance updates thereafter; post-collapse writes already canonicalize to the root. It maintains append-only fact logs and exact source/destination transfer cursors, lazy token-kind indexes updated on every insertion, and field-prefix snapshots invalidated by membership growth. No fields collapse before the original rule calls collapse. Constraints, abstract values, required-body handling and finalization are unchanged.

The original full sweeps, convergence test and 256-sweep fail-closed cap remain. There is no new worklist or heuristic termination rule.

## Exact equality and replication

All 108 cases passed exact scientific-file and internal points-to-state comparisons against the reference. Two independent candidate output directories matched. Tests also cover cap exhaustion, late empty collapse members, field-membership growth and transfer fanout.

| Suite | Cases | Result |
|---|---:|---|
| adapter | 1 | exact |
| calibration | 15 | exact |
| controlled | 31 | exact |
| focused | 30 | exact |
| memory | 12 | exact |
| operations | 13 | exact |
| synthetic | 5 | exact |
| transitive | 1 | exact |

Unit mirror: 49 tests passed; 35 analyzer calls compared reference and candidate, with separate live gates.

Every Rust calibration normalized graph and inclusion result matches the frozen artifact. Frozen pair statuses and dynamic inputs remain unchanged; the C qsort boundary failure and CALIBRATION-FAIL verdict remain intact. No C analyzer rerun was needed.

An initial reference-only harness comparison encountered Python tuple versus JSON list representation. The newly serialized and frozen inclusion files had identical SHA-256. The preserved harness note documents this non-scientific issue; the clean rerun uses canonical JSON and byte equality. No candidate scientific mismatch occurred.

## Solver-only performance

| Mode | Wall seconds | CPU seconds | Worker peak RSS GiB |
|---|---:|---:|---:|
| reference | 15.148725 | 15.147424 | 0.068 |
| candidate | 13.720985 | 13.717672 | 0.072 |

Aggregate wall speedup: 1.104x; CPU speedup: 1.104x. Candidate/reference peak RSS ratio: 1.068.

Timing excludes extraction, input loading, live gates and serialization. Peak memory is the independent worker peak across the complete suite, not a per-case allocation measurement. Small-case timings are sensitive to timer noise. Reference operation counts come from a separate in-memory observational AST pass, whose outputs matched the uninstrumented reference; its overhead is excluded from speed comparisons.

| Operation counter | Reference observed | Candidate |
|---|---:|---:|
| callsites_processed | 174945 | 174945 |
| collapse_calls | 232561 | 232561 |
| collapse_members_scanned | 25104090 | 13870 |
| collapse_tokens_scanned | 2977338 | 22288 |
| collapse_unions_avoided | not instrumented | 140549 |
| constraints_processed | 610310 | 610310 |
| copy_calls | 1388045 | 1388045 |
| delta_tokens_considered | not instrumented | 149244 |
| field_members_scanned | 4046635 | 59353 |
| field_snapshot_hits | not instrumented | 757384 |
| first_collapses | 3325 | 3325 |
| kind_index_build_scans | not instrumented | 6687 |
| kind_index_hits | not instrumented | 227064 |
| kind_lookups | not instrumented | 231074 |
| metadata_queries | 1405 | 1405 |
| plain_tokens_considered | 14177959 | 1207179 |
| points_to_additions | 145672 | 145672 |
| points_to_cells | not instrumented | 57312 |
| points_to_facts | not instrumented | 145672 |
| prefix_cache_entries | not instrumented | 17750 |
| store_calls | 6416639 | 6276090 |
| sweeps | 1183 | 1183 |
| token_filter_queries | 250276 | not applicable / zero |
| token_filter_tokens_scanned | 993140 | not applicable / zero |
| transfer_relations | not instrumented | 28529 |
| unchanged_transfers_avoided | not instrumented | 5307188 |

Token-filter scan and kind-index-build counters measure different implementation operations; they are not interchangeable semantic counts. There is no worklist-operation count because both implementations retain full sweeps.

## Selected historical-scale diagnostics

Selection is inherited unchanged from the earlier pre-solver size rule: printenv, mktemp, sort. Each run uses an immutable extracted snapshot, a fresh process, the same 900-second wall budget and the live gate. A 24-GiB RSS safety stop and 2-GiB host-memory floor protect the diagnostic host; these are not approved measurement limits. Historical graph hashes cover unchanged inclusion/export output only. No historical BFS, mapped-target resolution or vulnerability depth runs.

| Context/run | Outcome | Process seconds | Solver seconds | Peak RSS GiB | Sweeps |
|---|---|---:|---:|---:|---:|
| printenv/candidate-a | wall_timeout; converged=False | 901.384 | unavailable | 10.515 | 23 |
| mktemp/candidate-a | wall_timeout; converged=False | 901.392 | unavailable | 10.549 | 22 |
| sort/candidate-a | wall_timeout; converged=False | 901.499 | unavailable | 12.463 | 17 |

The following counters are final only for completed runs; otherwise they are the last recorded progress sample before termination. A timeout has no final fixed point, final graph hash or convergence-determinism result.

| Context/run | Sample seconds | CPU seconds | Constraints | Point additions | Collapse calls | Copy calls | Delta tokens considered |
|---|---:|---:|---:|---:|---:|---:|---:|
| printenv/candidate-a | 890.1121013700003 | 889.831163105 | 1800834 | 157492546 | 5104791 | 2483888 | 5023336821 |
| mktemp/candidate-a | 890.0565260470003 | 889.825646514 | 1818953 | 160685027 | 4809583 | 2521245 | 5326953881 |
| sort/candidate-a | 890.1795682300003 | 889.959135984 | 2017172 | 197262031 | 3677019 | 2904739 | 6322663409 |

Reference baselines: printenv 900s / 6.86 GiB; mktemp 900s / 7.03 GiB; sort 900s / 9.10 GiB; printenv 1800s / 9.71 GiB. All timed out while making progress. Original input, solver and Python executable identities are bound in the diagnostic results. No converged historical reference output exists, so historical-scale exact reference equality is not established. Complete controlled/calibration equality cannot prove equality for every possible historical input. 

None of the selected candidate contexts converged, so no longer reference run was warranted and no historical graph determinism claim is made.

## Cold replication and remaining scope

Two independent incremental-disabled extraction replays for each selected utility match the frozen normalized raw MIR exactly. Only the incremental argument was removed, CARGO_INCREMENTAL=0 was set and output directories were redirected. Dependencies remained frozen and read-only; this does not establish whole-dependency cold rebuild equivalence. Future measurement needs an additive approved amendment and independent extraction/solver output directories.

Addition logs, transfer cursors and indexes add memory. Full constraint sweeps and non-specialized operand unions remain possible scaling costs. No unvalidated optimization is deployed. od remains separate (133 unsupported intrinsic Instances and 19 required identities absent); chcon remains separate (selinux-sys 0.6.14, missing selinux/selinux.h). No policy waiver or system installation was made.

## Integrity and artifacts

All 701 saved gate-record files passed their component checks. Final integrity passed for 29514 protected files, immutable extracted inputs, all frozen runtime identities and 159 protected C files. Calibration, mappings, population, classifier, C results/instrument, reference solver and accepted extraction semantics remain unchanged.

Reference SHA-256: `12ba550d3f52f20f989ff596d292bc4ebdb2608ccc5fcd47beef16ad4d40d871`

Candidate SHA-256: `6fb1791a04d4a28eb3d2f49f4c893f4a4f71d89a99fae19fd5c5a9eedbb3180b`

Evidence is in build/rust-mir/solver-v2-performance: equality-v1, unit-mirror, performance, historical-diagnostic, cold-extraction, preservation_before.json, integrity_after.json and final_verdict.json. Source selection is exposed only through the separate solve.py command. No historical scientific result file is populated by this task.

PERFORMANCE-REPAIR-INSUFFICIENT
