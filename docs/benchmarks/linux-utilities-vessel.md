# linux-utilities on vessel: preflight and checkpoint-000 smoke tests

Diagnostic procedure only. It produces no formal results, no lineage seeds and no
change to the AMD64 lock, corpora or validation evidence. Run everything from the
repository root on vessel, in a native arm64 shell. The controller, Ollama and
Docker all run locally, so no tunnel and no remote endpoint are involved.

| Piece | Role |
|---|---|
| `scripts/vessel_preflight.py` | Runs non-generative checks, temporary probes and optional evidence/report writes, and fails closed. It never generates, installs, pulls, builds, or changes a context. |
| `scripts/vessel_smoke_stage.sh` | Runs checkpoint 000 for one selector. It prints its command unless `--generate` is given. |
| Reused unchanged | `lineage_plan.py`, `stage_test_bundle.py`, `run_experiment.sh`, `heldout_judge.py` (via the manifest `extra_test_command`), `checkpoint_boundary_gate.py`, `docker_benchmark.py` |

The smoke wrapper's `run_experiment.sh` arguments are identical to the stage-000
line from `run_lineage_experiment.sh --dry-run` (checked on WSL for all three
selectors). Diagnostic differences: `--max-loops` is capped at 1, the output directory must
be new and outside the repository, and observed model provenance is forwarded
after preflight. The print-only plan has no observed model provenance yet.

## 1. Execution path: AMD64 under emulation (Option A)

`docker/linux-utilities/lock-amd64.json` pins `linux/amd64`. The frozen corpora
record `x86_64`, and `docker_benchmark.py` refuses a mismatched target. Running
the validated configuration on vessel therefore requires **AMD64 containers
under emulation**, using the exact validated images. The two locally built
images cannot be pulled from a registry:

The original lock remains authoritative. Preflight accepts only its original
immutable references or the corresponding original **platform manifest** digests.
A platform manifest commits to the complete OCI configuration blob and ordered
layer blobs. It is not a configuration digest or an OCI index digest.

On the original Windows/WSL Docker host, capture a small metadata evidence file
(no image archive, build, pull, transfer, or inference):

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 -B scripts/vessel_preflight.py \
  --capture-image-evidence "$HOME/linux-utilities-amd64-image-evidence.json"
