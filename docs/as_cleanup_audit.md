# A/S consolidation audit

Baseline: `fc0a84df`; dedicated branch: `cleanup/canonical-ordered-diversity`.
The initial tracked and untracked status was clean. No ignored research files,
source snapshots, fixture manifests or generated utility implementations were
deleted. The [methodology entry point](diversity_methodology.md) inventories
retained modules, their responsibilities, the execution pipeline and evidence.

## History and dependency findings

| Commit | Role |
| --- | --- |
| `9bba9d85` | Initial syntax/Tree-sitter ordered graph and controlled pilot |
| `5f3ad801` | Phase 2.5 real-source feasibility and updated construct pilot |
| `9a2a1e10` | Clang probe, Phase 2.6 evidence |
| `00a19974` | Reproducible Clang profile and Phase 2.7 evidence |
| `20cc83af` | Final Clang adapter, MILP comparator and two-pair results |
| `237718b0` | Population reporting and threshold sensitivity |
| `c6af72ae` | Final methodology decision and limitations |
| `0be648bd` | Earlier cleanup deleted the ordered validation tests |
| `f27edb4b` | Final-checkpoint population report |
| `6befb360` | Longitudinal journal and reporting |

The final and threshold runners import the Clang probe and reproduction helpers.
The Clang adapter uses those helpers and `ordered_distances._tree`. The MILP
comparator imports `ordered_distances` for atom sets, alignment labels, budgets,
subtree size/edit operations and the independent exhaustive oracle. That module
imports `ordered_callgraph`, which imports `diversity_validation`. The threshold
runner supplies extraction and workers to both population runners. Longitudinal
reporting reuses final-checkpoint outcomes and `ordered_thresholds`.

Data dependencies are equally important: Phase 2.6 reads and hashes the Phase 2.5
audit; Phase 2.7 reads and hashes Phase 2.6; final/threshold/final-checkpoint and
longitudinal paths verify Phase 2.7. Algorithm hashes freeze the shared code.
No shared function was moved or pruned, because changing its containing file
would invalidate those attestations even if its runtime behavior were unchanged.

## Deleted files

| File | Reason |
| --- | --- |
| `scripts/ordered_diversity_pilot.py` | Standalone controlled-fixture Tree-sitter pilot. No retained code imports it; the final runner uses Clang and `ordered_exact.compare`. |
| `docs/ordered_diversity_pilot_results.json` | Initial syntax-only pilot matrices; not read or hash-verified by the final evidence chain. |
| `docs/ordered_diversity_phase25_construct_results.json` | Later output of the same controlled pilot, superseded by compiler integration validation; distinct from the retained Phase 2.5 real-source feasibility audit. |
| `docs/ordered_call_diversity_prototype.md` | Accumulated prototype/phase narrative and obsolete pilot commands. Final definitions, limitations and evidence are retained in the final/threshold decisions and canonical index. |

These files remain recoverable in Git history. Searches of retained code,
documentation, manifests and reports found no incoming dependencies on the
deleted pilot outputs. All construct source fixtures and their manifest remain.
No currently present tests exclusively supported the deleted pilot: those tests
had already been removed in `0be648bd`. They were not restored.

## Superseded material retained deliberately

- `ordered_callgraph.py`, its schema and `ordered_distances.py`: shared runtime
  support, mathematical recurrence and exhaustive oracle, despite phase names.
- `ordered_diversity_feasibility.py`, both Clang helper scripts, Phase 2.5/2.6/2.7
  feasibility JSONs and the two Clang feasibility narratives: provenance chain,
  compiler acceptance and deterministic reproduction context.
- `diversity_metrics.py`, `diversity_validation.py`, and the older A/S paths in
  `analyze_experiment.py`: active imports from lineage, reliability, maintenance,
  construct validation and execution-consistency tools. Removing these requires
  a separately scoped migration of those consumers. They are explicitly not the
  final paper A/S entry point.
- The old schema-v7 methodology text is retained as
  `experiment_analysis_reference.md` with a prominent legacy notice, because
  it also defines active non-A/S reporting. README and execution-consistency
  references now distinguish it from the canonical A/S index.
- Threshold code and results remain: they support coverage-qualified population
  reporting and the recorded decision not to select a primary family threshold.

## Validation and preservation

Restored unchanged from `c6af72ae`: `test_ordered_clang_integration.py`,
`test_ordered_clang_probe.py`, `test_ordered_clang_repro.py` and
`test_ordered_thresholds.py`. These cover compiler failure/attribution, AST
ordering and slot constraints, MILP versus exhaustive alignment, ambiguity,
scope compatibility, budgets and population reporting. Added direct recurrence
contracts in `test_ordered_subtrees.py` and read-only saved-evidence checks in
`test_ordered_reporting_integrity.py`.

The integrity tests compare algorithm/evidence hashes and frozen artifacts to
the baseline, recompute reporting summaries in memory, and intercept every
report write. Resume tests use a temporary copy of an existing outcome and
forbid compiler and comparison subprocess calls. They verify all 36 cohort
summaries, 14 transitions and four final-checkpoint summaries against recorded
results, including **495 pairs, 480 exact A outcomes and 363 available S
intervals**. Threshold summaries are checked against both recorded populations.
No new population distances or experiment results are generated.

Validation command (WSL, repository root):

```sh
python3 -m pytest -q tests/test_ordered_clang_integration.py tests/test_ordered_clang_probe.py tests/test_ordered_clang_repro.py tests/test_ordered_thresholds.py tests/test_ordered_reporting_integrity.py tests/test_ordered_subtrees.py
```

Result: **61 passed in 4.20 seconds**, no failures or skips. `git diff --check`
passed. The final diff contains only the four audited deletions, documentation
consolidation and six validation test files. No preserved measurement or
compiler/comparator source file has a diff.

Historical result files retain their original statements about tests being
absent at the time of that report; this audit records their restoration rather
than editing the published artifacts. Compiler integration tests compile only
temporary synthetic sources, not research candidates.

The cleanup changes no final A/S implementation files, metric definitions,
normalization, selection rules, solver limits or retained measurement artifacts.
No historical CVE analysis, SVF/RUPTA research, Rust compiler foundations,
cross-language calibration, functional-validation or lineage experiments are
changed. No remote push is performed.
