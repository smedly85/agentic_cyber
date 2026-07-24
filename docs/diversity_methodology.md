# Canonical v4.1.2 diversity methodology

This document defines schema-v5 analysis for repeated, baseline-backed software
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

1. **Functional reliability.** Infrastructure attrition, end-to-end and
   conditional-agent success, initial-public and final-public success, repair
   recovery, and the unbiased pass@k estimator quantify the workflow. An
   attempt is successful only when no agent-execution failure is recorded,
   the final public build/base/checkpoint validation succeeds, and the optional
   final extra test succeeds. Infrastructure failures remain in end-to-end
   counts but are separated from valid generated-agent trials.
2. **Architecture diversity.** Effective architecture-family count, dominant
   architecture-family share, and fixed-budget architecture normalized
   family-discovery AUC@K describe
   structural organization of the configured experiment source.
3. **Implementation-strategy diversity.** Effective strategy-family count,
   dominant strategy-family share, and fixed-budget strategy normalized
   family-discovery AUC@K describe
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
- The complete exact DF@K curve for every available `K`.
- Exact source convergence: distinct SHA-256 count, exact-unique rate, modal
  exact-copy share, and membership of each hash group.
- Patch and cost descriptors: lines and files edited; functions edited,
  created, and deleted; normalized GumTree edit-action magnitude; repair loops; LLM
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
- Fixed-threshold representation ablations for individual and combined Clang,
  Tree-sitter, and GumTree blocks, including strategy without `main`.

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

One complete generation/repair trajectory is one independent attempt and the
implementation is the sampling and inference unit. Only high-confidence
pre-invocation worktree/setup failure is infrastructure attrition. Once an
OpenCode invocation is attempted, the attempt is a valid agent trial even if it
times out, encounters a permission rejection, or exits nonzero. One valid trial
contributes its final candidate after the configured process. Repeated source
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
failed, or all-run results. Failed generated candidates and infrastructure
failures are excluded from primary diversity and exact convergence, but remain
visible in reliability and per-attempt records. Repeated identical successful
candidates remain separate observations. All-run, complete-run, and passing-run
partitions are diagnostic only.

## Functional reliability

Let `N_attempts` include every analyzed independent attempt,
`N_infrastructure_failures` count infrastructure attrition, and
`N_valid_agent_trials = N_attempts - N_infrastructure_failures`. The analyzer
reports infrastructure attrition and end-to-end success over all attempts, and
conditional agent success over valid trials. Initial-public and final-public
success also use valid trials. Repair Recovery Rate asks: among initial generated
implementations that completed generation but failed public validation and were
therefore eligible for feedback-based repair, what fraction were recovered?
Its denominator excludes setup attrition and initial agent-execution failures.
Build, public-test, and hidden/extra-evaluator failures after a completed initial
invocation are candidate/workflow failures; public build/base/checkpoint failure
is repair eligible. Overall success additionally requires the optional extra
test, when configured.

The failure taxonomy is deliberately conservative:

- **Infrastructure attrition:** experiment worktree/setup failed before a
  usable agent invocation was attempted.
- **Agent-execution failure:** timeout, configured-policy permission rejection,
  or another nonzero attempted OpenCode invocation. These are valid failed
  generated-agent trials.
- **Candidate/workflow failure:** build, public-test, or hidden/extra-evaluator
  failure after generation.

The analyzer does not infer provider or network outages from arbitrary error
text. Agent-execution failures remain in conditional-agent, initial/final
public-success, and Pass@k denominators. Exit 124 is classified as an agent
timeout and contributes a failed generated sample to those reliability
outcomes, but it is not repair eligible because no completed initial
implementation was produced. Initial permission rejection and nonzero OpenCode
execution failure are excluded from the repair-efficacy denominator for the
same reason. Infrastructure attrition is excluded from generated-sample
denominators, while end-to-end success still uses every analyzed attempt.

Following Chen et al. (2021), Pass@k uses `n = N_valid_agent_trials` and `c`
equal to successful valid trials:

```text
pass@k = 1 - C(n - c, k) / C(n, k),    1 <= k <= n,
```

with value `1` when `n - c < k`. It estimates the probability that at least one
of `k` generated candidate samples drawn without replacement is successful.
Infrastructure failures do not count as failed generated samples, while
end-to-end reporting still exposes them. Values are emitted only
for supported `k` among 1, 5, 10, 20, 50, and 100.

