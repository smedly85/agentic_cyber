# Agentic Cyber

An experimental repository for studying how LLM-generated software evolves
across maintenance checkpoints. Each checkpoint preserves the prompt, baseline
repository state, generated candidates, validation results, and metadata needed
to reproduce and compare independent repository histories.

## The experimental unit is a lineage

A **lineage** is one complete sequential walk through every checkpoint of a
single utility:

```text
000_base -> 001 -> 002 -> ... -> final candidate
```

* checkpoint 000 is generated **from scratch**, independently, per lineage
* every later checkpoint inherits **only the source produced by the previous
  checkpoint of that same lineage** — never a candidate from another lineage
* every stage starts a **fresh LLM session**; the seed file is the only
  implementation state that crosses a stage boundary
* controller-driven **repair sessions may occur within a stage**, bounded by
  `--max-loops`
* a stage that still fails after its allowed repairs **stops that lineage**; a
  broken implementation is never fed into the next feature. The lineage is
  retained with its stopping point and reason recorded

The experiment then repeats that whole lineage `N` times independently. `N` is a
command-line value (`--lineages`), not a constant in the code.

Two denominators are reported and never conflated:

* **reliability** is measured over every lineage **started**
* **final diversity** compares only the lineages that **completed every
  checkpoint**, and its report states both numbers

A stopped lineage is never replaced with another attempt to round out the number
of finished implementations.

### Selected feature surfaces

**BusyBox determines which flags are in scope.** These sequences are the
selected experimental feature surface; the experiments do **not** reproduce the
BusyBox implementations, and checkpoints are not added merely because GNU
Coreutils or another implementation supports a flag.

| Utility | Checkpoint sequence |
|---|---|
| `mkdir` | `000` → `-p` → `-m` |
| `sort`  | `000` → `-r` → `-f` → `-u` → `-c` |
| `grep`  | `000` → `-H` → `-h` → `-r` → `-i` |
| `chmod` | `000` → `-R` → `-c` → `-v` → `-f` |

`grep` and `chmod` have **no committed baseline source**: checkpoint 000 must
make the agent create `src/new_grep/new_grep.c` and `src/new_chmod/new_chmod.c`
from scratch.

## Requirements

Run experiments from the repository root.

### Python

The pinned analyzer dependencies need Python 3.11 or newer; `tree-sitter`
0.26 has no wheels for older interpreters, and on 3.9 it fails at import with
`Incompatible Language version`. Create the virtual environment with an
explicit interpreter rather than a bare `python3`, which on macOS is still the
system 3.9:

```bash
python3.14 -m venv ac_venv
ac_venv/bin/python -m pip install --upgrade pip
ac_venv/bin/python -m pip install -r scripts/analysis-requirements.txt
```

Use `ac_venv/bin/python` for the analyzer, and export `PYTHON_BIN` so the
runner uses it too:

```bash
export PYTHON_BIN="$PWD/ac_venv/bin/python"
```

### External tools

| Tool | Required for | Notes |
|---|---|---|
| `opencode` | generation | Must resolve by **name** on `PATH`; the runner checks `command -v` |
| `git` | generation | Also used per attempt to fence the agent into its working directory |
| `timeout` | generation | Bounds each agent session. macOS ships none; without it the runner warns, runs unbounded, and records `timeout_enforced: false` |
| `clang` | architecture measurement | Ships with the Xcode command line tools |
| `gumtree` | architecture measurement | Java program; without it `gumtree_available` is false and clustering is incomplete |
| `flawfinder` | `--security-diagnostics` only | Optional |

`timeout` matters for any unattended sweep: a stalled session otherwise blocks
every attempt behind it. It comes from GNU coreutils (`brew install coreutils`
provides it as `gtimeout`, which the runner also accepts). Where Homebrew is
unavailable, `scripts/timeout.py` implements the subset the runner uses and can
be linked onto `PATH`:

```bash
ln -sf "$PWD/scripts/timeout.py" ~/.local/bin/timeout
```

GumTree needs a real JDK. On macOS `/usr/bin/java` is a stub that shadows
anything later on `PATH`, so pin `JAVA_HOME` in a launcher instead of relying
on `PATH` order:

```bash
# JDK, user-local
mkdir -p ~/.local/opt/jdk-21
curl -sL "https://api.adoptium.net/v3/binary/latest/21/ga/mac/aarch64/jdk/hotspot/normal/eclipse" \
  | tar -xz -C ~/.local/opt/jdk-21 --strip-components=1

# GumTree (newest release carrying a distribution zip)
curl -sLo /tmp/gumtree.zip \
  https://github.com/GumTreeDiff/gumtree/releases/download/v4.0.0-beta4/gumtree-4.0.0-beta4.zip
mkdir -p ~/.local/opt/gumtree && unzip -q /tmp/gumtree.zip -d ~/.local/opt/gumtree

cat > ~/.local/bin/gumtree <<'SH'
#!/usr/bin/env bash
export JAVA_HOME="$HOME/.local/opt/jdk-21/Contents/Home"
exec "$HOME/.local/opt/gumtree/gumtree-4.0.0-beta4/bin/gumtree" "$@"
SH
chmod +x ~/.local/bin/gumtree
```

Confirm everything resolves before a run:

```bash
for t in opencode git timeout clang gumtree flawfinder; do printf '%-12s %s\n' "$t" "$(command -v $t || echo MISSING)"; done
```

### Model backend

Point the runner at any OpenAI-compatible endpoint with `--remote-base-url`;
the provider is injected for that run only, leaving `~/.config/opencode` alone.
For a local Ollama server:

```bash
export OPENCODE_REMOTE_API_KEY=ollama   # required to be non-empty; Ollama ignores it

bash scripts/run_experiment.sh \
    --model ollama/qwen3-coder-next:latest \
    --remote-base-url http://localhost:11434/v1 \
    ...
```

A per-session timeout additionally needs `timeout` or `gtimeout`; without
either the runner warns, runs unwrapped, and records `timeout_enforced: false`.

## Running an Experiment

There are two entry points, and they sit on top of each other:

* `scripts/run_lineage_experiment.sh` runs whole **lineages**. This is the
  experiment described above and the one to use for new work.
* `scripts/run_experiment.sh` runs a **single stage** — one prompt, one source
  mode, one validation command, with the generate/validate/repair loop. The
  lineage controller calls it once per checkpoint and adds nothing to it.

