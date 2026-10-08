# Cross-language calibration preflight

**CALIBRATION-STOP-REVIEW — the frozen paired-source inputs were not located.**

The user requested the previously frozen 15 C/Rust pairs unchanged. The repository's
`rust_mir/PREREGISTRATION.md` registers all 15 categories and qualitative relationships,
but supplies no paired source files, source hashes or complete source-to-entry/target
manifest. `rust_mir/calibration_results.json` contains 15 `not_run` placeholders.
The publisher that created that record enumerates category names only.

The existing `security/calibration/semantic_callgraph/fixtures.json` is the **11-case
C controlled suite**, not a 15-pair cross-language manifest. Separate Rust controlled,
focused, memory and adapter fixtures exist. Selecting or writing counterpart programs
now would constitute a new fixture registration, not execution of frozen paired sources.
No substitutes were chosen, and no backend was tuned.

The missing fixture location was requested from the user. Calibration must await the
frozen bundle/manifest, or an explicit preregistration amendment specifying new sources
and expectations before any calibration observations. This is an input/provenance block,
not evidence that the semantic instruments are scientifically incomparable.

## Preserved inputs and instrument freeze

`instrument_fingerprints.json` records actual compiler version output, compiler and
driver hashes, backend source hashes, rebuilt standard-library hashes/configuration,
and verified MIR-CORE-GO evidence. It was created before any calibration execution and
must not be overwritten.

- C: Clang/LLVM 21.1.8, SVF 3.4, AndersenWaveDiff, `-stat=false -ff-eq-base`.
- Canonical C helper SHA-256: `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2`.
- Rust: rustc 1.93.0, LLVM 21.1.8; static gate, assertions and dynamic traces 31/31.
- Rust calibration-start SHA-256: `514e397d83f9fd2be32e42b69970861036c7251dd2a2dbf38591a6ad7ec76e20`.

`PREREGISTRATION.snapshot.md` preserves the exact registration bytes.
`preregistered_expectations.json` transcribes its 15 relationships in order, with
unresolved fixture fields explicitly null. Expectations have not been changed.

## Results and their limits

All 15 entries in `pair_results.json` are **not run**. Their scientific pair status is
null: assigning EXACT, STRUCTURALLY_COMPARABLE, KNOWN_BOUNDARY_DIFFERENCE,
PRECISION_ASYMMETRY or FAIL without observations would misrepresent the evidence.
The requested status vocabulary will apply when actual paired fixtures are available.

`target_set_comparison.json`, `depth_comparison.json`, `dynamic_soundness.json`, and
`precision_summary.json` contain explicit nulls for unavailable calibration observations.
No target sets, cardinalities, raw depths, path decompositions, dynamic soundness,
application-graph equivalence or precision-class equivalence are inferred from the
separate controlled suites. No correction factor is derived.

The qsort/sort_by external-versus-compiled boundary is a **registered expectation**,
not a measured finding in this preflight. Cross-language runtime/static inclusion and
byte-identical paired calibration reruns remain unexecuted.

## Fresh frozen-instrument regression

The unmodified existing runners use new `calibration-preflight-v1` output roots.
`frozen_regression.json` records the completed results and hashes: Rust complete static
31/31, semantic assertions 31/31, dynamic 31/31, identical paired controlled outputs;
C controlled 11/11, historical bitcode replay 9/9, 159 protected artifacts unchanged,
canonical helper unchanged. Source/compiler/driver/stdlib hashes are checked against
the calibration-start freeze again after these runs.

These are **preflight regressions**, not post-calibration results. Existing Rust MIR
controlled evidence and finalized C historical results are not overwritten.

Added scripts: `preflight.py` freezes prerequisites; `report_preflight.py` verifies
unchanged instruments and publishes the input-blocked record. No backend changes or
new semantic fixtures/tests were introduced. No historical Rust specimen was built,
no historical Rust CVE path/depth was measured, and frozen population/mappings were
not changed. `final_verdict.json` records the restricted decision and required input.
