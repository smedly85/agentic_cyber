# Python LS suite

GNU Coreutils 9.11 functional oracle; ladder: base, all entries, long, recursive.
Cumulative public/held-out counts: 18/18, 23/23, 29/29, 36/36.

From the repository root, set `PYTHON_BIN` to the supported interpreter and
`LS_ORACLE_BIN` to an absolute GNU 9.11 ls executable, then run:

```bash
bash tests/python-ls-test-suite/selfcheck.sh
```

Fixtures use C locale, UTC, fixed dates, long-iso timestamps and nonterminal
literal output. Long fields that depend on the host filesystem are checked
against live metadata before canonicalization. Ordering, permission/type strings,
names, targets, headers and blank lines remain exact. Normalization is not a
license to omit fields. Cases also compare filesystem contents and fixture modes.

Use `scripts/python_candidate.py` to create a launcher for a generated source;
pass it and cumulative flags to `judge_candidate.sh`. `VALIDATION_JSON_REPORT`
selects a path outside the test bundle (default: beside the launcher).
`gen/generate.py --check` verifies deterministic frozen output and both judges at
every checkpoint; `--audit` checks offline integrity/isolation. Running without
either option intentionally regenerates goldens. Generators and held-out cases
are never staged into agent workspaces.
See [platform limitations and commands](../../docs/python_lineages.md).
