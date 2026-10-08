# MIR extraction for canonical Rust historical depth

The active historical depth method is [rust-only-lightweight-v1](../../historical/rust/results/rust-only-lightweight-v1/HISTORICAL_RUST_RESULTS.md).

Rust source / historical specimen → rustc → MIR → compiler-resolved call targets → retained MIR call graph → BFS from `uumain` → vulnerability depth and retained-graph maximum depth.

`driver.rs` provides compiler-resolved concrete Instances and raw MIR. The unchanged graph builder is `../rust_mir_lightweight/graph.py`; it uses the shared deterministic BFS finalizer. It does not invoke `inclusion.py`. Unresolved indirect calls remain explicit, and measured rows retain `measured_partial_graph`. There is no complete whole-program may-call coverage or direct C/Rust comparability claim.

The controlled case identities are owned by `controlled_results.json`. `controlled_probe.py` reads only its case identities and uses the unchanged source-selection split (first 13 cases: `tests/fixtures/rust_semantic/instrument.rs`; remaining cases: `expanded.rs`). It does not load another backend's results. The historical probe and inclusion-based milestone runners are retained for calibration provenance, not as historical measurement commands; do not run them to reproduce lightweight results.

The controlled scopeguard 1.2.0 archive and source are under `build/rust-mir/dependencies/`. `dependency_inputs.py` verifies archive SHA-256 `94143f37725109f92c262ed2cf5e59bce7498c01bcc1502d7b9afe439a4e9f49` and every extracted source file. The four legacy MIR extraction-validation runners use this MIR-owned dependency. No network acquisition is needed for the authenticated local input.

The frozen rustc 1.93.0 sysroot, compiler driver, MIR settings, rebuilt standard library and library identities remain unchanged. Canonical historical replays use immutable extracted MIR with its recorded per-crate edition and build provenance. No manifests or source editions are rewritten.

Use the fresh-output commands in the [historical method guide](../../historical/rust/SEMANTIC_README.md) for fixture validation, historical graph replay and integrity/BFS verification. Do not rerun old milestone publishers over frozen evidence.

The C LLVM/SVF backend, source, helper binary, restoration evidence and C regression artifacts remain intact. Original MIR/calibration metadata are immutable historical records; a recorded source hash describes that publication, not an active import. Namespace-only changes are documented separately in `namespace_refactor.json`.
