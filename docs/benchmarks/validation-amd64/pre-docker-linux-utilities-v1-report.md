# Linux utilities v1 delivery report

Prepared 2026-11-01. **Partial delivery: Linux functional validation and the
candidate Docker execution adapter remain incomplete. Formal runs are blocked.**

The [methodology](linux-utilities-v1.md) contains the original mkdir architecture
audit, reused source files, Darwin differences, full benchmark matrix, restricted
contracts, exact Docker commands for vessel, and remaining work. The
[input provenance inventory](linux-utilities-v1-input-provenance.json) records
historical source hashes. No historical expected output is presented as a Linux
result.

## Validation

- Six host-safe static tests passed; zero failed.
- Twelve shell files passed syntax checks.
- All four selectors and 15 cumulative checkpoint bundles resolve.
- Held-out input isolation passed: 552/402/57/104 values searched across
  cp/mv/mkdir/sort respectively, with no detected leaks.
- `git diff --check` passed. The index is unchanged and empty of staged changes.

For every checkpoint below, **oracle self-checks executed: 0; functional checks
passed: 0; functional checks failed: 0; status: NOT RUN**. Zero failures is not a
pass. These counts describe input definitions, not frozen or executed tests.
Sort additionally exercises stdin delivery variants when the runner executes.

| Utility | Checkpoint | Public inputs | Held-out inputs | Planned oracle case definitions | Static plan/filter/isolation |
|---|---|---:|---:|---:|---|
| c-cp | 000 | 32 | 32 | 64 | passed |
| c-cp | 001 | 37 | 37 | 74 | passed |
| c-cp | 002 | 54 | 54 | 108 | passed |
| c-cp | 003 | 66 | 66 | 132 | passed |
| c-mv | 000 | 34 | 34 | 68 | passed |
| c-mv | 001 | 37 | 37 | 74 | passed |
| c-mv | 002 | 52 | 52 | 104 | passed |
| c-mkdir | 000 | 28 | 6 | 34 | passed |
| c-mkdir | 001 | 51 | 12 | 63 | passed |
| c-mkdir | 002 | 150 | 25 | 175 | passed |
| c-sort | 000 | 13 | 4 | 17 | passed |
| c-sort | 001 | 16 | 6 | 22 | passed |
| c-sort | 002 | 19 | 8 | 27 | passed |
| c-sort | 003 | 48 | 18 | 66 | passed |
| c-sort | 004 | 68 | 28 | 96 | passed |

## Docker observations and remaining work

Windows has no Docker executable on PATH. WSL has Docker client 29.1.3,
linux/amd64, but daemon access fails with permission denied at
`/var/run/docker.sock`. No daemon or privilege configuration was changed.

**Actual container OS, architecture, compiler version and Coreutils version:
all unobserved.** Intended configuration: Linux ARM64, GCC 12.2.0, Python
3.12.8, GNU Coreutils 9.11. The immutable base digest must still be resolved,
the image built and the toolchain verified on vessel.

Pending: Linux generation, repeated-freeze determinism, oracle self-pass,
mutation detection, actual frozen-corpus isolation, compiler and ARM64 checks,
reviewed publication of Linux goldens, expanded restricted-subset rejection and
recursive-permission coverage, and a validated per-candidate Docker adapter for
all controller execution paths. The oracle-only container contains hidden
assets and must never execute generated candidates. Formal-run guards must
remain until that isolation is implemented and verified.

No candidate implementation or seed source was supplied. No formal LLM runs
were started. Rust/Python manifests and all historical research/results remain
unchanged.

## Modified files

- `scripts/checkpoint_boundary_gate.py` — C probe contracts and execution refusal.
- `scripts/heldout_judge.py` — refuse unisolated new C candidate evaluation.
- `scripts/lineage_plan.py` — new benchmark infrastructure provenance/fingerprints.
- `scripts/run_experiment.sh` — prevent native runs of the new C source identities.
- `scripts/run_lineage_experiment.sh` — block formal C runs, preserve static planning,
  disable unsupported security evaluation.

No pre-existing repository files were deleted. Temporary preparation helpers
were removed. The complete created-file inventory and final git status follow.

## Created files

Created files: 77. Modified tracked files: 5. Deleted pre-existing files: 0.

