# Standardized Linux utilities benchmark

Active name: **linux-utilities**. Protocol version **1**, unchanged by the naming
cleanup. C, Rust and Python now have 12 separate configurations and 45 checkpoints.
Linux/AMD64 infrastructure validation passed. Linux/ARM64 and formal Aider/Ollama
generation remain pending. No candidate implementations or lineage seeds are supplied.

The [canonical contract](linux-utilities-contract.md) defines observable behavior
for all languages. Copying, moving, directory creation and stream sorting cover
filesystem and byte-stream operations with incremental options, removing utility
choice as a cross-language confounder. Every checkpoint preserves its predecessors;
000 starts without source, and later stages inherit only their validated predecessor
within the same lineage. Internal algorithms and helper structure remain independent.

## Consolidated matrix

Counts are cumulative executed cases at successive checkpoints (sort includes
stdin delivery variants). Rust/Python suite directories are thin descriptors;
all three languages resolve the corresponding `tests/c-UTILITY-test-suite` as
the **single canonical corpus**, rather than maintaining separate expected answers.

| Language | Utility | Checkpoints | Manifest | Prompts | Suite/descriptor | Public | Held-out | Execution/status |
|---|---|---|---|---|---|---|---|---|---|
| C | cp | 000 Base → 001 -f → 002 -i → 003 -r | `experiments/utilities/c-cp.json` | `prompts/linux-utilities/c-cp/` | `tests/c-cp-test-suite` | 32/37/54/66 | 32/37/54/66 | Docker GCC + jailed ELF; AMD64 passed |
| C | mv | 000 Base → 001 -f → 002 -i | `experiments/utilities/c-mv.json` | `prompts/linux-utilities/c-mv/` | `tests/c-mv-test-suite` | 34/37/52 | 34/37/52 | Docker GCC + jailed ELF; AMD64 passed |
| C | mkdir | 000 Base → 001 -p → 002 -m | `experiments/utilities/c-mkdir.json` | `prompts/linux-utilities/c-mkdir/` | `tests/c-mkdir-test-suite` | 28/51/150 | 6/12/25 | Docker GCC + jailed ELF; AMD64 passed |
| C | sort | 000 Base → 001 -r → 002 -f → 003 -u → 004 -c | `experiments/utilities/c-sort.json` | `prompts/linux-utilities/c-sort/` | `tests/c-sort-test-suite` | 14/20/25/60/83 | 6/10/13/26/37 | Docker GCC + jailed ELF; AMD64 passed |
| Rust | cp | 000 Base → 001 -f → 002 -i → 003 -r | `experiments/utilities/rust-cp.json` | `prompts/linux-utilities/rust-cp/` | `tests/rust-cp-test-suite` | 32/37/54/66 | 32/37/54/66 | Docker rustc + jailed ELF; AMD64 passed |
| Rust | mv | 000 Base → 001 -f → 002 -i | `experiments/utilities/rust-mv.json` | `prompts/linux-utilities/rust-mv/` | `tests/rust-mv-test-suite` | 34/37/52 | 34/37/52 | Docker rustc + jailed ELF; AMD64 passed |
| Rust | mkdir | 000 Base → 001 -p → 002 -m | `experiments/utilities/rust-mkdir.json` | `prompts/linux-utilities/rust-mkdir/` | `tests/rust-mkdir-test-suite` | 28/51/150 | 6/12/25 | Docker rustc + jailed ELF; AMD64 passed |
| Rust | sort | 000 Base → 001 -r → 002 -f → 003 -u → 004 -c | `experiments/utilities/rust-sort.json` | `prompts/linux-utilities/rust-sort/` | `tests/rust-sort-test-suite` | 14/20/25/60/83 | 6/10/13/26/37 | Docker rustc + jailed ELF; AMD64 passed |
| Python | cp | 000 Base → 001 -f → 002 -i → 003 -r | `experiments/utilities/py-cp.json` | `prompts/linux-utilities/py-cp/` | `tests/py-cp-test-suite` | 32/37/54/66 | 32/37/54/66 | Docker syntax check + jailed Python; AMD64 passed |
| Python | mv | 000 Base → 001 -f → 002 -i | `experiments/utilities/py-mv.json` | `prompts/linux-utilities/py-mv/` | `tests/py-mv-test-suite` | 34/37/52 | 34/37/52 | Docker syntax check + jailed Python; AMD64 passed |
| Python | mkdir | 000 Base → 001 -p → 002 -m | `experiments/utilities/py-mkdir.json` | `prompts/linux-utilities/py-mkdir/` | `tests/py-mkdir-test-suite` | 28/51/150 | 6/12/25 | Docker syntax check + jailed Python; AMD64 passed |
| Python | sort | 000 Base → 001 -r → 002 -f → 003 -u → 004 -c | `experiments/utilities/py-sort.json` | `prompts/linux-utilities/py-sort/` | `tests/py-sort-test-suite` | 14/20/25/60/83 | 6/10/13/26/37 | Docker syntax check + jailed Python; AMD64 passed |

