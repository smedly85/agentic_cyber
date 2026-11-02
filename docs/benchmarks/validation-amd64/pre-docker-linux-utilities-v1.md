# Standardized C utility benchmark: Linux utilities v1

**Status: preparation only; not ready for formal lineage generation.** Docker
functional verification was unavailable on the Windows development machine on
2026-11-01. The WSL Docker client is 29.1.3, linux/amd64, but daemon access fails
with `permission denied ... /var/run/docker.sock`. That is client provenance,
not evidence of a Linux container. No container OS, architecture, compiler or
oracle version has been observed. No native execution was substituted.

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
created. All four configurations are statically resolvable; all functional
validation remains pending. The manifest build command deliberately refuses
candidate compilation until the isolation adapter is validated.

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

These are differences documented by the historical repository, not newly
measured results from this task:

| Behavior | Historical Darwin 9.11 | Recorded Linux 9.11 behavior |
|---|---|---|
| `mkdir -m +t` or `a+t` | 01777 | 01755 |
| `mkdir -m a=rwx,+t` or numeric 1777 | 01777 | 01777 |
| `sort +1` with POSIXLY_CORRECT | filename/error | obsolete-key interpretation |
| sort output to `/dev/full` | unavailable | deterministic ENOSPC fault |

The new symbolic-mode contract is Linux-specific and must still be verified.
The existing stdin-only sort subset excludes obsolete syntax and POSIXLY_CORRECT,
so it does not import that Darwin expectation. A Linux-only ENOSPC input and
independent held-out input are prepared without any invented expected outcome.

Other explicit corrections: mkdir parent creation ensures owner write/search
bits, as GNU requires; symbolic permission-copy syntax is stated because the
inherited mode test surface includes GNU symbolic cases. Sort checking uses
GNU's last-resort comparison unless unique suppresses it; the historical prompt's
folded-equality description was ambiguous. The new cp prompt does not impose
sorted recursive traversal: GNU filesystem enumeration is not a portable order,
and multiple recursive overwrite prompts are outside this version's subset.
No test assertion was weakened to accommodate a result.

## Public and held-out data

`gen/inputs.json.gz` stores input definitions and assertion policies only.
`suites/pending.json.gz` permits static planner/filtering inspection; every case
is marked `linux_freeze_pending` and runtime judging exits with infrastructure
status 2 rather than treating missing expectations as success. The held-out
corpus is also input-only. **These are not frozen Linux results.**

The independent GNU oracle must populate new outputs in a fresh directory.
The freezer executes every case twice, byte-compares canonical outputs, records
oracle/toolchain/image hashes, checks the reference against both corpora for
every checkpoint, and changes expected exit codes to test assertion sensitivity.
These controlled mutations do not supply candidate source implementations.

`stage_test_bundle.py` remains unchanged: its allowlist excludes generators,
models and hidden corpora, prunes properties, and filters future checkpoint
cases out of the bytes supplied to the agent. `check_heldout_isolation.py` also
remains unchanged and recognizes the new identities through the planner.
The Docker validator applies the same isolation rules to newly frozen data.
Hidden results remain separately recorded and must never become repair feedback.

## Docker configuration and vessel commands

Intended official target: **Linux ARM64 (`aarch64`)**, subject to compatibility
checks on vessel/Colima. Explicit amd64 is available for development, but it is
a separate provenance condition, not interchangeable experimental data.

