# Canonical v4 diversity methodology

This document defines schema-v4 analysis for repeated, baseline-backed software
generation experiments. `scripts/analyze_experiment.py` is the sole analysis
entry point. It evaluates functional reliability first, then two deliberately
separate forms of structural diversity among successful implementations. No
single composite score combines correctness, diversity, cost, validation, or
security diagnostics.

The methodology addresses a narrower question than semantic equivalence or
vulnerability independence: given candidates that satisfy the configured
validation contract, how reliably are they generated, and how varied are their
configured-source architectures and behavioral implementation strategies? Static
structure is evidence about implementation variation, not proof that failures
or exploits will not transfer.

## Evidence hierarchy

The reporting hierarchy prevents exploratory or easy-to-optimize measurements
from being presented as confirmatory outcomes.

### PRIMARY

1. **Functional reliability.** Overall, initial-public, and final-public
   success rates; repair recovery; and the unbiased pass@k estimator quantify
   whether generation produces valid final candidates. A run is successful
   only when OpenCode exits normally without a recorded permission rejection,
   the final public build/base/checkpoint validation succeeds, and the optional
   final extra test succeeds. Failed runs remain in reliability denominators.
2. **Architecture diversity.** Effective architecture-family count, dominant
   architecture-family share, and fixed-budget architecture NAUADC@K describe
   structural organization of the configured experiment source.
3. **Implementation-strategy diversity.** Effective strategy-family count,
   dominant strategy-family share, and fixed-budget strategy NAUADC@K describe
   changes inside behavioral functions while suppressing parser and usage
   organization by default.

Architecture and strategy are separate outcomes. A patch can reorganize option
parsing without changing core behavior, or change behavior while retaining the
same surrounding layout. Strategy families may capture control flow, data
structures, decomposition, call patterns, resource handling, or error handling;
they are not asserted to be classical algorithms.

### SUPPORTING

- Raw architecture- and strategy-family counts.
- Mean pairwise cosine distance in each structural representation.
- The complete exact DA@k curve for every available `k`.
- Exact source convergence: distinct SHA-256 count, exact-unique rate, modal
  exact-copy share, and membership of each hash group.
- Patch and cost descriptors: lines and files edited; functions edited,
  created, and deleted; normalized baseline edit magnitude; repair loops; LLM
  invocations; runtime; and available token usage.

These measurements explain the primary outcomes but do not replace them. Raw
family count is especially sensitive to sample size and small clusters. Patch
churn is descriptive effort, not structural diversity. The use of churn as a
software-change measure follows Nagappan and Ball (2005), while no defect claim
is inferred from churn in this study.

### ROBUSTNESS

- Vendi score on each structural feature matrix.
- Silhouette values where the number of families makes the statistic defined.
- Family statistics over a deterministic threshold-sensitivity grid.
- Adjusted Rand index (ARI) between every sensitivity partition and the fixed
  primary-threshold partition.

These assess whether the primary family result depends on one cut or one
summary. They are not used to select the primary threshold.

### CONSTRUCT VALIDATION

- Lexical normalized Levenshtein distance.
- Type-2-normalized token winnowing/Jaccard distance.
- Normalized APTED tree-edit distance.
- API-call-set Jaccard distance.
- Pairwise-complete Spearman correlations among those four distances and the
  architecture and strategy distances.
- Future blinded human validation of architecture and strategy judgments.

These independent representations test convergent and discriminant behavior.
They never determine family assignments.

### SECURITY/FUTURE RQ

Optional static profiles count unsafe calls, bounded-risk calls, heap
allocation/deallocation calls, fixed-size stack buffers, and indexing
operations. An optional Flawfinder cross-check reports tool availability and
hit counts. These profiles support future security research questions and
hypothesis formation only; they are neither a primary diversity representation
nor evidence of vulnerability or exploit non-transferability. Future work
should add dynamic testing, vulnerability-class labeling, and exploit-transfer
experiments before making security-effect claims.

## Experimental unit and populations

The implementation is the sampling and inference unit. One run contributes its
final candidate after the configured generation/repair process. Repeated source
or feature-identical candidates are retained as separate observations because
their frequency is part of the model's output distribution. Deduplicating first
would inflate effective diversity and erase convergence. Exact duplicates are
also reported separately by source-byte SHA-256.

Primary diversity uses **successful complete populations with no fallback**:

- The architecture population contains successful final candidates with a
  present source and complete baseline/candidate Clang, Tree-sitter C, and
  GumTree measurements.
