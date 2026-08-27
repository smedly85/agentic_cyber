# Agentic Cyber

An experimental repository for studying how LLM-generated software evolves
across maintenance checkpoints. Each checkpoint preserves the prompt, baseline
repository state, generated candidates, validation results, and metadata needed
to reproduce and compare independent repository histories.

The experiment generates C reimplementations of four standard utilities one
feature at a time. The primary paper analysis separates RQ1 correctness and
lineage completion, RQ2 implementation diversity and maintenance variation,
and RQ3 security. No composite score combines them.
`docs/diversity_methodology.md` defines the structural and maintenance
measurement. The existing behavioral-consistency tool is retained as an
optional post-hoc diagnostic and documented separately in
`docs/execution_consistency_methodology.md`.

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

### Materialized populations are valid input to every downstream tool

Diversity is not reimplemented at the lineage level. For each population
`analyze_lineages.py` materializes a *view* — a directory in exactly the layout
`scripts/analyze_experiment.py` already consumes — and runs that analyzer on it,
so the metric definitions and thresholds are unchanged.

A view must be a valid input to every downstream analysis, not only to the
diversity analyzer it was first written for. Alongside the baseline and one
attempt per member, `materialize_view` therefore carries the checkpoint's
`feature_test_command` and `build_command` into the view's `experiment.json`.
Those are what `scripts/measure_execution_consistency.py` reads to recover the
checkpoint's cumulative flag scope and to rebuild each candidate; a view without
them crashes the tool on a population it is documented to accept. Both are
recorded per checkpoint, and every member of a population is the same checkpoint
under the same condition, so each has exactly one value — verified rather than
assumed, and a population whose members disagree is refused rather than
described with a configuration it does not have.

The view's baseline is the empty translation unit, because lineages share no
seed and no member's source is a meaningful predecessor of another's. That keeps
clustering, family, Vendi, discovery, repetition and pairwise-distance metrics
valid, and makes every churn metric a whole-program measure rather than a
maintenance step. Those churn metrics are named individually in the view's
`baseline_dependent_metrics_unsupported`, and are answered properly by the
per-stage and total-lineage change tables instead.

## Selected feature surfaces

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

Each ladder is declared in `experiments/utilities/<name>.json` and nowhere else;
the table above is that file's `checkpoints[].implemented_flags`, which is
**cumulative** — checkpoint 002 of `sort` declares `-r -f`, not `-f`.

`grep` and `chmod` have **no committed baseline source**: checkpoint 000 must
make the agent create `src/new_grep/new_grep.c` and `src/new_chmod/new_chmod.c`
from scratch.

Two suites carry a platform contract, because their expected results were frozen
by running a real system binary: `sort` requires Linux and `mkdir` requires
Darwin (`tests/<utility>-test-suite/config.json`, `required_platform`). `grep`
and `chmod` declare none — their goldens come from specification models written
for this project.

## Installation

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

Install Aider with its official installer (do this separately on every host
that will execute generation, including the vessel):

```bash
python3 -m pip install aider-install
aider-install
aider --version
```

| Tool | Required for | Notes |
|---|---|---|
| `aider` | generation | Installed with `aider-install`; override the executable with `AIDER_BIN` |
| `git` | generation | Used only to resolve controller inputs; Aider runs with Git disabled |
| `timeout` | generation | Bounds each agent session. macOS ships none; without it the runner warns, runs unbounded, and records `timeout_enforced: false` |
| `clang` | architecture measurement | Ships with the Xcode command line tools |
| `gumtree` | architecture measurement | Java program; without it `gumtree_available` is false and clustering is incomplete |
| `flawfinder` 2.0.20 | formal RQ3 security analysis | Pinned in `scripts/analysis-requirements.txt`; formal RQ3 is unavailable rather than reporting zero when missing or mismatched |
| Clang `scan-build` / `clang-check` | optional RQ3 construct validation | Inspected independently; never merged with Flawfinder or installed automatically |

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
for t in aider git timeout clang gumtree flawfinder; do printf '%-12s %s\n' "$t" "$(command -v $t || echo MISSING)"; done
```

### Model backend

The formal configuration is self-contained. Each attempt gets an isolated home,
empty explicit Aider config and env files, and a generated model-settings file;
the runner does not inherit `~/.aider.conf.yml`, `~/.env`, or
`~/.aider.model.settings.yml`.

For a native Ollama endpoint, use Aider's recommended `ollama_chat/` provider
and pass the Ollama **root** URL (not `/v1`):

```bash
bash scripts/run_lineage_experiment.sh \
    --utility grep \
    --model ollama_chat/qwen3.8:27b \
    --editor-model ollama_chat/qwen3-coder-next:latest \
    --remote-base-url http://localhost:11434 \
    ...
