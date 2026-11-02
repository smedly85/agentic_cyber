# Linux utilities: c-mv

Linux GNU Coreutils 9.11 frozen expectations are in `suites/linux.json.gz`
and the separate controller-only `heldout/` directory. `suites/MANIFEST.json`
records input, corpus, oracle and environment hashes. `validation.json` records
the oracle job; separate adapter evidence is under `docs/benchmarks/validation-amd64`.
Archived pending inputs and revisions in `gen/` are never staged for agents.
The historical `tests/mv-test-suite/` remains unchanged.
All candidate operations require the Docker adapter and controller `HELDOUT_ROOT`.
See `docs/benchmarks/linux-utilities.md` for scope and reproduction commands.