- The strategy population contains successful final candidates with a present
  source and complete baseline/candidate Clang and Tree-sitter C measurements.

The populations can therefore differ. `architecture_population_n` and
`architecture_measurement_coverage` are reported separately from
`strategy_population_n` and `strategy_measurement_coverage`, where coverage is
the corresponding complete population divided by all successful runs. If a
representation is unavailable, its primary population shrinks, possibly to
zero; the analyzer does not substitute passing-but-incomplete, complete-but-
failed, or all-run results. Failed candidates are excluded from primary
diversity and exact convergence, but remain visible in reliability and per-run
records. All-run, complete-run, and passing-run partitions are diagnostic only.

## Functional reliability

Let `n` be all analyzed attempts and `c` the successful attempts. The reported
success proportion is `c/n`. Initial-public success is success after generation
before repair. Final-public success is success of the build/base/checkpoint
contract after the last generation or repair invocation. Repair recovery is the
number of initially failing runs that later reach public success divided by the
number initially failing. Overall success additionally requires the optional
extra test, when configured.

Following Chen et al. (2021), the unbiased pass@k estimator is

```text
pass@k = 1 - C(n - c, k) / C(n, k),    1 <= k <= n,
```

with value `1` when `n - c < k`. It estimates the probability that at least one
of `k` samples drawn without replacement is successful. Values are emitted only
for supported `k` among 1, 5, 10, 20, 50, and 100.

Reliability proportions receive 95% Wilson score intervals. This avoids the
poor boundary behavior of a symmetric normal interval and leaves an interval
undefined when its denominator is zero.

## Architecture representation

Architecture is a baseline-relative structural representation of the complete
configured primary source file. Other changed files remain visible through
descriptive patch metrics but do not enter the structural vector.
For each candidate, v4 constructs three non-duplicated feature blocks:

1. Clang AST count deltas for source-file and function contexts.
2. Tree-sitter C node-kind and call-count deltas for source-file and function
   contexts.
3. GumTree edit-action counts (`insert`, `delete`, `update`, and `move`
   variants), following Falleri et al. (2014).

Positive and negative baseline deltas are split into distinct non-negative
added and removed features. Newly created function names are canonicalized to
ordered parser-helper or behavior-helper placeholders, preventing arbitrary
names from creating distance. Each tool block is L2-normalized per candidate;
the blocks are concatenated and L2-normalized again. This gives each available
tool block controlled scale without counting the same syntax extractor twice.

Cosine distance is computed on the final vectors. Average-linkage
agglomerative clustering with a precomputed distance matrix and a fixed cut
defines architecture families. Patch size, test outcome, runtime, lexical
distance, validation distances, security profiles, and token use cannot affect
the assignment. GumTree's action profile is part of architecture, but its
single normalized edit-magnitude value is only a supporting patch descriptor.

## Implementation-strategy representation

Strategy uses baseline-relative Clang and Tree-sitter C deltas only from
behavioral functions. By default, `main` and function names matching parser,
argument, option, usage, help, flag, error-reporting, or diagnostic terms are
excluded. `--strategy-include-function` can force a known behavioral function
back into scope, and `--strategy-exclude-regex` records a different
pre-specified exclusion policy.

Created behavioral helper names are canonicalized, signed deltas are split,
tool blocks are normalized, and cosine distance plus average linkage are used
as for architecture. GumTree actions are omitted because they are whole-patch
rather than reliably function-scoped. This representation operationalizes
implementation decisions without claiming that every discovered family is a
named or classical algorithm. Lee et al. (2025) motivates measuring diversity
beyond correctness; v4 uses a broader, explicitly structural strategy
construct suitable for maintenance patches.

## Fixed clustering thresholds

The confirmatory architecture and strategy thresholds must be fixed before
condition labels are examined and reused across checkpoints, models, and
temperatures being compared. The CLI defaults architecture to `0.30` and
strategy to the architecture threshold; they can be pre-specified separately
with `--cluster-threshold` and `--strategy-threshold`. There is no
condition-specific optimization, silhouette maximization, or post-hoc choice of
the cut.

Threshold sensitivity is robustness analysis only. Unless `--thresholds`
provides an exact comma-separated positive grid, v4 evaluates positive members
of `t + {-0.10, -0.05, -0.025, 0, 0.025, 0.05, 0.10}` around each primary cut.
For every cut it reports raw and effective family counts, dominant share,
singleton rate, silhouette when `2 <= families < N`, and ARI against the
primary partition. Silhouette follows Rousseeuw (1987); chance-adjusted
partition comparison follows Hubert and Arabie (1985).