```

If the vessel exposes only its existing OpenAI-compatible gateway, use matching
`openai/` model names and its `/v1` URL instead. `--remote-api-key-env` may name
an exported credential; when omitted for an unauthenticated compatibility
gateway, the runner supplies the conventional dummy key `ollama`. The old
`school-ollama/` prefix was an OpenCode provider alias and is not an Aider model
provider name.

## Running a lineage

`scripts/run_lineage_experiment.sh` is the entry point:

```bash
bash scripts/run_lineage_experiment.sh \
    --utility sort \
    --model ollama_chat/qwen3.8:27b \
    --editor-model ollama_chat/qwen3-coder-next:latest \
    --temperature 0.2 \
    --lineages 10 \
    --max-loops 3
```

`--utility` names a manifest under `experiments/utilities/`. `--lineages`
defaults to 1 — there is no built-in experiment size — and `--max-loops`
defaults to 3 repair sessions within each stage, with 0 disabling repair
entirely.

Useful flags: `--lineage-start N` extends an existing run without touching
lineages already on disk, `--output-dir DIR` relocates the results, `--force`
reruns stages that are already complete, `--print-plan` shows the resolved stage
plan, `--dry-run` prints every `run_experiment.sh` command without running one
or touching the filesystem, and `--list-utilities` lists the manifests. Sandbox
and backend options (`--editor-model`, `--timeout`, `--keep-workdir`,
`--allow-no-progress`, `--repair-prompt`, `--remote-base-url`,
`--remote-api-key-env`) pass straight through to the stage runner.

### Sampling

Three optional sampling knobs are forwarded unchanged to every stage and every
repair session inside it: `--top-p P`, `--sampling-seed N` and `--max-tokens N`.
Leaving one unset means the flag is absent from the request and the server's own
default applies; that distinction is recorded as a JSON null rather than by
omitting the key. Every sampling value is part of the lineage configuration
fingerprint, so changing one refuses to resume an existing `--output-dir` rather
than mixing conditions.

Two spellings are refused outright rather than accepted and quietly ignored:

* **`--top-k`** — native `ollama_chat` can carry it, but transport support alone
  is not enough to add a new experimental control. It remains rejected until a
  separate transport-level verification establishes what the selected vessel
  endpoint forwards to Ollama.
  Model-definition-level top-k remains valid: create a derived Ollama model and
  record it explicitly with metadata-only `--model-provenance-json`, for example
  `'{"base_model":"qwen3-coder-next:latest","top_k":50,"top_k_control":"ollama_modelfile"}'`.
  This object is fingerprinted and never added to the request. Nothing parses
  top-k from the model alias and no local `ollama show` is required.
* **`--seed`** — ambiguous in this harness. `--sampling-seed` is the
  token-selection seed; `--seed-file` is the checkpoint source-inheritance file,
  and the two senses must never collide.

`--runs` is likewise refused: a lineage runs one attempt per stage, so the
number of independent samples is `--lineages`.

### Platform preflight

Run-level environment eligibility is decided **before any lineage is
initialized**. If the utility's suite declares a `required_platform` the host
does not satisfy, the controller prints `platform_incompatible`, records
`run_status: platform_incompatible` in `lineages.json`, and exits 4 — distinct
from 1 (a stage failed) and 2 (a usage error). No lineage directory, no
`lineage.json`, no checkpoint, and no agent invocation.

That ordering is the point. Letting the walk begin and stopping each lineage at
checkpoint 000 would create a start record for all `N`, so
`successful_finals / lineages_started` would read `0/N` — reporting a model
reliability of zero for what is purely an environment mismatch. `lineages.json`
also deliberately records no planned lineage ids in this case, so analysis
cannot later resurrect them. `analyze_lineages.py` reports reliability as **not
applicable**, which is not the same as 0.0 and is never rendered as one.

A `--dry-run` on the wrong host warns and continues, since it starts nothing.

### A real run

`runs/formal/grep-qwen3-topk40-t0-p05-seed42-maxtok32768-loops1-n10/` is a
complete ten-lineage `grep` run with its analysis in place. Read the invocation
from its `lineages.json` rather than from the directory name, which disagrees
with it — top-k is baked into the model here rather than passed as a flag, which
`--top-k` would refuse anyway, and `max_loops` is 3, not 1:

```bash
bash scripts/run_lineage_experiment.sh \
    --utility grep \
    --model ollama/qwen3-coder-next-topk1:latest \
    --temperature 0 \
    --top-p 0.5 \
    --sampling-seed 42 \
    --max-tokens 32768 \
    --model-provenance-json '{"base_model":"qwen3-coder-next:latest","top_k":1,"top_k_control":"ollama_modelfile"}' \
    --lineages 10 \
    --max-loops 3 \
    --output-dir runs/formal/grep-qwen3-topk40-t0-p05-seed42-maxtok32768-loops1-n10
