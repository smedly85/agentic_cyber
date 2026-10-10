# Preregistered implementation-scope policy for the chmod follow-up

This policy is selected before inspecting scoped depths. It does not change the
frozen C or Rust measurements. Full RUPTA graphs remain evidence.

The C methodology (`docs/semantic_callgraph_methodology.md`, and
`native/semantic_callgraph_svf.cpp`) analyzes the configured executable's objects
and extracted project archive members. It includes shared project support code,
not just the utility translation unit; it excludes unavailable system-library
definitions from internal BFS. It does not presently contract arbitrary library
callback paths or define normalized depth as its primary metric. The proposed
Rust policy is analogous in ownership, but not an already validated cross-language
equivalence.

Primary owned nodes: function instances defined in the selected utility binary
and implementation crate(s), plus reachable shared first-party uucore runtime
implementation. In this pilot the explicit crate allowlist is `chmod`, `uu_chmod`,
and `uucore`; other utility crates are not automatically included. Rust modules
inherit the crate's ownership. Source spans must be in the authenticated project
tree, with explicit allowance for project macro expansion spans. Monomorphizing
a dependency function with a utility type does not transfer ownership. The
inventory and exclusions are saved for review. A separate sensitivity excludes
uucore, reflecting the narrower utility-specific question.

Ownership-audit clarification: include authenticated configured-build-generated
project functions, just as the C policy includes generated translation units.
The audit identified `uucore::mods::locale::get_embedded_locales` in OUT_DIR:
`src/uucore/build.rs` generates it and `locale.rs:62` includes it. Record generator,
generated content hash and build provenance separately from release source.
Preliminary projections that quarantined this unknown span remain saved as
`*-scoped-pre-generated-audit.json`; this inclusion is based on provenance,
not the resulting depth.

Macro-expanded source-level main and project wrappers are included as distinct
compiler functions when their definition belongs to an allowed crate. Do not
substitute uumain or collapse its nested wrapper. Closures and source-defined
Drop/Display methods in included crates count. Compiler-synthesized glue/shims
and promoted/static initialization pseudo-functions do not count as implementation
functions, even if their type arguments or spans point into the utility.
Runtime initializer closures do count. Unknown ownership is excluded with an
explicit diagnostic, never silently assigned to the utility.

Let G be the complete exported instance/context graph and U the selected nodes.
The scoped graph has U as nodes. It has an edge u→v exactly when G has a nonempty
directed path from u to v with every internal node outside U. Each such scoped
edge counts one implementation transition. Store a full witness path and mark
dependency-mediated edges; these are projected reachability edges, not claims
of a direct MIR call. Cycles terminate via visited sets. A path stops at the first
included node, so it cannot skip included functions. Contexts/instances remain
distinct, even when their source labels agree. No missing callbacks are inferred
from address-taking, source syntax or expectations.

An excluded path that terminates without a return to U adds no scoped call edge;
its boundaries and unresolved sites remain coverage evidence. Trace which owned
callers can reach those sites through excluded interiors. Preserve the original
graph and compare reachability against a simple induced subgraph to demonstrate
the effect of mediation. Contracting a missing edge cannot recover it.

Both vulnerability depth and maximum utility depth use shortest-path BFS on this
same scoped graph rooted at source-level main. Dmax is the maximum finite shortest
distance among its reachable nodes. Normalized depth is d(v)/Dmax, undefined if
Dmax=0 or the mapping is absent/ambiguous/unreachable. A deepest path means a
shortest path to a node attaining Dmax, not the longest path. Results remain
provisional if callback/ownership coverage can change either metric.

Only four review mechanisms receive new tests: map_err closure/error flow;
LazyLock and thread-local initializer routes; formatting/Display callbacks; Once
callback attribution (including independent callers). Patches are separate from
the previously validated modern overlay. Stop at mechanisms requiring a new
large subsystem. Recompute only the saved chmod specimen; do not run the population.