## Family summaries and exact discovery

For family sizes `n_1, ..., n_F` in a complete population of size `N`, define
`p_j = n_j/N`. Duplicates contribute individually to these shares.

- Raw family count: `F`.
- Effective family count: `exp(-sum_j p_j ln p_j)`, the Hill number of order 1.
- Dominant family share: `max_j p_j`.
- Mean pairwise distance: the arithmetic mean of the upper-triangle cosine
  distances between implementations.

For a size-`k` sample drawn uniformly without replacement, exact Diversity
Awareness is the expected number of represented families:

```text
DA@k = sum(j=1..F) [1 - C(N - n_j, k) / C(N, k)],    1 <= k <= N,
```

where `C(a, k)` is treated as zero when `a < k`. This is an exact combinatorial
expectation, not a Monte Carlo estimate. The full curve `DA@1, ..., DA@N` is
always written.

NAUADC is the width-normalized trapezoidal area over that discrete curve:

```text
NAUADC@K = trapezoid(DA@1, ..., DA@K) / (K - 1),    K > 1,
NAUADC@1 = DA@1.
```

Width normalization removes the mechanical area increase caused by a wider
horizontal range; it does not normalize the number of families. The full-curve
value with `K=N` is useful within a population, but cross-condition comparison
requires the same population definition and a common fixed `K`. Supply that
budget with `--diversity-k-max K`. If a population has `N < K`, fixed-budget
NAUADC@K is null rather than extrapolated; therefore choose a pre-specified `K`
supported by every compared architecture and strategy population.

## Exact convergence and supporting change measures

Exact convergence is calculated over successful candidates. Complete SHA-256
coverage is required; otherwise the rates are null and hash coverage plus the
reason are reported rather than silently shrinking the population. For
population size `N_s`, v4 reports:

```text
exact unique rate = distinct SHA-256 hashes / N_s
exact modal share = largest hash-group size / N_s
```

Hash groups retain all run identifiers. Exact equality is not a family
definition: non-identical implementations may share a structural family, while
the exact metrics reveal literal model repetition.

Lines added and deleted come from Git numstat plus textual untracked files;
lines edited are their sum. Files changed, function edits/creations/deletions,
repair counts, invocations, runtime, and token extraction remain descriptive.
The normalized edit magnitude is parsed GumTree action count divided by the
larger baseline/candidate Tree-sitter node count. These variables may explain
cost or patch scope, but they are excluded from strategy assignments and are
not alternative correctness measures.

## Robustness and uncertainty

### Vendi score

For normalized structural feature matrix `X`, v4 forms the Gram matrix
`G = X X^T`, symmetrizes it numerically, normalizes its non-negative
eigenvalues to sum to one, and returns the exponential Shannon entropy of that
spectrum. This is the Vendi score of Friedman and Dieng (2023). Because `G` is a
Gram matrix it is positive semidefinite by construction. Tiny negative
eigenvalues within numerical tolerance are clipped to zero; a materially
negative eigenvalue makes the diagnostic unavailable rather than silently
repairing the matrix. Vendi is clustering-free robustness evidence, not a
primary family result.

### Intervals

Primary architecture and strategy populations receive deterministic,
implementation-level percentile bootstrap intervals. Each replicate samples
`N` implementation rows with replacement, then reconstructs the feature
matrix subset, cosine distances, clustering, family statistics, mean pairwise
distance, supported fixed-budget NAUADC, and Vendi score. This preserves the
implementation as the inference unit rather than incorrectly resampling
dependent pairs. Defaults are 1,000 repetitions and seed `20260723`; strategy
uses the next seed so its stream is distinct. Configure these with
`--bootstrap-repetitions` and `--bootstrap-seed`. Reported bounds are the 2.5th
and 97.5th percentiles. Functional proportions use the deterministic 95%
Wilson intervals described above.

## Construct validation

Construct-validation distances are computed only as optional pairwise
diagnostics among successful candidates with source files:

- **Lexical normalized Levenshtein distance:** comments are removed through the
  C parse tree, whitespace is collapsed, and edit distance is normalized.
- **Type-2 token winnowing/Jaccard distance:** leaf identifiers and number,
  string, and character literals become class placeholders; deterministic
  token k-grams (`k <= 5`) are winnowed with window size 4; distance is one
  minus fingerprint-set Jaccard similarity. This controls common Type-2 clone
  transformations in the taxonomy reviewed by Roy, Cordy, and Koschke (2009).