```

Its `analysis/summary.md` reports 10 lineages started, 7 successful final
implementations, and an end-to-end completion rate of 0.700 (95% Wilson
0.397–0.892), with all three stops at checkpoint 000.

### Output layout

```text
runs/lineages/<utility>/<model-slug>/temp-<slug>/
├── lineages.json                 run configuration + fingerprint
├── lineage-001/
│   ├── lineage.json              per-stage outcome, seed provenance, stop point
│   ├── 000/                      a complete single-stage run_experiment.sh tree
│   │   ├── test-bundle/          exactly what the agent could read here
│   │   ├── boundary-gate.json
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

### Lineage state, and counting every lineage that starts

Reliability is measured over every lineage **started**, so a lineage has to
become countable the moment it begins rather than when it finishes.
`lineage.json` is therefore written by `scripts/lineage_state.py` before
checkpoint 000 runs, rewritten after every checkpoint, and only closed out at
the end:

| state | meaning |
|---|---|
| `running` | created by the controller; the walk has not finished |
| `stopped` | a checkpoint failed — the lineage ended normally, unsuccessfully |
| `completed` | every checkpoint passed and `final/` was written |

A record still in `running` at analysis time means the controller itself died,
and the analyzer classifies it as `controller_interrupted`: counted in the
denominator, never counted as a successful final, and reported under its own
reason rather than as an implementation failure. A lineage directory with no
record or with an unparseable one is likewise counted and reported
(`missing_record`, `malformed_record`) instead of being silently skipped —
skipping shrinks the denominator in exactly the direction that flatters the
result, because interruptions are likeliest in the long, repair-heavy lineages.

Planned is not started, and the two are counted differently. `lineages.json` is
written once, before any lineage begins, and lists every id the invocation
intends to run; treating that as evidence of a start would report ten lineages
for a run interrupted after three. A lineage counts as started only when the
controller left durable proof — the directory and the `lineage.json` that
`lineage_state.py init` creates immediately before checkpoint 000. Ids that were
planned but never begun are reported under
`lineages_planned_not_started` and stay out of the reliability denominator
entirely.

Every update goes through a sibling temporary file and `os.replace`, which is
atomic on POSIX and Windows, so an interrupted write leaves either the previous
record or the new one and never a truncated file.

### Resume safety

`scripts/lineage_plan.py` computes a configuration fingerprint over the resolved
manifest, the *contents* of every checkpoint prompt, the contents of the judge
script, the shared automation notice, the per-checkpoint test-bundle
fingerprints, and the model, agent, temperature, sampling settings, repair budget
and session timeout. The controller refuses to write
into an existing lineage root whose `lineages.json` records a different
fingerprint, and names the specific field that differs rather than only reporting
a hash mismatch. When a completed stage is reused, its recorded seed snapshot is
compared against the seed the current walk holds, which catches the one remaining
way a resume could mix generations: an earlier stage regenerated while a later
one was left alone.

