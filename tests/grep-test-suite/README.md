# new_grep test suite

Deterministic checkpoint tests for the bounded `new_grep` experiment
(`experiments/utilities/grep.json`). Same shape as the sort and mkdir suites:
frozen cases under `suites/`, a config describing which flags the candidate
implements, a runner that filters cases by that list, and a checkpoint wrapper
that supplies the candidate path at run time.

## Checkpoint interface

```bash
tests/grep-test-suite/judge_candidate.sh build/new_grep                 # 000
tests/grep-test-suite/judge_candidate.sh build/new_grep -H              # 001
tests/grep-test-suite/judge_candidate.sh build/new_grep -H -h           # 002
tests/grep-test-suite/judge_candidate.sh build/new_grep -H -h -r        # 003
tests/grep-test-suite/judge_candidate.sh build/new_grep -H -h -r -i     # 004
```

The flag list is **cumulative**. A frozen case runs only when every flag in its
own `flags` list is present, so a later checkpoint automatically re-runs every
earlier checkpoint's applicable cases as regression coverage, and never reaches
a feature that does not exist yet. Base-tier cases (`flags: []`) run at every
checkpoint.

Coverage grows monotonically: 38 cases at 000, 44 at 001, 53 at 002, 67 at 003,
82 at 004, out of 88 frozen. `gen/verify.py` enforces both the growth and the
non-emptiness, and prints these counts. (000 through 003 include the
`absent_flags` cases that assert a later flag is *not* implemented yet; each
disappears at the checkpoint that introduces its flag, which is why the total
selected at 004 is lower than the corpus.)

`judge_candidate.sh` writes its runtime configuration to a throwaway file and
never modifies the committed `config.json`, so it is safe to call repeatedly
from an experiment harness with no shared mutable state.

## Where the goldens come from

**78 of the 88 frozen cases are derived from a real GNU grep**, the same way the
sort and mkdir suites use a real coreutils binary. The remaining 10 cannot come
from any grep and are listed by name, with a reason each, in
`suites/MANIFEST.json` under `model_only_cases`.

This suite previously claimed GNU grep could not be an oracle at all, because
`new_grep`'s PATTERN is a literal byte string rather than a regular expression.
That was incomplete: `grep -F` (`--fixed-strings`) treats PATTERN as a literal
substring, which *is* `new_grep`'s matching contract.

### Platform contract: none, and that is a measured result

**This suite is deliberately ungated — it declares no `required_platform`.**
The sort and mkdir suites each do, so the absence here is a finding rather than
an omission.

Checked directly rather than assumed, using the same method that settled sort's
gate: GNU grep 3.12 was built from source on Darwin, the full corpus was
regenerated there through the oracle path, and the result was compared against
the committed Linux-derived goldens.

| | |
|---|---|
| Method | oracle-backed regeneration on Darwin 3.12 vs committed Linux 3.12 |
| Cases compared | 88 (78 oracle-derived, 10 specification-model) |
| Result | `diff -r` byte-identical across every tier |

So `grep` is gated nowhere, because there is nothing to gate against. Adding
`required_platform` here would be protection theater: a check that can never
fire, obscuring the two suites where the gate is load-bearing.

The likeliest source of divergence is already neutralised by construction —
`engine.py` and `gen/oracle.py`'s `ORACLE_ENV` both pin `LC_ALL`, `LANG` and
`LC_CTYPE` to `C`, so locale-dependent case folding and binary detection cannot
vary by host. The behavioral precheck in `gen/oracle.py` runs on whatever
platform regenerates, and refuses a binary that drops CR, mis-folds under
`LC_ALL=C`, or sits on a filesystem that ignores mode 0000 — so a future
platform difference would surface as a refusal, not as silently wrong goldens.

### Oracle contract

Pinned to **GNU grep 3.12** (`oracle_version_required` in `config.json`, echoed
as `grep_version` in `suites/MANIFEST.json`). Note that grep is **not** part of
GNU coreutils: the sort and mkdir suites pin coreutils 9.11, and grep's 3.12 is
its own project's version series. There is no coreutils-numbered grep.