Toolchain requirements: Python **3.12.8**, GCC **12.2.0**, GNU Coreutils **9.11**.
The base image must include a resolved immutable digest. Debian dependencies
come only from snapshot **20250201T000000Z**. The GNU tarball checksum comes
from the [GNU 9.11 release announcement](https://lists.gnu.org/archive/html/coreutils-announce/2026-04/msg00000.html).
The Dockerfile verifies that checksum before building the reference. The
resulting immutable image ID and complete package inventory are recorded.
No base-image digest or final-image ID has been resolved on this machine.

On vessel, from the repository root, with Colima's Docker context selected:

```bash
docker version
docker buildx imagetools inspect python:3.12.8-bookworm
# Resolve the immutable multiarch index digest printed by that command:
BASE_DIGEST="$(docker buildx imagetools inspect python:3.12.8-bookworm --format '{{.Manifest.Digest}}')"
bash docker/linux-utilities-v1/build.sh \
  "python:3.12.8-bookworm@${BASE_DIGEST}" linux/arm64
IMAGE_ID="$(docker image inspect agentic-c-linux-v1 --format '{{.Id}}')"
# Choose a directory that does not exist; the launcher refuses overwriting.
bash docker/linux-utilities-v1/run.sh \
  "$IMAGE_ID" "$PWD/linux-v1-validation-001" linux/arm64
```

Archive `BASE_DIGEST`, `IMAGE_ID`, the image itself (`docker save`), provenance
files, `container-inspect.json`, `image-inspect.json`, logs and generated corpus
hashes together. Rebuilds must use the archived digest, not resolve a fresh tag.
If buildx's inspection template is unsupported, copy the printed `Digest:`
value into `BASE_DIGEST`; the build script rejects a mutable tag or empty digest.

The launcher uses a non-root UID, no networking, read-only root filesystem,
dropped capabilities, no new privileges, CPU/memory/process/file limits, and a
30-minute outer timeout. Case engines impose their own timeouts and fresh
temporary filesystems. Locale is C, timezone UTC, baseline umask 022; mkdir
cases explicitly override umask. Inputs are copied to a disposable container;
there is no host repository/results bind mount or Docker socket. A disposable
Docker-managed volume holds new validation outputs, copied out after shutdown.
Failures preserve logs and any completed utility artifacts in that new output
directory; an existing directory is never reused.

Verification requires Linux from both `uname -s` and Python, actual architecture
equal to `BENCHMARK_ARCH`, exact compiler/runtime/oracle versions, and an image
ID. Compiler checking builds an object-only probe, never a utility or seed.

## Controller audit and remaining isolation work

The historical controller evaluates build commands in the agent workdir, runs
public judges there, runs the held-out wrapper in the controller shell, and
rebuilds in a temporary tree before boundary checks. Those paths are native by
default. Merely changing a platform flag or wrapping the public judge would
leave native compilation, hidden evaluation and boundary execution exposed.

For new C identities, formal entry points, manifest builds, hidden judging and
boundary candidate execution are therefore blocked. Boundary option matrices
are defined for all four selectors, with sort rejecting future options using
status 2. Static plans remain available. Security evaluation is disabled for
these selectors; no unsupported evaluator is implicitly activated. New plan
fingerprints include the contract and Docker infrastructure hashes. Historical
selector behavior and fingerprints do not acquire these fields.

**A working host-controller/per-candidate Docker adapter is not delivered or
validated yet.** The new suite engines admit only the independently installed
GNU oracle, and refuse generated executables. The oracle-validation container
holds controller-only assets; it must never be repurposed to execute candidates.
A candidate sharing that filesystem/UID could read hidden tests. Docker alone
also does not guarantee protection from kernel attacks, resource exhaustion,
side channels or malicious generated code. Before enabling formal experiments,
implement and validate separate candidate containers containing only each case's
fixture, executable and necessary runtime, without controller assets, future
tests, oracle access or a Docker socket. Keep compilation, public tests, hidden
tests and boundary probes on that path, with hidden feedback kept separate.

Also pending: actual ARM64 build compatibility; Linux symbolic-mode verification;
reference self-pass, deterministic freezing and mutation checks; generated
corpus publication into this versioned namespace after review; direct tests of
all restricted-subset rejection surfaces (notably sort's forbidden operands);
full recursive permission coverage; independent comparator review; and
end-to-end controller integration. Do not remove guards merely to run tests.
Do not start formal lineages based on the current static report.

## Current verification

Six host-safe static tests passed: planner/filtering, input isolation, mv order
and historical Rust identities, boundary refusal, host execution refusal, and
Python syntax. Fifteen checkpoint bundles were inspected, without executing
programs. The final isolation checker searched 552/402/57/104 held-out values
for cp/mv/mkdir/sort after adding the Linux ENOSPC dual. No frozen-result
isolation claim is made.

See [the static counts](linux-utilities-v1-static-report.json) and
[the delivery report](linux-utilities-v1-report.md). All oracle executions,
functional passes/failures and observed container versions are unverified;
zero executed tests is not a passing result.
