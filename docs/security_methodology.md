# RQ3 security methodology

## Dynamic post-validation evaluator

The repository now also records a dynamic security dimension in each new
attempt's `security_results.json`. This stage runs after visible repair and the
hidden functional oracle have finalized `overall_success`. ASan/UBSan-backed
utility-specific adversarial execution checks memory/undefined behavior,
signals, bounded termination and resource behavior, and filesystem containment
inside disposable fixtures. Normalized signatures and complete triggering
artifacts support later failure-set-diversity analysis.

Dynamic findings are confirmed runtime observations, while the static analysis
described below remains a separate source-level measurement. Attacker-reachable
functions and sensitive calls are descriptive exposure data, not findings on
their own. An evaluator infrastructure failure is represented by
`security_evaluation_completed=false` and cannot be counted as either a clean
candidate or a candidate vulnerability. Conversely, `security_clean=true`
means only "no security finding was discovered within the bounded evaluation";
it is not a claim that the implementation is secure.

The seeded programs in `security/calibration/fixtures/` exist solely to validate
the evaluator. They never enter lineage generation, prompts, repair, functional
corpora, or formal candidate populations.

## Structural reachability study

The repository also records a deliberately simple, descriptive call-graph
measurement. For a function `f`, `d_call(f)` is the minimum number of statically
resolved direct-call edges from `main` to `f`. Thus `main` has depth zero, its
direct callees have depth one, and breadth-first traversal assigns the shortest
depth when several paths or cycles exist. A function without a resolved path
from `main` is recorded as unreachable with a null depth.

This is **call-graph reachability depth**, not literal AST nesting depth. The
initial hypothesis is intentionally narrow: shallow call-graph depth may be a
useful heuristic for prioritizing code to diversify. Shallow does not mean
vulnerable, and the resulting order is called a structural exposure or
diversification-priority ranking—not a vulnerability ranking. No dataflow,
control-flow depth, sensitive-call count, or vulnerability likelihood is folded
into the rank.

`security/common/callgraph.py` extends the same Tree-sitter characterization
used by the dynamic evaluator and retains its regex fallback. It records direct
callers/callees, shortest depth, unreachable functions, per-depth groups,
source locations, physical function LOC, and Tree-sitter node counts where
available. `SHALLOW`, seeded `RANDOM`, and `DEEP` helpers select equal numbers
of reachable functions for either an absolute or percentage budget. The
selection helpers do not regenerate or otherwise change code.

The retrospective study has a separate, initially empty dataset under
`security/historical/`. Its records must be manually curated from authoritative
GNU Coreutils or GNU grep sources. Exact vulnerable-function names are mapped
against a checked-out vulnerable source tree; missing and ambiguous names are
reported rather than guessed. Absolute depth remains primary. When maximum
reachable depth is greater than zero, the supporting normalized value is:

```text
normalized_depth = vulnerable_function_depth / maximum_reachable_depth
```

For selection policy `S`, Historical Vulnerability Coverage at a function or
percentage budget is the fraction of valid historical function mappings whose
mapped functions appear in the selected set. This measures how well a
structural selection policy would have covered historically vulnerable
function locations. It does not measure future vulnerability prevention.
Repeated recorded seeds support RANDOM means and confidence intervals.
Records that have not been source-and-patch verified remain visible in mapping
output but are excluded from HVC denominators and depth summaries.

The two security-oriented studies remain independent:

```text
historical source + curated mapping -> call depth -> SHALLOW/RANDOM/DEEP study
generated candidate -> functional finalization -> bounded dynamic evaluator
```

Historical evidence never changes lineage generation or dynamic security
findings, and call-depth metadata never changes either functional or security
pass/fail outcomes. Static resolution is conservative: direct identifier calls
are represented, while function pointers, macro-generated calls, dynamically
dispatched calls, and unavailable translation units may be unresolved.

This document defines the formal RQ3 analysis:

> Among functionally successful implementations, what security-relevant static
> findings and risk patterns are present, and how do they evolve across
> sequential maintenance tasks?

