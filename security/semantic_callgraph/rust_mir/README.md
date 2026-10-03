# Controlled MIR backend — MIR-STOP-INCOMPLETE

The current core milestone is in [CORE_REPORT.md](CORE_REPORT.md): allocation-site
Box propagation, receiver-refined dyn dispatch, closures/RustCall, local unsafe
collapse, typed static decoding, and a successful isolated build-std experiment.
Thirty focused core checks and twelve memory checks pass. All 31 original cases
pass explicit node/edge/target assertions, but required-body/operation gates and
independent traces still prevent complete semantic acceptance. Calibration and
historical Rust measurements remain unexecuted.

The prior controlled continuation is documented in [CONTINUATION.md](CONTINUATION.md).
It adds stage negative controls, typed aggregates, explicit missing-body handling,
root-scoped inclusion, two fresh 31-case extractions, 12 memory adversaries, and
a four-crate Cargo compilation wrapper. Nine memory target checks pass; heap,
dyn, unsafe, complete std/closure semantics, traces, and calibration remain open.
No full semantic acceptance or historical authorization follows from these checks.
The record below describes the **archived initial spike**, not the current code.

This is a **partial feasibility implementation**, not an accepted Rust semantic
backend and not evidence that MIR is unsuitable. The exact compiler API works,
and a typed-place inclusion prototype separates the two stack callback fields.
Required dyn/heap/unsafe/whole-program semantics remain unimplemented. Full
semantic validation, dynamic traces and cross-language calibration have not
been completed. No historical Rust specimen was checked out, built or measured.

## C instrument restoration

The canonical helper source was restored from commit `541a8df9`, and the local
Rust byte-GEP patch was removed from the canonical SVF build. Rebuilding at its
original location reproduced the original binary **byte for byte**:

| Role | Location | SHA-256 |
| --- | --- | --- |
| Frozen C helper | `build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf` | `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2` |
| Rejected experimental Rust/SVF helper | `build/semantic-toolchain/rust-svf-experimental/Release-build/bin/semantic-callgraph-svf` | `d081531faa7a82254bf209c347249b94d422ad37f51e850a3b59cca76c2d87e1` |

The entire experimental SVF source/build was copied before restoration, including
its libraries. Its CMake cache still contains original absolute paths: it is an
archival snapshot, **not** permission to rebuild it in place. Reconfiguration
would need a new isolated build. `$ORIGIN/../lib` resolves the archived helper's
copied libraries. The experimental repository helper and Python backend source
are also preserved under `retired_svf/`, authenticated against audit-v2 hashes.

The first restored-C replay found a second hygiene defect: the Rust-added
inventory guard rejected five system-header definitions (`__bswap_32` and its
instances, `__bswap_64`, `__uint64_identity`) deliberately excluded by the frozen
C helper. The original C `analyze_build` execution path was restored; the guard
utility remains available for old controlled audit tests, but is not injected
into C analysis. The complete experimental version is archived. The failed
restoration replay is retained in `build/rust-mir/c-restoration/initial-*`.

After restoration: **C controlled 11/11; nine historical observations 9/9**,
with unchanged depth/path/edge kinds/target sets/reachability. All **159**
protected C artifacts are unchanged. No C expected results were edited.
`c_restoration.json` and `c_regression.json` record the checks. C instrumentation
was not changed during the subsequent MIR probe.

## Retired SVF conclusion

LLVM/SVF is not accepted as the Rust scientific backend because common Rust
LLVM lowering produces systematically different and silently unreliable
field/heap precision **under the tested lowering and measurement precision
requirements**. This is not a claim that SVF is generally unsound.

The Rust SVF audit-v2/v3 results, wrong-target cases, Box diagnostics, raw WPA
comparisons and fingerprints remain intact. Their original commands refer to
the former experimental canonical path: do not rerun those commands against
the now-restored C helper. A future replay must explicitly select the archived
experimental helper and libraries and use fresh output directories, without
rewriting the old provenance.

## Exact compiler feasibility

`prepare.py` installs official checksum-verified rustc, rust-std, Cargo,
rustc-dev and rust-src **1.93.0** into `build/rust-mir/toolchain`. It does not
modify the prior toolchain, system compiler, or historical source. Compiler:

```text
rustc 1.93.0 (254b59607 2026-01-19)
revision 254b59607d4417e9dffbc307138ae5c86280fe4c
LLVM 21.1.8
x86_64-unknown-linux-gnu
```

The driver uses `#![feature(rustc_private)]` and **RUSTC_BOOTSTRAP=1** explicitly;
no silent nightly/version substitution. Components expose rustc_driver,
rustc_interface, rustc_middle, rustc_hir, rustc_span, rustc_target and
rustc_data_structures. `-C prefer-dynamic` links the driver to compiler libraries;
the runner sets `LD_LIBRARY_PATH` to the isolated sysroot libraries.

