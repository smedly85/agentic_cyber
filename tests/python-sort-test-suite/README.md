# Python SORT functional suite

This suite implements the existing C SORT feature progression for independent
Python 3.11+ candidates: base, reverse, ignore-case, unique, check. There is no
starter candidate. The source is `src/python-sort/new_sort.py`; the controller
syntax-checks it and creates `build/new_sort.py` with its pinned interpreter.

The corpus is currently **pending Darwin GNU Coreutils 9.11 generation**.
Committed compressed files contain deterministic scenario recipes, with unknown
outcomes explicitly null. They are not goldens and must not be used for formal
experiments. Both public and held-out runners refuse pending inputs. Non-Darwin
judging returns platform incompatibility (3), not a candidate failure.

| Checkpoint | Flags | Public / held-out recipes |
|---|---|---:|
| 000 base | none | 17 / 17 |
| 001 reverse | -r | 22 / 22 |
| 002 ignore-case | -r -f | 31 / 31 |
| 003 unique | -r -f -u | 46 / 46 |
| 004 check | -r -f -u -c | 75 / 75 |

The contract is stdin-only binary pipe I/O in LC_ALL=C. Tests cover empty and
unterminated records, NUL/non-UTF-8 bytes, long lines, folded tie-breaks, stable
unique representatives, strict unique checks, combined/repeated options and
invalid arguments. Status and stdout are exact; stderr presence/class is checked.
The five `scope_error` cases assert rejection of operands, a bare dash, `--`, and
an attached `--check` value; these are explicit bounded-interface assertions,
not GNU outcomes. GNU 9.11 itself exits 1 for an invalid `--check` value through
its argument parser (not its disorder check); the Python prompt requires 2 for
all attached values. Both public `c-value` and its held-out dual assert that
existing status-2 contract. Genuine check-mode disorder remains status 1. Offline
selfcheck uses a temporary adapter solely for those restrictions; supported
invocations always reach the verified GNU oracle. No adapter enters agent bundles.

Public and held-out inputs are separately maintained in
`tests/reference_generators/python_sort_cases.py` and `python_sort_heldout.py`.
Only selected public cases and runtime files are staged. Hidden results are
controller-only after repair. The manifest records deterministic gzip hashes.

Run on vessel as a non-root user from the repository root:

```bash
export PYTHON_BIN="$(command -v python3)"  # Python 3.11+
export SORT_ORACLE_BIN="$HOME/opt/coreutils-9.11/bin/sort"
test "$(uname -s)" = Darwin
"$SORT_ORACLE_BIN" --version
"$PYTHON_BIN" -B tests/python-sort-test-suite/gen/generate.py
bash tests/python-sort-test-suite/selfcheck.sh
"$PYTHON_BIN" -B scripts/check_heldout_isolation.py --utility python-sort
test -f tests/test_python_infrastructure.py
"$PYTHON_BIN" -B -m unittest discover -s tests -p 'test_python_infrastructure.py' -v
```

The integration command must discover 15 tests. With `SORT_ORACLE_BIN` set, all
15 should execute without skips. The test file is a repository-root `tests/`
file, not inside this suite; include it when transferring the changes to vessel.
The file-presence check prevents a missing file from looking like a successful
zero-test run. Live oracle/adapter comparisons on Linux are diagnostic only;
they do not replace Darwin generation or the complete five-checkpoint selfcheck.

The generator enforces the exact GNU program/version and refuses BSD sort.
`--audit` checks hashes/filtering/isolation without an oracle and reports status;
it does not certify GNU behavior. `--write-pending` deliberately resets outcomes
to unvalidated recipes for infrastructure maintenance. No C frozen corpus or
Linux GNU expectation is copied. See [Python lineage documentation](../../docs/python_lineages.md)
for diagnostic commands and the unchanged Linux-only MKDIR contract.
