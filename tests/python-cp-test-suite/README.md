# Python CP suite

GNU Coreutils 9.11 functional oracle; ladder: base, force, interactive, recursive.
Cumulative public/held-out counts: 36/36, 41/41, 58/58, 70/70.

From the repository root, set `PYTHON_BIN` to the supported interpreter and
`CP_ORACLE_BIN` to an absolute GNU 9.11 cp executable, then run:

```bash
bash tests/python-cp-test-suite/selfcheck.sh
```

For a separately generated candidate, use `scripts/python_candidate.py` to make
an interpreter-pinned launcher and pass it to `judge_candidate.sh` followed by
the checkpoint's cumulative flags. `VALIDATION_JSON_REPORT` selects the report
path; it must be outside the immutable test bundle. Default: beside the launcher.

`gen/generate.py --check` verifies deterministic goldens and every checkpoint's
public and isolated held-out GNU self-pass. `--audit` needs no oracle. Generation
without either option intentionally replaces frozen goldens. Never stage `gen/`,
`heldout/`, or this README into an agent workspace. Use the existing stage-bundle
builder. See [contracts and commands](../../docs/python_lineages.md).
