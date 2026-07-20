# Agentic Cyber

An experimental repository for studying how LLM-generated software evolves
across a sequence of maintenance checkpoints.

Each checkpoint introduces a new feature while preserving the prompts,
repository state, generated implementations, and evaluation results needed to
regenerate and compare alternative repository histories.

## Running an Experiment

Run experiments from the repository root. OpenCode must be installed and
configured for the requested model, and the analyzer dependencies must be
available:

```bash
python3 -m pip install -r scripts/analysis-requirements.txt
```

For example, the following command runs 25 isolated attempts for the reverse
sorting checkpoint at temperature 0.7:

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

The required arguments are `--model`, `--temperature`, and `--prompt`. Use
`--source` and the test-command options to run other utilities or checkpoints.
See all available options with:

```bash
bash scripts/run_llm_experiment.sh --help
```

Each attempt runs in a detached Git worktree. Completed attempts are skipped
when the same command is resumed; pass `--force` to regenerate them. After all
attempts, the analyzer runs automatically and writes per-experiment results to
`<experiment>/analysis/` and aggregate paper metrics to
`runs/experiments/paper_metrics.csv` and
`runs/experiments/paper_metrics.json`.

Unless `--output-dir` is supplied, experiments are stored under:

```text
runs/experiments/<model>/<checkpoint>/temp-<temperature>/
```

### Running the mkdir checkpoints (no Git)

`mkdir` is validated by a standalone, exhaustive golden/fuzz suite
(`tests/mkdir-test-suite/`) instead of hand-authored per-checkpoint unittest
files, via `tests/mkdir-test-suite/judge_candidate.sh CANDIDATE_BIN [FLAG...]`
(see that suite's own README). Its prompts (`prompts/mkdir/000_base_new_mkdir.md`,
`001_parents.md`, `002_mode.md`) have the agent compile directly with `cc` (no
Makefile) and run that command itself, iterating until every test passes — so
there is no baseline to git-diff against and no build/test step the harness
needs to drive. `scripts/run_sandboxed_pipeline.sh` runs this style of prompt
in a plain temporary directory instead of a Git worktree: for each of `--runs`
equally-spaced temperature points, it copies the prompt and any `--test-dir`
paths into a fresh working directory, runs OpenCode with `--dir` pointed at it
(and a permission config that denies every other path), and leaves whatever
OpenCode generated sitting in that same directory:

```bash
# Milestone 1 -- base (from-scratch; no --seed-file)
bash scripts/run_sandboxed_pipeline.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --runs 10 --temp-min 0 --temp-max 2 \
    --prompt prompts/mkdir/000_base_new_mkdir.md \
    --test-dir tests/mkdir-test-suite \
    --test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir" \
    --output-dir runs/sandboxed/mkdir/milestone-1
# -> inspect runs/sandboxed/mkdir/milestone-1/temp-*/{opencode.log,test.log,metadata.json},
#    pick a winning temp-*/workdir/src/new_mkdir/new_mkdir.c.

# Milestone 2 -- parents, seeded from the milestone-1 winner
bash scripts/run_sandboxed_pipeline.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --runs 10 --temp-min 0 --temp-max 2 \
    --prompt prompts/mkdir/001_parents.md \
    --test-dir tests/mkdir-test-suite \
    --seed-file "runs/sandboxed/mkdir/milestone-1/temp-0p0/workdir/src/new_mkdir/new_mkdir.c:src/new_mkdir/new_mkdir.c" \
    --test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir -p" \
    --output-dir runs/sandboxed/mkdir/milestone-2

# Milestone 3 -- mode, seeded from the milestone-2 winner
bash scripts/run_sandboxed_pipeline.sh \
    --model school-ollama/qwen3-coder-next:latest \
    --runs 10 --temp-min 0 --temp-max 2 \
    --prompt prompts/mkdir/002_mode.md \
    --test-dir tests/mkdir-test-suite \
    --seed-file "runs/sandboxed/mkdir/milestone-2/temp-0p0/workdir/src/new_mkdir/new_mkdir.c:src/new_mkdir/new_mkdir.c" \
    --test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir -p -m" \
    --output-dir runs/sandboxed/mkdir/milestone-3
```

