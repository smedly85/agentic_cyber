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
│   │
│   └── new_sort/
│       ├── 000_base_new_sort.md            # Base implementation prompt
│       ├── 001_reverse.md                  # Add -r / --reverse
│       ├── 002_ignore_case.md              # Add -f / --ignore-case
│       ├── 003_unique.md                   # Add -u / --unique
│       ├── 004_random_sort.md              # Add -R / --random-sort
│       │
│       └── tests/
│           ├── 001_reverse_tests.md
│           ├── 002_ignore_case_tests.md
│           ├── 003_unique_tests.md
│           └── 004_random_sort_tests.md
│
├── scripts/
│   ├── analysis-requirements.txt           # Python analysis dependencies
│   ├── analyze_experiment.py               # Metrics and clustering analyzer
│   └── run_llm_experiment.sh               # Isolated multi-run experiment runner
│
├── src/
│   └── new_sort/
│       ├── README.md                       # new_sort usage documentation
│       └── new_sort.c                      # new_sort C implementation
│
└── tests/
    └── new_sort/
        ├── test_new_sort.py                # Baseline new_sort tests
        ├── test_001_reverse.py             # Reverse-sort checkpoint tests
        ├── test_002_ignore_case.py         # Ignore-case checkpoint tests
        ├── test_003_unique.py              # Unique-output checkpoint tests
        └── test_004_random_sort.py         # Random-sort checkpoint tests
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
