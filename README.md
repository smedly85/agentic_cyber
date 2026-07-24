# Agentic Cyber

An experimental repository for studying how LLM-generated software evolves
across maintenance checkpoints. Each checkpoint preserves the prompt, baseline
repository state, generated candidates, validation results, and metadata needed
to reproduce and compare independent repository histories.

## Requirements

Run experiments from the repository root. OpenCode must be installed and
configured for the requested model. Install the canonical analyzer's Python
dependencies with:

```bash
python3 -m pip install -r scripts/analysis-requirements.txt
```

The analyzer also expects `clang` and `gumtree` on `PATH` for complete
architecture measurement. The static security cross-check is optional.

## Running an Experiment

`scripts/run_llm_experiment.sh` runs repeated patch-generation attempts from a
common Git baseline in detached worktrees. The required arguments are
`--model`, `--temperature`, and `--prompt`. Select any sort, mkdir, or future
utility by supplying its checkpoint prompt, repository-relative primary source
path, and validation commands rather than by changing the analysis command:

```bash
PROMPT=<repository-relative checkpoint prompt path>
SOURCE=<repository-relative primary source path>

bash scripts/run_llm_experiment.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --temperature 0.7 \
    --runs 25 \
    --max-loops 3 \
    --prompt "$PROMPT" \
    --source "$SOURCE" \
    --source-mode existing \
    --build-cmd "<build command>" \
    --base-test-cmd "<baseline test command>" \
    --feature-test-cmd "<checkpoint test command>" \
    --extra-test-cmd "<optional independent test command>"
```

Use `--source-mode existing` when the source is present in the selected baseline
commit. Use `--source-mode new` when the source must be absent. New-source mode
records an empty `baseline/<source_path>` snapshot but does not create the file
in the agent worktree; the model must create it. Existing-source sort and
new-source mkdir tasks can therefore use the same Git controller, bounded
repair loop, one-time hidden/extra evaluation, and canonical analyzer.
For new-source analysis, the known C entry point remains literally `main` in
both structural representations while arbitrary created helper names are
canonicalized.

For example, the reverse-sort checkpoint is:

```bash
bash scripts/run_llm_experiment.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --temperature 0.7 \
    --runs 25 \
    --prompt prompts/new_sort/001_reverse.md \
    --source src/new_sort/new_sort.c \
    --feature-test-cmd \
        "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/new_sort/test_001_reverse.py -v"
```

Each attempt starts at the same `--base-ref`. After the initial generation, a
failed public build/base/checkpoint validation may trigger at most `--max-loops`
repair invocations. Repair prompts contain only failing validation output,
deterministically limited to its final 16,000 characters. The optional extra
test runs once after the generation/repair loop and is not fed back to the
model. Generated changes are never committed.

Completed attempts are skipped when a command is resumed; pass `--force` to
regenerate them. See all runner options with:

```bash
bash scripts/run_llm_experiment.sh --help
```

Unless `--output-dir` is supplied, experiments are stored under:

```text
runs/experiments/<model>/<checkpoint>/temp-<temperature>/
```

The runner writes `experiment.json`, including `source_path`, baseline commit,
prompt, model, temperature, validation commands, and repair budget. It also
stores the baseline at `baseline/<source_path>` and each final candidate at
`attempt-*/candidate/<source_path>`. These metadata and source paths make the
same analysis invocation applicable to sort, mkdir, and future utilities.
Each attempt distinguishes setup infrastructure attrition from agent-execution
failure and candidate failure. Worktree/setup failure before invocation is
infrastructure attrition. Timeout, permission rejection, and a nonzero attempted
OpenCode invocation are failed valid agent trials. Build, public-test, and
hidden/extra-evaluator failures are candidate/workflow failures after generation.

Automatic analysis accepts `--analysis-architecture-threshold`,
`--analysis-strategy-threshold`, and optional `--analysis-diversity-k-max`.
The compatibility option `--analysis-threshold` sets both thresholds unless a
corresponding specific option overrides it. Without the shorthand, strategy
defaults to the resolved architecture threshold. K remains unset unless
explicitly supplied and is never inferred from successful-run count. Resolved
values are recorded in `experiment.json` and `analysis/summary.json`.

## Canonical Analysis

`scripts/analyze_experiment.py` is the sole analysis entry point. The Git
experiment runner invokes it automatically after all attempts. To reproduce or
extend an analysis manually, pass only the experiment directory; the analyzer
reads the target source, baseline, thresholds, and fixed K from
`experiment.json`:

```bash
EXPERIMENT=runs/experiments/<model>/<checkpoint>/temp-<temperature>

python3 scripts/analyze_experiment.py \
    --experiment "$EXPERIMENT" \
    --clean-output
```

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
`runs/experiments/paper_metrics.csv` and `paper_metrics.json` only from valid,
mutually compatible schema-v5 rows. A readable analysis signature covers both
thresholds, K, strategy scope, and `main` inclusion. Mixed signatures are
skipped and audited in `paper_metrics_metadata.json`. Historical experiments
must be re-analyzed with analyzer v4.1.1 before entering the final aggregate.

One complete generation/repair trajectory is one independent attempt.
Infrastructure attrition remains visible in end-to-end reliability but is
excluded from valid-agent denominators for initial/final public success, repair
recovery, and Pass@k. Agent-execution failures remain in those valid-agent
denominators: in particular, a timeout is a failed generated sample for Pass@k.
End-to-end success uses every analyzed attempt. Failed generated implementations
remain reliability failures but do not enter primary diversity. Repeated byte-identical successful
outputs remain separate diversity observations. Architecture means structural
organization of the configured primary C source, not repository- or system-wide
architecture; implementation strategy is separate. Primary strategy includes
`main`; excluding `main` is a diagnostic robustness ablation only. See
`docs/diversity_methodology.md` for formulas and interpretation.

## Exploratory No-Git Sandbox Runner

`scripts/run_sandboxed_pipeline.sh` is retained as an exploratory/legacy runner
for pilot and historical work. It is a separate runner for from-scratch or
seeded prompts that do not need a Git baseline. It creates a fresh plain
directory for each equally spaced temperature point, copies the prompt and any
`--test-dir` paths, applies any `--seed-file SRC[:DEST]` inputs, runs OpenCode,
and executes `--test-cmd` once afterward as an independent confirmation. It
does not create worktrees, commits, diffs, repair loops, or canonical analysis
artifacts.

For example, the mkdir checkpoints can be generated sequentially with the
standalone golden/fuzz judge:

```bash
# Base implementation, generated from scratch.
bash scripts/run_sandboxed_pipeline.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --runs 10 --temp-min 0 --temp-max 2 \
    --prompt prompts/mkdir/000_base_new_mkdir.md \
    --test-dir tests/mkdir-test-suite \
    --test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir" \
    --output-dir runs/sandboxed/mkdir/milestone-1

# Later checkpoint, seeded from a promoted prior candidate.
bash scripts/run_sandboxed_pipeline.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --runs 10 --temp-min 0 --temp-max 2 \
    --prompt prompts/mkdir/001_parents.md \
    --test-dir tests/mkdir-test-suite \
    --seed-file "<prior-workdir>/src/new_mkdir/new_mkdir.c:src/new_mkdir/new_mkdir.c" \
    --test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir -p" \
    --output-dir runs/sandboxed/mkdir/milestone-2
```

`--seed-file` defaults its destination to the source path when `:DEST` is
omitted. The prompt instructs the agent to compile, self-test, and iterate;
`--test-cmd` only records the runner's final pass/fail in `metadata.json`. See
`scripts/run_sandboxed_pipeline.sh --help` for endpoint and temperature options.

The same analyzer accepts one sandbox temperature condition. Legacy `run.json`
does not record the generated source path, so provide it explicitly. Seeded
runs derive the baseline from the matching recorded `--seed-file`; unseeded
from-scratch runs use an empty C translation unit as their recorded analysis
baseline:

```bash
python3 scripts/analyze_experiment.py \
    --experiment runs/sandboxed/mkdir/milestone-1/temp-0p0 \
    --source-path src/new_mkdir/new_mkdir.c \
    --cluster-threshold 0.30 \
    --strategy-threshold 0.30 \
    --clean-output
```

Analyze each `temp-*` condition separately. The analyzer rejects a sandbox root
containing multiple temperatures rather than pooling different experimental
conditions. `--baseline-source` can explicitly override baseline discovery.

The Git-backed `run_llm_experiment.sh` workflow is the intended confirmatory
workflow for cross-utility conference comparisons. Sandbox results remain
analyzable, but runs generated under materially different agent-feedback or
controller protocols must not be pooled as one condition. Sandbox rows are not
automatically added to the repository-level confirmatory paper aggregate.

## Repository Structure

```text
agentic_cyber/
├── Makefile
├── README.md
├── docs/
│   └── diversity_methodology.md          # Canonical v4.1.1/schema-v5 methodology
├── prompts/
│   ├── checkpoint_base_template.md
│   ├── checkpoint_feature_template.md
│   ├── mkdir/                             # mkdir checkpoints
│   └── new_sort/                          # sort checkpoints and prompt tests
├── scripts/
│   ├── analysis/                          # Canonical metric and validation modules
│   ├── analysis-requirements.txt
│   ├── analyze_experiment.py              # Sole analysis entry point
│   ├── run_llm_experiment.sh              # Git-worktree experiment runner
│   └── run_sandboxed_pipeline.sh           # Separate no-Git generator
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
