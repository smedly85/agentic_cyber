# Standardized C utility benchmark: Linux utilities v1

Linux/AMD64 Docker validation completed on 2026-11-01; ARM64 remains pending.

The new selectors are `c-cp`, `c-mv`, `c-mkdir`, and `c-sort`. Historical C
`mkdir`/`sort`, Rust `cp`/`mv`, all Python experiments, research datasets and
results remain unchanged. No implementation or seed source is supplied.

## Scientific contract and scope

The four utilities cover file copying, relocation, directory creation, and
stream ordering with incremental options and observable filesystem or byte-stream
effects. Sharing their contracts across languages removes utility selection as
a confounder. This phase prepares C only; later Rust/Python work should adopt the
same versioned contracts and independently generated Linux expectations.

The [language-neutral contract](linux-utilities-v1-contract.md) is normative.
It specifies operands, errors, streams, permissions, symlinks, overwrite policy,
option precedence and exclusions. C prompts add language/build requirements and
the existing transfer semantic anchors, without specifying algorithms. Every
checkpoint preserves earlier behavior. Checkpoint 000 creates from scratch;
later stages inherit only their own lineage's validated predecessor.

| Selector | Checkpoints | Manifest | Prompts | Suite | Source / executable |
|---|---|---|---|---|---|
| c-cp | 000 Base, 001 -f, 002 -i, 003 -r | `experiments/utilities/c-cp.json` | `prompts/linux-utilities-v1/c-cp/{000_base,001_force,002_interactive,003_recursive}.md` | `tests/c-cp-test-suite` | `src/c_cp/c_cp.c` / `build/c_cp` |
| c-mv | 000 Base, 001 -f, 002 -i | `experiments/utilities/c-mv.json` | `prompts/linux-utilities-v1/c-mv/{000_base,001_force,002_interactive}.md` | `tests/c-mv-test-suite` | `src/c_mv/c_mv.c` / `build/c_mv` |
| c-mkdir | 000 Base, 001 -p, 002 -m | `experiments/utilities/c-mkdir.json` | `prompts/linux-utilities-v1/c-mkdir/{000_base,001_parents,002_mode}.md` | `tests/c-mkdir-test-suite` | `src/c_mkdir/c_mkdir.c` / `build/c_mkdir` |
| c-sort | 000 Base, 001 -r, 002 -f, 003 -u, 004 -c | `experiments/utilities/c-sort.json` | `prompts/linux-utilities-v1/c-sort/{000_base,001_reverse,002_ignore-case,003_unique,004_check}.md` | `tests/c-sort-test-suite` | `src/c_sort/c_sort.c` / `build/c_sort` |

Every oracle is `/opt/gnu/bin/UTILITY`, GNU Coreutils **9.11**, inside Linux
Docker. Source paths above are declarations only: those source files were not
created. All four configurations and 15 checkpoints resolve. The manifest build commands
use the Docker adapter. Linux/AMD64 oracle and adapter calibration passed; ARM64
remains unverified.

## Audit of original mkdir architecture

The original `prompts/mkdir/` ladder is Base, parents, mode. Its implementation
is a single C source and direct compiler command. The original mode prompt
still cites 9.4 and describes a 0777 symbolic departure, whereas its suite pins
9.11 and Darwin. Reusing the prompt unchanged would contradict a Linux oracle.

`config.json` pins platform, oracle version, flag/tag filtering and executable
paths. `config.py` supplies JSON/dotted-key access. `judge_candidate.sh` creates
a temporary configuration with the checkpoint's cumulative flags, discovers
compressed suites, and invokes `runner.py`; it does not edit committed config.

The runner selects cases by required flags and excluded tags, tests exit status,
stdout, stderr and post-operation trees, dispatches property assertions, and
reports per-case and aggregate verdicts. `engine.py` creates a fresh temporary
filesystem per case, applies fixtures and permission faults, sets locale and
umask, executes with time/resource limits, and snapshots types, modes and links.
Symlink metadata is canonicalized separately from observable directory modes.
Permission-sensitive cases cannot meaningfully run as root.

`corpus/corpus.py`, `model/flags.py`, `model/constraints.py`,
`gen/combos.py` and `gen/curated_cases.py` supply discriminating fixtures,
option combinations, negative rules, curated cases, faults and deterministic
random scenarios. `gen/freeze.py` captures GNU results through the same engine;
`gen/generate.py` writes deterministic compressed suites and an inventory.
`selfcheck.sh` verifies platform/oracle identity, repeated generation and corpus
comparison, oracle self-pass, then rejects deliberately wrong behaviors.
`gen/heldout.py` derives structural duals with independent concrete paths/modes
and refreezes their expectations; they live outside public `suites/`.

