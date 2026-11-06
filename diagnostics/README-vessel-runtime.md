# Temporary Vessel address-space investigation

This is a trusted-probe diagnostic, not a benchmark change or formal validation.
It runs no Aider, lineage, public corpus, or held-out corpus. It leaves the
repository worker, limits, benchmarks, and provenance rules unchanged. Output
must be a new directory outside the repository and outside agent-visible work.

## Findings before running this harness

The operator reports a trusted C isolation failure at standard 256 MiB and a
pass with unlimited address space. This removes candidate correctness as a
necessary explanation. Finite-limit failures at 512 MiB, 1 GiB, and 4 GiB remain
**attempted-limit observations** until the actual worker payload or jailed
readback establishes those values. The earlier substitution snippets and raw
payloads were not available for this audit, so their effectiveness is unverified.

`docker_benchmark.command()` reads the worker file each time and embeds its
contents as the penultimate command argument, following `python3 -I -c`.
Changing an imported host worker function does not change that source. A patch
must reach each `case` invocation, not just compilation or the trusted judge.
Changing only `else 256 * 1024**2` is ineffective when the Docker environment
still selects `BENCHMARK_DIAGNOSTIC_ROSETTA=1`. A literal replacement can also
silently match nothing. Changing `execution_profile()` changes host metadata,
not the limit implementation in the child.

The jail drops UID/GID, then calls `set_jail_limits()`, then calls any engine
preexec callback. The current cp engine supplies no other setrlimit/preexec
implementation. The existing isolation control expects exactly 256 MiB or
infinity and, in standard mode, rejects a successful 512 MiB allocation. It is
not a valid unchanged acceptance test for arbitrary higher finite limits.

The harness replaces the **entire conditional assignment**, demands exactly one
match, verifies the actual command payload against the original worker, and
saves the exact source sent for every call. It runs each sweep point both with
and without instrumentation. Only the case worker is substituted. Compilation
uses the repository transport and compiler flags unchanged. The existing
isolation test runs verbatim using original worker source in standard and
unlimited diagnostic modes; it is not adapted or weakened for the sweep.

## Run on Vessel (Docker Desktop, not Colima)

Transfer this directory alongside the reviewed repository. Substitute your
existing absolute pinned lock path. No image is built or intentionally pulled
by the harness; it inspects both required pinned images locally before execution
and stops if either is absent. Docker's existing worker command and pull policy
are unchanged; do not remove images during collection.

```bash
cd ~/agentic_cyber
export PYTHONDONTWRITEBYTECODE=1
LOCK="/absolute/path/to/existing/vessel/lock.json"
EVIDENCE="$(mktemp -d "$HOME/vessel-runtime.XXXXXX")"
chmod 700 "$EVIDENCE"
python3 -B diagnostics/vessel_runtime_probe.py --repo "$PWD" --self-test
python3 -B diagnostics/vessel_runtime_probe.py \
  --repo "$PWD" --lock "$LOCK" --output "$EVIDENCE/run" \
  --limits-mib 256,512,1024,4096,16384,65536,unlimited \
  >"$EVIDENCE/console.log" 2>&1
printf 'Harness exit: %s; evidence: %s\n' "$?" "$EVIDENCE"
```

The larger limits are diagnostic virtual-address-space probes, not proposed
formal limits or RAM allocations. The Docker 768 MiB memory cap stays unchanged.
All Docker arguments, capabilities, network restrictions, chroot, UID/GID drop,
descriptor closure, timeouts, CPU/file/process limits and output bounding stay
as implemented in the repository. Instrumentation reads proc metadata only
before chroot in the trusted child; it does not mount proc or add descriptors
inside the jail. The emulation identity probe uses the existing preflight
read-only metadata mounts with the selected pinned compiler image.

The harness exits successfully when collection completes even when probes fail.
Read `results.json`, the two `isolation-*.log` files, and the numbered artifacts.
Each `results.json` sweep entry names its numbered `call`. The `.exit` file is
the Docker worker exit, **not** the candidate exit. The candidate exit/signal is
in `results.json` and `.stdout`. `.child-stderr` decodes the jailed process's
captured stderr. Worker failures and preexec exception captures are in `.stderr`.
Timeouts preserve partial supervisor output, but may lack child markers because
the supervisor has not yet returned its temporary capture. Missing files are
not proof that execution reached any particular phase.

## Interpret the phase markers conservatively

| Last evidence | What it establishes |
|---|---|
| `jailed-uid-dropped` | chroot and UID/GID drop completed; limit setup is next |
| `before-setrlimit-as` | the AS setter is about to be called |
| `setrlimit-as-returned` | Python's setrlimit call returned successfully |
| `observed-as=(soft, hard)` | getrlimit in the jailed child read back the actual limits |
| `preexec-complete` | all jail limits and any original preexec callback completed |
| `constructor-entered` | the dynamic loader reached a trusted executable constructor |
| `main-entered` | execution reached main |
| `executable-as=soft,hard` | the loaded trusted C executable confirmed inherited limits |

The constructor probe adds an early executable-code marker to the main probe.
Both are compiled by the existing pinned C compiler. A missing constructor/main
marker after `preexec-complete` narrows the failure to the interval spanning
Python subprocess's remaining exec work, exec/loading, emulator startup and
early runtime initialization. It **does not distinguish these completely**.
A missing post-setter marker similarly cannot distinguish trapping inside
setrlimit from trapping immediately afterward while writing the marker.
Python exceptions may instead report allocation failure or preexec failure.
Instrumentation itself consumes address space; compare each instrumented run
with its uninstrumented pair before interpreting a threshold.

`metadata.json` records binfmt registrations and interpreter hashes through the
existing preflight probe, Docker version/info/context, lock, revision/status,
and worker/binary hashes. Instrumented child stderr also records pre-jail proc
status, executable link, and maps. Look for the enabled AMD64 registration's
interpreter (`rosetta` versus `qemu-x86_64`) and corroborating runtime mappings.
Registrations show configured handlers, not necessarily the handler selected
for every execution. If mappings do not resolve the ambiguity, report the
active mechanism as unconfirmed and record Docker Desktop's VMM and Rosetta
settings manually. `uname -m=x86_64` alone is not identification. A failed or
unreadable metadata probe is retained as `emulation_error`; do not infer Rosetta
from the diagnostic profile's name.

## Smallest next action

Run this once on the unchanged Vessel environment. If a requested finite value
is not observed, correct the substitution experiment before diagnosing the
emulator. If it is observed and failure is before executable code, retain the
evidence as an infrastructure failure; do not repair cp or promote unlimited
results to formal evidence. A constructor/main marker moves investigation into
the executed runtime instead. Only then choose a narrowly targeted follow-up
(for example, repeat the same trusted probes with Docker Desktop's alternate
AMD64 emulator, explicitly recording the environment change). No permanent cap
or provenance change is justified by the currently available measurements.

## Windows checks

`py -3 -B diagnostics/vessel_runtime_probe.py --repo . --self-test` verifies 12
combinations of cap, instrumentation and inherited diagnostic environment using
a stub resource API. It verifies exact soft/hard arguments and all other rlimits,
parses substituted sources, and rejects a missing substitution target. It does
not validate Linux kernel behavior, Docker transport, or Vessel runtime.
