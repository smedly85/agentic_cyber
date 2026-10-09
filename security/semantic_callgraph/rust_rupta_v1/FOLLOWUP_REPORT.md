# Drop, reporting, edition-2024 compatibility, and one provisional pilot

This follow-up is separate from the canonical baseline recorded in README.md,
VALIDATION_REPORT.md and validation_results.json. Those artifacts are unchanged.
No historical result has been accepted, and no bulk CVE run was performed.

## Outcome

| Instrument | Compiler | ander | default cs | Exact designated target sets per mode | Deterministic repeats |
|---|---|---:|---:|---:|---:|
| Original canonical RUPTA | nightly-2024-02-03 | 33/35 | 33/35 | 23/23 | baseline evidence |
| Canonical source plus separate Drop/reporting patch, revision 2 | nightly-2024-02-03 | 35/35 | 35/35 | 23/23 | 38/38 entry runs per mode |
| Existing rust-2026 fork plus separate Drop/reporting overlay | nightly-2026-08-21 | 35/35 | 35/35 | 23/23 | 38/38 entry runs per mode |

Each patched instrument completed 152 analyses: 38 configured entry runs, two
modes, two repeats. The supplement has four entries, accounting for the difference
between 35 programs and 38 runs. Both normalized output and the authoritative
context-preserving finalized graph were compared byte-for-byte. Existing fixture
sources and requirements were reused without edits. No depth-2 sensitivity run
or new Rust fixture corpus was needed. Default cs uses the existing default
context depth (one callsite); no context-depth override was supplied.

The preserved per-entry results, exact expected/observed target sets, commands,
runtime, RSS and graph depths are in `patched_validation_results.json` (2024)
and `followup_results.json` (modern fork). Raw evidence remains under
`build/rupta-v1/drop-trial/validation-v2/` and
`build/rupta-v1/drop-trial/compatibility/modern-validation/`.

## The two failures

**expanded/crates_io:** the function-PAG builder ignored MIR Drop, so this was
an analysis omission, not just DOT serialization. The patch asks rustc for the
drop-glue instance, supplies the address of the dropped place through existing
PAG/call propagation, and analyzes the compiler-generated glue body. Dynamic
trait-object destruction reuses existing receiver propagation to select concrete
drop glue. It does not hardcode scopeguard or inject expected graph edges.

The previously missing route is now observed:

`main → dependency_path → core::mem::drop<ScopeGuard> → drop glue<ScopeGuard> → ScopeGuard::drop → dependency_path::{closure#0} → target`

The target is reachable at depth 6 in this controlled fixture. Boxed trait-object
destruction also selects the concrete pointee's glue. An earlier trial incorrectly
formed a static self-loop for dynamic Drop; it was rejected, corrected, and the
full corpus rerun twice. Its artifacts remain in `drop-trial/validation/` and
`initial-static-drop.patch`; only `validation-v2/` is accepted controlled evidence.
No general new pointer-analysis subsystem was introduced.

**supplement:** internal boundary/callsite information was absent from the DOT
representation used by the adapter. The sidecar now records
`entry_external_body → external_work` as an unavailable-body boundary, and
`entry_unresolved_indirect → call_unknown → external_callback` with the recognized
zero-target function-pointer callsite in `call_unknown` explicitly unresolved.
No callback target was fabricated. The inherited checks pass with these explicit
records.

## Minimal structured reporting and depth policy

`depth_export.rs`, `patched_adapter.py`, and the two saved source patches implement
the sidecar. Each DOT output has an accompanying `.depth.json`; cs also has
`.contexts.json`. The sidecar exports existing internal function IDs, DefId,
DefPathHash, generic arguments, promoted-body identity, source spans, body
availability, special-model marker, entry, reachable nodes, MIR callsite locations,
call kinds and caller/callee relationships. The modern fork's existing shim
identity is additionally preserved. Recognized indirect sites with no targets
are emitted explicitly.

Normalized function keys use DefPathHash, full printed generic arguments and
promoted identity, plus shim identity where the fork supplies it. These are
analysis/compiler-specific identities, not promises of stability across compiler
versions. Upstream type/region normalization remains in effect. Context-sensitive
nodes keep their call strings; raw allocation-order IDs in those strings are
replaced with function keys. Collisions trigger failure. Depth uses this graph,
not a source-name union. A separately labelled function-union view exists only
to run the inherited source-function validation requirements. Its external-call
schema excludes boundary edges from internal edges; the authoritative depth graph
retains those boundary edges and nodes.

The existing BFS finalizer is reused: vulnerability depth is shortest directed
distance; Dmax is maximum finite shortest distance. Compiler-generated glue,
shims, instantiated library functions, and unavailable-body endpoints count as
nodes. Consequently neither identical BFS code nor the common Andersen label
establishes numerical comparability with the C/SVF or prior Rust measurements.

Unresolved reporting is complete only for internally recognized indirect sites
with zero targets. It cannot certify that every semantic call was recognized,
or that a nonempty target set has no missing alternatives. Special models and
unavailable-body markers are distinct; body availability does not itself prove
that all body semantics were analyzed. Original DOT export remains lossy.

## Compatibility and provenance