`--seed-file SRC[:DEST]` copies an existing file into the working directory at
`DEST` (default: `SRC`'s own path) before OpenCode runs, so incremental
checkpoints can read/modify "the current program" without any commit step —
point it either at a promoted winner in the real tree or directly at a
previous run's own `workdir/` output under `runs/`. `--test-cmd` is the
harness's own independent confirmation, run once after OpenCode exits; the
agent is already instructed by the prompt to self-test and iterate, so this
just records a final pass/fail in `metadata.json`. See
`scripts/run_sandboxed_pipeline.sh --help` for all options, including
`--temp-min`/`--temp-max` (default `0`/`2`) and `--remote-base-url`/
`--remote-api-key-env` for a self-hosted OpenAI-compatible endpoint.

Unlike `run_llm_experiment.sh`, this script uses no Git at all: no worktrees,
no commits, no diffing, no `analyze_experiment.py` call. It's a separate,
simpler alternative for prompts that don't need git-diff-based baseline
comparison, not a replacement for the `new_sort` workflow above.

## Measuring implementation diversity

`scripts/measure_diversity.py` compares a set of independently generated
implementations of the same utility (e.g. multiple `new_mkdir.c` samples
under `runs/`) and reports how different they actually are, at several
levels each grounded in an established code-similarity/clone-detection
paradigm (lexical, AST, API/strategy, security-construct "attack surface",
and optionally neural). See `docs/diversity_methodology.md` for the full
methodology, citations, and interpretation guidance.

```bash
python3 -m pip install -r scripts/diversity-requirements.txt
python3 scripts/measure_diversity.py "runs/**/new_mkdir.c" --out-dir runs/diversity
python3 scripts/measure_diversity.py --calibrate   # sanity-check the tool itself
```

`tests/diversity-anchors/` vendors independently developed real-world
implementations (GNU coreutils, BusyBox, toybox, FreeBSD, NetBSD `mkdir`)
to use as a diversity reference point via `--reference`.

## Repository Structure

```text
agentic_cyber/
├── .gitignore
├── Makefile
├── README.md
│
├── build/                                  # Generated locally; ignored by Git
│   └── new_sort                            # Compiled executable created by make
│
├── prompts/
│   ├── checkpoint_feature_template.md      # Generic feature-prompt template
│   ├── checkpoint_base_template.md         # Generic from-scratch build template
│   │
│   ├── new_sort/
│   │   ├── 000_base_new_sort.md            # Base implementation prompt
│   │   ├── 001_reverse.md                  # Add -r / --reverse
│   │   ├── 002_ignore_case.md              # Add -f / --ignore-case
│   │   ├── 003_unique.md                   # Add -u / --unique
│   │   ├── 004_random_sort.md              # Add -R / --random-sort
│   │   │
│   │   └── tests/
│   │       ├── 001_reverse_tests.md
│   │       ├── 002_ignore_case_tests.md
│   │       ├── 003_unique_tests.md
│   │       └── 004_random_sort_tests.md
│   │
│   └── mkdir/
│       ├── 000_base_new_mkdir.md           # Base implementation prompt (no flags)
│       ├── 001_parents.md                  # Add -p / --parents
│       └── 002_mode.md                     # Add -m / --mode
│
├── scripts/
│   ├── analysis-requirements.txt           # Python analysis dependencies (analyze_experiment.py)
│   ├── analyze_experiment.py               # Metrics and clustering analyzer
│   ├── diversity-requirements.txt          # Python dependencies (measure_diversity.py)
│   ├── measure_diversity.py                # N-version implementation-diversity metrics
│   ├── run_llm_experiment.sh               # Isolated multi-run experiment runner (Git worktrees)
│   └── run_sandboxed_pipeline.sh           # No-Git temp-directory pipeline (mkdir checkpoints)
│
├── docs/
│   └── diversity_methodology.md            # Methodology behind measure_diversity.py
│
├── src/
│   └── new_sort/
│       ├── README.md                       # new_sort usage documentation
│       └── new_sort.c                      # new_sort C implementation
│
└── tests/
    ├── new_sort/
    │   ├── test_new_sort.py                # Baseline new_sort tests
    │   ├── test_001_reverse.py             # Reverse-sort checkpoint tests
    │   ├── test_002_ignore_case.py         # Ignore-case checkpoint tests
    │   ├── test_003_unique.py              # Unique-output checkpoint tests
    │   └── test_004_random_sort.py         # Random-sort checkpoint tests
    │
    ├── mkdir-test-suite/                   # Standalone exhaustive golden/fuzz suite
    │   ├── judge_candidate.sh              # Per-checkpoint harness entry point
    │   └── ...                            # config.json, runner.py, suites/, etc.
    │
    ├── diversity-anchors/mkdir/            # Vendored real-world mkdir implementations
    │   ├── SOURCES.md                      # Provenance/license for each vendored file
    │   └── *.c                             # GNU coreutils, BusyBox, toybox, FreeBSD, NetBSD
    │
    └── test_measure_diversity.py           # Unit tests for measure_diversity.py
```

The `build/` and `runs/` directories are generated locally and are not stored
in GitHub. The build directory is created when running:

```bash
make
```

The command compiles:

```text
src/new_sort/new_sort.c
```

and creates:

```text
build/new_sort
```

Running:

```bash
make clean
```

removes the generated `build/` directory.
