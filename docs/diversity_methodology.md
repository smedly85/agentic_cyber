# Canonical compiler-grounded Architecture and Strategy methodology

This is the entry point for the final C A/S implementation finalized on October
16, 2026. The [final decision](ordered_diversity_final_decision.md) defines the
unchanged objectives and limitations; the [threshold decision](ordered_diversity_threshold_decision.md)
records the population audit. Their **qualified acceptance for exploratory C
reporting** is preserved. Consolidating the implementation does not promote it
to a calibrated family metric or establish behavioral or security independence.

## Execution pipeline

1. Select existing public-checkpoint-success candidates by manifest, formal run,
   utility and checkpoint. Preserve candidate identity, including duplicate sources.
2. Verify source/compiler/header provenance and extract Clang JSON ASTs under
   the recorded `c11-posix2008-v1` profile. `clang_ordered.adapt` constructs defined
   functions, external API references, directed calls and ordered function bodies.
3. `ordered_exact.compare` uses entry-preserving partial function injections and
   a MILP to minimize node/edge atom symmetric difference divided by the sum of
   atom counts. It verifies the optimum against relabeled atom sets. External
   API identities remain meaningful; repeated calls do not duplicate A edges.
4. Over scope-compatible Architecture-optimal correspondences, compare ordered
   rooted subtrees using the retained sequence recurrence and constrained
   unordered-group assignment. S is the interval of minimum and maximum
   normalized costs across admissible optima. A non-singleton interval is not
   replaced by a scalar. Incompatibility, incomplete enumeration and exhausted
   budgets remain explicit unavailable outcomes.
5. Report within-population pairwise results, coverage and budget records.
   Longitudinal reporting separates all-stage and fixed-lineage cohorts and
   compares the same lineage pairs across adjacent checkpoints. Incomplete
   matrices do not receive imputed values or family counts. The 0.30 clustering
   reference is historical, not a selected threshold.

## Code responsibilities

| Retained path | Responsibility |
| --- | --- |
| `scripts/analysis/clang_ordered.py` | Compiler AST adaptation, validation and comparison trees |
| `scripts/analysis/ordered_exact.py` | MILP A optimum, compatible optimum enumeration, S intervals and limits |
| `scripts/analysis/ordered_distances.py` | Shared atom sets, exhaustive alignment oracle, subtree recurrence, sequence/assignment operations and budgets |
| `scripts/analysis/ordered_callgraph.py` and `.schema.json` | Retained representation/serialization support and historical syntax extractor; not the paper extraction entry point |
| `scripts/analysis/diversity_validation.py` | Parsing support imported by the shared module and active experiment analyzer |
| `scripts/ordered_diversity_clang_probe.py` | AST traversal, source attribution, build flags and provenance helpers imported by final code |
| `scripts/ordered_diversity_clang_repro.py` | Compiler profile, AST acceptance, canonical IDs and preprocessing provenance |
| `scripts/ordered_diversity_feasibility.py` | Historical Phase 2.5 audit producer retained for the chained extraction evidence |
| `scripts/ordered_diversity_final.py` | Final two-pair extraction, comparison and exhaustive-oracle check |
| `scripts/ordered_diversity_threshold_study.py` | Population selection, extraction, bounded comparison worker and saved pair reporting |
| `scripts/analysis/ordered_thresholds.py` | Identity-aware matrices, interval summaries and exploratory threshold sensitivity |
| `docs/final_checkpoint_diversity_sample.py` | Verified historical-pair reuse and final-checkpoint population reporting |
| `docs/checkpoint_diversity_trajectories.py` | Longitudinal provenance, measurement journal, budgets and resume semantics |
| `docs/checkpoint_diversity_reporting.py` | Cohorts, rational A checks, coverage, paired changes and report validation |

## Retained evidence and reproduction

- [Final pairwise results](ordered_diversity_final_results.json).
- [Threshold pairwise evidence](ordered_diversity_threshold_pairwise.json),
  [summaries](ordered_diversity_threshold_results.json) and
  [CSV](ordered_diversity_threshold_results.csv).
- [Final-checkpoint report](final_checkpoint_diversity_sample.md),
  [combined results](final_checkpoint_diversity_sample.json) and
  [additional pairwise evidence](final_checkpoint_diversity_new_pairwise.json).
- [Longitudinal report](checkpoint_diversity_trajectories.md),
  [results](checkpoint_diversity_trajectories.json),
  [CSV](checkpoint_diversity_trajectories.csv) and
  [measurement journal](checkpoint_diversity_measurements.json): 495 pairs,
  480 exact A outcomes and 363 available S intervals.
- [Phase 2.5 audit](ordered_diversity_phase25_feasibility.json),
  [Phase 2.6 evidence](ordered_diversity_phase26_feasibility.json) and
  [Phase 2.7 evidence](ordered_diversity_phase27_feasibility.json).
  These historical artifacts form a dependency chain: the probe reads Phase 2.5,
  reproduction reads Phase 2.6, and final runners verify Phase 2.7. Their hashes,
  source snapshots, manifest and compiler/header records must remain intact.
  The [Phase 2.6](ordered_diversity_phase26_feasibility.md) and
  [Phase 2.7](ordered_diversity_phase27_feasibility.md) narratives describe
  extraction history, not current metric recommendations.

The final scripts can write measurement artifacts. Do not run them just to
check a cleanup. Even `--summarize-only` rewrites reports. Use the read-only
regressions in `tests/test_ordered_reporting_integrity.py` for saved-result
checks; compiler integration tests use temporary synthetic sources only.
Historical compiler/header and raw versus LF-normalized hashes are checked
separately; this does not claim reproduction under arbitrary toolchains.

## Separate active research

The [legacy experiment analyzer reference](experiment_analysis_reference.md)
documents reliability, maintenance and older feature-vector outputs still used
by `analyze_experiment.py`, `analyze_lineages.py` and execution consistency.
Its cosine-based A/S columns are not the ordered compiler-grounded measurements
above. Shared `diversity_metrics.py` and validation code remain for those active
consumers; removing them would break unrelated reporting.

C Clang/LLVM/SVF semantic call graphs, Rust MIR/RUPTA pointer analysis,
historical CVE depth and cross-language calibration remain separate research
under `security/semantic_callgraph` and `security/historical`. Neither SVF nor
RUPTA feeds this A/S comparator. Rust compiler-analysis foundations are retained;
the accepted comparator and its evidence here are C-only.

See the [cleanup audit](as_cleanup_audit.md) for the deletion decisions, history
and validation record.