Canonical commit: `b19f187e9cbe37b5afb1103d88b663253e1f0a03`, pinned to
nightly-2024-02-03. Separate correction: `drop_trial.patch` SHA256
`ae50983b5fc951565f03964f7f05d1003d69a6a4f32821716091a7639ac78c01`.

A bounded check of upstream and its exposed fork branches found an existing
[rust-2026 compiler port](https://github.com/wenyaoc/rupta-fork/commit/66e29895748bd7a289b448a875d198711f1382dd):
`wenyaoc/rupta-fork`, commit `66e29895748bd7a289b448a875d198711f1382dd`.
It pins nightly-2026-08-21, rustc
`1.100.0-nightly (8925ea358a0f265ca61026aadc7ecc506c545cbe)`, LLVM 23.1.0.
This is an existing substantial compiler port with other upstream changes, not
a claim that canonical RUPTA runs unchanged on edition 2024. We independently
validated the selected fork plus the small Drop/reporting overlay. No large
rustc-private port was undertaken in this experiment.

`modern_overlay.patch` SHA256:
`df269e35f6170aa87ea5b1e9ebeaeeeb2cbd37279db9e1ef06f0acda46b0532d`.
Modern PTA binary SHA256:
`5d68d7384636ae01a4540a6a366255db3a920a430a74113030c485074e94caec`.
Full binary/compiler/lockfile hashes and commands are in `followup_results.json`
and `build/rupta-v1/drop-trial/compatibility/modern-provenance.json`.
Both builds use isolated directories under build, explicit pinned toolchains,
rustc-dev/rust-src/LLVM tools, and locked analyzer dependencies. No system compiler
or global default toolchain was changed.

The frozen uutils 0.2.2 chmod specimen built and analyzed on Linux x86_64 under WSL
using the modern fork. Edition 2024, lockfile format 4, pinned dependencies,
build scripts, procedural macros and its multi-crate dependency build succeeded.
Source and lockfile were unchanged. This establishes compatibility for this
specimen, not all historical versions, utilities or operating systems. The
candidate compiler and its standard library differ from the frozen historical
measurement compiler; candidate provenance remains separate.

## Reproduction and preservation

Run modules from the repository root in Linux/WSL. Existing output directories
are deliberately not overwritten by validation/build-pilot setup. For a fresh
reproduction use a fresh experiment workspace with the baseline prerequisites
documented in README.md; do not delete existing evidence.

```text
python3 -m security.semantic_callgraph.rust_rupta_v1.patched_trial setup
python3 -m security.semantic_callgraph.rust_rupta_v1.patched_trial patch
python3 -m security.semantic_callgraph.rust_rupta_v1.patched_trial reporting
python3 -m security.semantic_callgraph.rust_rupta_v1.patched_trial dynamic-drop
python3 -m security.semantic_callgraph.rust_rupta_v1.patched_trial build
python3 -m security.semantic_callgraph.rust_rupta_v1.patched_trial validate
python3 -m security.semantic_callgraph.rust_rupta_v1.patched_trial preservation
python3 -m security.semantic_callgraph.rust_rupta_v1.patched_trial summarize
```

For the modern branch, clone `https://github.com/wenyaoc/rupta-fork` branch
`rust-2026` into `build/rupta-v1/drop-trial/compatibility/modern-fork` and check out
the exact commit above; do not rely on a moving branch tip. Then:

```text
python3 -m security.semantic_callgraph.rust_rupta_v1.modern_trial install
python3 -m security.semantic_callgraph.rust_rupta_v1.modern_trial prepare
python3 -m security.semantic_callgraph.rust_rupta_v1.modern_trial build
python3 -m security.semantic_callgraph.rust_rupta_v1.modern_trial provenance
python3 -m security.semantic_callgraph.rust_rupta_v1.modern_trial validate
python3 -m security.semantic_callgraph.rust_rupta_v1.historical_build_trial
python3 -m security.semantic_callgraph.rust_rupta_v1.historical_pilot
python3 -m security.semantic_callgraph.rust_rupta_v1.followup_summary
```

The pilot enforces saved controlled-validation and historical-build gates.
All concrete compiler/analyzer arguments and environment overrides are saved in
per-run command JSON, including resource limits and completion status. The pilot
report describes its deliberately narrow Cargo wrapper.

Regression checks: 11 tests passed across the existing RUPTA adapter, the small
new sidecar test, calibration revision-freeze tests, and MIR dependency-input
tests. Hash preservation checked 39,457 preexisting research/test files with no
changed or missing files. Git diff whitespace check passed. Original C, MIR,
LLVM/SVF, calibration and historical results remain untouched. Nothing was
committed or pushed.

## Decision

Drop traversal and structured reporting work for all existing controlled
requirements in both modes. Edition-2024 compatibility is demonstrated for the
one frozen specimen using the separately identified modern fork. See
[HISTORICAL_PILOT_REPORT.md](HISTORICAL_PILOT_REPORT.md) for its provisional result.

The bulk historical study is **not yet approved**. The single primary blocker is
pilot graph-coverage acceptance: 35 recognized unresolved sites and 92 unavailable
bodies remain, and the unresolved inventory is not globally complete. The smallest
next step is a bounded review of the saved pilot mapping and those call/boundary
records to decide whether they invalidate the intended depth scope. Do not
automatically launch a new analysis subsystem or the 45-CVE study.
