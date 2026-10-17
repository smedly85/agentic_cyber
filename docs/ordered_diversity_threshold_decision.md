# Bounded exploratory RQ2 threshold-sensitivity study

**Decision: QUALIFIED ACCEPT for exploratory reporting.** Architecture has complete
measurement coverage in both audited populations, but family counts depend on
threshold. Strategy is incomplete in both populations and cannot support
full-population family statistics. **Do not freeze a new primary threshold from
this study.** The legacy 0.30 remains a comparison reference only; it has not been
independently calibrated for these distances.

The independent review reran all 66 pairwise comparisons, verified the saved
statistics, and compared all 21 mkdir Architecture pairs against the exhaustive
oracle. It reported no CRITICAL defects and a **QUALIFIED ACCEPT** verdict. This
supports implementation correctness within the audited scope, not independent
calibration or substantive validity of structural families. This documentation
pass does not recompute measurements or change the saved results.

## Population, method and computation

The existing `security/generated_candidate_population.json` supplied all seven
successful mkdir/002 observations and all ten successful grep/004 observations
from their respective `*-qwen38-t1-seed42-low-ctx64k-max64k-n10` formal runs.
Formal run, utility, checkpoint, lineage, candidate identity and manifest source
hashes are retained in the pairwise report. No successful member was dropped;
the two populations were never pooled or compared across utilities. These are
success-conditioned populations, not all attempted generations. They share one
model/configuration; these observations do not establish generality across models
or generation configurations.

Each candidate received exactly one Clang AST extraction under the unchanged
`c11-posix2008-v1` profile, then a cached representation was reused. Compiler and
previously audited header hashes matched Phase 2.7. Each candidate also has its
own preprocessing macro dump and header/source input hashes. All 17 extractions
succeeded, and all 17 source files remained byte-identical through the completed
study. Manifest hashes matching only after CRLF-to-LF normalization are explicitly
distinguished from actual extracted-byte hashes. No duplicate source hashes were
observed; duplicate observations would nevertheless retain separate identities
and weights rather than being silently deduplicated.

The raw SHA-256 identifies the actual source bytes passed to Clang. An
LF-normalized SHA-256 identifies bytes after CRLF-to-LF normalization and is
reported separately when needed to verify manifest membership. These hashes are
not interchangeable: a checkout's line-ending conversion can change the raw hash
and source offsets without changing the normalized source. Report byte identity
is therefore checkout-dependent, not a cross-checkout reproducibility guarantee;
paths, raw-byte provenance and fresh-run timings can also differ.

The committed graph-atom Architecture objective and rooted-subtree Strategy
objective, optimizer and name-based scope policy were reused unchanged. The
default production exclusion regex was applied independently, with `main` always
included and no forced includes configured. Only unordered off-diagonal pairs
were computed. Both original sprint pairs reproduced their committed A/S values
exactly.

In mkdir/002, the inherited default regex excludes mode-parsing helper functions.
Parser code inlined into `main` remains included. Thus Strategy's
content and measurement coverage depend on helper naming and compatible scope
membership, even though no reference candidate is selected. A helper rename that
crosses the exclusion boundary is not an invariant of this Strategy estimand.

Budgets were prespecified: unchanged comparator defaults (45 s for alignment,
128 admissible optima, 45 s/2,000,000 work units for S and the existing size
limits), a 100 s pair-process guard and a 900 s total comparison budget. Extraction
and each of two provenance-preprocessing calls retain their existing 120 s
timeout. Pair-process elapsed times totaled 13.65 s for mkdir and 159.78 s for
grep; extraction/provenance elapsed times totaled 5.38 s and 10.28 s. Neither
the study budget nor process guard was reached. These are local observed timings,
not portability guarantees. Compiler: Ubuntu Clang 21.1.8; package versions,
implementation SHA-256 identifiers and exact commands are in the evidence.

## Coverage and threshold-free results

| Population | Exact A coverage | Full-population mean A | Complete S pair intervals | Available-pair mean S interval **only** | Singleton / sensitive S intervals |
| --- | --- | ---: | --- | --- | --- |
| mkdir/002, n=7 | 21/21 | **0.2009486264** | 20/21 (95.24%) | **[0.6824929873, 0.6825878040]** | 19 / 1 |
| grep/004, n=10 | 45/45 | **0.3091366392** | 24/45 (53.33%) | **[0.6250179064, 0.6416192981]** | 2 / 22 |

