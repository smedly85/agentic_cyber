# Python MV suite

GNU Coreutils 9.11 functional oracle; ladder: base, force, interactive.
Unlike Rust MV, force is introduced before interactive.
Cumulative public/held-out counts: 38/38, 42/42, 57/57.

From the repository root, set `PYTHON_BIN` to the supported interpreter and
`MV_ORACLE_BIN` to an absolute GNU 9.11 mv executable, then run:

```bash
bash tests/python-mv-test-suite/selfcheck.sh
```

For a separately generated candidate, use `scripts/python_candidate.py` to make
an interpreter-pinned launcher and pass it to `judge_candidate.sh` followed by
the checkpoint's cumulative flags. `VALIDATION_JSON_REPORT` selects the report
path outside the test bundle (default: beside the launcher).

`gen/generate.py --check` verifies deterministic goldens and every checkpoint's
public and isolated held-out GNU self-pass. `--audit` needs no oracle. Generation
without either option intentionally replaces frozen goldens. Only the existing
stage-bundle builder may select agent-visible files; generators, this README and
held-out cases stay controller-side.
See [contracts and commands](../../docs/python_lineages.md).