Reused in the new namespace: runtime engine, runner, config reader, judge wrapper,
property assertions, and in-scope public/held-out input definitions. Original
expectations and platform declarations were **not** copied as Linux truth.
The new shared freezer uses the established engine/result schemas, but replaces
the historical generation/selfcheck entry points with a Docker-only path.
Original generator models remain untouched. Input provenance hashes are in
[linux-utilities-v1-input-provenance.json](linux-utilities-v1-input-provenance.json).

Transfer cases come from `tests/reference_generators/transfer_cases.py` and
their runtime from the existing transfer suites. No Rust/Python implementation
was read or copied into a candidate. Force-only mv cases have been retagged
for the new force-before-interactive sequence.

## Platform differences and specification corrections

The historical column comes from repository documentation. Linux symbolic modes
and `/dev/full` were independently verified in Docker in this task. The excluded
POSIX compatibility behavior is recorded for context, not claimed as newly tested:

| Behavior | Historical Darwin 9.11 | Recorded Linux 9.11 behavior |
|---|---|---|
| `mkdir -m +t` or `a+t` | 01777 | 01755 |
| `mkdir -m a=rwx,+t` or numeric 1777 | 01777 | 01777 |
| `sort +1` with POSIXLY_CORRECT | filename/error | obsolete-key interpretation |
| sort output to `/dev/full` | unavailable | deterministic ENOSPC fault |

The Linux-specific symbolic-mode contract passed direct oracle checks.
The existing stdin-only sort subset excludes obsolete syntax and POSIXLY_CORRECT,
so it does not import that Darwin expectation. A Linux-only ENOSPC input and
independent held-out input now have independently frozen Linux expectations.

Other explicit corrections: mkdir parent creation ensures owner write/search
bits, as GNU requires; symbolic permission-copy syntax is stated because the
inherited mode test surface includes GNU symbolic cases. Sort checking uses
GNU's last-resort comparison unless unique suppresses it; the historical prompt's
folded-equality description was ambiguous. The new cp prompt does not impose
sorted recursive traversal: GNU filesystem enumeration is not a portable order,
and multiple recursive overwrite prompts are outside this version's subset.
No test assertion was weakened to accommodate a result.

## Frozen corpora and independent evaluation

Public `suites/linux-v1.json.gz` and controller-only `heldout/heldout_cases.json.gz`
were generated twice using `/opt/gnu/bin/{cp,mv,mkdir,sort}` inside the pinned
Linux container. Compressed outputs were byte-identical. Each checkpoint passed
its public and hidden oracle self-check; controlled wrong exit expectations were
detected for all 30 checkpoint/split combinations. Input-only predecessors and
revised new-namespace artifacts are archived under `gen/`, never staged for agents.
See the delivery report for input-definition versus execution counts and hashes.

The existing engines still compare exit status, streams, filesystem contents,
types, link targets and required modes using their established assertion policies.
No assertion was relaxed. Permission cases execute as UID 1000. Runs use jobs=1
to stay within the deliberately bounded descriptor limit. Sort's inherited `-y0`
compatibility case is outside the canonical contract, skipped by the runner and
excluded from visible bundles. Two public and two independent hidden sort error
cases were added; forbidden existing file operands also have boundary probes.

`stage_test_bundle.py` keeps only current/prior public cases and runtime files.
It excludes generators, archives, held-out data and future checkpoints. The new
C-only scope filter agrees with runtime exclusions. Hidden judging receives no
agent feedback channel and records counts separately. The isolation scanner still
checks hidden inputs/names/expected values. Its only new exception is the fixed
GNU `/dev/full` diagnostic, identical across all inputs: matching that constant
does not identify a hidden test. Exact stderr comparison in judging is unchanged.
An injected hidden identifier is still detected by the scanner regression test.

## Docker reproduction

Development validation: **Linux/AMD64**, Docker Desktop through WSL2. Preferred
future official target: **Linux/ARM64** on vessel. AMD64 success establishes no
ARM64 reproducibility. Python 3.12.8, GCC 12.2.0 and GNU Coreutils 9.11 are checked
inside containers. The Dockerfile pins Debian snapshot 20250201T000000Z and
verifies the GNU tarball checksum before building. The base multiarch digest is
`sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad`.
`docker/linux-utilities-v1/lock-amd64.json` pins the observed image IDs.
Rebuilds have pinned inputs; bit-identical image rebuilds are not claimed.
Archive the actual image with `docker save` before official runs.

From PowerShell, enter WSL with `wsl.exe --cd "$PWD"`; then run these Bash commands
in the repository (choose new output directory names for repeated oracle runs):

