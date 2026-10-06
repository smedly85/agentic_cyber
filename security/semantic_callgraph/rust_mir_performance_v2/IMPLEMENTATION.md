# Separate performance candidate

Select `reference` or `solver-v2-performance` with `solve.py`. Both consume the same raw MIR JSON and root identity, use the live frozen runtime gate, and write to a new output directory. This command produces diagnostic inclusion output only. It is not a historical measurement entry point. The reference file and default imports are unchanged.

## Collapse

The first actual collapse executes the original member union and root store. All later stores canonicalize to that root, so existing non-root sets are immutable thereafter. New raw member reads can create only empty sets. A repeated collapse therefore cannot add a fact to the root. It still updates the same span/reason sets on every invocation.

`field_names[(Instance, local)]` is maintained when a cell is materialized. A member-count generation allows `affected_fields` to absorb new names on the next collapse, including late empty members. No collapse is inferred from compatible types or membership in this index. Distinct fields remain distinct until the reference rule calls collapse.

## Transfer deltas

Each cell owns the same abstract-token set plus an append-only log of actual additions. A transfer cursor is keyed by `(source raw cell, destination canonical cell)`. On first transfer, all source additions are considered. Later transfers consider exactly the suffix after that relation's cursor. The source generation is the log length; the destination remains monotone. Sharing a cursor between constraints with the same relation is exact because the destination already contains all values that either constraint previously copied.

Changing canonical destinations creates a different key. A destination is still materialized before an empty/unchanged transfer is skipped. Source-place resolution and collapse side effects are performed anew on every copy. A live source set replaces an operand snapshot only for the single-source copy/store operation: the only way that store can modify the source itself is a self-union, which adds nothing. General operand evaluation retains its snapshot behavior.

## Indexes

Token-kind indexes are built lazily on first lookup and receive every subsequent insertion delta. Callers do not mutate an index. Place-based selected-kind reads perform the same location resolution, empty-cell creation, and union-read collapse as the original operand. Other operand forms use the original evaluator before filtering. Dyn pointee reads remain raw reads where the reference uses raw reads; they are not silently canonicalized.

Field-prefix caches retain the original filtered member snapshot and are invalidated whenever membership count changes. Membership only grows. Cached snapshots do not include fields created partway through the current copy. These indexes change lookup cost, not which fields or abstract values exist.

## Convergence and resource accounting

The candidate retains every full sweep, every active-function/constraint/call traversal, the same `changed` test, and the 256-sweep cap. There is no worklist, extra heuristic limit, target-based priority, or early acceptance. Sweep-cap exhaustion remains `converged: false`. Both full fixpoints and the cap-bound state are compared in validation.

Counters are separate from scientific JSON. Controlled-suite timing excludes gates, extraction, input loading, serialization, and the read-only equality profiler. An additional in-memory AST copy of the reference supplies observational counters; its outputs must match the uninstrumented reference, and its overhead is excluded from baseline timing. The on-disk reference is never rewritten.

The addition logs, transfer cursors, prefix caches, and lazy kind indexes consume memory. Historical diagnostics must report that cost; lower runtime alone does not establish scalability. No historical depth is calculated or accepted by the diagnostic runner, and no od/body-policy or chcon/environment repair is included.
