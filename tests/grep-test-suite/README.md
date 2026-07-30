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

Coverage grows monotonically: 32 cases at 000, 40 at 001, 50 at 002, 65 at 003,
82 at 004. `gen/verify.py` enforces both the growth and the non-emptiness.

`judge_candidate.sh` writes its runtime configuration to a throwaway file and
never modifies the committed `config.json`, so it is safe to call repeatedly
from an experiment harness with no shared mutable state.

## Where the goldens come from

The sort and mkdir suites freeze their goldens from a GNU oracle binary.
`new_grep` has no oracle: it is a deliberately bounded utility whose contract
comes from the checkpoint prompts, not from any shipping grep. In particular
**PATTERN is a fixed byte string, not a regular expression**, so GNU grep is not
a valid oracle for it.

`tests/reference_generators/grep_reference.py` is therefore the oracle — an executable restatement of the
prompt contract. `gen/generate.py` derives every case's expected stdout, exit
status and stderr class from it. Cases themselves are written in
`gen/curated_cases.py` as **inputs only**; no expectation is ever typed by hand.

That makes the model a single point of failure, so it is audited from two
independent directions:

* **Freshness.** `gen/generate.py --check` fails if `suites/` differs by a byte
  from what the current definitions and model produce.
* **Invariants.** `props.case_invariants()` asserts properties that hold however
  the golden was produced: exit status agrees with stdout (0 selected something,
  1 selected nothing, 2 carries a diagnostic), stdout ends with a newline, every
  emitted line really is a matching line of some input, and each case's declared
  `flags` match the options its argv actually uses.

Run both, plus the config-immutability check, with:

```bash
tests/grep-test-suite/selfcheck.sh
```

`selfcheck.sh` executes no candidate, so it runs anywhere.

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
│   ├── generate.py      # freeze suites/ from the model
│   └── verify.py        # freshness + invariants + checkpoint reachability
├── model/
│   └── reference.py     # the specification model (the oracle)
└── suites/
    ├── MANIFEST.json
    ├── base.json  with_filename.json  no_filename.json
    └── recursive.json  ignore_case.json
```

## Regenerating

```bash
cd tests/grep-test-suite
python3 gen/generate.py          # rewrite suites/
python3 gen/generate.py --check  # fail if suites/ is stale
python3 gen/verify.py            # full offline audit
```

Editing `tests/reference_generators/grep_reference.py` changes the contract, and therefore the goldens.
Do that only alongside the corresponding prompt change, and regenerate. Note
that regenerating changes the lineage configuration fingerprint recorded by
`scripts/lineage_plan.py`, so an in-progress lineage run cannot be resumed
across such a change — which is the intended protection, not an obstacle.