```bash
docker info
BASE=python:3.12.8-bookworm@sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad
bash docker/linux-utilities-v1/build.sh "$BASE" linux/amd64
IMAGE=$(docker image inspect agentic-c-linux-v1 --format '{{.Id}}')
bash docker/linux-utilities-v1/run.sh "$IMAGE" "$PWD/linux-v1-validation-new" linux/amd64
# Compare with the checked-in lock; record a newly built image ID before adapting it.
python3 scripts/validate_linux_static.py
python3 tests/test_docker_benchmark_integration.py
python3 scripts/validate_docker_entrypoints.py
python3 scripts/validate_docker_adapter.py --output "$PWD/adapter-validation-new"
```

The first launcher is a **trusted oracle job**, using read-only staged inputs and
a fresh writable output directory. It never executes generated candidates. It
checks `uname`, Python platform, architecture, oracle/compiler/runtime versions,
and freezes/tests both corpora. Failures preserve output and logs. Publication is
explicit via `publish_linux_corpora.py OUTPUT/validated`; revised new-namespace
artifacts require `--revise-new-namespace`, which archives previous bytes.

On vessel, once its existing Docker service is accessible, use the same pinned
base and repository files; no transfer or context changes have been performed:

```bash
docker info
BASE=python:3.12.8-bookworm@sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad
bash docker/linux-utilities-v1/build.sh "$BASE" linux/arm64
IMAGE=$(docker image inspect agentic-c-linux-v1 --format '{{.Id}}')
bash docker/linux-utilities-v1/run.sh "$IMAGE" "$PWD/linux-arm64-validation-new" linux/arm64
```

Then create a separately reviewed lock with `platform: linux/arm64`, the actual
ARM64 oracle image ID and pinned compiler base; set `C_BENCHMARK_LOCK` to that
absolute file path. Validate/publish ARM64 corpora in a separately preserved
snapshot with `--platform linux/arm64`, review cross-architecture differences,
and rerun the same static, integration, entry-point and adapter commands. The
adapter refuses corpus/target architecture mismatch. Do not overwrite AMD64
evidence or claim ARM64 validation before those checks succeed.

## Candidate execution and controller integration

The existing controller used host shell build/public/hidden/boundary commands.
New C manifests now route compilation through `docker_benchmark.py`; public
wrappers, held-out judging and boundary probes use the same mandatory backend.
The controller rejects noncanonical new-C command overrides, exports the
controller root/lock, records public and held-out reports separately, and treats
status 2 as infrastructure failure instead of giving it to the agent for repair.
Security analysis remains disabled for these new selectors. Plan fingerprints
include adapter, contract, isolation and lock provenance. Historical branches of
these helpers retain their previous behavior.

Compilation runs as UID 1000 in the pinned compiler image. A trusted judge
container holds one split's corpus but never executes the candidate. For each
case the host transport launches a fresh container with only input fields and
the candidate bytes; expected outputs and other cases are not transmitted.
A trusted supervisor prepares fixtures, chroots the candidate, closes inherited
descriptors, drops groups/UID/GID to 1000, and runs it without capabilities.
The jail contains only that fixture, executable and required shared libraries:
no oracle executables, shell, Python, controller files, procfs or Docker socket.
The supervisor alone uses a limited capability set to prepare the jail and
restore filesystem metadata; no container is privileged.

Containers have no external network, no host bind mounts, read-only roots,
no-new-privileges, CPU/memory/process limits and bounded tmpfs. Each child also
has CPU, address-space, file-size, process and wall-clock limits. Output capture
is file-size bounded. The transport kills/removes containers on timeout or error;
there is no native fallback. Environment is LC_ALL=C, TZ=UTC, umask 022 unless an
individual permission case specifies another mask. Compiler errors/candidate
failures return 1; Docker/setup failures return 2.

Docker plus chroot is not a complete hostile-code security boundary: the Linux
kernel is shared, and kernel exploits, side channels and daemon vulnerabilities
remain possible. The trusted controller and generation agent require appropriate
host access controls; bundle isolation is not a general sandbox for a malicious
host-side agent. No full Aider/Ollama run was performed. Bounded shell entry-point
tests and isolated GNU calibration validate the backend without creating lineages.

## Review status and limitations

Linux/AMD64 is ready for infrastructure review, subject to the recorded checks
in the [delivery report](linux-utilities-v1-report.md). ARM64/vessel is pending.
No formal lineage, research outcome, structural diversity result or candidate
correctness claim is produced. Corpora are restricted finite coverage, not a
proof of GNU equivalence. Exhaustive recursive permission combinations and
independent comparator/security review remain useful before official experiments.
Historical test source modules for the controller were absent in this checkout;
available new static/integration tests cover the changed C paths, but a complete
historical controller regression suite could not be run.
