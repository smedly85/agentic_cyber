# Agentic Cyber

An experimental repository for studying how LLM-generated software evolves
across maintenance checkpoints. Each checkpoint preserves the prompt, baseline
repository state, generated candidates, validation results, and metadata needed
to reproduce and compare independent repository histories.

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
    --feature-test-cmd \
        "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/new_sort/test_001_reverse.py -v"
```

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

`scripts/analyze_experiment.py` is the sole analysis entry point. The experiment
runner invokes it automatically once per temperature. To reproduce or extend an
analysis manually, pass only the experiment directory; the analyzer reads the
target source, baseline, thresholds, and fixed K from `experiment.json`:

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

## Chained Checkpoints

Later checkpoints are seeded from a promoted earlier candidate. Because working
directories are removed after each attempt, the seed comes from the preserved
flattened candidate:

```bash
# Base implementation, generated from scratch.
bash scripts/run_experiment.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --temp-min 0 --temp-max 2 --temp-points 10 --runs 1 \
    --prompt prompts/mkdir/000_base_new_mkdir.md \
    --source src/new_mkdir/new_mkdir.c --source-mode new \
    --test-dir tests/mkdir-test-suite \
    --build-cmd "mkdir -p build && cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_mkdir/new_mkdir.c -o build/new_mkdir" \
    --feature-test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir" \
    --output-dir runs/experiments/mkdir/milestone-1

# Later checkpoint, seeded from a promoted prior candidate.
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
├── prompts/
│   ├── checkpoint_base_template.md
│   ├── checkpoint_feature_template.md
│   ├── repair_continuation_template.md    # Continuation prompt for repair loops
│   ├── mkdir/                             # mkdir checkpoints
│   └── new_sort/                          # sort checkpoints and prompt tests
├── scripts/
│   ├── analysis/                          # Canonical metric and validation modules
│   ├── analysis-requirements.txt
│   ├── analyze_experiment.py              # Sole analysis entry point
│   ├── capture_candidate.py               # Flat capture, integrity check, cleanup
│   ├── opencode_stats.py                  # Per-session token, timing and tool stats
│   ├── repair_prompt.py                   # Continuation prompt renderer
│   ├── run_experiment.sh                  # Sole experiment runner
│   └── timeout.py                         # `timeout` subset for hosts without coreutils
├── src/
│   └── new_sort/
│       ├── README.md
│       └── new_sort.c
└── tests/
    ├── mkdir-test-suite/
    └── new_sort/
```

The ignored `build/` and `runs/` directories are generated locally. Build the
checked-in sort implementation with `make`, producing `build/new_sort`, and
remove generated build files with `make clean`.