Security measurement is strictly post-hoc. It does not change generation,
repair, validation, lineage progression, success/failure, population
membership, architecture/strategy features, clustering, or thresholds.

## Population and interpretation

At each evaluated stage, RQ3 uses exactly the same retained successful
implementation population as RQ2. Security findings never re-filter that
population. A candidate remains functionally successful when security analysis
reports findings.

Flawfinder results are **security-relevant static-analysis findings**, not
confirmed vulnerabilities and not proof of exploitability. They may contain
false positives. Likewise, unsafe or bounded-risk API calls, heap operations,
fixed-size buffers, and indexing operations are security-sensitive exposure
descriptors; their presence alone is not a vulnerability.

No composite security score, cross-severity weighting, or arbitrary
"vulnerability rate" is defined.

## Two measurement layers

### Primary: Flawfinder findings

Flawfinder 2.0.20 is the selected primary RQ3 static analyzer. The frozen
configuration uses:

```text
flawfinder --csv --dataonly --quiet --minlevel=1 <source-basename>
```

The scanner runs with the candidate source's parent directory as its working
directory, so scientific source identifiers are stable run-relative identifiers
rather than absolute paths. The absolute executable path is retained only as
environment provenance. Every raw finding preserves the supported CSV fields:
reported filename, line, column, default and effective Flawfinder levels,
category, rule/name, warning, suggestion, note, all CWE identifiers, context,
Flawfinder fingerprint, tool version, rule ID, and help URI.

### Supporting: security-sensitive source descriptors

Tree-sitter supplies five separate counts:

- `unsafe_call_count`
- `bounded_risky_call_count`
- `heap_allocation_deallocation_call_count`
- `fixed_size_stack_buffer_count`
- `indexing_operation_count`

The exact API classifications and their version are frozen in
`scripts/security-analysis-config-v1.json`. These descriptors do not enter the
Flawfinder finding count and are not combined into a score.

## Paper-facing population metrics

Let `M` be the eligible successful population and `F_i` the Flawfinder finding
count for implementation `i`.

### Static Finding Prevalence

```text
Static Finding Prevalence = count(i: F_i >= 1) / M
```

This is not called a vulnerability rate. It is null unless every eligible
candidate has a successful Flawfinder measurement; coverage is reported
separately so missing scans are never treated as zero findings.

### Finding count

Per implementation, `flawfinder_finding_count` is the number of preserved CSV
finding rows. Population output reports mean, median, minimum, maximum, and
sample standard deviation. Sample SD is null for fewer than two measurements.

### Flawfinder Findings per KLOC

Using the same physical LOC definition as RQ2 descriptive output:

```text
source_line_count_i = len(source_text.splitlines())
findings_per_kloc_i = 1000 * F_i / source_line_count_i
```

Blank and comment lines are included. Density is null when LOC is zero or
missing. Population output reports mean, median, and sample SD over defined
densities, provided Flawfinder coverage is complete.

### Flawfinder level distributions

Levels are preserved exactly as Flawfinder reports them. Outputs include the
finding count at each level, the number and prevalence of implementations with
at least one finding at each level, the maximum observed level per
implementation, and the population distribution of those maxima. Zero-finding
implementations have maximum-level category `none`. No levels are weighted or
collapsed, and no study-defined high-severity threshold exists.

### CWE distributions

All CWE identifiers attached to each finding are retained. For every CWE, the
analysis reports occurrence count, number of implementations containing that
CWE, and candidate prevalence:

```text
CWE candidate prevalence = implementations containing CWE x / M
```

It also reports the number of distinct observed CWE identifiers. A finding
mapped to several CWEs contributes to every supplied relationship.

### Security-sensitive construct profile

Each Tree-sitter descriptor reports mean, median, number of implementations
with at least one occurrence, and candidate prevalence. `Unsafe API
Prevalence` is the prevalence for `unsafe_call_count`; the remaining categories
retain their descriptor names and are not called vulnerabilities.

## Measurement coverage and failure handling