Reliability proportions receive 95% Wilson score intervals (Wilson, 1927).
This avoids the poor boundary behavior of a symmetric normal interval and
leaves an interval undefined when its denominator is zero.

## Architecture representation

Here, architecture narrowly means baseline-relative **configured-source
structural organization** of the complete primary C source file. It does not
measure repository-wide, module, or system architecture. Other changed files
remain visible through descriptive patch metrics but do not enter the
structural vector.
For each candidate, v4.1.2 constructs three non-duplicated feature blocks:

1. Clang AST count deltas for source-file and function contexts.
2. Tree-sitter C node-kind and call-count deltas for source-file and function
   contexts.
3. GumTree edit-action counts (`insert`, `delete`, `update`, and `move`
   variants), following Falleri et al. (2014).

Positive and negative baseline deltas are split into distinct non-negative
added and removed features. Newly created function names are canonicalized to
ordered parser-helper or behavior-helper placeholders, preventing arbitrary
names from creating distance. The known C entry point `main` always retains the
literal identity `main` in both architecture and strategy representations,
including an empty-baseline new-source task; only arbitrary helper names are
canonicalized. Each tool block is L2-normalized per candidate;
the blocks are concatenated and L2-normalized again. This gives each available
tool block controlled scale without counting the same syntax extractor twice.

Cosine distance is computed on the final vectors. Average-linkage
agglomerative clustering with a precomputed distance matrix and a fixed cut
defines architecture families. Patch size, test outcome, runtime, lexical
distance, validation distances, security profiles, and token use cannot affect
the assignment. GumTree's action profile is part of architecture, but its
single normalized edit-action magnitude is only a supporting patch descriptor.

## Implementation-strategy representation

Strategy uses baseline-relative Clang and Tree-sitter C deltas only from
behavioral functions. `main` is included by default because generated
maintenance code is not guaranteed to decompose behavior into helper functions.
Function names matching parser, argument, option, usage, help, flag,
error-reporting, or diagnostic terms remain excluded by default.
`--strategy-include-function` can force a known behavioral function back into
scope, and `--strategy-exclude-regex` records a different pre-specified policy.
Helper naming is an operational scope rule, not a reliable semantic classifier.
Excluding `main` defines only the `strategy_without_main` robustness ablation;
it is not a second primary strategy definition.

Created behavioral helper names are canonicalized, signed deltas are split,
tool blocks are normalized, and cosine distance plus average linkage are used
as for architecture. GumTree actions are omitted because they are whole-patch
rather than reliably function-scoped. This representation operationalizes
implementation decisions without claiming that every discovered family is a
named or classical algorithm. Lee et al. (2025) motivates measuring diversity
beyond correctness; v4.1.2 uses a broader, explicitly structural strategy
construct suitable for maintenance patches.

## Fixed clustering thresholds

The clustering thresholds are calibrated using pilot experiments and then
frozen before the confirmatory cross-model analysis. They are reused across the
checkpoints, models, and temperatures in that comparison. For Git experiments,
each setting resolves by explicit CLI value, then the value recorded in
`experiment.json`, then analyzer default. Architecture finally defaults to
`0.30`; strategy finally inherits the resolved architecture threshold; K
finally remains unset. Thus a manual analyzer invocation without threshold/K
arguments reproduces the recorded runner configuration, while explicit
`--cluster-threshold`, `--strategy-threshold`, or `--diversity-k-max` values
override it. These defaults/calibration values are not a claim of
preregistration before all pilot inspection. There is no condition-specific
optimization, silhouette maximization, or post-hoc replacement of the
configured cut. `summary.json` records every resolved value and whether it came
from CLI, experiment metadata, an analyzer default, or the architecture cut.
CLI overrides remain valid for exploratory or sensitivity analysis. A Git
paper row is confirmatory only when its thresholds, K, strategy scope, and
Clang arguments match the configuration recorded with that experiment; an
override that changes those settings cannot enter or anchor the repository
confirmatory aggregate.

Threshold sensitivity is robustness analysis only. Unless `--thresholds`
provides an exact comma-separated positive grid, v4.1.2 evaluates positive members
of `t + {-0.10, -0.05, -0.025, 0, 0.025, 0.05, 0.10}` around each primary cut.
For every cut it reports raw and effective family counts, dominant share,
singleton rate, silhouette when `2 <= families < N`, and ARI against the
primary partition. Silhouette follows Rousseeuw (1987); chance-adjusted
partition comparison follows Hubert and Arabie (1985).

