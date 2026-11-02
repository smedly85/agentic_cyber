# Linux utilities cross-language delivery report

Linux/AMD64 infrastructure is **ready for review** across C, Rust and Python:
12 configurations, 45 checkpoints. No formal lineages or permanent candidate
implementations were generated. ARM64/vessel and end-to-end Aider/Ollama generation
remain **pending**; this is not a claim of validated experimental outcomes.

## Observed toolchains and Docker

The [observed toolchains](cross-language-validation/toolchains.json) record Linux
from both uname and Python, x86_64, UID 1000, GCC 12.2.0, Rust
`1.85.1 (4eb161250 2025-03-15)` with edition 2021, and Python 3.12.8.
Docker Desktop server 29.9.2 / client 29.1.3, default existing context, Linux/AMD64.
GNU cp/mv/mkdir/sort each identify as Coreutils **9.11** inside Docker.

- Oracle image ID: `sha256:02cf23e5c3273ff2969f25010e79346dfbd98ae51499e04996ba802d49f99ad7`.
- Rust compiler image ID: `sha256:39f8094edc3cf9548d5e9ce794d01b721da55e424bb45b2da4f86cd189d9577d`.
- Python/C compiler base: `python:3.12.8-bookworm@sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad`.
- Rust base: `rust:1.85.1-bookworm@sha256:e51d0265072d2d9d5d320f6a44dde6b9ef13653b035098febd68cce8fa7c0bc4`.

The [lock](../../docker/linux-utilities/lock-amd64.json), image inspection JSONs,
oracle executable hashes and pinned source/build configuration provide provenance.
The full [matrix and reproduction commands](linux-utilities.md) identify every
manifest, prompt directory and shared suite. Original C scientific contracts and
frozen expected outcomes were preserved; only naming and execution plumbing changed.

## Validation results

- Four final static parity/preservation tests passed: all 45 configurations,
  fingerprints, cumulative case equivalence, hidden isolation, historical assets,
  and exact functional corpus equivalence across the rename.
- Eight existing C static tests and six C Docker integration tests passed.
- Forty-eight Python files parsed and all 20 active shell entry points passed
  syntax checks; the later documentation/audit recorders also executed successfully.
- Six Rust/Python Docker integration tests passed: actual compilation/syntax
  checks, runtime binary I/O/filesystem behavior, non-root permissions, asset and
  network isolation, timeouts, 30 checkpoint boundaries, permissive negative
  boundaries, missing Docker classification, and 60 runtime mutation controls.
- C, Rust and Python cp manifest shell entry points passed: build status 0;
  deliberately incorrect public and hidden controls each status 1 with 31
  failures/1 pass. Those expected failures demonstrate sensitivity, not regressions.
- GNU judge calibration passed **1,593 executions**, zero failures/infrastructure
  errors: 531 identical active final-checkpoint executions per language binding.
  This uses reference executable bytes for judge calibration, including Python
  bindings; real Rust/Python adapters are separately exercised by the temporary
  smoke controls. No GNU delegation is permitted in generated implementations.
- The renamed C oracle run passed all 15 checkpoints on both splits, deterministic
  repeated generation, and **30 full oracle mutation checks**. The 60 additional
  Rust/Python runtime mutation controls each exercise one eligible case through
  its actual language runtime per checkpoint/split. Together these are 90 controls,
  with their differing coverage stated explicitly.
- All 45 visible bundles passed held-out isolation. Per language, identifying
  values checked were cp 686, mv 466, mkdir 349, sort 140. No hidden inputs are
  disclosed here. Future-feature public cases are absent from earlier bundles.

Final evidence: [static parity](cross-language-validation/checks-release/summary.json),
[C checks](cross-language-validation/c-static-final/summary.json),
[C integration](cross-language-validation/c-runtime-001/summary.json),
[Rust/Python integration](cross-language-validation/runtime-final/summary.json),
[calibration](cross-language-validation/calibration-001/summary.json), and
[oracle checks](cross-language-validation/rename-oracle/validation.log).
The first Python run exposed a missing jailed shared-library search path; that
infrastructure issue was fixed and the suite rerun successfully. An initially
overstrict rename audit compared held-out metadata bytes too; its final version
allows only the requested provenance label plus correctly recomputed fingerprint,
while requiring all cases and expected outcomes to be identical. Failed exploratory
evidence is preserved. No functional assertion was weakened to obtain a pass.

