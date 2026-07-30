# new_chmod test suite

Deterministic checkpoint tests for the bounded `new_chmod` experiment
(`experiments/utilities/chmod.json`). Same shape as the grep, sort and mkdir
suites: frozen cases under `suites/`, a config describing which flags the
candidate implements, a runner that filters cases by that list, and a checkpoint
wrapper that supplies the candidate path at run time.

## Checkpoint interface

```bash
tests/chmod-test-suite/judge_candidate.sh build/new_chmod                  # 000
tests/chmod-test-suite/judge_candidate.sh build/new_chmod -R               # 001
tests/chmod-test-suite/judge_candidate.sh build/new_chmod -R -c            # 002
tests/chmod-test-suite/judge_candidate.sh build/new_chmod -R -c -v         # 003
tests/chmod-test-suite/judge_candidate.sh build/new_chmod -R -c -v -f      # 004
```

The flag list is **cumulative**. A frozen case runs only when every flag in its
own `flags` list is present, so a later checkpoint automatically re-runs every
earlier checkpoint's applicable cases as regression coverage, and never reaches
a feature that does not exist yet. Base-tier cases (`flags: []`) run at every
checkpoint.

Coverage grows monotonically: 40 cases at 000, 55 at 001, 70 at 002, 83 at 003,
98 at 004. `gen/verify.py` enforces both the growth and the non-emptiness.

`judge_candidate.sh` writes its runtime configuration to a throwaway file and
never modifies the committed `config.json`, so it is safe to call repeatedly
from an experiment harness with no shared mutable state.

## Filesystem isolation

chmod changes filesystem metadata, so every case runs inside its own
`tempfile.TemporaryDirectory`:

* `engine.materialize_fixture` builds the case's starting tree there — files,
  directories and symlinks, each with an explicit starting mode
* the candidate is spawned with that directory as its working directory
* a fixture entry or operand whose path would resolve outside the directory is
  refused (`SandboxEscapeError`) rather than run
* `engine.snapshot_modes` then records the mode of every fixture path, visiting
  shallowest-first and capturing each path's mode *before* relaxing anything, so
  a directory the candidate locked down can still be descended for the snapshot
  without falsifying it
* `engine.restore_writable` finally re-grants owner permissions so the temporary
  directory can be removed

No repository file is read or written by a case, and nothing outside the
temporary directory is ever chmod'ed.

Cases whose outcome depends on a permission denial declare `needs_non_root`, and
are skipped when the suite runs as root — where the denial would not happen.

## What is compared

| Aspect | How |
|---|---|
| Resulting modes | every fixture path, exactly, as a four-digit octal string (symlinks recorded as `link` and expected to be untouched) |
| stdout | exact bytes; `-c` / `-v` report lines are part of the contract |
| stderr | class (`empty` / `nonempty`) plus a regex asserting the diagnostic names the offending operand, or contains `invalid mode` |
| exit status | exactly 0 or 1 |
| crashes, timeouts, sanitizer reports | classified separately from wrong output |

## Where the goldens come from

The sort and mkdir suites freeze their goldens from a GNU oracle. `new_chmod`
has no oracle: it is a deliberately bounded utility whose contract comes from
the checkpoint prompts, not from any shipping chmod. In particular **`s` and `t`
are not symbolic permission letters here, no symbolic clause touches the
setuid/setgid/sticky bits, and the umask plays no part** — so GNU chmod is not a
valid oracle for it.

`tests/reference_generators/chmod_reference.py` is therefore the oracle — an executable restatement of the
prompt contract. `gen/generate.py` derives every case's expected stdout, exit
status, stderr class and resulting mode tree from it. Cases themselves are
written in `gen/curated_cases.py` as **inputs only**; no expectation is ever
typed by hand.

That makes the model a single point of failure, so it is audited from two
independent directions:

* **Freshness.** `gen/generate.py --check` fails if `suites/` differs by a byte
  from what the current definitions and model produce.
* **Invariants.** `props.case_invariants()` asserts properties that hold however
  the golden was produced: exit 0 pairs with an empty stderr and exit 1 with a
  non-empty one, only `-c`/`-v` cases write to stdout, every report line is well
  formed and names a fixture path, each line's octal and symbolic renderings
  agree, every fixture path has an expected mode, and each case's declared
  `flags` match the options its argv actually uses.

Run both, plus the config-immutability check, with:

```bash
tests/chmod-test-suite/selfcheck.sh
```

`selfcheck.sh` executes no candidate, so pass 1 runs anywhere.

## Contract the cases encode

| Aspect | Behavior |
|---|---|
| Octal MODE | one to four octal digits, absolute, including setuid/setgid/sticky; no umask |
| Symbolic MODE | `[ugoa...][+-=][rwxX...]` clauses, comma-separated, applied to the current mode; empty class list means all three classes |
| `X` | execute only for a directory, or when an execute bit is already set at that point in the clause chain |
| Special bits | never changed by a symbolic clause; `s` and `t` are rejected as permission letters |
| Operands | every one is attempted; a failure is diagnosed and the rest continue |
| Symlinks | an operand naming one is followed; one found during `-R` traversal is skipped entirely |
| `-R` | pre-order, directory before its entries, entries in ascending byte order of name |
| `-c` / `-v` | `mode of 'PATH' changed from 0644 (rw-r--r--) to 0755 (rwxr-xr-x)` and `mode of 'PATH' retained as 0644 (rw-r--r--)`; last of `-c`/`-v` wins |
| `-f` | suppresses per-operand diagnostics *and* their effect on the exit status; never suppresses a usage error or an invalid MODE |
| Exit status | 0 = everything succeeded, 1 = something failed |

## Layout

```text
tests/chmod-test-suite/
├── config.json          # candidate path + implemented flags (the only file to edit)
├── config.py            # dotted-key config reader, also usable from shell
├── engine.py            # fixture materialization, mode snapshot, argv/env pinning
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
    ├── base.json  recursive.json  changes.json
    └── verbose.json  silent.json
```

## Regenerating

```bash
cd tests/chmod-test-suite
python3 gen/generate.py          # rewrite suites/
python3 gen/generate.py --check  # fail if suites/ is stale
python3 gen/verify.py            # full offline audit
```

Editing `tests/reference_generators/chmod_reference.py` changes the contract, and therefore the goldens. Do
that only alongside the corresponding prompt change, and regenerate. Note that
regenerating changes the lineage configuration fingerprint recorded by
`scripts/lineage_plan.py`, so an in-progress lineage run cannot be resumed
across such a change — which is the intended protection, not an obstacle.