```text
Security Measurement Coverage =
    fully security-analyzed eligible implementations / M
```

Flawfinder and Tree-sitter coverage are also reported separately. Every
unmeasured run and reason remains in `security_summary.json` and
`security_per_run.csv`. Reasons include missing source, parser failure,
Flawfinder unavailable, version mismatch, timeout, execution failure, and
malformed CSV. Scanner unavailability or failure produces null finding count,
never zero.

In formal mode, incomplete coverage marks RQ3 `formally_unavailable`; RQ1 and
RQ2 outputs remain valid and unchanged. Formal RQ3 requires both the ordinary
frozen analysis configuration and the independent frozen security
configuration. The latter records `security_analysis_enabled`, analyzer and
expected version, explicit minimum reported level and timeout, classification
version and lists, and the absence of a severity threshold. Its domain-
separated fingerprint permits exact definition comparisons without adding RQ3
settings to the RQ2 clustering signature.

## Sequential lineage analysis

Every successful checkpoint population receives a security profile, including
checkpoint 000 and implementations from lineages that stop later. The final
population is the completed-lineage population. Failed stages never enter that
or any later checkpoint population.

`security_stage_summary.csv` reports each checkpoint's population size,
coverage, finding prevalence/count/density summaries, unsafe-call prevalence
and mean, and distinct CWE count. `security_stage_severity.csv` retains the
per-stage Flawfinder level distribution.

`security_transitions.csv` compares only adjacent successful stages within the
same lineage. It reports before/after/delta values for finding count, findings
per KLOC, and unsafe-call count, plus before/after CWE sets and newly/no-longer
observed CWEs. Checkpoint 000 is a valid source population but has no invented
predecessor. No final source is compared with an empty translation unit for
security change.

## Outputs

For an ordinary or materialized population, `<analysis>/security/` contains:

```text
security_summary.json
paper_security_metrics.csv
paper_security_schema.json
security_per_run.csv
flawfinder_findings.csv
security_severity_distribution.csv
security_max_level_distribution.csv
security_cwe_distribution.csv
security_construct_profile.csv
```

The dedicated paper row contains Security Population N, Static Finding
Prevalence, Flawfinder count and KLOC summaries, Unsafe API Prevalence, Mean
Unsafe API Calls, Distinct CWE Count, Flawfinder Version, and Security
Measurement Coverage. None is inserted into RQ1 or RQ2 columns.

A lineage analysis additionally writes `analysis/security_stage_summary.csv`,
`analysis/security_stage_severity.csv`, and
`analysis/security_transitions.csv`, with detailed stage outputs under
`analysis/security/stages/` and final-population RQ3 outputs under
`analysis/security/`.

## Reproducible commands

Population analysis:

```bash
python3 scripts/analyze_experiment.py \
  --experiment <population> \
  --analysis-config <frozen-rq2-config.json> \
  --security-analysis \
  --security-config scripts/security-analysis-config-v1.json \
  --formal-analysis \
  --clean-output
```

Lineage analysis:

```bash
python3 scripts/analyze_lineages.py \
  --lineage-root <lineage-root> \
  --analysis-config <frozen-rq2-config.json> \
  --security-analysis \
  --security-config scripts/security-analysis-config-v1.json \
  --formal-analysis
```

`--security-diagnostics` remains a backward-compatible alias for
`--security-analysis`.

## Limitations and construct validation

Static findings can be false positives and can miss defects; source-level
descriptors do not establish exploitability. Comparisons therefore describe
reported findings and exposure patterns, not confirmed vulnerability incidence.

The inspected analysis host provides Clang 21.1.8 on `PATH`. Its matching
`scan-build` and `clang-check` are usable at `/usr/lib/llvm-21/bin/`, although
those wrappers are not themselves on the current `PATH`. They are not merged
with Flawfinder and are not part of the frozen primary RQ3 measurement. A future
independent construct-validation cross-check may report Clang Static Analyzer
results in a separate table after freezing its invocation and version. Nothing
is installed automatically.