The number of lineages and the output directory are deliberately excluded from
the fingerprint — extending a run from 10 lineages to 15 is a valid resume,
while editing a prompt is not.

## Analyzing a lineage run

Analysis uses the lineage and experiment analyzers for the three paper-facing
research questions. Optional representation diagnostics deepen RQ2, while the
behavioral-consistency tool remains a separate post-hoc diagnostic.

### 1. Reliability, change, and the diversity populations

```bash
python3 scripts/analyze_lineages.py \
    --lineage-root runs/lineages/sort/<model-slug>/temp-0p2 \
    --checkpoint-diversity
```

This writes `analysis/lineage_report.json`, `analysis/lineage_stages.csv` and
`analysis/summary.md`, covering the end-to-end completion rate over all lineages
started, the count of lineages stopped at each checkpoint and why, and repair
behavior per checkpoint. Infrastructure failures and agent-execution failures
stay distinguishable from implementation and test failures, using the
single-stage runner's own metadata vocabulary rather than a second
classification. It also re-checks seed provenance from the recorded hashes, so a
pooled or hand-edited result set cannot pass silently.

Two change tables are written against the baseline each measurement actually
has, never against the population view's placeholder baseline:
`analysis/lineage_transitions.csv` pairs each stage's candidate with the exact
file it was seeded with, and `analysis/lineage_total_change.csv` pairs each
completed lineage's final source with that same lineage's own checkpoint 000
source, labelled as total trajectory change rather than a single maintenance
step. `analysis/lineage_change_summary.csv` aggregates the real same-lineage
transition rows by destination checkpoint; checkpoint 000 has no transition
row. `--skip-change` omits these change outputs.

For diversity it materializes each population under
`analysis/populations/<label>/` and runs `scripts/analyze_experiment.py` on it.
The **final** population is the last stage of every lineage that completed every
checkpoint; `--checkpoint-diversity` additionally analyzes the successful
implementations at each intermediate checkpoint, including those from lineages
that stopped later. `--skip-diversity` aggregates outcomes only. A population
with fewer than two members is skipped with its reason rather than reported as a
failure — diversity over one implementation is undefined, not failed.

`summary.md` always states both `lineages started = N` and
`successful final implementations = n`; the completion rate is never computed
over the survivors.

Each population view records `analysis_population_member: true` and
`population_selection_basis: lineage_stage_success`. Its paper row retains
population size and structural coverage but sets reliability and Pass@k to NA
with `reliability_scope: parent_lineage_experiment`; it also sets empty-baseline
maintenance-change fields to NA. Baseline-independent physical source LOC and
source-byte descriptors remain supported in final and checkpoint population
views. The parent
`analysis/lineage_paper_metrics.csv` combines all-started lineage completion
with the final population's structural metrics. Thus 7 finals from 10 started
lineages report completion 0.70, never 7/7.

Note that stages themselves are not analyzed individually: the controller passes
`--no-analysis` to the stage runner, so `analyze_experiment.py` runs only on the
materialized populations, never once per checkpoint attempt.

### 2. Deeper diagnostics, run directly against a population

Representation ablation and construct-validation distances can be obtained by
invoking the experiment analyzer directly against a materialized population
directory:

```bash
POPULATION=runs/lineages/sort/<model-slug>/temp-0p2/analysis/populations/final

python3 scripts/analyze_experiment.py \
    --experiment "$POPULATION" \
    --cluster-threshold 0.30 \
    --strategy-threshold 0.30 \
    --diversity-k-max 25 \
    --diagnostic-output \
    --clean-output
```

A materialized view is an ordinary experiment directory, so nothing about the
analyzer changes here. Analyze one population at a time; the analyzer rejects a
directory holding multiple conditions rather than pooling them. Use a common
`--diversity-k-max` supported by every compared population for cross-condition
normalized family-discovery AUC@K, and omit it when only complete within-
population DF@K curves are needed.