sha256sum "$HOME/linux-utilities-amd64-image-evidence.json"
```

The output must be new and outside the repository. Capture resolves the original
lock references using platform-aware Docker inspection and checks the recorded
AMD64 manifest and ordered-filesystem hashes. The JSON records the original ref,
platform manifest, platform, ordered diff IDs, and a canonical fingerprint of the
runtime configuration returned by inspect. That last fingerprint is explicitly
**not** an OCI config-blob digest: the authenticated manifest binds the full blob.

Supply this source-host evidence through the normal reviewed transfer process,
and compare its SHA-256 on vessel (`shasum -a 256 FILE`). Image transport itself
is outside this preparation procedure; preflight never saves, loads or pulls.
All three validated images must already be present on vessel.

```bash
export VESSEL_IMAGE_EVIDENCE="$HOME/linux-utilities-amd64-image-evidence.json"
```

Every target image must match the original platform manifest AND the captured
configuration/platform/ordered filesystem identity. Missing evidence, changed
configuration, unrelated layers, and unknown references fail closed. Docker
must support `image inspect --platform` and return a platform manifest descriptor.

An independently reviewed alternate lock may change only the three execution
image references, and only to these original platform manifests:

| Field | Allowed platform manifest |
|---|---|
| `oracle_image` | `sha256:42a38e1ed65aa195d65c6563c54187a07dad361158129278fd3b2dfe5a783528` |
| `compiler_image` | `sha256:90b5639c188a54aa4252028b19d6f1134e43a13d0947ba463bae09a5b6776804` |
| `rust_compiler_image` | `sha256:9c040eb21f2e7bdd9d913d50ee39cc382622a4b7f6d615531dbb7bc562129514` |

Select such a lock with an absolute `LINUX_BENCHMARK_LOCK` path. Preflight and the
unchanged execution adapter resolve those same references from that same lock.
Never edit `lock-amd64.json`. No alternate lock is created by these scripts.
The table identifies allowed manifests, not guaranteed Docker lookup handles:
the source WSL engine does not resolve these bare manifest digests as image refs.
An alternate reference is usable only if platform-aware inspection actually
resolves it on the target store. Otherwise preflight fails before any probe or
generation; do not infer that a digest printed by inspect is runnable.

**Classic-store config-ID-only transfers are unsupported and rejected.** A
matching layer list cannot authenticate a replacement configuration ID. A
verified original-manifest-to-raw-config mapping and cross-store validation are
outstanding requirements before such transfers can be supported. Do not work
around this failure by substituting IDs or relaxing validation. Compatibility of
the actual target store remains to be established on vessel.

Emulation must also exist in the Docker VM. Colima provides it via
`--vz-rosetta` (vz) or qemu binfmt. Preflight checks it but never changes it.
`colima status` shows the current profile. Changing it (for example
`colima stop && colima start --vm-type vz --vz-rosetta`) is an operator decision.

**Emulation equivalence is unverified.** Candidates run in a chroot jail that
contains no emulator, so emulation must be registered with the fix-binary flag.
QEMU/Rosetta can also distort the timing of per-case timeouts and the
address-space rlimits, and such distortions would surface as candidate
failures. Before any generation, run the jailed Docker validation in step 3.

## 2. Preflight

```bash
cd ~/agentic_cyber            # /Users/sonjabrown/agentic_cyber
# Use the reviewed checkout containing these scripts; inspect its revision.
git status -sb
git rev-parse HEAD
export PYTHONDONTWRITEBYTECODE=1
export VESSEL_IMAGE_EVIDENCE="$HOME/linux-utilities-amd64-image-evidence.json"
export PYTHON_BIN="$(command -v python3)"
python3 scripts/vessel_preflight.py \
  --temperature 1.0 --architect-think low --sampling-seed 42 \
  --num-ctx 65536 --max-tokens 65536 \
  --json-report "$HOME/linux-utilities-smoke/preflight-$(date -u +%Y%m%dT%H%M%SZ).json"