Source/executable declarations and each rendered prompt/bundle fingerprint are in
[the resolved matrix](linux-utilities-static-report.json). No declared candidate
source exists. Rust is one safe Rust 2021 file, std-only, compiled with Rust 1.85.1;
Python is a standalone std-only 3.12.8 source with main entry point and shebang.
C remains C11/POSIX. Semantic anchors `copy_path`/`move_path` are retained across
transfer prompts; Python's existing `sort_lines` anchor is retained. No arbitrary
helper count or predetermined algorithm is introduced.

## Relationship to historical experiments

The historical Rust `cp`/`mv`, Python `python-*`, C `mkdir`/`sort`/`grep`/`chmod`,
all Darwin corpora, research results, CVE/diversity/DROID artifacts, and their
documentation remain unchanged. The new selectors are `c-*`, `rust-*`, `py-*`.
In particular, historical Rust mv still introduces interactive before force;
standardized mv introduces force before interactive in every language.

Historical Rust cp/mv support POSIX Linux/Darwin and native rustc preflight.
Historical Python cp/mv use those transfer contracts, Python mkdir is Linux-pinned,
and Python sort is Darwin-pinned. Historical Python sort rejects a bare `--`;
the canonical C/Linux contract allows the terminator alone but still rejects
operands. New Python follows that canonical contract. The standardized sort suite
also includes Linux `/dev/full`; excluded obsolete/POSIX compatibility behavior
is not imported from Darwin. All languages use Linux symbolic mkdir modes,
GNU cp's independent force/interactive flags, mv's last-force-or-interactive rule,
and sort's original-byte tie-break unless unique suppresses it.

The historical Python source validator is reused unchanged **inside Docker**:
nonempty source, in-memory compile without candidate execution or bytecode, and
build failure on syntax errors. Its temporary host-style launcher is discarded;
the new adapter launches the pinned jailed interpreter directly. Thus original
source snapshots remain `.py`, and no host interpreter path enters execution.
Historical Rust safe/std-only constraints and 2021 edition are preserved. Neither
new Rust nor Python activates C AST/SVF or security analysis; those backends are
unsupported/unverified for these standardized selectors, not recorded as passes.

The manifest schema, Aider architect/editor workflow, prompt renderer/shared
automation notice, checkpoint inheritance, immutable bundle staging, public
repair, promotion and separate held-out recording are reused. Narrow selector
branches route build/public/hidden/boundary commands through Docker, bypass native
Rust preflight only for standardized selectors, and disable unsupported analysis.
Docker preflight occurs before starting a real standardized run. Noncanonical
command overrides are rejected. Infrastructure errors return 2 and stop repair;
candidate build/test failures return 1. No native-host fallback exists.

## Oracle, provenance and test isolation

GNU Coreutils **9.11** runs in the pinned Linux oracle image. The Dockerfile checks
the source tarball SHA256 before building, pins Debian snapshot 20250201T000000Z,
GCC 12.2.0 and Python 3.12.8. The original C engines, runners, config readers and
property checks are reused. They compare status, stdout/stderr according to each
case's assertion policy, filesystem paths/types/content, symlink targets and modes.
Tests exercise permissions as UID 1000 with controlled umask, locale C and UTC.
The contract excludes full GNU functionality: no transfer EXDEV fallback or
ownership/ACL/xattr preservation; sort remains stdin-only, byte oriented and
restricted to its listed ordering/check options. Finite coverage is not a proof
of equivalence across all possible inputs.

Public bundles contain only current and preceding cases, pruned runtime/property
code and a language-specific Docker judge wrapper. They contain no generators,
full suite manifests, archived revisions, hidden cases or future-feature inputs.
All 45 bundles were fingerprinted and checked for held-out identifying values.
The sole shared-diagnostic scan exception remains the fixed GNU ENOSPC message;
exact judging assertions are unchanged, and an injected hidden identifier is
detected. Hidden reports stay controller-only and never become repair feedback.

The C oracle rerun generated each corpus twice with byte-identical results and
passed every checkpoint/split plus 30 controlled expected-result mutations.
Public corpus bytes are identical before/after rename. Held-out case dictionaries
and expected outcomes are identical; regenerated provenance changes only the
benchmark label, with its corpus fingerprint correctly recomputed. Published
original corpus bytes/hashes remain preserved. Metadata still containing the old
protocol identifier is intentional, not an active path. Old/new configuration
fingerprints differ because paths and Docker infrastructure are configuration
inputs; never resume an old configuration under the new fingerprint.

The original wrapper interface is retained, but its implementation now calls the
mandatory Docker transport. Legacy `record_linux_*` maintenance entry points
delegate to consolidated recorders; their previous source is archived so they
cannot accidentally overwrite prior C evidence with an obsolete report.

## Execution isolation

The host performs transport and orchestration only. A compiler container receives
source bytes; Rust/C compilation or Python source validation runs non-root inside
Linux. The trusted judge container holds the chosen corpus but never executes
candidates. Each candidate case gets a fresh container receiving only that case's
input fields and executable/source bytes, with no expected results or other cases.

