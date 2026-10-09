# Scope and scientific limitations

Canonical upstream is inspected at
`b19f187e9cbe37b5afb1103d88b663253e1f0a03`. These source findings are separate
from empirical outcomes in VALIDATION_REPORT.md.

- `src/util/results_dumper.rs::dump_call_graph` calls `to_ci_call_graph`
  for both analysis modes. Context-sensitive node IDs are converted to FuncId,
  and callsites to BaseCallSite; targets are unioned across contexts. DOT is
  therefore a context-insensitive projection of a context-sensitive solution.
  It cannot recover context-specific paths. Projection can join incompatible
  contexts into paths and shortcuts, affecting both shortest distances and
  their maximum. No claim of context-sensitive BFS is justified by this export.
- That conversion iterates edges, not the reachable-function inventory. An
  isolated entry can disappear from DOT. Absence is not proof of unreachability.
- DOT labels carry function reference strings and MIR basic-block locations,
  not source spans, call type, DefId, context IDs or body-availability status.
  The separate MIR/dynamic-call dumps are necessary but are not a complete,
  structured identity and boundary ledger.
- `dump_dyn_calls` iterates `callsite_to_edges`, so a callsite with no resolved
  edge can be absent. An empty dynamic dump must never be read as zero
  unresolved calls. DOT edge absence cannot distinguish an unresolved call,
  unsupported instruction, unvisited body or a truly unreachable function.
- `FunctionReference::to_string` preserves printed generic type/const arguments
  but removes crate disambiguators and lifetimes, renders non-scalar constants
  as `_`, and omits generic arguments for promoted references. Display names
  are not demonstrated collision-free identities for arbitrary Cargo graphs.
  An adapter must reject observed duplicate labels rather than merge them.
- Entry-name lookup compares unqualified item names and keeps the last match.
  An unmatched name falls back to an entry ID or rustc's entry function. A
  successful process is not proof that the requested entry was selected.
  Nested uutils `uumain` functions need authenticated DefIds/instance matching.
- `fpag_builder.rs::visit_terminator` handles Call, ignores InlineAsm and falls
  through for other terminators, including Drop. Special function models
  cannot be presumed to restore all compiler drop/shim semantics. This needs
  controlled evidence, especially scopeguard, Box and unwind paths.
- Rustc-private API coupling prevents simply selecting a newer compiler.
  Pinned Rust 1.77 nightly cannot faithfully build the frozen edition-2024,
  Rust-1.85-minimum uutils 0.2.2 sources. A compiler port is a new instrument.
- The Cargo wrapper sets RUSTFLAGS to `-Z always_encode_mir`, potentially
  replacing caller flags; an eventual historical integration must preserve
  cfg/features, target, edition and all frozen compilation choices explicitly.
- Memory monitoring uses Linux `/proc`. This experiment targets WSL Linux
  x86_64, not native Windows or macOS. Upstream warns that large analyses can
  require substantial time and memory; small-fixture success would not settle
  whole-utility scalability.

RUPTA Andersen and C SVF AndersenWaveDiff have different IRs, constraints,
models, library boundaries and node inventories. A common inclusion-analysis
family and BFS definition do not establish numerical cross-language
comparability. No historical depths or cross-language numerical claims are
authorized by this experiment.