## Family summaries and exact discovery

For family sizes `n_1, ..., n_F` in a complete population of size `N`, define
`p_j = n_j/N`. Duplicates contribute individually to these shares.

- Raw family count: `F`.
- Effective family count: `exp(-sum_j p_j ln p_j)`, the Hill number of order 1
  (Hill, 1973; Jost, 2006).
- Dominant family share: `max_j p_j`.
- Mean pairwise distance: the arithmetic mean of the upper-triangle cosine
  distances between implementations.

For a size-`K` sample drawn uniformly without replacement, **Distinct Families
at K (DF@K)** is the expected number of represented families:

```text
DF@K = sum(j=1..F) [1 - C(N - n_j, K) / C(N, K)],    1 <= K <= N,
```

where `C(a, K)` is treated as zero when `a < K`. This is an exact combinatorial
expectation, not a Monte Carlo estimate. It adapts Lee et al.'s (2025) DA@K
estimator: Lee et al. apply the formula to distinct algorithm clusters, whereas
this study applies it to source-structural and implementation-strategy families.
Because these families are not claimed to be classical algorithms, the adapted
quantity is named DF@K. The full curve `DF@1, ..., DF@N` is always written.

Normalized Family-Discovery AUC@K is the width-normalized trapezoidal area over
that discrete curve:

```text
Family-Discovery AUC@K = trapezoid(DF@1, ..., DF@K) / (K - 1),    K > 1,
Family-Discovery AUC@1 = DF@1.
```

Width normalization removes the mechanical area increase caused by a wider
horizontal range; it does not normalize the number of families. The full-curve
value with `K=N` is useful within a population, but cross-condition comparison
requires the same population definition and a common fixed `K`. Supply that
budget with `--diversity-k-max K`. If a population has `N < K`, fixed-budget
family-discovery AUC@K is null rather than extrapolated; therefore choose a
fixed `K` supported by every compared architecture and strategy population.

## Exact convergence and supporting change measures

Exact convergence is calculated over successful candidates. Complete SHA-256
coverage is required; otherwise the rates are null and hash coverage plus the
reason are reported rather than silently shrinking the population. For
population size `N_s`, v4.1.2 reports:

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
The normalized GumTree edit-action magnitude is parsed GumTree action count
divided by the larger baseline/candidate Tree-sitter node count. It is not an
APTED tree edit distance; APTED remains separate construct validation. These
variables may explain cost or patch scope, but they are excluded from strategy
assignments and are not alternative correctness measures.

## Robustness and uncertainty

### Vendi score

For normalized structural feature matrix `X`, v4.1.2 augments only the Vendi
representation. A nonzero row becomes `[x, 0]`, while a zero row becomes a new
unit basis vector `[0, ..., 0, 1]`. Thus zero-zero similarity is one,
zero-nonzero similarity is zero, every diagonal is one, nonzero similarities
are unchanged, and the Gram matrix remains positive semidefinite by
construction. The analyzer forms `G = X_vendi X_vendi^T`, symmetrizes it
numerically, and normalizes its non-negative
eigenvalues to sum to one, and returns the exponential Shannon entropy of that
spectrum. This is the Vendi score of Friedman and Dieng (2023). Because `G` is a
Gram matrix it is positive semidefinite by construction. Tiny negative
eigenvalues within numerical tolerance are clipped to zero; a materially
negative eigenvalue makes the diagnostic unavailable rather than silently
repairing the matrix. Vendi is clustering-free robustness evidence, not a
primary family result.

### Representation ablation

Under `--diagnostic-output`, architecture is recomputed with Clang only,
Tree-sitter only, GumTree only, Clang plus Tree-sitter, and the primary
three-block representation. Strategy is recomputed with Clang only, Tree-sitter
only, the primary two-block representation, and the same representation with
`main` excluded. Every comparison uses the exact same successful-complete
population/order and the corresponding fixed primary threshold. Raw and
effective family counts, dominant share, mean pairwise distance, and ARI versus
the primary partition are reported in `diagnostics/representation_ablation.csv`.
No ablation retunes a threshold. Silhouette, ARI, Vendi, and representation
ablation are robustness checks, not threshold selectors.