## Per-checkpoint counts

Definitions count distinct scenarios; executions include sort stdin delivery
variants. All three languages share the same definitions and expected outcomes.
The canonical oracle self-check ran once for the 15 shared utility/checkpoints:
1,190 executions. Rows repeat those shared counts for each language binding;
they do not claim three independent oracle generations. Language-binding GNU
calibration ran final checkpoints (1,593 executions total), while actual runtime
controls separately exercised all 45 boundary configurations.
Every oracle execution passed (zero failures/infrastructure errors). Later-feature
cases are skipped in earlier oracle checkpoints; one inherited out-of-scope sort
compatibility input remains skipped and is excluded from public bundles.

| Selector | Checkpoint | Public definitions | Held-out definitions | Canonical public executions | Canonical held-out executions | Shared oracle status |
|---|---|---:|---:|---:|---:|---|
| c-cp | 000 | 32 | 32 | 32 | 32 | passed |
| c-cp | 001 | 37 | 37 | 37 | 37 | passed |
| c-cp | 002 | 54 | 54 | 54 | 54 | passed |
| c-cp | 003 | 66 | 66 | 66 | 66 | passed |
| c-mv | 000 | 34 | 34 | 34 | 34 | passed |
| c-mv | 001 | 37 | 37 | 37 | 37 | passed |
| c-mv | 002 | 52 | 52 | 52 | 52 | passed |
| c-mkdir | 000 | 28 | 6 | 28 | 6 | passed |
| c-mkdir | 001 | 51 | 12 | 51 | 12 | passed |
| c-mkdir | 002 | 150 | 25 | 150 | 25 | passed |
| c-sort | 000 | 14 | 6 | 14 | 6 | passed |
| c-sort | 001 | 17 | 8 | 20 | 10 | passed |
| c-sort | 002 | 20 | 10 | 25 | 13 | passed |
| c-sort | 003 | 49 | 20 | 60 | 26 | passed |
| c-sort | 004 | 69 | 30 | 83 | 37 | passed |
| rust-cp | 000 | 32 | 32 | 32 | 32 | passed |
| rust-cp | 001 | 37 | 37 | 37 | 37 | passed |
| rust-cp | 002 | 54 | 54 | 54 | 54 | passed |
| rust-cp | 003 | 66 | 66 | 66 | 66 | passed |
| rust-mv | 000 | 34 | 34 | 34 | 34 | passed |
| rust-mv | 001 | 37 | 37 | 37 | 37 | passed |
| rust-mv | 002 | 52 | 52 | 52 | 52 | passed |
| rust-mkdir | 000 | 28 | 6 | 28 | 6 | passed |
| rust-mkdir | 001 | 51 | 12 | 51 | 12 | passed |
| rust-mkdir | 002 | 150 | 25 | 150 | 25 | passed |
| rust-sort | 000 | 14 | 6 | 14 | 6 | passed |
| rust-sort | 001 | 17 | 8 | 20 | 10 | passed |
| rust-sort | 002 | 20 | 10 | 25 | 13 | passed |
| rust-sort | 003 | 49 | 20 | 60 | 26 | passed |
| rust-sort | 004 | 69 | 30 | 83 | 37 | passed |
| py-cp | 000 | 32 | 32 | 32 | 32 | passed |
| py-cp | 001 | 37 | 37 | 37 | 37 | passed |
| py-cp | 002 | 54 | 54 | 54 | 54 | passed |
| py-cp | 003 | 66 | 66 | 66 | 66 | passed |
| py-mv | 000 | 34 | 34 | 34 | 34 | passed |
| py-mv | 001 | 37 | 37 | 37 | 37 | passed |
| py-mv | 002 | 52 | 52 | 52 | 52 | passed |
| py-mkdir | 000 | 28 | 6 | 28 | 6 | passed |
| py-mkdir | 001 | 51 | 12 | 51 | 12 | passed |
| py-mkdir | 002 | 150 | 25 | 150 | 25 | passed |
| py-sort | 000 | 14 | 6 | 14 | 6 | passed |
| py-sort | 001 | 17 | 8 | 20 | 10 | passed |
| py-sort | 002 | 20 | 10 | 25 | 13 | passed |
| py-sort | 003 | 49 | 20 | 60 | 26 | passed |
| py-sort | 004 | 69 | 30 | 83 | 37 | passed |

