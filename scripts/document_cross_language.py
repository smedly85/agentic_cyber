"""Write the consolidated report from completed, recorded validation evidence."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/benchmarks'; E=DOC/'cross-language-validation'
data=json.loads((DOC/'linux-utilities-static-report.json').read_text())
for folder,key in [('checks-release','static'),('runtime-final','integration'),('c-runtime-001','c-integration')]:
    assert json.loads((E/folder/'summary.json').read_text())[key]==0
assert all(v==0 for v in json.loads((E/'c-static-final/summary.json').read_text()).values())
calibration=json.loads((E/'calibration-001/summary.json').read_text())
assert len(calibration)==12
assert all(v['status']==0 for entry in calibration.values() for v in entry.values())
assert sum(v['counts']['PASS'] for entry in calibration.values() for v in entry.values())==1593
for name in ('c','rust','python'):
    entry=json.loads((E/f'{name}-entrypoints/summary.json').read_text())
    assert (entry['build'],entry['public'],entry['heldout'])==(0,1,1)

matrix=[]; rows=[]
labels={'c':'C','rust':'Rust','py':'Python'}
for selector,entry in data['utilities'].items():
    stages=entry['checkpoints']
    sequence=' → '.join(s['id']+' '+(s['flags'][-1] if s['flags'] else 'Base') for s in stages)
    public='/'.join(str(s['public_executions']) for s in stages)
    hidden='/'.join(str(s['heldout_executions']) for s in stages)
    execution={'c':'Docker GCC + jailed ELF','rust':'Docker rustc + jailed ELF','py':'Docker syntax check + jailed Python'}[entry['language']]
    matrix.append(f"| {labels[entry['language']]} | {selector.split('-',1)[1]} | {sequence} | `{entry['manifest']}` | `prompts/linux-utilities/{selector}/` | `{entry['suite']}` | {public} | {hidden} | {execution}; AMD64 passed |")
    for s in stages:
        rows.append(f"| {selector} | {s['id']} | {s['public_definitions']} | {s['heldout_definitions']} | {s['public_executions']} | {s['heldout_executions']} | passed |")

method='''# Standardized Linux utilities benchmark

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
'''+ '\n'.join(matrix)+'''

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
docker build --platform linux/amd64 -f docker/linux-utilities/Rust.Dockerfile \\
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
docker build --platform linux/arm64 -f docker/linux-utilities/Rust.Dockerfile \\
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
'''
# Retain the original architecture audit in the active methodology without altering
# the archived historical report or corpora.
old=(E/'before-rename/linux-utilities-v1.md').read_text()
audit=old[old.index('## Audit of original mkdir architecture'):old.index('## Platform differences')]
method+='\n'+audit.replace('linux-utilities-v1-input-provenance.json','linux-utilities-input-provenance.json')
(DOC/'linux-utilities.md').write_text(method)

report='''# Linux utilities cross-language delivery report

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
'''+ '\n'.join(rows)+'''

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
'''
for label,name in [('Initial','initial-status.txt'),('Final','final-status.txt')]:
    path=E/name
    if path.exists(): report+='\n## '+label+' Git status\n\n```text\n'+path.read_text(encoding='utf-8-sig').rstrip()+'\n```\n'
(DOC/'linux-utilities-report.md').write_text(report)
print('Wrote consolidated methodology, 12-row benchmark matrix and 45-row results report')