`Callbacks::after_analysis` obtains `TyCtxt`. `collect_and_partition_mono_items`
provides concrete `MonoItem::Fn(Instance)` entries; `tcx.instance_mir(instance.def)`
returns ordinary or generated-shim MIR. Every queried callable type is explicitly
substituted with `instantiate_mir_and_normalize_erasing_regions` under a fully
monomorphized typing environment. `Instance::try_resolve` resolves known calls;
`InstanceKind::Virtual` is retained as **unresolved_dyn**, not mapped to all impls.

## MIR stage and boundaries

The probe uses `-C opt-level=0 -Z mir-opt-level=0 -Z inline-mir=no`,
`-Z always-encode-mir`, one codegen unit, and `panic=unwind` for binary fixtures.
Original library fixtures retain `panic=abort`. The queried phase is
`Runtime(Optimized)` even with MIR optimization level zero. This is post-drop
elaboration; explicit Drop terminators resolve to drop instances and shims are
retained. Source calls `main -> a -> target` survive in the controlled probe.

This does **not** establish a universal pre-optimization stage for upstream
precompiled std MIR. Upstream MIR was encoded with its own build options.
The probe sees `Option::map`, concrete Fn-family instances and drop glue, but
has not calibrated all upstream transformations or a build-std configuration.
Ordinary non-generic external functions may have no exported body in the current
crate's codegen units. A Cargo invocation/dependency closure has not been proven.
The controlled dependency and scopeguard 1.2.0 are compiled with always-encode-mir;
that is not a claim of whole-program or linker-exact scope. rust-src is acquired
for further stage investigation, not used to rebuild std in this pass.

## Identity and partial graph contract

Instance identity uses rustc's **stable hash of the complete Instance**, plus
untrimmed, non-reexported, crate-qualified display information. The stable hash
includes the concrete substitutions and instance kind. Source identity uses
DefPathHash and DefPath, with a separate source span. Session DefId integers are
not serialized as identities. The two `generic::<u8/u16>` instances remain
distinct and share one source identity. Compiler shims retain their instance
identities; no shim is contracted.

`graph.py` exports functions, edges, callsites, target sets, unresolved/external
sites and unsupported-operation records into an incomplete common-shape graph.
It **refuses finalization** for incomplete results. The existing C/common BFS
implementation is imported, not reimplemented. No historical graph or depth
artifact is emitted. MIR display strings are inspection evidence only; they
are never parsed to manufacture scientific edges.

## Inclusion prototype and actual limitations

`inclusion.py` is an inclusion-based, flow-insensitive, context-insensitive
fixed-point prototype over compiler-exported local/Field/Downcast/Deref places.
It propagates reified function items, direct copies, references, per-field stack
copies, direct-call arguments and returns. It never fills an empty set from
compatible types. The two callback fields resolve to separate singleton sets.

This prototype is deliberately incomplete:

- Aggregate variant kind is not fully exported; enum layout is not established.
- Dyn receiver concrete-type flow and vtable target resolution are not implemented.
- Box/allocation-site heap semantics and pointer-producing intrinsics are not modeled.
- Unsafe/raw-pointer/union/byte-copy/unknown-index conservative merging is not implemented.
- Closure values can expose compiler-resolved call instances, but complete
  environment/Fn-family/dyn propagation is not established.
- External bodies and multi-crate scope are not closed.

Unsupported operations are **rejection records**, not a claim that a conservative
merge has been implemented. Partial target sets must not be used scientifically.

## Results and gate

All **31 existing controlled fixtures** successfully pass the compiler/MIR API
extraction probe. **None is claimed as a complete semantic validation pass**.
`controlled_results.json` lists each case and its unsupported reasons. The new
focused fixture yields 29 instances and four unresolved callsites at extraction;
the inclusion subset resolves the two struct callbacks without contamination.
The dyn site remains unresolved.

Two clean focused-probe runs produce byte-identical normalized JSON. This is
**probe determinism**, not the required two full validated-suite reruns.

The 15 C/Rust calibration pairs were pre-registered in `PREREGISTRATION.md`.
They have not been executed. Dynamic trace comparisons have not been executed.
Rust-source unsafe adversarial coverage remains outstanding. Result artifacts
say `not_run`, not zero observations or success. There is no target-set-size
distribution from a cross-language calibration.

**MIR-STOP**: the compiler is feasible, but pointer-analysis/dyn/heap/unsafe,
whole-program/std-boundary, trace and calibration requirements are incomplete.
This milestone must not authorize historical pilots. A further implementation
pass is needed; this result does not reject MIR as a possible future backend.

## Reproduction

```sh
# First restore C and verify its exact binary and regression results.
python3 security/semantic_callgraph/rust_mir/verify_c_restoration.py
python3 security/semantic_callgraph/rust_mir/prepare.py
python3 security/semantic_callgraph/rust_mir/probe.py --label fresh-label
python3 security/semantic_callgraph/rust_mir/controlled_probe.py
python3 security/semantic_callgraph/rust_mir/publish.py
python3 -m pytest -q tests
```

Runners require fresh controlled output directories and do not recursively
delete old evidence. Component acquisition requires network only when uncached;
unit tests use committed records and require no network/toolchain.
