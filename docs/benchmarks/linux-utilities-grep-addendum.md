# Standardized grep extension validation addendum

Date: 2026-11-15. Implementation branch: `feature/standardized-grep` (uncommitted).
This addendum extends, but does not replace, the sealed
[12-configuration report](linux-utilities-report.md). No model-generated grep
candidate, development trace, result, lineage seed, commit, push or merge was
created during this work.

## Configuration and checkpoint matrix

The active standardized catalog has 15 configurations and 60 cumulative
checkpoints. Every checkpoint 000 has `source_mode=new`; every later checkpoint
has `source_mode=existing` and inherits only its own trace's validated predecessor.

| Language | cp | mv | mkdir | sort | grep | Total |
|---|---:|---:|---:|---:|---:|---:|
| C | 4 | 3 | 3 | 5 | 5 | 20 |
| Rust | 4 | 3 | 3 | 5 | 5 | 20 |
| Python | 4 | 3 | 3 | 5 | 5 | 20 |
| **Total** | **12** | **9** | **9** | **15** | **15** | **60** |

The grep ladder is identical in all languages: 000 fixed-byte base, 001 `-H` /
`--with-filename`, 002 `-h` / `--no-filename`, 003 `-r` / `--recursive`, and
004 `-i` / `--ignore-case`. The canonical source/executable pairs are
`src/c_grep/c_grep.c` / `build/c_grep`, `src/rust_grep/rust_grep.rs` /
`build/rust_grep`, and `src/py_grep/py_grep.py` / `build/py_grep.py`.

## Contract and corpus

The normative language-neutral contract is in
[linux-utilities-contract.md](linux-utilities-contract.md). It is a bounded
fixed-byte substring search, not a regular-expression or full GNU grep task.
It covers operand termination, stdin, multiple operands, byte-invalid content,
NULs, empty patterns/input, final unterminated records, filename prefix policy,
permissions/errors, symlinks, normal 0/1/2 grep status classification,
deterministic bounded recursion and ASCII-only folding in `LC_ALL=C`. Filename
`-` remains an ordinary pathname by explicit specification.

`tests/c-grep-test-suite/` owns the only grep expectations. The Rust and Python
suite directories are thin descriptors resolving to that corpus. Fresh Docker
freezing produced 88 public definitions and 29 held-out definitions. Cumulative
definition counts are:

| Checkpoint | Implemented flags | Public | Held-out | Oracle public PASS/SKIP | Oracle held-out PASS/SKIP |
|---|---|---:|---:|---:|---:|
| 000 | none | 32 | 6 | 63 / 50 | 9 / 23 |
| 001 | `-H` | 40 | 11 | 68 / 44 | 15 / 18 |
| 002 | `-H -h` | 50 | 14 | 77 / 35 | 19 / 15 |
| 003 | `-H -h -r` | 65 | 20 | 90 / 21 | 25 / 9 |
| 004 | `-H -h -r -i` | 82 | 29 | 113 / 6 | 37 / 0 |

Execution counts exceed definition counts where stdin is checked through both
pipe and redirected-file delivery. All ten public/held-out checkpoint mutation
controls were detected. The final sealed regeneration was byte-identical to the
checked-in public corpus, held-out corpus, manifest and validation report:

- input definitions: `ba1cae369cf279de42ba89052e3739b8253366ece6d6514dc51fde8666f2740c`
- public corpus: `9cfd1a70a24e5acaab679ad7a01d75e5f84a2afc820f55c977e86d4f88fd1908`
- held-out corpus: `394b3ca576dbf36442f4cd22b5ab3cb568b23a14fa1751b464b3aa0fcef14177`
- corpus manifest: `5dba172af929c9644420051b6c0f87af607d82c4a559df4fa7c9df534b2cbaa4`
- validation report: `0cffc98aa1ec3d65af0558eac614bfc334de2cbd96244ce0f841bf3c1b2f0d69`

The manifest identifies ten specification-derived grammar/boundary cases. All
matching expectations, including the intentional ordinary-filename treatment of
`-`, were independently exercised against the pinned oracle or explicitly marked
as bounded-contract departures.

## GNU grep oracle provenance

GNU grep is independently pinned; the Coreutils 9.11 image and
`docker/linux-utilities/lock-amd64.json` were not overwritten.