Means use unordered pairs with equal pair weight; Strategy averages lower and
upper endpoints separately. **Neither S mean is a full-population estimate.**
No missing pair or certified bound is substituted by zero or an exact scalar.
All 66 A values are exact; no bounded-only Architecture result occurred.

The missing mkdir S pair is lineage-001 versus lineage-009: no architecture-optimal
correspondence has compatible Strategy scope. Grep has 13 such scope-incompatible
pairs, two pairs whose optimal-alignment enumeration reached the unchanged
128-mapping cap, and six pairs reaching the unchanged Strategy work limit.
Every pair and reason is retained in the machine report. No budget was increased
and no scope rule was relaxed to improve coverage.

The independent review found that **12 of the 13 scope-incompatible grep pairs**
involve a usage-helper versus no-excluded-helper difference. No excluded helper
does not imply absence of parsing/usage code: that code may remain in included
functions. These failures expose a scope-policy limitation, not missing source
implementations.

Alignment uncertainty is distinct from missingness. Available S interval widths
reach 0.00189633 for mkdir and 0.06682641 for grep. In particular, 22 of 24 available
grep S results are alignment-sensitive. An optimistic minimum would erase that
uncertainty.

## Prespecified threshold sensitivity

The grid is exactly **0.05, 0.10, ..., 0.95**, analyzed separately for A and S.
For complete matrices, SciPy average linkage consumes the condensed precomputed
distances; a merge is included when its height is **at most** the threshold.
Distances and heights are not rounded before clustering. Candidate IDs are sorted
before linkage, fixing indexing and tie handling under the recorded SciPy version.

At every grid point, the CSV records raw family count, effective family count
`exp(-sum p_k log p_k)`, dominant share `max p_k`, singleton rate (observations in
singleton families divided by n), candidate membership-neighborhood changes and
co-membership pair changes relative to the previous threshold, and silhouette
where defined. Silhouette uses the precomputed dissimilarities, assigning singleton
observations zero; it is undefined unless `2 <= families < n`. No silhouette-based
threshold selection is performed. The first threshold has no previous assignment.

| Threshold | mkdir A families | grep A families |
| --- | ---: | ---: |
| 0.05 | 6 | 10 |
| 0.10 | 5 | 10 |
| 0.15 | 4 | 9 |
| 0.20 | 2 | 8 |
| 0.25 | 2 | 6 |
| **0.30 reference** | **2** | **3** |
| Every grid point 0.35–0.95 | 1 | 1 |

At 0.30, mkdir's partition is **six implementations plus one singleton**.
It has effective count **1.50699**, dominant share **6/7**, singleton
rate **1/7** and silhouette **0.48284**. Grep has effective count **2.45456**,
dominant share **0.6**, singleton rate **0.1** and silhouette **0.20965**.
Grep changes 13 pair co-memberships and six candidates' family memberships between
0.25 and 0.30; mkdir's partition is unchanged across those adjacent grid points.

The mkdir two-family partition is stable on grid points 0.20–0.30; its exact
height interval is approximately **[0.17671253, 0.34181367)**. Grep's three-family
partition at 0.30 occupies only approximately **[0.29814588, 0.30127843)**: a narrow
interval that the coarse grid alone would obscure. Both populations have one
family from 0.35 onward on the grid, with final merge heights 0.34181367 and
0.34187441 respectively. The JSON records every merge height, linkage tree,
unchanged grid-partition range and continuous stability interval. Plateau width
does not establish substantive correctness of a family definition.

In particular, grep's three-family result exists only approximately over
**[0.29815, 0.30128)**. The continuous merge-height intervals above, rather than
grid-level counts alone, are necessary to interpret the 0.30 reference cut.

### Strategy endpoint scenarios

Every available off-diagonal S interval is preserved in separate lower/upper
matrices. **Both matrices remain incomplete in each population.** Accordingly,
both separately labeled endpoint clustering scenarios are `unavailable` at all
19 thresholds, with reason `incomplete_full_population_matrix`. These are explicit
rows in the CSV, not omitted populations. No complete-case subpopulation, imputed
matrix or optimistic scalar was substituted. Therefore alignment-dependent
*family* sensitivity cannot be estimated for these full populations in this run.

The reporting code and controlled tests support separately labeled lower- and
upper-endpoint scenarios when all pair intervals are available, and compare their
partitions without promoting either to a definitive family statistic. Even
agreement between those endpoints does **not** prove invariance over all possible
interior distance assignments or admissible alignments.

