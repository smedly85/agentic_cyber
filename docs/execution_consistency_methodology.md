# Behavioral and execution consistency

This document defines the evaluation's second measurement dimension.
`scripts/measure_execution_consistency.py` is its sole entry point. It is a
strictly post-hoc, read-only layer over the canonical analysis in
`docs/diversity_methodology.md`: it never re-runs the agent, never enters the
repair loop, and never changes a success/failure determination.

The three dimensions are separate outcomes and no composite score combines
them:

1. **Correctness and completion** — `scripts/analyze_experiment.py` (success
   rates, Pass@k) and `scripts/analyze_lineages.py` (lineage completion).
2. **Behavioral and execution consistency** — this document.
3. **Implementation diversity among functionally valid outputs** —
   `scripts/analyze_experiment.py` with `scripts/analysis/diversity_metrics.py`,
   defined in `docs/diversity_methodology.md`.

## What it measures, and why the diversity measurement does not

Architecture and strategy diversity describe baseline-relative **source
structure**. Exact convergence describes **source-byte identity**: a SHA-256
over the configured source file. Both are static, and neither is evidence about
execution. A condition can produce ten structurally distinct candidates that are
indistinguishable when run, and it can produce two nearly identical ones that
diverge on the first input neither was shown.

This measurement asks the complementary question: among the successful
candidates of one condition, how often does repeated generation produce the same
**observed behavior**? "Observed behavior" is deliberately narrow — it is the
verdict vector a suite's own runner assigns, not semantic equivalence. Two
candidates with identical fingerprints agree on every case in the corpus; they
are not thereby proven equivalent on any input outside it.

Behavior is measured twice, and the two are reported separately:

- against the checkpoint's **visible** corpus (`tests/<utility>-test-suite/suites/`),
  which the agent could read and whose failures fed the repair loop;
- against the **held-out** corpus (`tests/<utility>-test-suite/heldout/`, see
  `tests/reference_generators/heldout_contract.py`), which was never copied into
  a sandbox and never fed back.

Agreement on cases the agent could read is the weaker claim. Held-out agreement
is the one that speaks to generalisation, and pooling the two would hide the
difference.

## Experimental unit and population

The unit is the same one `docs/diversity_methodology.md` defines: one complete
generation/repair trajectory is one independent attempt, and repeated identical
candidates are retained as separate observations rather than deduplicated.

The population is the **successful runs of one condition**, exactly as
`analyze_experiment.py` determined them. The failure taxonomy is not
reimplemented here. `analyze_experiment.py` must have been run on the target
experiment first; this reads `<experiment>/analysis/per_run_metrics.csv` and
filters to `overall_success == True`, and takes `architecture_cluster_id` and
`strategy_cluster_id` from the same rows. If that file is absent the measurement
refuses to run rather than deriving a second, possibly divergent, notion of
success.

Within that population, a run is **measured** when its retained candidate source
rebuilds and both judging passes produce a report. A run that cannot be measured
is recorded with its reason and excluded from the fingerprint statistics:

- `candidate_source_missing` — no `attempt-*/candidate/<source_path>`;
- `rebuild_failed` — the recorded `build_command` did not produce the binary, or
  exceeded its time bound;
- `judge_failed` — `runner.py` produced no report (a usage error, or its
  platform gate refusing to judge), or exceeded its time bound.

Both subprocesses are bounded, because this runs unattended over a whole
population and a candidate that sends the compiler into a blowup would otherwise
stall the batch with nothing to recover it. An expiry is folded into the status
above with its reason, exactly as a compile error is; it does not abort the
condition. The judge bound is much the more generous of the two, since one judge
call runs an entire corpus through `runner.py`'s thread pool where each case
already carries its own per-case timeout.

None is silently dropped. `measurement_coverage` is measured runs over
successful runs, and a condition whose candidates mostly fail to rebuild has a
very different meaning from one whose candidates all behave identically — an
unqualified convergence rate cannot distinguish the two.