The analyzer writes schema-v7 results under `<population>/analysis/`:
`summary.json`, `per_run_metrics.csv`, `paper_metrics.csv`,
`paper_descriptive_metrics.csv`, diversity family assignments and DF@K curves,
robustness tables, and uncertainty intervals. A view's `experiment.json` points
`repository` at the view itself rather than at the checkout, so the repository-
level paper aggregate the analyzer maintains is never rewritten by a lineage
analysis. Exploratory analysis retains CLI/metadata/default precedence. Only a
row produced with `--formal-analysis` from a complete frozen configuration can
enter or anchor a confirmatory aggregate. See
`docs/diversity_methodology.md` for the formulas and their interpretation.

Formal analysis uses `--analysis-config FILE --formal-analysis`. The versioned
JSON must explicitly provide architecture/strategy thresholds, the sensitivity
grid or deterministic rule, bootstrap repetitions/seed, strategy exclusion and
forced includes, `include_main`, Clang extra arguments, and fixed K (including
explicit `null`). Formal mode refuses a missing/incomplete file instead of
falling back to scientific defaults. The resolved object, schema version, and
domain-separated fingerprint are written to every population summary and the
parent lineage report.

### 3. RQ3 security

```bash
python3 scripts/analyze_experiment.py \
    --experiment "$POPULATION" \
    --security-analysis \
    --security-config scripts/security-analysis-config-v1.json \
    --clean-output
```

Formal runs additionally use `--formal-analysis --analysis-config <RQ2-CONFIG>`.
RQ3 uses exactly the successful RQ2 population and never re-filters it.
Flawfinder 2.0.20 findings are the primary external static-analysis layer;
Tree-sitter counts unsafe/bounded-risk APIs, heap calls, fixed-size buffers, and
indexing as supporting security-sensitive descriptors. Findings and descriptors
are never combined into a score or called confirmed vulnerabilities.

Population outputs are written beneath `<population>/analysis/security/`:
`paper_security_metrics.csv`, `security_summary.json`,
`security_per_run.csv`, `flawfinder_findings.csv`, severity/maximum-level/CWE
tables, and the construct-profile table. Lineage analysis with
`--security-analysis` additionally writes `analysis/security_stage_summary.csv`,
`analysis/security_stage_severity.csv`, and
`analysis/security_transitions.csv`. See
`docs/security_methodology.md` for definitions and coverage rules.

To measure every successful lineage stage and the final population in one
invocation, use:

```bash
python3 scripts/analyze_lineages.py \
    --lineage-root runs/lineages/sort/<model-slug>/temp-0p2 \
    --checkpoint-diversity \
    --security-analysis \
    --security-config scripts/security-analysis-config-v1.json
```

### 4. Optional behavioral and execution consistency diagnostic

```bash
python3 scripts/measure_execution_consistency.py \
    --experiment "$POPULATION" \
    --clean-output
```

This rebuilds each selected population member and re-judges it twice — once against
the checkpoint's visible corpus and once against the held-out corpus the agent
never saw — and summarizes the resulting verdict vectors as behavioral
fingerprints. It is strictly post-hoc and read-only: it never re-runs Aider,
never enters the repair loop, and never turns a pass into a fail.

**It requires the previous steps to have run.** It does not re-derive the
population or the family labels: ordinary experiments use `overall_success`,
while lineage views use the controller's explicit `analysis_population_member`.
It takes `architecture_cluster_id` and `strategy_cluster_id` from the same rows.
Without that file it refuses to run
rather than growing a second, possibly divergent, definition of "successful". It
also reads `source_path`, `feature_test_command`, `build_command` and
`source_workdir_path` out of the view's `experiment.json`, and takes the suite
and the held-out corpus from `tests/<utility>-test-suite/` in the checkout.