A trusted supervisor prepares fixtures and a chroot, closes descriptors, then
drops groups/UID/GID to 1000. Candidate jails contain only the individual fixture,
program and necessary runtime libraries. Python additionally receives the pinned
interpreter and standard library, excluding site-packages, test packages and cache
files. Its runtime is checked independently before candidate execution, so a
missing runtime is infrastructure failure. There are no oracle binaries, shell,
controller files, procfs, Docker socket or host mounts inside candidate jails.

Containers use no external networking, read-only roots, no-new-privileges, bounded
tmpfs, CPU/memory/PID limits and wall-clock timeouts. Children have CPU, address-space,
file-size and process limits; stdout/stderr capture is bounded. Fixture state resets
per case. The supervisor alone receives limited setup capabilities, never a
privileged container. Candidate startup/runtime overhead is included in its timeout;
the same limits apply across languages. Docker/chroot shares a kernel and is not
a complete defense against kernel exploits, side channels or daemon compromise.
Host-side agents/controllers still require appropriate access control.

## Reproduction on Windows/WSL

Use the existing Docker Desktop engine; no extra daemon or context switch is needed.
From PowerShell enter the repository's WSL directory with `wsl.exe --cd "$PWD"`.
Then run these Bash commands, choosing fresh output names on repeated runs:

```bash
docker info
BASE=python:3.12.8-bookworm@sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad
bash docker/linux-utilities/build.sh "$BASE" linux/amd64
docker build --platform linux/amd64 -f docker/linux-utilities/Rust.Dockerfile \
  -t agentic-linux-utilities-rust docker/linux-utilities
ORACLE=$(docker image inspect agentic-linux-utilities --format '{{.Id}}')
RUST=$(docker image inspect agentic-linux-utilities-rust --format '{{.Id}}')
# Compare IDs with docker/linux-utilities/lock-amd64.json. For new build IDs,
# create a separate lock copying the recorded fields and update only verified IDs.
# export LINUX_BENCHMARK_LOCK=/absolute/path/to/that-lock.json
bash docker/linux-utilities/run.sh "$ORACLE" "$PWD/oracle-check-new" linux/amd64
python3 scripts/validate_linux_static.py --output "$PWD/c-static-new"
python3 scripts/validate_cross_language.py --output "$PWD/cross-checks-new"
python3 scripts/validate_docker_adapter.py --output "$PWD/calibration-new"
for selector in c-cp rust-cp py-cp; do
  python3 scripts/validate_docker_entrypoints.py --utility "$selector" --output "$PWD/entry-$selector-new"
done
```

The checked-in lock points to actual validated immutable images; use archived
images with those IDs or verify and record new build IDs. Inputs are pinned, but
bit-identical image rebuilds are not claimed. Archive images with `docker save`
for official runs. The oracle launcher is trusted-only and mounts staged read-only
inputs plus a fresh output directory. Candidate containers never use these mounts.
No validation command starts Aider/Ollama or a formal lineage.

## Future vessel / ARM64 validation

No files were transferred to vessel and no Docker context was changed. Once IT
restores access to its existing engine, use the same pinned multiarch inputs:

```bash
docker info
BASE=python:3.12.8-bookworm@sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad
bash docker/linux-utilities/build.sh "$BASE" linux/arm64
docker build --platform linux/arm64 -f docker/linux-utilities/Rust.Dockerfile \
  -t agentic-linux-utilities-rust docker/linux-utilities
ORACLE=$(docker image inspect agentic-linux-utilities --format '{{.Id}}')
bash docker/linux-utilities/run.sh "$ORACLE" "$PWD/arm64-oracle-new" linux/arm64
```

Record actual ARM64 image/toolchain IDs in a separate lock with platform
`linux/arm64`, set `LINUX_BENCHMARK_LOCK`, and verify/publish ARM64 corpora in a
separately preserved snapshot using `publish_linux_corpora.py --platform linux/arm64`.
Replace AMD64-specific manifest metadata with observed ARM64 manifest identifiers.
Review cross-architecture differences, then rerun all validation commands above.
The adapter refuses an architecture-mismatched corpus. AMD64 validation establishes
no ARM64 result; do not overwrite AMD64 evidence or reuse its readiness label.
The two static naming-migration audits apply only to the recorded AMD64 rename;
they are explicitly skipped on ARM64, where fresh oracle reproducibility evidence
is required instead. Shared-contract parity, isolation and runtime checks still run.

See [the delivery report](linux-utilities-report.md) for exact evidence, counts,
renames, changes, Git status and remaining readiness limits.

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
[linux-utilities-input-provenance.json](linux-utilities-input-provenance.json).

Transfer cases come from `tests/reference_generators/transfer_cases.py` and
their runtime from the existing transfer suites. No Rust/Python implementation
was read or copied into a candidate. Force-only mv cases have been retagged
for the new force-before-interactive sequence.

