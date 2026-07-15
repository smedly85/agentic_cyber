# Agentic Cyber

An experimental repository for studying how LLM-generated software evolves
across a sequence of maintenance checkpoints.

Each checkpoint introduces a new feature while preserving the prompts,
repository state, generated implementations, and evaluation results needed to
regenerate and compare alternative repository histories.

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
├── src/
│   └── new_sort/
│       ├── README.md                       # new_sort usage documentation
│       └── new_sort.c                      # new_sort C implementation
│
└── tests/
    └── new_sort/
        └── test_new_sort.py                # Baseline new_sort tests
```

The `build/` directory is not stored in GitHub. It is created locally when
running:

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
