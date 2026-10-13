# Python MKDIR suite

Linux GNU Coreutils 9.11 functional oracle; ladder: base, parents, mode.
Cumulative public/held-out counts: 21/21, 31/31, 63/63.
The suite refuses other platforms because GNU symbolic-mode behavior differs.

From the repository root, set `PYTHON_BIN` to the supported interpreter and
`MKDIR_ORACLE_BIN` to an absolute GNU 9.11 mkdir executable, then run as non-root:

```bash
bash tests/python-mkdir-test-suite/selfcheck.sh
```

Cases explicitly vary umask, numeric/symbolic modes, special bits, omitted
classes, permission copying, parent modes, existing targets and option ordering.
Each process receives its case's umask inside an isolated temporary fixture.

Use `scripts/python_candidate.py` to create a launcher for generated source;
pass it and cumulative flags to `judge_candidate.sh`. `VALIDATION_JSON_REPORT`
selects a path outside the test bundle (default: beside the launcher).
`gen/generate.py --check` verifies deterministic frozen output and both judges at
every checkpoint; `--audit` checks offline integrity/isolation. Running without
either option intentionally regenerates goldens. Generators and held-out cases
are never staged into agent workspaces.
See [platform limitations and commands](../../docs/python_lineages.md).