Everything in the rest of this section describes the single-stage runner,
because that is where the sandbox, the repair loop, the validation and the
metadata live. See [Lineage experiments](#lineage-experiments) for the layer
above it.

`scripts/run_experiment.sh` is the single experiment runner. Each attempt gets a
fresh plain working directory containing only the prompt, any `--test-dir`
directories, and any `--seed-file` inputs. OpenCode runs with `--dir` pointed at
it and a configuration denying every other path, so nothing else in the
repository is ever visible. No Git worktrees are involved.

The required arguments are `--model`, `--prompt`, and `--source`. Select any
sort, mkdir, or future utility by supplying its checkpoint prompt, source path,
and validation commands rather than by changing the analysis command:

```bash
PROMPT=<repository-relative checkpoint prompt path>
SOURCE=<working-directory-relative primary source path>

bash scripts/run_experiment.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --temperature 0.7 \
    --runs 25 \
    --max-loops 3 \
    --prompt "$PROMPT" \
    --source "$SOURCE" \
    --source-mode new \
    --test-dir tests/mkdir-test-suite \
    --build-cmd "<build command>" \
    --base-test-cmd "<baseline test command>" \
    --feature-test-cmd "<checkpoint test command>" \
    --extra-test-cmd "<optional independent test command>"
```

Use `--source-mode new` for from-scratch checkpoints; the model must create the
file and the analysis baseline is an empty translation unit. Use
`--source-mode existing` for continuation checkpoints, together with a
`--seed-file` whose destination is `--source`; that seed is also recorded as the
analysis baseline. For new-source analysis, the known C entry point remains
literally `main` in both structural representations while arbitrary created
helper names are canonicalized.

For example, the reverse-sort checkpoint is:

```bash
bash scripts/run_experiment.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --temperature 0.7 \
    --runs 25 \
    --prompt prompts/new_sort/001_reverse.md \
    --source src/new_sort/new_sort.c \
    --source-mode existing \
    --seed-file "src/new_sort/new_sort.c" \
    --test-dir tests/sort-test-suite \
    --build-cmd "mkdir -p build && cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_sort/new_sort.c -o build/new_sort" \
    --feature-test-cmd "tests/sort-test-suite/judge_candidate.sh build/new_sort -r"
```

Every utility is judged the same way: `tests/<command>-test-suite/` is copied
into the sandbox, and `judge_candidate.sh CANDIDATE [FLAG...]` runs the frozen
cases whose required flags are all named on the command line. Passing a
checkpoint's **cumulative** flag list therefore re-runs every earlier
checkpoint's applicable cases as regression coverage. The agent may read the
copied suite; it may not modify, weaken, or delete any part of it, and tampering
is detected and recorded in `metadata.json`.

### Generation, validation, and continuation

After each OpenCode session the controller independently runs `--build-cmd`,
`--base-test-cmd`, and `--feature-test-cmd` inside the working directory. If any
of them fails, it renders a continuation prompt from
`prompts/repair_continuation_template.md` and starts a **new** OpenCode session
against the **same** working directory, so the model picks up where the previous
session left off. This repeats up to `--max-loops` times (default 3).

The continuation prompt quotes the original task, states where the source and
the visible tests live, and reports what failed as a compact list of failing
test names with short details, followed by a bounded raw tail. Failing tests are
read from a suite `--json-report` when one exists, otherwise parsed from the
suite runner's output, unittest output, or compiler diagnostics. Every rendered
prompt is saved as `attempt-*/repair-prompt-<loop>.md`.

The loop also stops early when a session leaves the source byte-identical to the
previous loop, recorded as `stop_reason: "no_progress"`; pass
`--allow-no-progress` to spend the full budget regardless. Other stop reasons
are `success`, `loop_limit`, and `agent_execution_failure`. The optional extra
test runs once after the loop and is never fed back to the model.

Override the continuation template with `--repair-prompt FILE`.

### Temperature

`--temperature T` runs a single point. For an evenly spaced sweep, give
`--temp-min`, `--temp-max`, and `--temp-points N`. `--temp-points` is required
whenever the endpoints differ, so a sweep can never be confused with an attempt
count. `--runs` is always the number of attempts *per temperature*.

Grids that are not evenly spaced — a doubling ladder, for example — are given
directly with `--temp-list`, which is mutually exclusive with the three options
above:

```bash
--temp-list 0.0,0.125,0.25,0.5,1.0,2.0 --runs 10
```

That is one sweep of six temperatures with ten attempts each, sharing a single
`sweep.json`.

Completed attempts are skipped when a command is resumed; pass `--force` to
regenerate them. Resuming with a different configuration is rejected rather than
silently mixing conditions. See all runner options with:

```bash
bash scripts/run_experiment.sh --help
```

Unless `--output-dir` is supplied, experiments are stored under:

```text
runs/experiments/<model>/<checkpoint>/
```

with one self-contained experiment directory per temperature inside it. The
runner writes `experiment.json` per temperature, including `source_path`,
prompt, model, temperature, validation commands, and repair budget. It stores
the baseline at `baseline/<source_path>` and each final candidate at
`attempt-*/candidate/<source_path>`. These metadata and source paths make the
same analysis invocation applicable to sort, mkdir, and future utilities.

### Agent sandboxing

Each attempt runs in its own working directory, and the agent must not be able
to reach anything else — not the repository it is nested inside, and not another
attempt.

OpenCode enforces this through its `external_directory` permission, which the
runner sets to deny everything except the working directory. That rule alone is
not enough: OpenCode decides whether a path *is* external by comparing it
against the session's project root, which it finds by walking up from `--dir`
looking for a `.git` directory. A working directory nested inside this
repository therefore inherits the repository as its root, every repository path
counts as internal, and the deny rule is never consulted. Observed directly: a
session asked to create `src/new_mkdir/new_mkdir.c` wrote it into the real
checkout.

The runner closes this by running `git init` in each working directory before
the first invocation, which moves the project root onto the working directory
itself, and then verifying the boundary took effect before spending any model
time. The repository is a marker only — nothing is ever committed to it, and it
is removed during cleanup along with the rest of the working directory (or on
its own when `--keep-workdir` is used).

### Session statistics

`opencode run` reports no usage figures, so after each attempt the runner reads
them out of OpenCode's own database
(`~/.local/share/opencode/opencode.db`) and writes them into the attempt
directory before the working directory is pruned:

```text
attempt-001/opencode-stats.json   one record per session
attempt-001/opencode-stats.txt    the same, formatted for reading
```

Sessions are matched by working directory and floored at the attempt's start
time, so a re-run under `--force` does not inherit the abandoned run's numbers.
Each validation loop is a separate session, reported in order as loop 0 (the
initial generation) onward, with input/output/reasoning/cache token counts, cost,
wall and model time, per-step latency, finish reasons, tool-call and tool-error
counts by tool, and reasoning-block volume. `scripts/opencode_stats.py` can also
be run by hand against any working directory that still has sessions on record.

Note that token *counts* depend on the backend: Ollama's OpenAI-compatible
endpoint does not report reasoning tokens separately, so `reasoning tokens`
reads 0 there even for a reasoning model. Reasoning blocks and characters are
counted from the transcript and remain accurate.

### Working directory cleanup

The working directory is a per-attempt copy of the test suite
(`tests/sort-test-suite` alone is 14M), so it is deleted once the attempt
finishes. Before deletion the runner:

1. copies every kept source file into `attempt-*/candidate/`, **flattened** to
   its basename, with `candidate/manifest.json` recording the original layout;
2. writes the diff artifacts the analyzer reads;
3. hashes each copied `--test-dir` against the repository original, records
   `test_dir_integrity` in `metadata.json`, and preserves anything the agent
   modified or added under `attempt-*/tampered-tests/`.

Every prompt forbids modifying the visible tests, so the integrity record is
what makes a violation visible after the copies are gone. Use `--keep-glob` to
preserve additional file patterns (default `*.c` and `*.h`), or `--keep-workdir`
to retain the working directory.

To reclaim space in runs produced earlier:

```bash
bash scripts/run_experiment.sh --prune-only runs/
```

This removes the working directory from completed attempts in the current
format. Older sandbox-format runs are analyzed straight out of `workdir/`, so
for those it removes only the copied test suites and build output and leaves the
generated source in place. Incomplete attempts are never touched.

### Failure classification

Each attempt distinguishes infrastructure attrition from agent-execution failure
and candidate failure. Timeout, permission rejection, and a nonzero attempted
OpenCode invocation are failed valid agent trials. Build, public-test, and
hidden/extra-evaluator failures are candidate/workflow failures after generation.

A per-session timeout needs `timeout` or `gtimeout` on `PATH`. When neither is
available the runner warns, runs sessions unwrapped, and records
`timeout_enforced: false` so the distinction stays visible in analysis.

Automatic analysis accepts `--analysis-architecture-threshold`,
`--analysis-strategy-threshold`, and optional `--analysis-diversity-k-max`.
The compatibility option `--analysis-threshold` sets both thresholds unless a
corresponding specific option overrides it. Without the shorthand, strategy
defaults to the resolved architecture threshold. K remains unset unless
explicitly supplied and is never inferred from successful-run count. Resolved
values are recorded in `experiment.json` and `analysis/summary.json`.

## Canonical Analysis

`scripts/analyze_experiment.py` is the sole analysis entry point for a
**population** of implementations. The single-stage runner invokes it
automatically once per temperature, and `scripts/analyze_lineages.py` invokes it
once per lineage population; neither adds or redefines a metric. To reproduce or
extend an analysis manually, pass only the experiment directory; the analyzer
reads the target source, baseline, thresholds, and fixed K from
`experiment.json`:

```bash
EXPERIMENT=runs/experiments/<model>/<checkpoint>/temp-<temperature>

python3 scripts/analyze_experiment.py \
    --experiment "$EXPERIMENT" \
    --clean-output
```

Analyze each `temp-*` condition separately. The analyzer rejects a directory
containing multiple temperatures rather than pooling different experimental
conditions.

Analysis-setting precedence is explicit CLI value, then recorded experiment
metadata, then analyzer default. Supplying threshold or K options manually
overrides the recorded value; omitting them reproduces the experiment's stored
analysis configuration.

Use a common `--diversity-k-max` supported by every compared population for
cross-condition normalized family-discovery AUC@K. Omit it when only complete
within-population DF@K curves are needed. Detailed construct-validation,
representation-ablation artifacts, and plots are opt-in:

```bash
python3 scripts/analyze_experiment.py \
    --experiment "$EXPERIMENT" \
    --cluster-threshold 0.30 \
    --strategy-threshold 0.30 \
    --diversity-k-max 25 \
    --diagnostic-output \
    --security-diagnostics \
    --clean-output
```

The analyzer writes schema-v5 results under `<experiment>/analysis/`. The main
files are `summary.json`, `per_run_metrics.csv`, `paper_metrics.csv`,
`paper_descriptive_metrics.csv`, diversity family assignments and DF@K curves,
robustness tables, and uncertainty intervals. It rebuilds the repository-level
`runs/experiments/paper_metrics.csv` and `paper_metrics.json` only from complete
analyzer-v4.1.2/schema-v5 rows that match each Git experiment's recorded
confirmatory configuration and are mutually signature-compatible. Explicit CLI
overrides remain valid for exploratory analysis, but a row that changes the
recorded thresholds, K, strategy scope, or default Clang arguments cannot enter
or anchor the confirmatory aggregate. A readable analysis signature covers both
thresholds, K, strategy scope, `main` inclusion, and ordered Clang extra
arguments. Old, exploratory/nonconfirmatory, and incompatible confirmatory rows
are counted separately in `paper_metrics_metadata.json`. Historical experiments
must be re-analyzed with analyzer v4.1.2 before entering the final aggregate.

One complete generation/repair trajectory is one independent attempt.
Infrastructure attrition remains visible in end-to-end reliability but is
excluded from valid-agent denominators for initial/final public success and
Pass@k. Agent-execution failures remain in those valid-agent denominators: in
particular, a timeout counts against initial/final agent reliability and is a
failed generated sample for Pass@k. Repair Recovery Rate instead asks: among
initial generated implementations that completed generation but failed public
validation and were therefore eligible for feedback-based repair, what fraction
were recovered? Initial timeouts, permission rejections, and OpenCode execution
errors do not enter that repair-efficacy denominator because no repairable
initial implementation was produced. Completed generations that fail public
build/base/checkpoint validation are repair eligible. End-to-end success uses
every analyzed attempt. Failed generated implementations remain reliability
failures but do not enter primary diversity. Repeated byte-identical successful
outputs remain separate diversity observations. Architecture means structural
organization of the configured primary C source, not repository- or system-wide
architecture; implementation strategy is separate. Primary strategy includes
`main`; excluding `main` is a diagnostic robustness ablation only. See
`docs/diversity_methodology.md` for formulas and interpretation.

## Lineage Experiments

`scripts/run_lineage_experiment.sh` runs complete lineages. It owns lineage
bookkeeping only: every stage is one call to `scripts/run_experiment.sh`, so the
isolated working directory, the OpenCode permissions, the source modes, the seed
files, the repair loop, the build and test validation, the candidate capture and
the infrastructure-failure metadata are all the mechanisms documented above,
unchanged and not duplicated.

```bash
bash scripts/run_lineage_experiment.sh \
    --utility sort \
    --model school-ollama/qwen3-coder-next:latest \
    --temperature 0.2 \
    --lineages 10 \
    --max-loops 3
```

Useful flags: `--lineage-start N` extends an existing run without touching
lineages already on disk, `--output-dir DIR` relocates the results, `--force`
reruns stages that are already complete, `--print-plan` shows the resolved stage
plan, `--dry-run` prints every `run_experiment.sh` command without running one,
and `--list-utilities` lists the manifests. Sandbox and backend options
(`--agent`, `--timeout`, `--keep-workdir`, `--allow-no-progress`,
`--repair-prompt`, `--remote-base-url`, `--remote-api-key-env`) pass straight
through.

### Utility manifests

No utility detail lives in the controller. `experiments/utilities/<name>.json`
describes the source path, executable path, build command, visible test
directory, ordered checkpoints, per-checkpoint prompt, and the **cumulative**
implemented-flag list that becomes the judge command. See
[`experiments/utilities/README.md`](experiments/utilities/README.md) for the
schema. `scripts/lineage_plan.py` resolves a manifest into the stage plan and is
where the manifest's invariants are enforced: checkpoint 000 must be
`source_mode: new`, every later checkpoint must be `existing`, and
`implemented_flags` must never drop a flag an earlier checkpoint declared.

### Source inheritance

Stage 000 runs `--source-mode new`. Every later stage runs
`--source-mode existing` with a `--seed-file` pointing at the immediately
preceding **successful candidate of the same lineage**:

```text
lineage-003 / 000 candidate  ->  lineage-003 / 001 seed
lineage-003 / 001 candidate  ->  lineage-003 / 002 seed
```

There is no cross-lineage path. A stage whose seed is missing is a hard error
rather than a silent substitution, and `lineage.json` records the SHA-256 of
both the seed consumed and the candidate produced, so the chain can be proved
after the fact — `scripts/analyze_lineages.py` re-checks it.

### Visible tests are built per checkpoint, not copied

The agent at checkpoint N may read the current prompt, the inherited source, the
shared runtime judging files, the cases for checkpoint N, and the cases for
checkpoints before N. It must not be able to read anything describing a
checkpoint it has not reached. Copying `tests/<utility>-test-suite/` wholesale
fails that: the frozen corpora carry every later checkpoint's cases *with their
expected outputs*, `gen/` names and groups them, `model/` holds the flag and
specification models, and the READMEs tabulate the whole ladder. Filtering which
cases the judge *runs* does not help, because the files are still readable.

`scripts/stage_test_bundle.py` therefore **builds** each stage's visible tests:

* an explicit allowlist ships the runtime judging path only — `judge_candidate.sh`,
  `runner.py`, `engine.py`, `props.py`, `config.py`. Nothing under `gen/`,
  `model/` or `corpus/`, no generator, no fuzzer, no README, no self-check, no
  prior run logs;
* `suites/` is re-frozen to the cases whose required flags are all implemented at
  that checkpoint, so a later checkpoint's case is **absent**, not skipped;
* `config.json` is reduced to the minimal judging configuration, dropping
  `paths.oracle_bin` — an oracle path is a hint;
* `props.py` is pruned to the property checks the retained cases actually
  dispatch to, plus their transitive dependencies, and regenerated from its AST
  so comments and the module docstring go too. Both were leaking: mkdir's
  `check_idempotent_p` spells out the `-p`/`-m` contract, and chmod's report-line
  regexes spell out the exact `-c`/`-v` output format.

The bundle is mounted at the suite's own path (`run_experiment.sh --test-dir
SRC:DEST`), so the prompt and the judge command stay literally correct, and it is
kept next to the stage results as the record of what was visible. Its fingerprint
is folded into the run's configuration fingerprint, so regenerated goldens or an
edited allowlist invalidate a resume instead of silently mixing bundles.

No reference implementation reaches a bundle. `new_grep` and `new_chmod` have no
valid external oracle, so their specification models were written for this
project and live in `tests/reference_generators/`, outside every suite; only
offline generation and auditing import them, and the runtime judge works from
frozen expected results alone.

### Detecting premature implementation

The checkpoint contract is incremental: 000 implements base behavior only, 001
adds exactly one feature, and so on. Cumulative flag filtering tests the ladder
from *below* — it never reaches a feature that does not exist yet — but on its
own it cannot notice a candidate that implemented the whole option set at 000.

A case may therefore declare `absent_flags`. It is selected only while none of
those flags is implemented, which is how a checkpoint asserts a later feature is
still missing:

```text
grep  base-rejects-i-before-its-checkpoint   -i must exit 2 at 000..003
chmod base-rejects-v-before-its-checkpoint   -v must exit 2 at 000..002
```

Every prompt makes an option it has not introduced an unknown option, so these
are contract-consistent rather than extra requirements. Each case disappears at
the checkpoint that introduces its flag, where the same invocation must now
succeed; `gen/verify.py` asserts exactly that, and the suites' monotone-coverage
invariant excludes them so their intended disappearance does not read as lost
coverage.

**Coverage and its limits.** `new_grep` and `new_chmod` carry rejection cases for
every flag in their ladders, because their goldens come from specification models
that `parse_args` can restrict to one checkpoint's option set. `new_sort` and
`new_mkdir` **do not**, and cannot without a different mechanism: their goldens
are frozen by running a real GNU binary, and GNU `sort` supports `-r` and GNU
`mkdir` supports `-p`, so the oracle cannot produce a "this must be rejected"
golden for a flag it implements. Adding them there means authoring those
expectations by hand instead of deriving them from the oracle. Until then,
premature implementation is detected for grep and chmod only; for sort and mkdir
the ladder is still tested from below, and the unknown-option rejection cases
that do exist (`-Z`, `--no-such-flag`) cover options outside the experiment.

### Output layout

```text
runs/lineages/<utility>/<model-slug>/temp-<slug>/
├── lineages.json                 run configuration + fingerprint
├── lineage-001/
│   ├── lineage.json              per-stage outcome, seed provenance, stop point
│   ├── 000/                      a complete single-stage run_experiment.sh tree
│   │   ├── sweep.json
│   │   └── temp-<slug>/
│   │       ├── experiment.json
│   │       ├── baseline/
│   │       └── attempt-001/{metadata.json,candidate/,*.log,repair-prompt-*.md}
│   ├── 001/  002/  ...
│   └── final/<source>.c          only when every checkpoint succeeded
└── lineage-002/ ...
```

Every stage stays inspectable, including the repair prompts and logs. Failed
lineages are retained; `final/` exists **only** for a lineage that completed the
whole sequence, so its presence is never ambiguous.

### Resume safety

`lineage_plan.py` computes a configuration fingerprint over the resolved
manifest, the *contents* of every checkpoint prompt, the contents of the judge
script, and the model, agent, temperature and repair budget. The controller
refuses to write into an existing lineage root whose `lineages.json` records a
different fingerprint, so a run cannot silently mix stage configurations. When a
completed stage is reused, its recorded seed snapshot is compared against the
seed the current walk holds, which catches the one remaining way a resume could
mix generations: an earlier stage regenerated while a later one was left alone.

The number of lineages and the output directory are deliberately excluded from
the fingerprint — extending a run from 10 lineages to 15 is a valid resume,
while editing a prompt is not.

### Analyzing a lineage run

```bash
python3 scripts/analyze_lineages.py \
    --lineage-root runs/lineages/sort/<model-slug>/temp-0p2
```

This writes `analysis/lineage_report.json`, `analysis/lineage_stages.csv` and
`analysis/summary.md`, covering the end-to-end completion rate over all lineages
started, the count of lineages stopped at each checkpoint and why, and repair
behavior per checkpoint. Infrastructure failures and agent-execution failures
stay distinguishable from implementation and test failures, using the
single-stage runner's own metadata vocabulary rather than a second
classification.

Diversity is not reimplemented. For each population the script materializes a
*view* — a directory in exactly the layout `scripts/analyze_experiment.py`
already consumes — and runs that analyzer on it, so the metric definitions and
the architecture/strategy thresholds are unchanged. The **final** population is
the last stage of every lineage that completed every checkpoint;
`--checkpoint-diversity` additionally analyzes the successful implementations at
each intermediate checkpoint. `--skip-diversity` aggregates outcomes only.

`summary.md` always states both `lineages started = N` and
`successful final implementations = n`; the completion rate is never computed
over the survivors.

### Running a single stage by hand

The single-stage runner remains usable directly, which is how the older
non-lineage results in `runs/experiments/` were produced:

```bash
bash scripts/run_experiment.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --temp-min 0 --temp-max 2 --temp-points 10 --runs 1 \
    --prompt prompts/mkdir/001_parents.md \
    --source src/new_mkdir/new_mkdir.c --source-mode existing \
    --test-dir tests/mkdir-test-suite \
    --seed-file "runs/experiments/mkdir/milestone-1/temp-0p0/attempt-001/candidate/new_mkdir.c:src/new_mkdir/new_mkdir.c" \
    --build-cmd "mkdir -p build && cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_mkdir/new_mkdir.c -o build/new_mkdir" \
    --feature-test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir -p" \
    --output-dir runs/experiments/mkdir/milestone-2
```

`--seed-file` defaults its destination to the source path when `:DEST` is
omitted. The seed whose destination matches `--source` also becomes that
experiment's analysis baseline, so churn is measured against the promoted
candidate rather than against nothing.

Results produced this way are **not** lineage results: each temperature point
there is an independent single-checkpoint population, not a sequential walk, and
the existing output under `runs/` and `review-bundle/` should not be
reinterpreted as lineages.

### Historical sandbox runs

Runs under `runs/sandboxed/` were produced by the earlier no-Git runner and
remain analyzable in place. Their `run.json` does not record the generated
source path, so provide it explicitly, and analyze one temperature at a time:

```bash
python3 scripts/analyze_experiment.py \
    --experiment runs/sandboxed/mkdir/milestone-1/temp-0p0 \
    --source-path src/new_mkdir/new_mkdir.c \
    --cluster-threshold 0.30 \
    --strategy-threshold 0.30 \
    --clean-output
```

`--baseline-source` can explicitly override baseline discovery. Runs generated
under materially different agent-feedback or controller protocols must not be
pooled as one condition; sandbox rows are not added to the repository-level
confirmatory paper aggregate.

## Repository Structure

```text
agentic_cyber/
├── Makefile
├── README.md
├── docs/
│   └── diversity_methodology.md          # Canonical v4.1.2/schema-v5 methodology
├── experiments/
│   └── utilities/                        # One manifest per experimental utility
│       ├── README.md                     # Manifest schema and feature surfaces
│       ├── chmod.json  grep.json  mkdir.json  sort.json
├── prompts/
│   ├── checkpoint_base_template.md
│   ├── checkpoint_feature_template.md
│   ├── repair_continuation_template.md    # Continuation prompt for repair loops
│   ├── chmod/                             # chmod checkpoints (000 -> -R -> -c -> -v -> -f)
│   ├── grep/                              # grep checkpoints  (000 -> -H -> -h -> -r -> -i)
│   ├── mkdir/                             # mkdir checkpoints (000 -> -p -> -m)
│   └── new_sort/                          # sort checkpoints  (000 -> -r -> -f -> -u -> -c)
├── scripts/
│   ├── analysis/                          # Canonical metric and validation modules
│   ├── analysis-requirements.txt
│   ├── analyze_experiment.py              # Sole per-population analysis entry point
│   ├── analyze_lineages.py                # Lineage aggregation; delegates diversity
│   ├── capture_candidate.py               # Flat capture, integrity check, cleanup
│   ├── lineage_plan.py                    # Manifest -> stage plan + config fingerprint
│   ├── opencode_stats.py                  # Per-session token, timing and tool stats
│   ├── repair_prompt.py                   # Continuation prompt renderer
│   ├── run_experiment.sh                  # Single-stage experiment runner
│   ├── run_lineage_experiment.sh          # Lineage controller over the stage runner
│   └── timeout.py                         # `timeout` subset for hosts without coreutils
├── src/
│   └── new_sort/                          # Historical checked-in sort implementation
│       ├── README.md
│       └── new_sort.c
└── tests/
    ├── chmod-test-suite/                  # Model-derived goldens, isolated fixtures
    ├── grep-test-suite/                   # Model-derived goldens
    ├── mkdir-test-suite/                  # GNU-oracle goldens
    ├── sort-test-suite/                   # GNU-oracle goldens
    ├── new_sort/                          # Historical per-checkpoint unittest files
    ├── test_lineage_tools.py              # Manifests, stage plan, lineage aggregation
    └── test_measure_diversity.py          # Analysis and controller tests
```

There is deliberately no `src/new_grep/` or `src/new_chmod/`: checkpoint 000 of
those lineages must make the agent create the source.

The ignored `build/` and `runs/` directories are generated locally. Build the
checked-in sort implementation with `make`, producing `build/new_sort`, and
remove generated build files with `make clean`.