All matrix diagonals are zero **by candidate identity**, without self-comparison.
This convention does not assert that architecture-optimal alignments of equivalent
representations have a singleton Strategy range. Distinct observations, including
identical sources, still require an off-diagonal measurement.

## Construct validity and interpretation limits

Architecture measures **function decomposition and directed call/API
connectivity**, using defined-function nodes, named external API nodes and
distinct directed call edges. The independent review found that approximately
**61–86% of Architecture atoms are external API nodes or edges** in the audited
implementations. This is an atom-count composition, not a percentage attribution
of pairwise distance. With the existing unit-atom objective, API connectivity is
a substantial component; A must not be described as purely internal organization.

Strategy's declaration-order-based binding normalization preserves repeated
references under consistent renaming, but inserting an unused declaration can
shift subsequent declaration slots and increase S. The effect can extend beyond
the inserted declaration subtree. Renaming invariance does not imply invariance
under all behavior-preserving edits, and syntax similarity is not behavioral
equivalence.

Shared candidates make pairwise distances statistically dependent: the 66 pairs
are not 66 independent observations. The reported summaries are descriptive for
these success-conditioned, single-model/configuration populations. No causal or
inferential comparison across utilities is warranted. Structural diversity does
not establish exploit independence, independent vulnerabilities, or a security
benefit.

## Eventual frozen reporting protocol

Recommend a coverage-first protocol: freeze the population unit/manifest,
compiler/header profile, algorithm version, independent scope rules, resource
budgets, missingness rules, duplicate-observation policy, linkage/tie policy and
diagonal convention before examining outcomes. Report mean A and mean S intervals
as full-population summaries only when the corresponding pair measurements are
complete. Otherwise publish coverage, exact failure reasons and clearly labeled
available-pair descriptions. Retain Strategy ambiguity; require complete matrices
before publishing endpoint family scenarios and never call those definitive when
alignment uncertainty remains.

A primary threshold would require **independent calibration**: blinded expert
judgments or another independently specified structural-family criterion on held-out
implementations, with agreement and error assessed separately for Architecture
and Strategy. Prespecify how those judgments determine the cut and evaluate it on
different populations, including duplicate observations and scope-boundary cases.
Do not optimize the threshold on family count, silhouette, observed treatment
effects, or the most favorable coverage subset. This study's plateaus and the
legacy 0.30 value are descriptive references, not calibration evidence sufficient
to freeze a primary threshold. Existing production reporting remains unchanged.

## Artifacts and validation

* [Pairwise measurements and provenance](ordered_diversity_threshold_pairwise.json)
* [114-row threshold-sensitivity table](ordered_diversity_threshold_results.csv):
  2 populations × 3 labeled scenarios × 19 thresholds, including unavailable rows.
* [Matrices, threshold summaries, assignments and merge heights](ordered_diversity_threshold_results.json)
* Runner: `scripts/ordered_diversity_threshold_study.py`; reporting functions:
  `scripts/analysis/ordered_thresholds.py`; tests: `tests/test_ordered_thresholds.py`.

**138 tests passed**, preserving all 126 existing tests. New tests cover family-count
monotonicity, deterministic analysis, complete/incomplete matrices, bound rejection,
alignment intervals, candidate indexing, duplicate observations, identity checks,
manifest membership and cross-population rejection. Regenerating only the reports
from saved measurements in the same checkout produced byte-identical JSON and CSV
files; this is not a claim of byte identity across differently normalized
checkouts or fresh extraction/comparison runs. No candidate
was re-extracted or pair recomputed for that determinism check.

```sh
python3 -m scripts.ordered_diversity_threshold_study
# Reproduce reporting without another extraction/comparison run:
python3 -m scripts.ordered_diversity_threshold_study --summarize-only
python3 -m pytest -q tests/test_ordered_thresholds.py tests/test_ordered_clang_integration.py tests/test_ordered_clang_repro.py tests/test_ordered_clang_probe.py tests/test_ordered_callgraph.py tests/test_ordered_distances.py tests/test_ordered_phase25.py
```

All changes are new experimental reporting files. No established distance,
extractor, optimizer, production metric, frozen threshold, historical artifact,
lineage infrastructure or semantic depth backend was modified. No LLM experiments,
commits or pushes were performed.