### Intervals

Primary architecture and strategy populations receive deterministic,
implementation-level percentile bootstrap intervals following the resampling
principle of Efron (1979). Each replicate samples
`N` implementation rows with replacement, then reconstructs the feature
matrix subset, cosine distances, clustering, family statistics, mean pairwise
distance, supported fixed-budget family-discovery AUC, and Vendi score. This
preserves the implementation as the inference unit rather than incorrectly
resampling dependent pairs. Defaults are 1,000 repetitions and seed `20260723`; strategy
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
  minus fingerprint-set Jaccard similarity, adapting document fingerprinting
  from Schleimer, Wilkerson, and Aiken (2003). This controls common Type-2 clone
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
labels, and use separate codebooks for configured-source structural organization
and implementation strategy. At least two reviewers should label independently;
report raw agreement and Cohen's kappa (Cohen, 1960), adjudicate only after independent
coding, and compare the adjudicated partition with machine families using ARI.
This is required before treating machine families as human-validated semantic
categories.

## Output layout (schema v5)

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
│   ├── architecture_family_discovery_curve.csv
│   ├── strategy_family_discovery_curve.csv
│   └── exact_repetition.csv
└── diagnostics/
    ├── architecture_threshold_sensitivity.csv
    ├── strategy_threshold_sensitivity.csv
    ├── representation_ablation.csv          # With --diagnostic-output
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
Issue, Checkpoint, Model, Temp, N Attempts, Valid Agent Trials,
Infrastructure Failures, Infrastructure Attrition Rate, Successful Runs,
End-to-End Success Rate, Conditional Agent Success Rate,
Initial Public Success Rate, Final Public Success Rate,
Repair Recovery Rate, Pass@1, Pass@5, Pass@10,
Architecture Population N, Effective Architecture Families,
Dominant Architecture Family Share, Architecture Family-Discovery AUC@K,
Strategy Population N, Effective Strategy Families,
Dominant Strategy Family Share, Strategy Family-Discovery AUC@K,
Diversity K Max
```

The file is the compact publication-facing primary schema. Unsupported Pass@k
values remain blank rather than being extrapolated.

The standardized **descriptive CSV schema** is:

```text
Issue, Checkpoint, Model, Temp,
Raw Architecture Families, Mean Pairwise Architecture Distance,
Architecture Vendi Score, Raw Strategy Families,
Mean Pairwise Strategy Distance, Strategy Vendi Score,
Exact Unique Rate, Exact Modal Share,
Mean Repair Loops, Median Repair Loops, Max Repair Loops,
Mean LLM Invocations, Mean Repair LLM Runtime (s),
Mean Total Runtime (s), Median Total Runtime (s),
Mean Lines Edited, Mean Files Edited, Mean Functions Edited,
Mean Functions Created, Mean Functions Deleted,
Mean Normalized GumTree Edit-Action Magnitude
```

`paper_metrics_row.json` records `_schema_version`, `_analyzer_version`, and a
readable `_analysis_signature`. The signature contains architecture and strategy
thresholds, fixed K, the strategy exclusion regex, sorted forced includes,
whether `main` is included, and Clang extra arguments in supplied order. Because
argument order is preserved and treated as significant, differently ordered
Clang arguments are different signatures. Repository-level aggregation includes
only current schema-v5/analyzer-v4.1.2 complete rows that individually match
their owning Git experiment's recorded configuration and share the first such
row's exact signature. Older/incompatible, exploratory/nonconfirmatory, and
incompatible-confirmatory-configuration rows are counted separately.
`runs/experiments/paper_metrics_metadata.json` records the accepted signature
and all four row counts. Historical analyses must be rerun with analyzer v4.1.2
before inclusion; historical analysis directories are not rewritten
automatically.

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

The Git runner accepts explicit `--source-mode existing|new`. Existing mode
requires the source in the selected baseline commit and snapshots it; new mode
requires the source to be absent, records an empty baseline snapshot, and leaves
creation to the agent. This is the intended confirmatory controller for both
existing-source sort and new-source mkdir comparisons. Its automatic analyzer
options are `--analysis-architecture-threshold`,
`--analysis-strategy-threshold`, and optional `--analysis-diversity-k-max`.
Legacy `--analysis-threshold` sets both thresholds unless a corresponding
specific option overrides it; otherwise strategy defaults to architecture. An
unset K stays unset.

Manual reanalysis uses CLI > recorded experiment metadata > analyzer default
for architecture threshold, strategy threshold, and K. Omitting those CLI
arguments reproduces the stored Git experiment configuration. Exploratory CLI
overrides are allowed, but rows that change the recorded primary settings are
excluded from repository-level confirmatory aggregation. Among individually
confirmatory rows, mixed thresholds, K, strategy scope, or Clang arguments are
rejected rather than silently pooled.

Optional diagnostics and controlled overrides are:

- `--diagnostic-output`: detailed feature, clustering, plot, and construct-
  validation artifacts.
- `--security-diagnostics`: exploratory security profiles and the optional
  static-tool cross-check.
- `--thresholds`: exact sensitivity cuts; never changes the primary cut.
- `--strategy-exclude-regex` and repeatable `--strategy-include-function`:
  pre-specified strategy scope adjustments.
- Repeatable `--clang-extra-arg`: compilation-context arguments for parsing;
  supplied order is preserved in the reproducibility signature.
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

The no-Git sandbox runner is retained for exploratory/pilot and historical
analysis. Results generated under materially different agent-feedback or
controller protocols must not be pooled as one experimental condition. Sandbox
analyses are not automatically included in the repository-level confirmatory
paper aggregate. Security diagnostics remain exploratory/future-RQ outputs and
never enter either clustering representation.

## References

These references support the underlying statistical and software-analysis
concepts. They do not validate this study's exact custom architecture or
strategy representations.

- Chen, M., et al. (2021). “Evaluating Large Language Models Trained on Code.”
  arXiv:2107.03374. [https://doi.org/10.48550/arXiv.2107.03374](https://doi.org/10.48550/arXiv.2107.03374).
- Cohen, J. (1960). “A Coefficient of Agreement for Nominal Scales.”
  *Educational and Psychological Measurement*, 20(1), 37-46.
  [https://doi.org/10.1177/001316446002000104](https://doi.org/10.1177/001316446002000104).
- Efron, B. (1979). “Bootstrap Methods: Another Look at the Jackknife.” *The
  Annals of Statistics*, 7(1), 1-26.
  [https://doi.org/10.1214/aos/1176344552](https://doi.org/10.1214/aos/1176344552).
- Falleri, J.-R., Morandat, F., Blanc, X., Martinez, M., and Monperrus, M.
  (2014). “Fine-grained and Accurate Source Code Differencing.” *Proceedings of
  ASE 2014*, 313-324.
  [https://doi.org/10.1145/2642937.2642982](https://doi.org/10.1145/2642937.2642982).
- Friedman, D., and Dieng, A. B. (2023). “The Vendi Score: A Diversity
  Evaluation Metric for Machine Learning.” *Transactions on Machine Learning
  Research*. [https://openreview.net/forum?id=g97OHbQyk1](https://openreview.net/forum?id=g97OHbQyk1).
- Hill, M. O. (1973). “Diversity and Evenness: A Unifying Notation and Its
  Consequences.” *Ecology*, 54(2), 427-432.
  [https://doi.org/10.2307/1934352](https://doi.org/10.2307/1934352).
- Hubert, L., and Arabie, P. (1985). “Comparing Partitions.” *Journal of
  Classification*, 2, 193-218.
  [https://doi.org/10.1007/BF01908075](https://doi.org/10.1007/BF01908075).
- Jost, L. (2006). “Entropy and Diversity.” *Oikos*, 113(2), 363-375.
  [https://doi.org/10.1111/j.2006.0030-1299.14714.x](https://doi.org/10.1111/j.2006.0030-1299.14714.x).
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
- Schleimer, S., Wilkerson, D. S., and Aiken, A. (2003). “Winnowing: Local
  Algorithms for Document Fingerprinting.” *Proceedings of SIGMOD 2003*,
  76-85. [https://doi.org/10.1145/872757.872770](https://doi.org/10.1145/872757.872770).
- Wilson, E. B. (1927). “Probable Inference, the Law of Succession, and
  Statistical Inference.” *Journal of the American Statistical Association*,
  22(158), 209-212.
  [https://doi.org/10.1080/01621459.1927.10502953](https://doi.org/10.1080/01621459.1927.10502953).