Resolution order, matching the other suites: `--oracle-bin` >
`$GREP_ORACLE_BIN` > `config.json` `paths.oracle_bin` > a conventional
location. On Linux/WSL `/usr/bin/grep` is already GNU; on macOS the system grep
is BSD, so build 3.12 from source or `brew install grep` and point
`GREP_ORACLE_BIN` at its `gnubin/grep` (or `ggrep`).

Three invocation-level adjustments make a live grep speak this contract. Each
was verified against the binary rather than assumed:

| Adjustment | Why | What was observed |
|---|---|---|
| `-F` | PATTERN is literal bytes | `-F 'a.c'` selects only `a.c`; without `-F` it also selects `abc` and `aXc`. Same for `*`, `[`, `^`, `$`, `\`. An empty PATTERN selects every line |
| `-a` | NUL bytes are ordinary data | Plain `-F` suppresses the line and reports "binary file matches" — on **stdout** in grep 3.0, on **stderr** in 3.12. `-a` prints the line with its NUL bytes intact, and is byte-identical to plain `-F` for input that has none |
| `LC_ALL=C` | `-i` folds `A`–`Z` only | Under `C.UTF-8` a live grep also folds U+00C9/U+00E9 together; under `C` it does not. `LANG`, `LC_CTYPE` and `LC_COLLATE` are pinned too, since `LC_CTYPE` alone re-enables multibyte folding |

Two contract points needed no adjustment and are confirmed rather than assumed:
a match on a final line with **no trailing newline** is still emitted *with* one,
and a **directory operand without `-r`** is a diagnosed error with exit 2.

### `-r` order is computed, not taken from `grep -r`

GNU grep's own recursive walk follows raw `readdir` order. The same tree
produced two different orders on two hosts, and neither matched the contract
(pre-order, ascending byte order of entry name). Freezing from `grep -r` would
bake one filesystem's directory order into the benchmark.

So `gen/oracle.py` computes the traversal itself and invokes the oracle **once
per file, non-recursively**. Every byte of every emitted line still comes from
the live grep; only the visiting order comes from the contract. Symlink handling
needed no such treatment — GNU grep `-r` skips symlinks met during traversal,
which is already what the contract says (verified: a symlink to a file is not
read, a symlink to a directory is not descended).

### The 10 cases a real grep cannot produce

* **Nine argument-grammar cases.** `new_grep` implements five options and
  rejects everything else, so a case asserting an option is *rejected* is a
  statement about the bounded utility, not about fixed-string matching. This
  covers `-Z`, `--colour` (a real GNU option), the no-arguments case, and the
  six `absent_flags` cases — at checkpoint 000, `-H` must be an *unknown
  option*, and no real grep will ever say so.
* **`base-stdin-dash-is-an-operand-name`.** GNU grep reads standard input for
  the operand `-`; `new_grep`'s contract makes `-` an ordinary pathname. A
  genuine, unavoidable disagreement, so it is documented rather than forced —
  the same way the mkdir suite documents its Darwin/Linux mode quirk.

These keep goldens from `tests/reference_generators/grep_reference.py`, the
executable restatement of the prompt contract. Cases themselves are written in
`gen/curated_cases.py` as **inputs only**; no expectation is ever typed by hand.

### How the two derivations are kept honest

Freezing computes *both* the model's answer and the oracle's for every
non-exempt case and **refuses to write anything if they differ**, naming the
case and both outputs. Switching this suite to the oracle changed no golden at
all: all 88 files came out byte-identical, and only `MANIFEST.json` gained the
provenance fields.

That equality is what lets the offline audit stay offline:

* **Freshness.** `gen/generate.py --check` compares `suites/` against the
  model-derived derivation. It needs no grep, so it still runs on any host —
  and it is sound precisely because freezing refuses to write unless the model
  reproduced the oracle byte for byte.
* **Fitness.** Regenerating verifies the oracle twice: `oracle_contract.py`
  checks it *is* GNU grep at the pinned version, and `gen/oracle.py --oracle-bin`
  checks it *behaves* — a build can report the right version and still be
  unusable. The Git-for-Windows grep 3.0 is GNU, reports a version, drops CR
  from its output (text-mode build), and aborts outright under `LC_ALL=C -i`;
  freezing against it silently produced three wrong goldens before the precheck
  existed. The precheck also refuses a filesystem that ignores mode 0000 or
  cannot create symlinks, and refuses to run as root, because each of those
  turns a fault case into a passing one.
* **Invariants.** `props.case_invariants()` asserts properties that hold however
  the golden was produced: exit status agrees with stdout (0 selected something,
  1 selected nothing, 2 carries a diagnostic), stdout ends with a newline, every
  emitted line really is a matching line of some input, and each case's declared
  `flags` match the options its argv actually uses.

Run all of it with:

```bash
tests/grep-test-suite/selfcheck.sh                          # offline
GREP_ORACLE_BIN=/usr/bin/grep tests/grep-test-suite/selfcheck.sh
```

`selfcheck.sh` executes no candidate, so it runs anywhere. Its oracle pass
reports "not verified on this host" where there is no GNU grep, but fails hard
when `GREP_ORACLE_BIN` is set and unfit.

## Contract the cases encode

| Aspect | Behavior |
|---|---|
| Matching | PATTERN occurs as a contiguous byte substring; empty PATTERN matches every line |
| Lines | Newline-delimited bytes; a final line without a newline is still a line; every emitted line ends with a newline |
| stdin | Searched when there are no file operands; the name used under `-H` is `(standard input)` |
| Operands | Ordinary pathnames. `-` is not special. `--` ends options |
| Prefix (default) | Printed when there is more than one file operand, or when `-r` is given and an operand is a directory |
| Prefix (`-H`/`-h`) | Whichever appeared last on the command line wins; both are idempotent |
| `-r` | Pre-order traversal, entries in ascending byte order of name; symlinks reached during traversal are skipped |
| `-i` | ASCII-only folding of `A`–`Z`; bytes ≥ 0x80 and non-letters are untouched |
| Exit status | 0 = a line was selected, 1 = none was, 2 = an error occurred (regardless of matches) |
| Diagnostics | stderr only; the suite asserts empty/non-empty plus that the message names the offending operand, not its exact wording |

Byte-level fidelity is part of the contract: NUL bytes and invalid UTF-8 are
ordinary data, and there is no "binary file matches" suppression.

## Layout

```text
tests/grep-test-suite/
├── config.json          # candidate path + implemented flags (the only file to edit)
├── config.py            # dotted-key config reader, also usable from shell
├── engine.py            # fixture materialization, argv/env pinning, one subprocess path
├── runner.py            # judge: flag filtering, comparison, verdict severities
├── props.py             # runtime property checks + frozen-case invariants
├── judge_candidate.sh   # cumulative checkpoint wrapper
├── selfcheck.sh         # offline audit; runs no candidate
├── gen/
│   ├── curated_cases.py # case inputs, grouped by checkpoint
│   ├── oracle.py        # live-grep harness + the fitness precheck
│   ├── generate.py      # freeze suites/ from the oracle, cross-checked
│   └── verify.py        # freshness + invariants + checkpoint reachability
└── suites/
    ├── MANIFEST.json
    ├── base.json  with_filename.json  no_filename.json
    └── recursive.json  ignore_case.json
```

## Regenerating

```bash
cd tests/grep-test-suite
GREP_ORACLE_BIN=/usr/bin/grep python3 gen/generate.py   # rewrite suites/
python3 gen/generate.py --check  # fail if suites/ is stale (offline)
python3 gen/verify.py            # full offline audit
python3 gen/oracle.py --oracle-bin /usr/bin/grep   # is this host fit to freeze?
```

Only the first of those needs a GNU grep. Regeneration writes the corpus with a
pinned line terminator, so freezing on a different host cannot change the
lineage configuration fingerprint without changing a golden.

Editing `tests/reference_generators/grep_reference.py` changes the contract, and therefore the goldens.
Do that only alongside the corresponding prompt change, and regenerate. Note
that regenerating changes the lineage configuration fingerprint recorded by
`scripts/lineage_plan.py`, so an in-progress lineage run cannot be resumed
across such a change — which is the intended protection, not an obstacle.