| Item | Observed/verified value |
|---|---|
| Project/version | GNU grep 3.12 |
| Upstream source | `https://ftp.gnu.org/gnu/grep/grep-3.12.tar.xz` |
| Source SHA-256 | `2649b27c0e90e632eadcd757be06c6e9a4f48d941de51e7c0f83ff76408a07b9` |
| Immutable image | `agentic-grep-oracle@sha256:cbbad98ee0789ff00de59bf1a3a825f38a137f86ee4a67c19e3fbd1528217508` |
| Local platform image ID | `sha256:5a1839c2ff7be3eee3a8e482ab334aa174e9f2f16b8edc8be1c85387d1cc39bc` |
| grep binary SHA-256 | `5f90bdcaa8d67f8cae1be43fb4ef0a1642c04a8dd0fd7870d33b9eb358b935f2` |
| Platform/toolchain | Linux x86_64; GCC 12.2.0; Python 3.12.8 |
| Base platform manifest | `sha256:42a38e1ed65aa195d65c6563c54187a07dad361158129278fd3b2dfe5a783528` |

The image build verified the source checksum before compilation. Runtime probes
verify version/hash and the assumptions behind binary-text `-a`, fixed matching
`-F`, `-i`, single/multiple filename prefixes, `-H`, `-h`, and byte-sorted
recursive traversal. Jobs use Linux/AMD64, no network, read-only roots, dropped
capabilities, no-new-privileges and finite CPU/memory/PID/file limits. Missing or
wrong grep fails closed; host grep is never consulted.

The `agentic-grep-oracle@sha256:...` and base-image references currently name
objects in the local Docker content store; no registry or verified `docker save`
archive is recorded. A digest identifies content but does not distribute it.
Therefore a clean Vessel host cannot pull these names as written. Before Vessel
validation, either publish both images to an immutable registry and update a new
lock with those pullable references, or distribute `docker save` archives with
separately recorded archive SHA-256 values and verify the loaded platform IDs.
Rebuilding is supported, and now fails if the resulting grep binary hash differs,
but a bit-identical OCI image digest is not claimed.

## Validation evidence

Verified on the pinned Linux/AMD64 Docker infrastructure:

- all 15 manifests resolved; all 60 checkpoint prompts and cumulative bundles
  were nonempty; C/Rust/Python grep resolved to `tests/c-grep-test-suite`;
- all five C utilities passed checkpoint filtering and held-out isolation;
- 53 Python files parsed and 25 shell files passed `bash -n`;
- all 17 integrity checks passed inside Linux; the combined integrity/workflow
  run passed 50/50 tests;
- all 40 Rust/Python premature-feature probes passed, with grep requiring status
  2 so normal no-match status 1 is never misclassified as rejection;
- all 80 Rust/Python runtime mutation controls passed with exact execution counts;
- C, Rust and Python grep checkpoint-000 entrypoint checks compiled temporary
  no-op controls successfully and rejected them in both public and held-out judges;
- the three entrypoint reports each recorded public `FAIL=62, SKIP=51` and
  held-out `FAIL=9, SKIP=23`, demonstrating that a buildable wrong program is
  detected rather than treated as infrastructure failure;
- final GNU grep validation passed all five public and held-out filters, all ten
  mutations, frozen-bundle isolation and byte-identical regeneration;
- existing cp/mv/mkdir/sort contract, integrity, workflow, boundary and mutation
  paths continued to pass before the newly added grep cases were reached.

The Windows-native negative-permission integrity test cannot restore a directory
after deliberately removing access under Windows ACL semantics. The same test
passed in the required pinned Linux container; this is recorded as a host-only
environment limitation, not as a benchmark pass on Windows.

Pending by design: Linux/ARM64 reproduction, a fresh clean-commit Vessel
preflight/approval record, and every formal grep development trace/diversity/
security result. Those cannot truthfully exist until this uncommitted branch is
reviewed and a separate formal-experiment branch is selected.

## Fingerprint compatibility

The planner hashes shared catalog, oracle, Docker worker and contract inputs.
This extension modifies six such files, so all 12 prior standardized configurations
correctly receive new fingerprints even though their manifests, prompts, judges
and corpora were not changed by this branch. The preserved fingerprint table was
recorded at commit `5ffe7420253dfc18f466a2385678f17a30fb39fc`; `main` evolved after
that commit before grep work began, so not every old/new difference is attributable
to grep. The previous exact "after" values were also generated with normal CLI
defaults while the historical table used the 0/0 static-report parameters; they
were not comparable and have been withdrawn. The corrected scope and input hashes
are in [grep-extension-fingerprint-impact.json](grep-extension-fingerprint-impact.json).