- **APTED distance:** ordered tree-edit distance over named, non-comment
  Tree-sitter C nodes, normalized by the larger tree size, following Pawlik and
  Augsten (2016). Pairs above 20,000 named nodes return missing rather than
  risking unbounded computation.
- **API-call-set Jaccard distance:** one minus Jaccard similarity over directly
  named called functions. This is interpretable but syntactic: wrappers,
  aliases, indirect calls, and equivalent APIs can obscure semantic agreement.

For every pair of representations, Spearman correlation uses pairwise-complete
rows: a pair contributes only when both distances are finite. The output records
`supporting_pairs`, and a correlation is null when support or variation is
insufficient. Pairwise completion avoids discarding valid measurements from
other representations, but different cells can have different support and must
not be compared as though based on one common sample.

Future human validation should sample implementation pairs and family medoids,
blind reviewers to model, temperature, checkpoint condition, and machine family
labels, and use separate codebooks for whole-patch architecture and behavioral
strategy. At least two reviewers should label independently; report raw
agreement and Cohen's kappa (Cohen, 1960), adjudicate only after independent
coding, and compare the adjudicated partition with machine families using ARI.
This is required before treating machine families as human-validated semantic
categories.

## Output layout (schema v4)

The default output is `<experiment>/analysis/`:

```text
analysis/
├── summary.json
├── per_run_metrics.csv
├── runs.csv                              # Compatibility alias of per-run data
├── paper_metrics.csv
├── paper_descriptive_metrics.csv
├── paper_metrics_row.json
├── paper_metrics_schema.json
├── diversity/
│   ├── architecture_clusters.csv
│   ├── strategy_clusters.csv
│   ├── architecture_da_curve.csv
│   ├── strategy_da_curve.csv
│   └── exact_repetition.csv
└── diagnostics/
    ├── architecture_threshold_sensitivity.csv
    ├── strategy_threshold_sensitivity.csv
    └── uncertainty.csv
```

`--diagnostic-output` additionally writes baseline and per-run parser/tool
artifacts, normalized feature matrices and schemas, assignments for diagnostic
populations, medoid tables, dendrograms, `pairwise_validation.csv`, and
`cross_representation_correlation.csv` beneath `diagnostics/`.
`--security-diagnostics` writes `security/security_profiles.csv` and
`security/flawfinder.csv`; absence of the optional executable is recorded, not
treated as a candidate failure. Missing JSON values are `null` and missing CSV
values are blank.

The standardized **primary CSV schema** is:

```text
Issue, Checkpoint, Model, Temp, N Runs, Successful Runs,
Overall Success Rate, Initial Public Success Rate, Final Public Success Rate,
Repair Recovery Rate, Pass@1, Pass@5, Pass@10,
Architecture Population N, Effective Architecture Families,
Dominant Architecture Family Share, Architecture NAUADC@K,
Strategy Population N, Effective Strategy Families,
Dominant Strategy Family Share, Strategy NAUADC@K,
Exact Unique Rate, Exact Modal Share, Diversity K Max
```

The file is the compact publication-facing schema; the evidence hierarchy above
still classifies its exact-convergence columns as supporting rather than primary
outcomes.

The standardized **descriptive CSV schema** is:

```text
Issue, Checkpoint, Model, Temp,
Raw Architecture Families, Mean Pairwise Architecture Distance,
Architecture Vendi Score, Raw Strategy Families,
Mean Pairwise Strategy Distance, Strategy Vendi Score,
Mean Repair Loops, Median Repair Loops, Max Repair Loops,
Mean LLM Invocations, Mean Repair LLM Runtime (s),
Mean Total Runtime (s), Median Total Runtime (s),
Mean Lines Edited, Mean Files Edited, Mean Functions Edited,
Mean Functions Created, Mean Functions Deleted,
Mean GumTree/AST Edit Magnitude
```

## Reproducible usage and optional flags

For Git experiments, the analyzer discovers the target from
`experiment.json["source_path"]`, reads `baseline/<source_path>`, and matches
`attempt-*/candidate/<source_path>`. Do not construct utility-specific source
globs:

```bash
python3 scripts/analyze_experiment.py \
    --experiment runs/experiments/<model>/<checkpoint>/temp-<temperature> \
    --cluster-threshold 0.30 \
    --strategy-threshold 0.30 \
    --diversity-k-max <common-K> \
    --bootstrap-repetitions 1000 \
    --bootstrap-seed 20260723 \
    --clean-output
```

Optional diagnostics and controlled overrides are:

- `--diagnostic-output`: detailed feature, clustering, plot, and construct-
  validation artifacts.
- `--security-diagnostics`: exploratory security profiles and the optional
  static-tool cross-check.
- `--thresholds`: exact sensitivity cuts; never changes the primary cut.
- `--strategy-exclude-regex` and repeatable `--strategy-include-function`:
  pre-specified strategy scope adjustments.
- Repeatable `--clang-extra-arg`: compilation-context arguments for parsing.
- `--paper-issue-label` and `--paper-checkpoint-label`: reporting labels only.
- `--output-dir`: alternate output location; default is
  `<experiment>/analysis`.
- `--clean-output`: removes only the selected analysis output before rewriting
  it.

For a no-Git `run.json` experiment, select one `temp-*` condition and pass the
workspace-relative source path when legacy metadata does not contain it:

```bash
python3 scripts/analyze_experiment.py \
    --experiment runs/sandboxed/<utility>/<milestone>/temp-<temperature> \
    --source-path src/<utility>/<source>.c \
    --clean-output
```

The adapter maps each final sandbox workspace and pass/fail record into the
same attempt, population, feature, clustering, and output code used for Git
experiments. A matching recorded seed is the baseline for seeded checkpoints;
an unseeded from-scratch condition has an empty C translation-unit baseline.
`--baseline-source` can override this explicitly. A mixed-temperature sandbox
root is rejected rather than pooled into one reported condition.

## References

- Chen, M., et al. (2021). “Evaluating Large Language Models Trained on Code.”
  arXiv:2107.03374. [https://doi.org/10.48550/arXiv.2107.03374](https://doi.org/10.48550/arXiv.2107.03374).
- Cohen, J. (1960). “A Coefficient of Agreement for Nominal Scales.”
  *Educational and Psychological Measurement*, 20(1), 37-46.
  [https://doi.org/10.1177/001316446002000104](https://doi.org/10.1177/001316446002000104).
- Falleri, J.-R., Morandat, F., Blanc, X., Martinez, M., and Monperrus, M.
  (2014). “Fine-grained and Accurate Source Code Differencing.” *Proceedings of
  ASE 2014*, 313-324.
  [https://doi.org/10.1145/2642937.2642982](https://doi.org/10.1145/2642937.2642982).
- Friedman, D., and Dieng, A. B. (2023). “The Vendi Score: A Diversity
  Evaluation Metric for Machine Learning.” *Transactions on Machine Learning
  Research*. [https://openreview.net/forum?id=g97OHbQyk1](https://openreview.net/forum?id=g97OHbQyk1).
- Hubert, L., and Arabie, P. (1985). “Comparing Partitions.” *Journal of
  Classification*, 2, 193-218.
  [https://doi.org/10.1007/BF01908075](https://doi.org/10.1007/BF01908075).
- Lee, S., Chon, H., Jang, J., Lee, D., and Yu, H. (2025). “How Diversely Can
  Language Models Solve Problems? Exploring the Algorithmic Diversity of
  Model-Generated Code.” *Findings of EMNLP 2025*, 152-167.
  [https://doi.org/10.18653/v1/2025.findings-emnlp.10](https://doi.org/10.18653/v1/2025.findings-emnlp.10).
- Nagappan, N., and Ball, T. (2005). “Use of Relative Code Churn Measures to
  Predict System Defect Density.” *Proceedings of ICSE 2005*, 284-292.
  [https://doi.org/10.1145/1062455.1062514](https://doi.org/10.1145/1062455.1062514).
- Pawlik, M., and Augsten, N. (2016). “Tree Edit Distance: Robust and
  Memory-efficient.” *Information Systems*, 56, 157-173.
  [https://doi.org/10.1016/j.is.2015.08.004](https://doi.org/10.1016/j.is.2015.08.004).
- Rousseeuw, P. J. (1987). “Silhouettes: A Graphical Aid to the Interpretation
  and Validation of Cluster Analysis.” *Journal of Computational and Applied
  Mathematics*, 20, 53-65.
  [https://doi.org/10.1016/0377-0427(87)90125-7](https://doi.org/10.1016/0377-0427(87)90125-7).
- Roy, C. K., Cordy, J. R., and Koschke, R. (2009). “Comparison and Evaluation
  of Code Clone Detection Techniques and Tools: A Qualitative Approach.”
  *Science of Computer Programming*, 74(7), 470-495.
  [https://doi.org/10.1016/j.scico.2009.02.007](https://doi.org/10.1016/j.scico.2009.02.007).
