"""Refresh documentation from recorded Docker evidence; never execute a candidate."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/benchmarks'
EVIDENCE=DOC/'validation-amd64'
for name in ('linux-utilities.md','linux-utilities-report.md'):
    backup=EVIDENCE/('pre-docker-'+name)
    if not backup.exists(): shutil.copyfile(DOC/name,backup)
for utility in ('cp','mv','mkdir','sort'):
    path=ROOT/f'experiments/utilities/c-{utility}.json'
    manifest=json.loads(path.read_text())
    manifest['functional_oracle']['status']='verified Linux/AMD64; ARM64 pending'
    path.write_text(json.dumps(manifest,indent=2)+'\n')
    (ROOT/f'tests/c-{utility}-test-suite/README.md').write_text(f'''# Linux utilities: c-{utility}

Linux GNU Coreutils 9.11 frozen expectations are in `suites/linux.json.gz`
and the separate controller-only `heldout/` directory. `suites/MANIFEST.json`
records input, corpus, oracle and environment hashes. `validation.json` records
the oracle job; separate adapter evidence is under `docs/benchmarks/validation-amd64`.
Archived pending inputs and revisions in `gen/` are never staged for agents.
The historical `tests/{utility}-test-suite/` remains unchanged.
All candidate operations require the Docker adapter and controller `HELDOUT_ROOT`.
See `docs/benchmarks/linux-utilities.md` for scope and reproduction commands.
''')

old=(EVIDENCE/'pre-docker-linux-utilities.md').read_text()
middle=old[old.index('The new selectors'):old.index('## Public and held-out data')]
middle=middle.replace('All four configurations are statically resolvable; all functional\nvalidation remains pending. The manifest build command deliberately refuses\ncandidate compilation until the isolation adapter is validated.',
'''All four configurations and 15 checkpoints resolve. The manifest build commands
use the Docker adapter. Linux/AMD64 oracle and adapter calibration passed; ARM64
remains unverified.''')
middle=middle.replace('These are differences documented by the historical repository, not newly\nmeasured results from this task:',
'''The historical column comes from repository documentation. Linux symbolic modes
and `/dev/full` were independently verified in Docker in this task. The excluded
POSIX compatibility behavior is recorded for context, not claimed as newly tested:''')
middle=middle.replace('The new symbolic-mode contract is Linux-specific and must still be verified.',
                         'The Linux-specific symbolic-mode contract passed direct oracle checks.')
middle=middle.replace('independent held-out input are prepared without any invented expected outcome.',
                         'independent held-out input now have independently frozen Linux expectations.')
tail='''## Frozen corpora and independent evaluation

Public `suites/linux.json.gz` and controller-only `heldout/heldout_cases.json.gz`
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
`docker/linux-utilities/lock-amd64.json` pins the observed image IDs.
Rebuilds have pinned inputs; bit-identical image rebuilds are not claimed.
Archive the actual image with `docker save` before official runs.

From PowerShell, enter WSL with `wsl.exe --cd "$PWD"`; then run these Bash commands
in the repository (choose new output directory names for repeated oracle runs):

```bash
docker info
BASE=python:3.12.8-bookworm@sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad
bash docker/linux-utilities/build.sh "$BASE" linux/amd64
IMAGE=$(docker image inspect agentic-linux-utilities --format '{{.Id}}')
bash docker/linux-utilities/run.sh "$IMAGE" "$PWD/linux-v1-validation-new" linux/amd64
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
bash docker/linux-utilities/build.sh "$BASE" linux/arm64
IMAGE=$(docker image inspect agentic-linux-utilities --format '{{.Id}}')
bash docker/linux-utilities/run.sh "$IMAGE" "$PWD/linux-arm64-validation-new" linux/arm64
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
in the [delivery report](linux-utilities-report.md). ARM64/vessel is pending.
No formal lineage, research outcome, structural diversity result or candidate
correctness claim is produced. Corpora are restricted finite coverage, not a
proof of GNU equivalence. Exhaustive recursive permission combinations and
independent comparator/security review remain useful before official experiments.
Historical test source modules for the controller were absent in this checkout;
available new static/integration tests cover the changed C paths, but a complete
historical controller regression suite could not be run.
'''
(DOC/'linux-utilities.md').write_text('# Standardized C utility benchmark: Linux utilities\n\nLinux/AMD64 Docker validation completed on 2026-11-01; ARM64 remains pending.\n\n'+middle+tail)

rows=[]
for utility in ('cp','mv','mkdir','sort'):
    val=json.loads((ROOT/f'tests/c-{utility}-test-suite/validation.json').read_text())
    for row in val['checkpoints']:
        p,h=row['public'].get('PASS',0),row['heldout'].get('PASS',0)
        rows.append(f"| c-{utility} | {row['checkpoint']} | {p} | {h} | {p+h} | 0 | 2/2 |")
report='''# Linux utilities Docker validation report

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
The [lock](../../docker/linux-utilities/lock-amd64.json), per-suite manifests,
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
'''+ '\n'.join(rows)+'''

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

The [methodology](linux-utilities.md) retains the original mkdir architecture
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
'''
report += '\n## Git status snapshots\n\nInitial:\n\n```text\n' + (EVIDENCE/'initial-status.txt').read_text(encoding='utf-8-sig').rstrip() + '\n```\n\nFinal:\n\n```text\n' + (EVIDENCE/'final-status.txt').read_text(encoding='utf-8-sig').rstrip() + '\n```\n'
(DOC/'linux-utilities-report.md').write_text(report)
print('Updated methodology, report, manifest status and four suite readmes')

