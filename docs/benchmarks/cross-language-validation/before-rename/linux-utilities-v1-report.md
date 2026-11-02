# Linux utilities v1 Docker validation report

2026-11-01. Linux/AMD64 oracle freezing and isolated execution validation passed.
ARM64/vessel remains **unverified**. No formal lineages were started.

## Observed environment

Docker Desktop client 29.1.3 / Linux server 29.9.2 through WSL2, architecture
linux/amd64 (x86_64), kernel 6.18.54.1-microsoft-standard-WSL2. Container `uname -s`
and Python platform both report Linux. GCC: `gcc (Debian 12.2.0-14) 12.2.0`;
Python 3.12.8; all four `/opt/gnu/bin` oracles report GNU Coreutils 9.11.

Oracle image ID: `sha256:02cf23e5c3273ff2969f25010e79346dfbd98ae51499e04996ba802d49f99ad7`.
AMD64 image manifest: `sha256:42a38e1ed65aa195d65c6563c54187a07dad361158129278fd3b2dfe5a783528`.
Base multiarch digest: `sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad`.
The [lock](../../docker/linux-utilities-v1/lock-amd64.json), per-suite manifests,
and [oracle image inspection](validation-amd64/oracle-007/image-inspect.json)
record additional identifiers. GNU source SHA256 is verified by the Dockerfile;
the pinned Debian snapshot and image `/provenance/packages.txt` record build inputs.

## Oracle self-checks, all checkpoints

Counts below are actual executions (including sort stdin delivery variants), not
just distinct input definitions. Earlier checkpoints skip future-feature cases.
Sort also skips one historical out-of-scope `-y0` compatibility case, absent from
visible bundles. Every executed case passed; infrastructure errors were zero in
the final run. Mutation checks must fail judging and did so for both splits.

| Utility | Checkpoint | Public passes | Held-out passes | Oracle self-check total | Failures | Mutations detected |
|---|---|---:|---:|---:|---:|---|
| c-cp | 000 | 32 | 32 | 64 | 0 | 2/2 |
| c-cp | 001 | 37 | 37 | 74 | 0 | 2/2 |
| c-cp | 002 | 54 | 54 | 108 | 0 | 2/2 |
| c-cp | 003 | 66 | 66 | 132 | 0 | 2/2 |
| c-mv | 000 | 34 | 34 | 68 | 0 | 2/2 |
| c-mv | 001 | 37 | 37 | 74 | 0 | 2/2 |
| c-mv | 002 | 52 | 52 | 104 | 0 | 2/2 |
| c-mkdir | 000 | 28 | 6 | 34 | 0 | 2/2 |
| c-mkdir | 001 | 51 | 12 | 63 | 0 | 2/2 |
| c-mkdir | 002 | 150 | 25 | 175 | 0 | 2/2 |
| c-sort | 000 | 14 | 6 | 20 | 0 | 2/2 |
| c-sort | 001 | 20 | 10 | 30 | 0 | 2/2 |
| c-sort | 002 | 25 | 13 | 38 | 0 | 2/2 |
| c-sort | 003 | 60 | 26 | 86 | 0 | 2/2 |
| c-sort | 004 | 83 | 37 | 120 | 0 | 2/2 |

All four repeated generations were byte-identical. Frozen file/input hashes and
oracle executable hashes are in each new suite's `suites/MANIFEST.json`.
[Final oracle evidence](validation-amd64/oracle-007/validation.log) records all
15 checkpoints. The oracle-only `validation.json` snapshots retain an obsolete
â€œcandidate isolation not validatedâ€ annotation from the initial freezer; that
job did not test candidates. The separate adapter evidence below supersedes that
annotation for overall delivery status, without rewriting recorded oracle output.

## Docker adapter and bounded validation

- Isolated GNU calibration: cp 66 public + 66 hidden, mv 52 + 52, mkdir 150 + 25,
  sort 83 + 37: **531 passes, zero failures/infrastructure errors**, covering
  every active final-checkpoint case. See [adapter-001](validation-amd64/adapter-001/summary.json)
  and the final sort revision [adapter-002](validation-amd64/adapter-002/summary.json).
- Six Docker integration tests passed, including compilation/execution, UID and
  inaccessible assets, network denial, timeout classification, compiler error,
  missing Docker without fallback, all 15 checkpoint boundaries and permissive
  negative controls. Negative public/hidden cp controls each intentionally failed
  31 of 32 executed cases; these are sensitivity checks, not oracle failures.