A `rebuild_failed` run is not necessarily a defective candidate. The recorded
`build_command` is the one the experiment host ran, so a candidate using an
extension its compiler provided (glibc's `memmem` under GNU C, say) will not
rebuild elsewhere. Run this measurement on the host family the experiment ran
on; a systematic rebuild failure across the whole population is a host mismatch,
not a result.

## Rebuild and re-judgement

For each run in the population, in a discarded temporary working directory:

1. The retained source `attempt-*/candidate/<source_path>` is staged at
   `source_workdir_path`, and the recorded `build_command` is run there. Both
   come from that experiment's own `experiment.json`, so the binary under
   measurement is the one the experiment defined rather than one reconstructed
   from a convention.
2. The resulting binary is judged twice through the suite's own
   `runner.py --json-report`, once over the visible suite files
   (`suites/*.json` and `*.json.gz`, excluding `MANIFEST.json`) and once over
   the single frozen held-out corpus.

Judging is delegated for the same reason `scripts/heldout_judge.py` delegates
it: each suite already materialises fixtures, pins argv and environment,
executes the candidate and compares against frozen expectations. A second
comparator could disagree with the recorded verdict and nobody would know which
was right.

Each pass gets a throwaway config carrying `paths.candidate_bin`, the
checkpoint's cumulative `implemented` flag list and `unimplemented_policy:
"skip"`. The flag list is parsed out of the recorded `feature_test_command`,
whose shape is fixed by `experiments/utilities/<utility>.json` as
`<judge script> <binary> [FLAG...]`, so the measurement is scoped to the rung
the experiment actually ran rather than to the ladder. The suite's
`required_platform` is copied across when it declares one: that key is not a
scope filter but an abort gate, and without it the sort and mkdir suites would
fingerprint the host instead of the candidate. Nothing in the repository is
modified.

The two passes differ in one respect, deliberately, because they reproduce two
different real judging paths.

The **visible** pass reproduces the scope `judge_candidate.sh` applied when the
checkpoint was actually judged, so that `visible_case_count` and the visible
fingerprint describe the same corpus that produced `feature_test_exit_code` and
drove the repair loop. Two suites need this: `sort` and `mkdir` commit real
`excluded_tags` in their own `config.json` (`["debug", "doc", "compress",
"files0", "obsolete"]` and `["selinux", "doc"]`), which every wrapper inherits by
loading that committed config as its base; and `sort`'s wrapper additionally
injects `scope.stdin_only = True`, which `runner.py`'s `modes_for()` reads to
decide whether to run the file-redirect invocation mode. `grep` and `chmod`
commit `excluded_tags: []` and pin no scope, so nothing changes for them. Both
overrides are read from the suite and its wrapper rather than hardcoded per
utility, so a suite that changes its exclusions or its wrapper's scope carries
the measurement with it.

The **held-out** pass takes none of those overrides, and keeps
`excluded_tags: []` with no `scope` key. That is not an oversight: it matches
`scripts/heldout_judge.py`, which is what actually ran the held-out corpus
during the experiment. A held-out fingerprint judged under different filtering
would describe a pass the experiment never performed.

Neither pass can alter a recorded outcome, because no verdict produced here is
written back.

## Fingerprints

`runner.py --json-report` emits `{"counts": {...}, "per_suite": {...},
"failures": [[name, verdict, detail], ...]}` — verified identical across the
mkdir, sort, grep and chmod suites. It enumerates **failures** individually;
every case not listed passed.

A behavioral fingerprint is a canonical SHA-256 over the sorted
`(case name, verdict)` pairs of a report:

```text
fingerprint = SHA-256( JSON( sorted( [[name, verdict], ...] ) ) )
```

Three are produced per measured candidate: **visible**, **held-out**, and
**combined**, where the combined material is the concatenation of both failure
lists with case names namespaced `visible::<name>` and `heldout::<name>` so a
shared name in the two corpora cannot collide.

Three properties are intended. Sorting makes the hash order-independent, since
the runner reports from a thread pool and order carries no information about the
candidate. The verdict is part of the material, because a candidate that timed
out on a case did not behave as one that produced wrong output on it. `detail`
is excluded, because it carries prose containing absolute paths, byte offsets
and timings, none of which are behavior.

Hashing failures alone identifies the full pass/fail vector only if every
candidate was judged on the same case set. That holds by construction — the case
set is a deterministic function of the suite files, the corpus and the
cumulative flag list, all fixed within a condition — but it is verified rather
than assumed. `case_count_stable` is true when the visible and held-out case
totals (summed over every verdict, including skips) were identical across the
measured population. A false value means the condition was not held constant and
the convergence rates are comparing candidates judged on different cases.

## Metrics

### Exact behavioral convergence

Over the measured population of size `N`, and separately for the visible,
held-out and combined fingerprints:

```text
exact_behavioral_unique_rate = distinct fingerprint hashes / N
exact_behavioral_modal_share = largest fingerprint-group size / N
```

These are the exact-convergence statistics of
`docs/diversity_methodology.md` applied to a different hash, computed by the
same function — `diversity_metrics.exact_repetition_summary` is generic over
hash strings and nothing in it is specific to source bytes. Reusing it keeps one
definition of "distinct over N" in the repository rather than two that could
drift. Fingerprint groups retain all run identifiers, as source-hash groups do.

A unique rate near `1/N` with a modal share near `1` is behavioral convergence:
repeated sampling under this condition reproduces one observed behavior. Both
statistics are undefined and reported as null for an empty measured population.

### Architecture/strategy–behavior agreement

The adjusted Rand index (Hubert and Arabie, 1985) between the combined-
fingerprint partition and each of the architecture-family and strategy-family
partitions `analyze_experiment.py` computed:

```text
adjusted_rand_index = ARI( behavioral groups, structural family labels )
```

Only runs present in both partitions contribute, so a run outside a primary
structural population simply does not enter that comparison, and each
comparison reports its own `population_n`. ARI is undefined below two shared
runs and is reported as null rather than as a number.

This is the number that tests the paper's own framing directly. Near 1,
structural family membership predicts behavioral identity. Near 0, it does not —
structurally distinct candidates converged on the same observed behavior, or
structurally similar ones diverged. Neither direction is a defect. The value is
evidence about how much the structural diversity result implies about behavior,
which is a claim the diversity measurement does not itself make.

## Output layout

The default output is `<experiment>/analysis/execution_consistency/`:

```text
analysis/
└── execution_consistency/
    ├── summary.json
    └── behavioral_fingerprints.csv
```

`summary.json` records the schema version, the resolved utility, flag list and
candidate binary, the corpora used, population counts with
`measurement_coverage` and a per-run reason for every unmeasured run,
`case_count_stable` with the distinct case counts observed, the three exact
behavioral convergence summaries, and both agreement results. Missing values are
`null`.

`behavioral_fingerprints.csv` is one row per measured run:

```text
run_id, visible_case_count, visible_failure_count,
heldout_case_count, heldout_failure_count,
visible_fingerprint_sha256, heldout_fingerprint_sha256,
combined_fingerprint_sha256,
architecture_cluster_id, strategy_cluster_id
```

The two cluster columns are copied from `analysis/per_run_metrics.csv`, not
recomputed, and are blank for runs outside the corresponding primary population.

## Usage

`scripts/analyze_experiment.py` must have been run on the target experiment
first; this reads its population and family labels.

```bash
python3 scripts/analyze_experiment.py \
    --experiment runs/experiments/<model>/<checkpoint>/temp-<temperature> \
    --clean-output

python3 scripts/measure_execution_consistency.py \
    --experiment runs/experiments/<model>/<checkpoint>/temp-<temperature> \
    --clean-output
```

`--output-dir` selects an alternate output location; `--clean-output` removes
only the selected output before rewriting it. One invocation measures one
condition — one model, temperature and checkpoint — because a fingerprint is
only comparable within a fixed case set. Populations from different conditions
are never pooled.

For a lineage experiment, point it at whatever population directory
`scripts/analyze_lineages.py` materialized — `<lineage-root>/analysis/populations/<label>/`
— exactly as the diversity measurement is pointed at one. Nothing in this
document changes for that case. The prerequisite above is satisfied by that same
step rather than by a separate invocation: `analyze_lineages.py` runs
`analyze_experiment.py` on each view it materializes, which is what writes the
`analysis/per_run_metrics.csv` this measurement reads. It also carries the
checkpoint's `build_command` and `feature_test_command` into the view's
`experiment.json`, which is where the flag scope and the rebuild come from here.

## Limitations

- Identical fingerprints mean agreement on the corpus, not semantic
  equivalence. The corpus is finite and frozen.
- The measurement inherits every suite's judging semantics, including its
  platform contract and its notion of a verdict. It is not an independent
  oracle.
- Behavioral convergence is not evidence about vulnerability independence.
  Establishing that requires dynamic testing, vulnerability-class labeling and
  exploit-transfer experiments, as `docs/diversity_methodology.md` also notes
  for its security profiles.
- Rebuilding is a re-execution of the recorded build on the analysis host, not
  a reproduction of the original toolchain. Cross-host rebuild failures are an
  infrastructure property and are reported as such.

## References

- Hubert, L., and Arabie, P. (1985). “Comparing Partitions.” *Journal of
  Classification*, 2, 193-218.
  [https://doi.org/10.1007/BF01908075](https://doi.org/10.1007/BF01908075).
- Chen, M., et al. (2021). “Evaluating Large Language Models Trained on Code.”
  arXiv:2107.03374. [https://doi.org/10.48550/arXiv.2107.03374](https://doi.org/10.48550/arXiv.2107.03374).
- Lee, S., Chon, H., Jang, J., Lee, D., and Yu, H. (2025). “How Diversely Can
  Language Models Solve Problems? Exploring the Algorithmic Diversity of
  Model-Generated Code.” *Findings of EMNLP 2025*, 152-167.
  [https://doi.org/10.18653/v1/2025.findings-emnlp.10](https://doi.org/10.18653/v1/2025.findings-emnlp.10).