## Renames, hashes and historical preservation

[All directory/file renames](cross-language-validation/renames.json) include the
Docker and prompt roots, five active documentation/provenance files, and four
public corpus filenames (`linux.json.gz`). Protocol/schema versions remain 1.
Historical artifacts were not renamed. [The file inventory](cross-language-validation/file-inventory.md)
lists every created/modified/moved active file and its purpose against the initial
working tree; prior evidence and original metadata are archived/preserved.

Old protocol names remain only in immutable historical validation, frozen
provenance/config protocol identifiers, and explicit migration/audit code. The
repository-wide name search and classification are recorded beside the report.
Original corpus hashes remain valid. Regenerated held-out provenance changes the
active label and fingerprint, not cases. [Initial C fingerprints](cross-language-validation/initial-c-fingerprints.json)
and [final fingerprints](cross-language-validation/final-fingerprints.json) document
the configuration change; all final fingerprints recompute consistently. Do not
resume old lineages under these new configuration fingerprints.

## Remaining limits and readiness

No functional C regression was observed. Canonical/public corpus and hidden-case
equivalence were verified, and C static/integration/oracle/mutation/isolation
checks passed. Historical Rust/Python manifests, prompts, suites and results were
left unchanged; standardized descriptors share the C scenarios by construction.

Linux/AMD64 is ready for infrastructure review and a future explicitly authorized
formal-run preflight. Full Aider/Ollama orchestration remains unverified because
no generation was launched; smoke tests are not represented as agent experiments.
Linux/ARM64 must be built and validated on vessel after IT restores Docker access.
No files were transferred. Structural/security backends are disabled and unverified
for these selectors. Exhaustive GNU support, exhaustive permission combinations,
hostile-kernel isolation and independent comparator/security review are outside
the completed bounded validation. The historical controller regression test source
modules are absent from this checkout; available new regression tests were run.

No files were staged, committed or pushed; no branch changed. Historical research
artifacts and initial uncommitted work were preserved. The tracked diff is confined
to the seven controller helpers already involved in standardized execution.
The [preservation audit](cross-language-validation/preservation.json) and Git status
snapshots below record the final state.

## Initial Git status

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

## Final Git status

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
?? experiments/utilities/py-cp.json
?? experiments/utilities/py-mkdir.json
?? experiments/utilities/py-mv.json
?? experiments/utilities/py-sort.json
?? experiments/utilities/rust-cp.json
?? experiments/utilities/rust-mkdir.json
?? experiments/utilities/rust-mv.json
?? experiments/utilities/rust-sort.json
?? prompts/linux-utilities/
?? scripts/audit_cross_language.py
?? scripts/check_linux_contract.py
?? scripts/docker_benchmark.py
?? scripts/docker_benchmark_worker.py
?? scripts/document_cross_language.py
?? scripts/linux_benchmark.py
?? scripts/linux_benchmark_isolation.py
?? scripts/linux_utilities_catalog.py
?? scripts/prepare_linux_languages.py
?? scripts/prepare_linux_names.py
?? scripts/publish_linux_corpora.py
?? scripts/record_cross_language.py
?? scripts/record_linux_delivery.py
?? scripts/record_linux_environment.py
?? scripts/record_linux_preservation.py
?? scripts/validate_cross_language.py
?? scripts/validate_docker_adapter.py
?? scripts/validate_docker_entrypoints.py
?? scripts/validate_linux_static.py
?? scripts/wire_linux_languages.py
?? tests/c-cp-test-suite/
?? tests/c-mkdir-test-suite/
?? tests/c-mv-test-suite/
?? tests/c-sort-test-suite/
?? tests/py-cp-test-suite/
?? tests/py-mkdir-test-suite/
?? tests/py-mv-test-suite/
?? tests/py-sort-test-suite/
?? tests/rust-cp-test-suite/
?? tests/rust-mkdir-test-suite/
?? tests/rust-mv-test-suite/
?? tests/rust-sort-test-suite/
?? tests/test_cross_language_docker.py
?? tests/test_cross_language_static.py
?? tests/test_docker_benchmark_integration.py
?? tests/test_linux_benchmark_static.py
```