```

The architect values shown match the recorded historical values in section 5.
This does not make the diagnostic workflow equivalent to those formal runs.
Omitting them reports architect sampling as UNRESOLVED; editor pinning is still checked.

Checks, in order:

1. Git revision and tracked changes. Unavailable or timed-out status fails. A dirty tree fails unless `--allow-dirty` is given; the generation wrapper does not supply that override.
2. Host OS and architecture. A Rosetta-translated shell fails.
3. `python3` resolves to `PYTHON_BIN` and imports every controller module. Manifests call bare `python3`, so Apple's Python 3.9 would fail here.
4. Bash version, and `bash -n` on the three controller scripts.
5. A real timeout test: `timeout` or `gtimeout --signal=TERM --kill-after=1 1 sleep 5` must exit 124.
6. `aider --version` must report `aider 0.86.2`, the version every formal `lineages.json` records.
7. Colima status, Docker context and endpoint, and `DOCKER_HOST`/`DOCKER_CONTEXT` (`DOCKER_CONTEXT` overrides `DOCKER_HOST`; otherwise `DOCKER_HOST` overrides the current context). Only a local absolute Unix-socket endpoint is accepted; SSH/TCP endpoints fail before daemon probes. The daemon must report `OSType=linux`. No context or Docker environment variable is changed.
8. Every execution reference resolves to the original platform manifest and matches the source-host configuration/platform/filesystem evidence. Config-ID-only transfers fail. Preflight never pulls.
9. `docker run --pull never --platform linux/amd64 <oracle> uname -m` reports `x86_64`.
10. `docker_benchmark.py preflight` passes for each selector (GCC 12.2.0, rustc 1.85.1, Python 3.12.8).
11. Editor pinned to temperature 0, seed 0 and `editor-diff`. When supplied, the architect settings are rendered through `aider_settings.py`.
12. Ollama `GET /api/version` and `/api/tags`, and `POST /api/show` (metadata only) at the loopback root URL; `/v1` is refused. Both models must be available with valid digests, positive sizes, parameter/quantization metadata and positive context lengths. Missing metadata fails. Observed identities and a model-definition fingerprint are retained; they are not verification against unknown historical digests.
13. Checkpoint 000 for each selector. The plan resolves with mode `new` and no flags. Manifest commands pass `check-commands`. The prompt renders. The bundle fingerprint matches the plan. `check_heldout_isolation.py` and the boundary matrix pass.
14. Judging inputs are present: runtime, public and held-out corpora. The corpus architecture must match the lock.

Resolving failures (operator actions; preflight performs none of them):

| Failure | Command |
|---|---|
| python3 too old | `brew install python@3.12`, then put it first on `PATH` (or use `ac_venv/bin`) |
| no timeout | `brew install coreutils` (provides `gtimeout`), or `ln -sf "$PWD/scripts/timeout.py" ~/.local/bin/timeout` |
| aider missing or wrong version | `uv tool install --force aider-chat==0.86.2`, or `python3 -m pip install aider-install && aider-install`, then pin 0.86.2 |
| docker/colima | `brew install docker colima`, then `colima start` with the intended profile |
| image missing or unverified | stop; arrange reviewed image availability and the source-host evidence in section 1 |
| Ollama down / model missing | start the existing service; `ollama pull <name>` only by explicit decision |

## 3. Docker validation on vessel (no model; required before generation)

These commands reuse existing validators and start no Aider or Ollama process.
Output goes outside the repository. They exercise the jailed candidate path
under emulation; any failure blocks generation and must be investigated. It does
not by itself prove that emulation caused the failure. The wrapper does not
automatically run these validators: completing them is a required operator step.

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
V="$HOME/linux-utilities-smoke/docker-validation-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$V"
python3 -m unittest tests.test_docker_benchmark_integration tests.test_cross_language_docker 2>&1 | tee "$V/unittest.log"
python3 scripts/validate_docker_adapter.py --utility c-cp --utility rust-cp --utility py-cp --output "$V/calibration"
for s in c-cp rust-cp py-cp; do
  python3 scripts/validate_docker_entrypoints.py --utility "$s" --output "$V/entry-$s" || exit $?
done
```

Optional, and slow under emulation: a full trusted-oracle revalidation with
the effective verified oracle reference, including an approved alternate lock:

```bash
ORACLE="$(python3 -B -c 'import sys; sys.path.insert(0,"scripts"); import docker_benchmark; print(docker_benchmark.settings()["oracle_image"])')"
bash docker/linux-utilities/run.sh "$ORACLE" "$V/oracle" linux/amd64
```

That script bind-mounts a `mktemp -d` directory under `/var/folders`, so first
confirm Colima shares that path. The smoke path itself uses no bind mounts.

## 4. Smoke tests (explicitly opt-in; one selector at a time)

Leave off `--generate` to print the exact `run_experiment.sh` command without
generation or creating diagnostic output. Read-only planning commands do execute;
Python bytecode writes are suppressed. With `--generate`, a fresh external output
directory is created first so `preflight.log` and `preflight.json` can be retained,
even on failure. The wrapper exits 4 on preflight failure before Aider starts.
Both explicit output and `TMPDIR` are resolved through symlinks and must be outside
the repository. Successful observed model provenance is forwarded to the runner
and included in the final plan fingerprint. It then:

- runs one initial generation and at most one repair, each bounded by `--timeout` (enforced via timeout/gtimeout);
- runs public tests in Docker;
- runs held-out evaluation in the controller, never fed back to the agent;
- runs the boundary gate after a public pass;
- writes `smoke-summary.json` with `public_outcome`, `heldout_outcome` and `infrastructure_failure`.

```bash
export PYTHON_BIN="$(command -v python3)"
SAMPLING=(--temperature 1.0 --architect-think low --sampling-seed 42 --num-ctx 65536 --max-tokens 65536)  # explicit diagnostic selection; not historical equivalence
mkdir -p "$HOME/linux-utilities-smoke"
for s in c-cp rust-cp py-cp; do
  bash scripts/vessel_smoke_stage.sh --selector "$s" --timeout 1800 --max-loops 1 "${SAMPLING[@]}" \
    --ollama-url http://127.0.0.1:11434 \
    --output-dir "$HOME/linux-utilities-smoke/$s-$(date -u +%Y%m%dT%H%M%SZ)"          # print only
done
# After reviewing the printed command, run one selector at a time, e.g.:
bash scripts/vessel_smoke_stage.sh --selector c-cp --timeout 1800 --max-loops 1 "${SAMPLING[@]}" \
  --ollama-url http://127.0.0.1:11434 \
  --output-dir "$HOME/linux-utilities-smoke/c-cp-$(date -u +%Y%m%dT%H%M%SZ)" --generate
```

Repeat the `--generate` command with `--selector rust-cp`, then `--selector py-cp`.
Each run uses a fresh directory and starts from no source, so the candidates are
independent.

Wrapper exit codes:

| Exit | Meaning |
|---|---|
| 0 | Classified without infrastructure failure. The candidate verdict is in the summary. |
| 1 | Infrastructure/controller failure, or the timeout was not enforced. |
| 2 | Usage error. |
| 4 | Preflight failed; nothing generated. |

## 5. Historical evidence and diagnostic choices

The four recorded formal runs agree: architect temperature **1.0**, thinking
**low**, seed **42**, context **65536**, maximum generated tokens **65536**;
editor temperature **0**, seed **0**, format **whole**; repair budget **3** and
per-invocation timeout **1800 seconds**. Top-p was unset. The Python guides
explicitly describe different diagnostic settings; they do not contradict this
historical record.

This smoke wrapper retains its existing diagnostic choices: **editor-diff** and
at most **one repair**, at checkpoint 000 only. It requires explicit temperature,
thinking, seed and context; maximum tokens and top-p remain optional. These are
not equivalent historical formal-run conditions. No sampling value or editor
format is silently changed by this preparation.

Historical `model_provenance` is null. Current digests cannot be verified against
invented historical digests. Preflight establishes availability and records a
valid current identity, not historical identity equivalence. Future comparable
formal runs need an explicit choice of conditions, approved model identities,
controller/benchmark provenance, and accepted vessel emulation evidence.

## 6. Native ARM64 (Option B, separate configuration)

This option is not prepared here and is never substituted for AMD64. It
requires the following:

1. `bash docker/linux-utilities/build.sh "$BASE" linux/arm64`, plus the Rust image built with `--platform linux/arm64`.
2. A new `lock-arm64.json` holding the observed IDs and ARM64 manifest digests.
3. A trusted-oracle run via `run.sh … linux/arm64`.
4. ARM64 corpora regenerated and published as a separately preserved snapshot (`publish_linux_corpora.py --platform linux/arm64`), with cross-architecture differences reviewed.
5. All validators in section 3 rerun.

AMD64 frozen expectations must not be reused as ARM64 truth. The adapter refuses
a corpus whose recorded architecture differs from the lock.

## Readiness states

| State | Can be established on Windows? |
|---|---|
| Ready to transfer to vessel | yes |
| Ready to attempt preflight on vessel | yes |
| Verified ready for model generation | only after sections 2 and 3 pass on vessel |
| Formal lineage readiness | no: needs explicitly chosen formal conditions, model identity controls and accepted emulation evidence |
