# Canonical Rust historical vulnerability-depth analysis

The sole active Rust historical CVE depth method is
[`results/rust-only-lightweight-v1/`](results/rust-only-lightweight-v1/HISTORICAL_RUST_RESULTS.md).
Use its [function table](results/rust-only-lightweight-v1/tracker_ready.csv) and
[program maxima](results/rust-only-lightweight-v1/program_max_depths.csv).

Method fingerprint:
`456d46f1d50601b3928de37b8445a734dd345b1772131087b077bb503d8b394c`.

The compiler-resolved MIR retained-call graph uses no inclusion/points-to solver.
The active path is: Rust source / historical specimen → rustc → MIR → compiler-resolved call targets → retained MIR call graph → BFS from `uumain` → vulnerability depth and retained-graph maximum depth.
Unresolved indirect calls remain explicit; targets are not invented. Vulnerability
depth is the shortest BFS distance from the frozen utility entry to a legitimate
Instance of the mapped source function. Program maximum depth is the maximum
finite shortest BFS distance among reachable Instances, not a longest path.
All measured observations are labeled `measured_partial_graph`. These are Rust-only
retained-graph measurements, without complete whole-program may-call coverage or
direct numerical C/Rust comparability claims.

The canonical results contain 48 measured executable/function observations,
representing 46 frozen source-function records across 41 of 45 CVEs, and 28
executable maximum-depth graphs. Build failures, platform exclusions, unresolved
mappings and the not-applicable CVE remain explicit. Missing depth is not zero.

The previous historical inclusion-solver approach was abandoned. Its historical
runners, timeout diagnostics and unsuccessful performance/compact solver candidates
are not part of the active pipeline. The original MIR instrument and earlier
controlled/calibration evidence remain only where required by extraction,
reproducibility and frozen calibration provenance. Do not run those inclusion
solvers to reproduce the canonical historical depths.

## Verify or repeat the canonical method

Run in the recorded Linux/WSL environment from the repository root. Use a fresh
output directory for each repeat; the tools refuse to overwrite existing evidence.

```sh
python3 security/historical/rust/validate.py
python3 security/semantic_callgraph/rust_mir_lightweight/integrity.py --output build/rust-depth-check/integrity.json
python3 security/semantic_callgraph/rust_mir_lightweight/validate.py --output build/rust-depth-check/fixtures
python3 security/semantic_callgraph/rust_mir_lightweight/replay.py --output build/rust-depth-check/historical
python3 security/semantic_callgraph/rust_mir_lightweight/verify_results.py --output build/rust-depth-check/results.json
```

The fixture validator repeats all 103 frozen inputs in two clean graph runs and
requires equality to canonical validation evidence. Historical replay independently
rebuilds all 28 retained-call graphs from immutable raw MIR, runs the live runtime
gate before every graph invocation, and requires byte equality to canonical graphs.
It does not recompile sources, invoke a points-to solver or overwrite results.
`verify_results.py` independently checks BFS depths, selected target Instances,
statistics inputs, graph replicas and all 45 CVEs.

## Retained dependencies and frozen documentation

`build/historical-rust-measurement/method-v1/` remains a provenance/input location:
its raw MIR, source checkouts, Cargo/compiler records and observation plan are bound
by the canonical method fingerprint. Its directory name does not designate an
active measurement method. The extractor in `security/semantic_callgraph/rust_mir/`,
the frozen compiler/runtime libraries, rebuilt standard library, controlled fixtures,
cross-language calibration evidence and shared BFS utilities remain intact.

[README.md](README.md) is the byte-frozen population/mapping preregistration, including
its original premeasurement wording. This document is the current depth-method
guide. The population, mappings, evidence dossiers and freeze/validation scripts
remain unchanged. Historical statements in immutable provenance describe the time
of publication; they are not instructions to rerun removed experiments.

The cleanup audit, exhaustive deletion manifest, dependency check, preservation
hashes and fresh validation evidence are under `build/rust-depth-cleanup/`.