Final post-extension fingerprints must be recorded only after commit from a clean
Linux checkout using one documented parameter set. Never resume an old trace with
those fingerprints. Reproduce each prior trace from the `repository_commit`, plan,
image lock and `config_fingerprint` embedded in its own `lineages.json`; do not edit
sealed metadata. Keep execution protocol schema version 1, but identify this expanded
15/60 catalog as benchmark revision 2 before any formal grep trace.

## File inventory

Added:

- `docker/grep-oracle/{Dockerfile,build.sh,run.sh,lock-amd64.json}`
- `experiments/utilities/{c-grep.json,rust-grep.json,py-grep.json}`
- `prompts/linux-utilities/{c-grep,rust-grep,py-grep}/` with
  `000_base.md`, `001_with-filename.md`, `002_without-filename.md`,
  `003_recursive.md`, and `004_ignore-case.md` in each directory
- `tests/c-grep-test-suite/{README.md,config.json,config.py,engine.py,runner.py,props.py,judge_candidate.sh,validation.json}`
- `tests/c-grep-test-suite/gen/{generate.py,inputs.json.gz}`
- `tests/c-grep-test-suite/suites/{linux.json.gz,MANIFEST.json}`
- `tests/c-grep-test-suite/heldout/heldout_cases.json.gz`
- `tests/{rust-grep-test-suite,py-grep-test-suite}/{README.md,config.json,judge_candidate.sh}`
- `tests/reference_generators/standard_grep_oracle.py`
- `docs/benchmarks/{linux-utilities-grep-addendum.md,grep-extension-fingerprint-impact.json,legacy-cleanup-audit.md,grep-final-reproducibility-audit.md}`

Changed:

- benchmark/oracle execution: `docker/linux-utilities/run.sh`,
  `scripts/linux_benchmark.py`, `scripts/docker_benchmark.py`,
  `scripts/docker_benchmark_worker.py`, `scripts/validate_docker_adapter.py`,
  `scripts/validate_linux_static.py`
- catalog/orchestration/isolation: `scripts/linux_utilities_catalog.py`,
  `scripts/checkpoint_boundary_gate.py`, `scripts/stage_test_bundle.py`,
  `scripts/run_experiment.sh`, `scripts/run_lineage_experiment.sh`,
  `scripts/vessel_preflight.py`, `scripts/vessel_smoke_stage.sh`
- regression checks: `scripts/validation/test_integrity.py`,
  `scripts/validation/test_runtime.py`, `scripts/validation/test_workflow.py`
- active documentation: `docs/benchmarks/linux-utilities.md`,
  `docs/benchmarks/linux-utilities-contract.md`,
  `docs/benchmarks/linux-utilities-vessel.md`, and
  `docs/benchmarks/vessel-validation-maintenance.md`
- navigation: `README.md` and `experiments/utilities/README.md`

No `src/*grep*` candidate file was added. The original report, frozen legacy
corpora, formal runs and completed experimental evidence were not modified.

## External reproduction

From a clean checkout of the reviewed grep-extension commit on Linux/AMD64 (or
through WSL with Docker Desktop), using fresh output directories:

```bash
bash docker/linux-utilities/build.sh \
  python:3.12.8-bookworm@sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad \
  linux/amd64
CORE_IMAGE=$(docker image inspect --platform linux/amd64 agentic-linux-utilities --format '{{.Id}}')
bash docker/grep-oracle/build.sh "$CORE_IMAGE" linux/amd64
GREP_IMAGE=$(docker image inspect --platform linux/amd64 agentic-grep-oracle --format '{{.Id}}')
bash docker/grep-oracle/run.sh "$GREP_IMAGE" "$PWD/grep-oracle-validation-new" linux/amd64
python3 -B scripts/validate_linux_static.py --output "$PWD/static-validation-new"
for s in c-grep rust-grep py-grep; do
  python3 -B scripts/validate_docker_entrypoints.py --utility "$s" \
    --output "$PWD/entry-$s-new"
done
python3 -B scripts/run_vessel_validation_tests.py --suite workflow --suite integrity
```

Compare observed image IDs, source/binary hashes and regenerated corpus hashes to
the lock and this addendum. Do not substitute a host grep or mutable image tag.
These commands validate infrastructure only; they do not launch Aider/Ollama or
create a development trace.