- Eight static regression tests passed inside Docker. Forty Python files
  parsed and 12 shell scripts passed syntax checks. Direct Linux contract checks
  confirmed symbolic modes, overwrite declines and sort check semantics.
- Frozen held-out isolation passed across all 15 bundles: 686/466/349/140 hidden
  identifying values checked for cp/mv/mkdir/sort. Hidden inputs are not disclosed
  here. Fixed shared ENOSPC diagnostic handling is explained in methodology.
- Manifest build/public/held-out shell entry points passed a disposable negative
  control: build 0, public 1, hidden 1, with separate durable reports. No model or
  formal experiment was invoked. See [entry-point results](validation-amd64/entrypoints/summary.json).

The [container check summaries](validation-amd64/container-checks/summary.json)
and logs distinguish successful final checks from earlier preserved exploratory
failures. Earlier oracle jobs exposed read-only output setup, descriptor pressure,
and the shared diagnostic scan issue; fixes changed infrastructure/filtering, not
functional assertions. Historical Darwin expectations were never used as Linux
truth. Pending new-namespace inputs and changed frozen revisions are archived.

## Audit, matrix, changed files and reproduction

The [methodology](linux-utilities-v1.md) retains the original mkdir architecture
audit and exact reused source families, historical Darwin assumptions, canonical
contracts, all four manifest/prompt/suite/source/executable declarations, and
Windows/WSL plus future vessel commands. Each matrix row now has verified GNU
9.11 Linux/AMD64 oracle status; ARM64 status is pending for every row.

The [file inventory](validation-amd64/file-inventory.md) lists every current
created/modified/deleted file against the initial working-tree snapshot, with
purpose descriptions. The initial changes were preserved and extended. Four
new-namespace pending public files were moved into `gen/` archives; no historical
corpus or research result was removed. The seven tracked helper modifications
are restricted to namespaced C behavior; Rust/Python manifests are unchanged.

## Remaining limits and readiness

Ready for Linux/AMD64 infrastructure review. ARM64 image/toolchain/corpus/adapter
validation must still run on vessel after IT restores access. No files were
transferred. Full Aider/Ollama orchestration was deliberately not run, and the
historical controller regression test source files were not present in this
checkout. Exhaustive GNU support is excluded; recursive permission combinations
and independent comparator/security review remain coverage limitations.
The trusted supervisor uses limited root capabilities before dropping privileges;
Docker/chroot does not protect against every kernel attack or side channel.

No staging, commits, pushes, branch changes or formal experiments were performed.
[Initial git status](validation-amd64/initial-status.txt) and
[final git status](validation-amd64/final-status.txt) are recorded verbatim.
Historical source/corpus hashes and tracked-path verification are recorded in
[preservation verification](validation-amd64/preservation.json).

## Git status snapshots

Initial:

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

Final:

```text
 M scripts/check_heldout_isolation.py
 M scripts/checkpoint_boundary_gate.py
 M scripts/heldout_judge.py
 M scripts/lineage_plan.py
 M scripts/run_experiment.sh
 M scripts/run_lineage_experiment.sh
 M scripts/stage_test_bundle.py
?? docker/
?? docs/benchmarks/
?? experiments/utilities/c-cp.json
?? experiments/utilities/c-mkdir.json
?? experiments/utilities/c-mv.json
?? experiments/utilities/c-sort.json
?? prompts/linux-utilities-v1/
?? scripts/check_linux_contract.py
?? scripts/docker_benchmark.py
?? scripts/docker_benchmark_worker.py
?? scripts/linux_benchmark.py
?? scripts/linux_benchmark_isolation.py
?? scripts/publish_linux_corpora.py
?? scripts/record_linux_delivery.py
?? scripts/record_linux_environment.py
?? scripts/record_linux_preservation.py
?? scripts/validate_docker_adapter.py
?? scripts/validate_docker_entrypoints.py
?? scripts/validate_linux_static.py
?? tests/c-cp-test-suite/
?? tests/c-mkdir-test-suite/
?? tests/c-mv-test-suite/
?? tests/c-sort-test-suite/
?? tests/test_docker_benchmark_integration.py
?? tests/test_linux_benchmark_static.py
```
