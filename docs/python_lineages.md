# Python functional lineages

These utilities use the existing manifest, Aider architect/editor, stage-bundle,
repair, boundary-gate and promotion pipeline. No candidate implementation or
seed is supplied. Checkpoint 000 starts with an absent source file; every later
checkpoint inherits only the preceding candidate from the same lineage.

| Utility selector | Candidate source | Cumulative ladder |
|---|---|---|
| python-cp | src/python-cp/new_cp.py | base; -f; -f -i; -f -i -r |
| python-mv | src/python-mv/new_mv.py | base; -f; -f -i |
| python-ls | src/python-ls/new_ls.py | base; -a; -a -l; -a -l -R |
| python-mkdir | src/python-mkdir/new_mkdir.py | base; -p; -p -m |

Each prompt includes the complete baseline, inherited features, the new feature,
reserved options, argument/error contract and standard-library-only restriction.
The shared automation notice and repair template are rendered by the existing
controller. Delegation to external utilities, shells or subprocesses is forbidden.
As in the existing suites, this is an implementation requirement, not a claim
that the functional harness is an operating-system security sandbox.

## Interpreter and validation

Use the repository's supported Python 3 environment (3.11 or newer), selected
with `PYTHON_BIN`. Both controllers resolve that interpreter to `sys.executable`.
The manifest invokes `scripts/python_candidate.py`, which requires nonempty
source and compiles it in memory without executing it or writing bytecode.
Syntax failures return a nonzero build status and enter the existing repair loop.
Successful checks create a disposable executable launcher in `build/new_NAME.py`
that uses that exact interpreter; candidate source snapshots remain `.py` files.
The requested generated source itself must be a standalone program with a shebang.

Public validation retains `public-validation-N.json` for each executed test pass
beside the existing build/test logs and loop metadata. After public repair,
`heldout-validation.json` records isolated evaluation. A syntax failure has build
logs and the existing loop result but no public-test JSON because tests did not
execute. Reports are outside the agent workspace and the immutable test bundle.
Held-out results never become repair feedback. Fixed per-lineage sampling seeds,
source hashes, checkpoint inheritance and promotion rules are unchanged.

Python is functional-only: the existing C/Rust structural and security evaluators
do not support Python and are not run for these selectors. Their absence is not a
security pass. Existing manifest/result schemas and C/Rust execution remain intact.

## Suites and oracle

The four `tests/python-NAME-test-suite/` directories follow the Rust suite layout:
`config.json`, `config.py`, `engine.py`, `runner.py`, `props.py`,
`judge_candidate.sh`, `gen/generate.py`, `selfcheck.sh`, frozen public cases under
`suites/`, and a separate compressed corpus under `heldout/`.
Offline scenario definitions are in `tests/reference_generators/python_cases.py`.
Transfers reuse the Rust transfer scenarios; Python MV changes only their rung
assignment to introduce force before interactive. No utility implementation model
is included. Expected outcomes are obtained from independent GNU executables.

GNU Coreutils **9.11** is required for regeneration and self-checks. Set each
`NAME_ORACLE_BIN` to an absolute path to that GNU executable; program/version checks
fail closed. BSD/macOS commands are never substituted. Ordinary candidate judging
uses committed goldens and does not need the oracle installed.

Every case executes in its own disposable directory with pipe I/O, C locale and
a controlled environment. The engine compares exit status, exact stdout,
stderr presence/class, complete filesystem path/type/content state, symlink
targets and selected modes. Error wording and host-specific errno text are not
frozen. Permission tests require a non-root user. Generation runs twice, checks
byte-identical output, fixes gzip timestamps and records SHA-256 digests.

| Checkpoint | python-cp public / held-out | python-mv public / held-out | python-ls public / held-out | python-mkdir public / held-out |
|---|---:|---:|---:|---:|
| 000 | 36 / 36 | 38 / 38 | 18 / 18 | 21 / 21 |
| 001 | 41 / 41 | 42 / 42 | 23 / 23 | 31 / 31 |
| 002 | 58 / 58 | 57 / 57 | 29 / 29 | 63 / 63 |
| 003 | 70 / 70 | — | 36 / 36 | — |

Counts are cumulative. Held-out cases are separately frozen duals with distinct
paths/data, not additional requirements. The existing allowlisted stage-bundle
builder exposes only applicable public cases and their runtime harness. Offline
generators, full ladders, oracle paths, READMEs and held-out corpora are excluded.
The existing isolation scanner checks every checkpoint. Future-option rejection
is checked by controller-only probes, not future-feature public cases.

## Bounded and platform-sensitive behavior