**It must run on the same host family the experiment was generated on.** The
recorded `build_command` is the one the experiment host ran, so a candidate that
used an extension its compiler provided will not rebuild elsewhere. This is a
real, documented limitation rather than a bug to work around — see
`docs/execution_consistency_methodology.md`. The example run above shows what it
looks like when the hosts do not match. Its `lineages.json` records
`host_platform: "Darwin"`, and its
`analysis/populations/final/analysis/execution_consistency/summary.json` records
all seven finals as `rebuild_failed` with a `measurement_coverage` of 0.0, each
detail a GCC diagnostic for an implicit declaration of `memmem` or `strdup`.
Such runs are recorded with their reason and excluded from the fingerprint
statistics, never silently dropped, because a condition whose candidates mostly
fail to rebuild means something very different from one whose candidates all
behave identically.

Output lands in `<population>/analysis/execution_consistency/` as `summary.json`,
`behavioral_fingerprints.csv`, `behavioral_verdict_traces.json`, and
`pairwise_behavioral_distances.csv`. These behavioral results, including
structure-versus-behavior ARI, are optional diagnostics and are not part of the
primary paper-facing RQ metrics.

## How the harness works

Everything in this section is mechanism the lineage controller reuses rather than
reimplements.

### The single-stage runner

`scripts/run_experiment.sh` runs a **single stage** — one prompt, one source
mode, one validation command, with the generate/validate/repair loop. The
lineage controller calls it once per checkpoint and adds nothing to it, so the
isolated working directory, the Aider file boundary, the source modes, the seed
files, the repair loop, the build and test validation, the candidate capture and
the infrastructure-failure metadata all live here.

Its required arguments are `--model`, `--prompt` and `--source`. Use
`--source-mode new` for from-scratch checkpoints, where the model must create the
file and the analysis baseline is an empty translation unit; use
`--source-mode existing` together with a `--seed-file` whose destination is
`--source`, in which case that seed is also recorded as the analysis baseline so
churn is measured against the promoted candidate rather than against nothing.

Run standalone it also supports temperature sweeps (`--temp-min`/`--temp-max`/
`--temp-points`, or `--temp-list` for grids that are not evenly spaced) with
`--runs` attempts per temperature, and it invokes `analyze_experiment.py`
automatically once per temperature unless `--no-analysis` is passed. The lineage
controller passes `--runs 1` and `--no-analysis` at every stage.

Every utility is judged the same way: `judge_candidate.sh CANDIDATE [FLAG...]`
runs the frozen cases whose required flags are all named on the command line.
Passing a checkpoint's **cumulative** flag list therefore re-runs every earlier
checkpoint's applicable cases as regression coverage. The agent may read the
tests it is given; it may not modify, weaken, or delete any part of them, and
tampering is detected and recorded in `metadata.json`.

### Generation, validation, and continuation

The generation path is:

```text
Qwen3.8-27B
    ↓
Aider architect/reasoning stage
    ↓
qwen3-coder-next
    ↓
Aider editor stage
    ↓
candidate source
    ↓
controller-owned build/tests
```

The editor model is Aider's editing phase, not a separate autonomous subagent.
After each one-shot Aider process the controller independently runs `--build-cmd`,
`--base-test-cmd`, and `--feature-test-cmd` inside the working directory. If any
of them fails, it renders a continuation prompt from
`prompts/repair_continuation_template.md` and starts a **new** Aider process
against the **same** working directory, so the model picks up where the previous
process left off. This repeats up to `--max-loops` times. Neither Aider model
runs validation or decides whether repair occurs.

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

For all four utilities that extra test is the held-out judging pass
(`scripts/heldout_judge.py`), which every manifest names through `$HELDOUT_ROOT`.
The runner exports that variable itself, pointing it at the repository root, so
no setup is needed: the command is evaluated in the controller's shell with the
working directory set to the attempt sandbox, and a relative path would resolve
inside the sandbox — exactly where held-out material must never be.

### Agent sandboxing

Each attempt runs in its own plain working directory containing only the prompt,
the checkpoint-specific `--test-dir` bundle and the `--seed-file` inputs. Aider
starts **inside** that directory with `--no-git`, `--no-gitignore`, a zero-token
repository map and a Git discovery ceiling at the directory's parent. It never
initializes a repository and cannot scan the parent checkout for a repo map.