- `docker/linux-utilities-v1/Dockerfile` — Pinned-toolchain Linux image recipe and GNU source checksum verification.
- `docker/linux-utilities-v1/build.sh` — Immutable base-digest requirement and architecture-specific Docker build.
- `docker/linux-utilities-v1/run.sh` — Bounded non-root, network-disabled oracle validation and artifact capture.
- `docs/benchmarks/linux-utilities-v1-contract.md` — Versioned language-neutral observable behavioral contract.
- `docs/benchmarks/linux-utilities-v1-input-provenance.json` — SHA-256 inventory of reused historical input and runtime source material.
- `docs/benchmarks/linux-utilities-v1-report.md` — This delivery report, complete file inventory and git verification.
- `docs/benchmarks/linux-utilities-v1-static-report.json` — Checkpoint counts and bundle fingerprints; functional status unknown.
- `docs/benchmarks/linux-utilities-v1.md` — Methodology, repository audit, Docker reproduction commands and limitations.
- `experiments/utilities/c-cp.json` — Namespaced C manifest and cumulative checkpoint sequence.
- `experiments/utilities/c-mkdir.json` — Namespaced C manifest and cumulative checkpoint sequence.
- `experiments/utilities/c-mv.json` — Namespaced C manifest and cumulative checkpoint sequence.
- `experiments/utilities/c-sort.json` — Namespaced C manifest and cumulative checkpoint sequence.
- `prompts/linux-utilities-v1/c-cp/000_base.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-cp/001_force.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-cp/002_interactive.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-cp/003_recursive.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-mkdir/000_base.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-mkdir/001_parents.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-mkdir/002_mode.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-mv/000_base.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-mv/001_force.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-mv/002_interactive.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-sort/000_base.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-sort/001_reverse.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-sort/002_ignore-case.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-sort/003_unique.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `prompts/linux-utilities-v1/c-sort/004_check.md` — C11 checkpoint prompt with observable requirements and no supplied implementation.
- `scripts/linux_benchmark.py` — Static inspection, environment checks, freezer, self-pass, isolation and mutation workflow.
- `tests/c-cp-test-suite/README.md` — Suite status and methodology pointer.
- `tests/c-cp-test-suite/config.json` — Linux version/platform and restricted-scope configuration.
- `tests/c-cp-test-suite/config.py` — Inherited configuration reader.
- `tests/c-cp-test-suite/engine.py` — Inherited fixture engine with Linux Docker and oracle-only guards.
- `tests/c-cp-test-suite/gen/generate.py` — Docker-only oracle freeze entry point.
- `tests/c-cp-test-suite/gen/inputs.json.gz` — Controller-only input definitions and assertion policies; no frozen expectations.
- `tests/c-cp-test-suite/heldout/heldout_cases.json.gz` — Independent held-out inputs, explicitly unfrozen.
- `tests/c-cp-test-suite/judge_candidate.sh` — Checkpoint wrapper; generated candidate execution remains blocked.
- `tests/c-cp-test-suite/props.py` — Inherited property checks, pruned by checkpoint bundle construction.
- `tests/c-cp-test-suite/runner.py` — Inherited cumulative judge with explicit pending-corpus refusal.
- `tests/c-cp-test-suite/selfcheck.sh` — Bounded oracle validation entry point.
- `tests/c-cp-test-suite/suites/pending.json.gz` — Public inputs for static filtering; runtime refuses unfrozen data.
- `tests/c-mkdir-test-suite/README.md` — Suite status and methodology pointer.
- `tests/c-mkdir-test-suite/config.json` — Linux version/platform and restricted-scope configuration.
- `tests/c-mkdir-test-suite/config.py` — Inherited configuration reader.
- `tests/c-mkdir-test-suite/engine.py` — Inherited fixture engine with Linux Docker and oracle-only guards.
- `tests/c-mkdir-test-suite/gen/generate.py` — Docker-only oracle freeze entry point.
- `tests/c-mkdir-test-suite/gen/inputs.json.gz` — Controller-only input definitions and assertion policies; no frozen expectations.
- `tests/c-mkdir-test-suite/heldout/heldout_cases.json.gz` — Independent held-out inputs, explicitly unfrozen.
- `tests/c-mkdir-test-suite/judge_candidate.sh` — Checkpoint wrapper; generated candidate execution remains blocked.
- `tests/c-mkdir-test-suite/props.py` — Inherited property checks, pruned by checkpoint bundle construction.
- `tests/c-mkdir-test-suite/runner.py` — Inherited cumulative judge with explicit pending-corpus refusal.
- `tests/c-mkdir-test-suite/selfcheck.sh` — Bounded oracle validation entry point.
- `tests/c-mkdir-test-suite/suites/pending.json.gz` — Public inputs for static filtering; runtime refuses unfrozen data.
- `tests/c-mv-test-suite/README.md` — Suite status and methodology pointer.
- `tests/c-mv-test-suite/config.json` — Linux version/platform and restricted-scope configuration.
- `tests/c-mv-test-suite/config.py` — Inherited configuration reader.
- `tests/c-mv-test-suite/engine.py` — Inherited fixture engine with Linux Docker and oracle-only guards.
- `tests/c-mv-test-suite/gen/generate.py` — Docker-only oracle freeze entry point.
- `tests/c-mv-test-suite/gen/inputs.json.gz` — Controller-only input definitions and assertion policies; no frozen expectations.
- `tests/c-mv-test-suite/heldout/heldout_cases.json.gz` — Independent held-out inputs, explicitly unfrozen.
- `tests/c-mv-test-suite/judge_candidate.sh` — Checkpoint wrapper; generated candidate execution remains blocked.
- `tests/c-mv-test-suite/props.py` — Inherited property checks, pruned by checkpoint bundle construction.
- `tests/c-mv-test-suite/runner.py` — Inherited cumulative judge with explicit pending-corpus refusal.
- `tests/c-mv-test-suite/selfcheck.sh` — Bounded oracle validation entry point.
- `tests/c-mv-test-suite/suites/pending.json.gz` — Public inputs for static filtering; runtime refuses unfrozen data.
- `tests/c-sort-test-suite/README.md` — Suite status and methodology pointer.
- `tests/c-sort-test-suite/config.json` — Linux version/platform and restricted-scope configuration.
- `tests/c-sort-test-suite/config.py` — Inherited configuration reader.
- `tests/c-sort-test-suite/engine.py` — Inherited fixture engine with Linux Docker and oracle-only guards.
- `tests/c-sort-test-suite/gen/generate.py` — Docker-only oracle freeze entry point.
- `tests/c-sort-test-suite/gen/inputs.json.gz` — Controller-only input definitions and assertion policies; no frozen expectations.
- `tests/c-sort-test-suite/heldout/heldout_cases.json.gz` — Independent held-out inputs, explicitly unfrozen.
- `tests/c-sort-test-suite/judge_candidate.sh` — Checkpoint wrapper; generated candidate execution remains blocked.
- `tests/c-sort-test-suite/props.py` — Inherited property checks, pruned by checkpoint bundle construction.
- `tests/c-sort-test-suite/runner.py` — Inherited cumulative judge with explicit pending-corpus refusal.
- `tests/c-sort-test-suite/selfcheck.sh` — Bounded oracle validation entry point.
- `tests/c-sort-test-suite/suites/pending.json.gz` — Public inputs for static filtering; runtime refuses unfrozen data.
- `tests/test_linux_benchmark_static.py` — Six static tests; never executes functional programs.

## Git verification

Initial and final branch: `cleanup/canonical-ordered-diversity`.

Initial `git status --short`:

```text
(empty; clean working tree)
```

Final `git status --short`:

```text
 M scripts/checkpoint_boundary_gate.py
 M scripts/heldout_judge.py
 M scripts/lineage_plan.py
 M scripts/run_experiment.sh
 M scripts/run_lineage_experiment.sh
?? docker/
?? docs/benchmarks/
?? experiments/utilities/c-cp.json
?? experiments/utilities/c-mkdir.json
?? experiments/utilities/c-mv.json
?? experiments/utilities/c-sort.json
?? prompts/linux-utilities-v1/
?? scripts/linux_benchmark.py
?? tests/c-cp-test-suite/
?? tests/c-mkdir-test-suite/
?? tests/c-mv-test-suite/
?? tests/c-sort-test-suite/
?? tests/test_linux_benchmark_static.py
```

`git diff --cached --name-only` is empty. Only the five listed controller files differ among pre-existing tracked files. Historical manifests, prompts, corpora, results, CVE data, diversity/call-graph research and DROID artifacts were preserved. No files were staged, committed or pushed. No branches or pull requests were created.
