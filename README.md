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
    --build-cmd "<build command>" \
    --base-test-cmd "<baseline test command>" \
    --feature-test-cmd "<checkpoint test command>" \
    --extra-test-cmd "<optional independent test command>"
```

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

## Canonical Analysis

`scripts/analyze_experiment.py` is the sole analysis entry point. The Git
experiment runner invokes it automatically after all attempts. To reproduce or
extend an analysis manually, pass only the experiment directory; the analyzer
reads the target source and baseline locations from `experiment.json`:

```bash
EXPERIMENT=runs/experiments/<model>/<checkpoint>/temp-<temperature>

python3 scripts/analyze_experiment.py \
    --experiment "$EXPERIMENT" \
    --cluster-threshold 0.30 \
    --strategy-threshold 0.30 \
    --diversity-k-max 25 \
    --clean-output
```

Use a common `--diversity-k-max` supported by every compared population for
cross-condition NAUADC@K. Omit it when only complete within-population curves
are needed. Detailed construct-validation artifacts and plots are opt-in:

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

The analyzer writes schema-v4 results under `<experiment>/analysis/`. The main
files are `summary.json`, `per_run_metrics.csv`, `paper_metrics.csv`,
`paper_descriptive_metrics.csv`, diversity family assignments and DA curves,
robustness tables, and uncertainty intervals. It rebuilds the repository-level
`runs/experiments/paper_metrics.csv` and `paper_metrics.json` from valid
per-experiment v4 rows. See `docs/diversity_methodology.md` for metric roles,
population rules, formulas, output layout, and interpretation.

## No-Git Sandbox Runner

`scripts/run_sandboxed_pipeline.sh` is a separate runner for from-scratch or
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

## Repository Structure

```text
agentic_cyber/
├── Makefile
├── README.md
├── docs/
│   └── diversity_methodology.md          # Canonical v4 methodology
├── prompts/
│   ├── checkpoint_base_template.md
│   ├── checkpoint_feature_template.md
│   ├── mkdir/                             # mkdir checkpoints
│   └── new_sort/                          # sort checkpoints and prompt tests
├── scripts/
│   ├── analysis/                          # v4 metric and validation modules
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