The source path is the sole `--file` editable path. Visible text files already
copied into the attempt are explicit `--read` context; binary/compressed corpus
files remain available only to controller validation. Later checkpoint tests,
hidden tests, generators, specification models and every file outside the
attempt are absent from model context. Shell-command suggestions, automatic
linting and automatic testing are disabled, and stdin is closed. The harness
does not use blanket `--yes-always`; `--auto-accept-architect` only transfers
Aider's architect proposal into its configured editor phase.

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
kept at `<lineage>/<checkpoint>/test-bundle/` as the record of what was visible.
Its fingerprint is folded into the run's configuration fingerprint and re-checked
against the built bundle at every stage, so regenerated goldens or an edited
allowlist abort the run instead of silently mixing bundles.

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

Detecting that requires asserting "`-H` is still refused here", and the obvious
place to put such an assertion is the worst one: a frozen suite case spells the
flag out in its own argv, so shipping it at checkpoint 000 would hand the agent
the name of the option the checkpoint is withholding. Enforcement therefore
lives entirely outside anything the agent can read.

**`scripts/checkpoint_boundary_gate.py`** is a controller-only gate. It lives in
`scripts/`, which is never copied into a sandbox. The gate:

* runs **after** public validation has already succeeded, and **before** the
  candidate is promoted, against a rebuild of the captured candidate in a
  throwaway tree;
* is never copied into the worktree or the stage bundle;
* never feeds the repair loop — a failure is not reported back to the agent,
  because the diagnostic would name the flag;
* fails the stage with `premature_feature_implementation`, so the candidate is
  not promoted and the lineage produces no `final/` artifact. A gate that cannot
  run at all is recorded distinctly, as `boundary_gate_error`.

The availability matrix is derived from `experiments/utilities/<utility>.json`,
not written twice: a checkpoint's allowed set is its own cumulative
`implemented_flags`, and its forbidden set is every flag the manifest introduces
later. Only the short flags the manifest declares are probed — no alias is
invented.

For each forbidden flag the gate invokes the built candidate so that the only
thing wrong with the command line is that option, and requires a refusal:
nonzero exit, no termination by signal, no sanitizer diagnostic, nothing on
stdout, and a diagnostic on stderr. These are weak enough to accept any
reasonable "unknown option" handling and strong enough that actually honouring
the flag fails.

Because the matrix comes from the manifest rather than from frozen goldens, all
four utilities are covered uniformly. That closes an asymmetry the earlier
suite-case approach could not: `new_grep` and `new_chmod` freeze their goldens
from specification models that can be restricted to one checkpoint's option set,
but `new_sort` and `new_mkdir` freeze theirs by running a real system binary,
which implements `-r` and `-p` and so can never produce a "this must be
rejected" golden.

The prompts state only the current cumulative requirements plus a generic bound:

```text
Do not implement options or behavior outside this checkpoint's stated scope.
```

They never enumerate a later checkpoint's flags.

### Session statistics

Aider output is retained in `attempt-*/aider.log`. Controller metadata records
the backend exit code and wall time for every initial/repair invocation, plus
the exact architect/editor model pair and generated model settings. Aider does
not expose a stable local database equivalent to the previous backend's session
store, so new runs do not manufacture token-usage fields that cannot be
reliably recovered.

Legacy OpenCode attempts remain unchanged and analyzable. Their historical
session files retain their original names:

```text
attempt-001/opencode-stats.json   one record per session
attempt-001/opencode-stats.txt    the same, formatted for reading
```

`scripts/opencode_stats.py` is retained only as a legacy reader; the active
runner never calls it.

### Working directory cleanup

The working directory is a per-attempt copy of the test bundle, so it is deleted
once the attempt finishes. Before deletion the runner:

1. copies every kept source file into `attempt-*/candidate/`, **flattened** to
   its basename, with `candidate/manifest.json` recording the original layout;
2. writes the diff artifacts the analyzer reads;
3. hashes each copied `--test-dir` against its source, records
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

This removes the working directory from completed attempts. Incomplete attempts
are never touched.

### Failure classification

