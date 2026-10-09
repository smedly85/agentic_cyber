# Preregistered acceptance criteria — Rust LLVM/SVF backend v1

Written on 2026-10-08, before any validation graph was generated or inspected.
The only analyzer output observed beforehand was the reproduction of the
already-documented `dynamic_dispatch` failure (one exploratory run on the
canonical helper), which is the defect this experiment exists to examine.
Expectations live in `expectations.json` (instrument, expanded and supplement
programs) and in the frozen calibration manifest
`security/semantic_callgraph/cross_language_calibration/fixture_manifest.json`
(15 Rust/C pairs), which is reused unchanged.

## Configurations

| Id | Instrument | Helper options | Role |
|---|---|---|---|
| `P` | canonical C helper `build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf` (SHA-256 `ca8ce8cd…`) | `-stat=false -ff-eq-base` | **primary**; identical to the C study |
| `P-noffeq` | same canonical helper | `-stat=false` | sensitivity: is `-ff-eq-base` implicated? |
| `S` | separately built SVF 67efb774 + `svf-byte-offset.patch` + `svf-rust-vcall-gate.patch` | `-stat=false -ff-eq-base` | sensitivity: smallest general corrections |
| `S-noffeq` | same patched build | `-stat=false` | sensitivity |

Only `P` is the instrument the C study used. A sensitivity configuration
cannot by itself authorize historical Rust measurement, because C would then
be measured by a different instrument. If a sensitivity configuration passes
everything, the next required step is to re-validate the C controlled fixtures
and C historical replays on that same build before any use.

## Criteria (all must hold for configuration `P`)

- **A1 Toolchain identity.** rustc 1.93.0 (LLVM 21.1.8); llvm-link / opt /
  llvm-dis 21.1.8; canonical helper, `libSvfCore.so.3.4`, `libSvfLLVM.so.3.4`
  and `extapi.bc` hashes identical before and after the experiment.
- **A2 Bitcode integrity and identity coverage.** Every program compiles,
  links with `llvm-link`, and passes `opt -passes=verify`. Every LLVM
  definition carrying debug metadata is exported by the helper
  (`backend.validate_definition_inventory`). Definitions without a
  `DISubprogram` are listed explicitly; none of them may be an
  application-source function.
- **A3 Mandatory trait-object dispatch.** `instrument.rs::dynamic_dispatch`
  callsite line 73 resolves to exactly `{<First as Operation>::operation,
  <Second as Operation>::operation}`, and `entry_dynamic_trait -> target` has
  BFS depth 3.
- **A4 Exact adjudicated indirect sites.** Every adjudicated indirect site
  has exactly its expected target set: no missing target and no unexpected
  target. A superset is a failure, not a pass: a false may-target is not a
  conservative harmless extra here, because it can create a shortcut and bias
  vulnerability depth downward.
- **A5 Depths and paths.** `exact` rules: the BFS depth equals the
  preregistered value and the shortest path visits exactly the listed
  application functions. `application_subsequence` rules (chains that pass
  through compiled std/core/alloc, dependency or compiler-shim bodies whose
  exact layering is a compiler detail): the target is reachable, the
  application functions on the reported shortest path are exactly the listed
  sequence, and every other node on it is a library, dependency or shim node.
- **A6 Unreachability.** Functions preregistered as unreachable from an entry
  remain unreachable.
- **A7 Boundaries.** A direct call to a body-unavailable external function is
  reported as an external call and produces no internal edge. An indirect call
  through a pointer whose only origin is a body-unavailable external function
  is reported as unresolved with zero targets (no invented targets).
- **A8 Determinism.** Two runs per configuration, each in a fresh directory
  with a fresh compilation, produce byte-identical normalized helper output
  and finalized graphs.
- **A9 C unchanged.** The 15 C calibration fixtures through the canonical
  helper reproduce the committed C calibration relations and depths; the
  pre-existing regression checks (semantic gate, MIR result verification,
  lightweight integrity, existing pytest files) pass before and after.

Not adjudicated (recorded and counted, never counted as passes): indirect
sites inside std/core/alloc runtime code that no fixture specifies (for
example `lang_start`, `black_box`, drop-glue vtable slots).

## Decision rule

- `P` satisfies A1–A9 → the backend may proceed to the documented historical
  scope/entry requirements; historical work still requires a whole-program
  bitcode capture for the Cargo builds and the entry policy in README.md.
- Any failure of A2–A8 under `P` → **STOP** (task §11). No historical Rust
  depth, no MIR-vs-LLVM/SVF numeric comparison and no historical CSV/JSON are
  produced. Failure evidence and the smallest next engineering step are
  recorded instead.
- Passing a subset of fixtures never establishes semantic completeness.