* CP/MV retain the Rust POSIX Linux/Darwin, same-filesystem contract. EXDEV fallback,
  ownership/ACL/xattr preservation, special file types, trailing-slash symlink
  operands and filesystem races are outside it. Existing raw-byte path handling
  is required where the filesystem supports it; portable frozen cases use missing
  non-UTF-8 operands rather than creating APFS-incompatible names.
* LS uses nonterminal single-column output, byte ordering in locale C, literal
  names, `TZ=UTC` and `TIME_STYLE=long-iso`. Block-size overrides are unset.
  Long-listing ownership, link counts, sizes, timestamps and allocated totals are
  validated against the live fixture before normalization; they are not ignored.
  Permission/type strings, names, link targets, order, headers and blank lines
  remain exact. Fixtures have fixed timestamps and a private parent directory.
  Terminal layout, colors, ACL/security-context markers and special files are
  outside the contract. Normalization tolerates field alignment whitespace.
* MKDIR is explicitly **Linux-pinned**. GNU 9.11 symbolic modes have a known
  Linux/Darwin difference already documented by the existing C mkdir suite. This
  new corpus checks numeric and symbolic modes, special bits, omitted classes,
  permission copying, repeated options, umasks and parents/final-mode interaction.
  It refuses incompatible hosts instead of reporting candidate defects or using
  BSD semantics. A Darwin Python mkdir corpus needs separate GNU validation.
* Linux self-checks do not constitute Darwin validation of CP/MV/LS. Run their
  self-checks against GNU 9.11 on the target Darwin host before collecting data.

## Local checks (no model calls)

Run from the repository root as a non-root Linux user, including under WSL:

```bash
export PYTHON_BIN="$(command -v python3)"  # or the absolute supported venv interpreter
export PYTHONDONTWRITEBYTECODE=1
export CP_ORACLE_BIN=/absolute/gnu-coreutils-9.11/src/cp
export MV_ORACLE_BIN=/absolute/gnu-coreutils-9.11/src/mv
export LS_ORACLE_BIN=/absolute/gnu-coreutils-9.11/src/ls
export MKDIR_ORACLE_BIN=/absolute/gnu-coreutils-9.11/src/mkdir
for utility in cp mv ls mkdir; do
  bash "tests/python-$utility-test-suite/selfcheck.sh"
done
"$PYTHON_BIN" -B -m unittest discover -s tests -p 'test_*.py' -v
"$PYTHON_BIN" -B scripts/check_heldout_isolation.py
```

Self-checks regenerate twice without changing committed files, verify hashes and
isolation, and invoke actual staged public and isolated held-out judges at every
checkpoint. For intentional corpus maintenance only, omit `--check` when invoking
`gen/generate.py`. `--audit` requires no oracle and checks committed corpus integrity
and isolation. No generated candidates, oracle installations/caches or run outputs
should be added to Git.

To judge a separately generated candidate manually, first run the syntax helper,
then the appropriate judge with the cumulative flags. For example:

```bash
"$PYTHON_BIN" -B scripts/python_candidate.py /absolute/new_cp.py /tmp/python-cp-launcher
VALIDATION_JSON_REPORT=/tmp/python-cp-validation.json \
  bash tests/python-cp-test-suite/judge_candidate.sh /tmp/python-cp-launcher -f -i
```

## One diagnostic lineage per utility

These are explicit diagnostic settings, not new runner defaults. They require the
existing Aider/backend setup and available models. Run MKDIR on Linux. The commands
are provided for a later operator invocation; infrastructure self-checks do not
launch them. Use fresh output directories.

```bash
export PYTHON_BIN="$(command -v python3)"
common=(--model ollama_chat/qwen3.8:27b
        --editor-model ollama_chat/qwen3-coder-next:latest
        --architect-think false --temperature 0 --sampling-seed 42
        --num-ctx 65536 --lineages 1 --max-loops 3
        --remote-base-url http://localhost:11434 --no-security-evaluation)
bash scripts/run_lineage_experiment.sh --utility python-cp "${common[@]}" --output-dir runs/diagnostic/python-cp
bash scripts/run_lineage_experiment.sh --utility python-mv "${common[@]}" --output-dir runs/diagnostic/python-mv
bash scripts/run_lineage_experiment.sh --utility python-ls "${common[@]}" --output-dir runs/diagnostic/python-ls
bash scripts/run_lineage_experiment.sh --utility python-mkdir "${common[@]}" --output-dir runs/diagnostic/python-mkdir
```

Append `--print-plan` to inspect a plan without generation. The explicit context
capacity applies to Ollama allocation; choose a capacity that fits the target host
before collecting data. No model settings are changed by installing these suites.