Each attempt distinguishes infrastructure attrition, invocation completion,
candidate availability, artifact validation, and workflow success. A
non-salvageable Aider error is an agent-execution failure. A
timeout that leaves a candidate remains an incomplete invocation, but the
controller may validate and repair that artifact and the workflow may succeed.
Build, public-test, and
hidden/extra-evaluator failures are candidate/workflow failures after
generation. A `feature_test_exit_code` of 3 is the suite's platform gate
refusing to judge on this host, and is classified with the infrastructure
failures rather than counted against the candidate.

A per-session timeout needs `timeout` or `gtimeout` on `PATH`. When neither is
available the runner warns, runs sessions unwrapped, and records
`timeout_enforced: false` so the distinction stays visible in analysis.

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

## Repository structure

```text
agentic_cyber/
├── Makefile
├── README.md
├── findings.md
├── docs/
│   ├── diversity_methodology.md            # Canonical v5.2.0/schema-v7 methodology
│   └── execution_consistency_methodology.md # Behavioral/execution consistency
├── experiments/
│   └── utilities/                          # One manifest per experimental utility
│       ├── README.md                       # Manifest schema and feature surfaces
│       └── chmod.json  grep.json  mkdir.json  sort.json
├── prompts/
│   ├── _shared/                            # Canonical automation notice, the one copy
│   ├── checkpoint_base_template.md
│   ├── checkpoint_feature_template.md
│   ├── repair_continuation_template.md     # Continuation prompt for repair loops
│   ├── chmod/                              # chmod checkpoints (000 -> -R -> -c -> -v -> -f)
│   ├── grep/                               # grep checkpoints  (000 -> -H -> -h -> -r -> -i)
│   ├── mkdir/                              # mkdir checkpoints (000 -> -p -> -m)
│   └── new_sort/                           # sort checkpoints  (000 -> -r -> -f -> -u -> -c)
├── scripts/
│   ├── analysis/                           # Canonical metric and validation modules
│   ├── analysis-requirements.txt
│   ├── aider_settings.py                   # Per-attempt architect/editor settings
│   ├── analyze_experiment.py               # Sole per-population analysis entry point
│   ├── analyze_lineages.py                 # Lineage aggregation; delegates diversity
│   ├── capture_candidate.py                # Flat capture, integrity check, cleanup
│   ├── check_heldout_isolation.py          # Asserts held-out material never leaks
│   ├── checkpoint_boundary_gate.py         # Controller-only premature-feature gate
│   ├── heldout_judge.py                    # Held-out corpus judging
│   ├── lineage_plan.py                     # Manifest -> stage plan + config fingerprint
│   ├── lineage_state.py                    # Atomic lineage.json state transitions
│   ├── measure_execution_consistency.py    # Behavioral fingerprints and convergence
│   ├── opencode_stats.py                   # Legacy OpenCode session-stat reader
│   ├── prompt_render.py                    # Single expansion point for that notice
│   ├── repair_prompt.py                    # Continuation prompt renderer
│   ├── run_experiment.sh                   # Single-stage experiment runner
│   ├── run_lineage_experiment.sh           # Lineage controller over the stage runner
│   ├── stage_test_bundle.py                # Per-checkpoint visible test bundle builder
│   └── timeout.py                          # `timeout` subset for hosts without coreutils
├── src/
│   ├── new_mkdir/                          # Checked-in mkdir implementation
│   └── new_sort/                           # Checked-in sort implementation
└── tests/
    ├── chmod-test-suite/                   # Model-derived goldens, isolated fixtures
    ├── grep-test-suite/                    # Model-derived goldens
    ├── mkdir-test-suite/                   # System-oracle goldens (requires Darwin)
    ├── sort-test-suite/                    # System-oracle goldens (requires Linux)
    ├── reference_generators/               # Specification models, outside every suite
    ├── test_execution_consistency.py       # Behavioral fingerprinting and agreement
    ├── test_lineage_tools.py               # Manifests, stage plan, lineage aggregation
    └── test_measure_diversity.py           # Analysis and controller tests
```

There is deliberately no `src/new_grep/` or `src/new_chmod/`: checkpoint 000 of
those lineages must make the agent create the source.

The ignored `build/` and `runs/` directories are generated locally. `make`
builds the checked-in sort implementation as `build/new_sort`, and `make clean`
removes the generated build files.
