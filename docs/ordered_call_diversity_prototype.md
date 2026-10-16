# Ordered call structure: Phase 1 exploratory prototype

This is a **syntax-derived exploratory representation**, not an SVF-equivalent
semantic call graph, a replacement RQ2 metric, or a clustering input. The
implementation lives in `scripts/analysis/ordered_callgraph.py`; its independent
version-1 JSON Schema is `scripts/analysis/ordered_callgraph.schema.json`.
No existing analysis entry point imports this prototype. Primary architecture
and strategy metrics, thresholds, schema-v7 results, frozen configurations,
paper aggregation, security depth, and lineage workflows are unchanged.

## Motivation and infrastructure review

The existing methodology in `diversity_methodology.md` uses baseline-relative
Clang and Tree-sitter node/call count vectors, with GumTree action counts added
for architecture. Counting loses ordering: `validate(); transform(); write();`
and `write(); transform(); validate();` have the same node and call counts.
GumTree can provide additional change information; the fixture does **not**
claim that the entire existing architecture metric necessarily collides.

Files reviewed before implementation:

| Existing component | Finding and reuse decision |
| --- | --- |
| `scripts/analyze_experiment.py` | `parse_tree_sitter` produces count vectors and function call sets. The tests invoke this actual extractor to demonstrate the collision. The prototype does not import the analyzer. |
| `scripts/analysis/diversity_metrics.py` | Statistical, distance, population, and clustering helpers; no extraction utility needed here. Unchanged. |
| `scripts/analysis/diversity_validation.py` | Reuses `parse_source` (lazy Tree-sitter C parser, compatibility initialization, cached parsed bytes) and `iter_nodes` (deterministic preorder traversal). These need no production security evaluator. Its optional distance libraries are imported only inside their own functions. |
| `security/common/callgraph.py` | Superseded syntax-only prototype. Its regex fallback, callback guesses, reachability, and selection logic are not imported. The new declarator helper follows the same ordinary Tree-sitter declarator-field pattern, without error recovery. |
| `security/semantic_callgraph/backend.py` and `schema.json` | Official Clang/LLVM/SVF may-call backend: compiled and linked bitcode, AndersenWaveDiff target analysis, resolved indirect edges, shortest-path depth, and scientific provenance. Neither imported nor modified. |

The existing validation `_call_name` helper recognizes bare identifiers, but
does not distinguish pointer bindings from direct functions. The prototype uses
its own conservative binding checks. It does not reuse an analyzer that might
silently replace missing structural analysis with regex output.

## Running and output contract

From the repository root, using Python with `tree-sitter` and `tree-sitter-c`
(versions pinned by the existing `scripts/analysis-requirements.txt`):

```sh
python3 -m scripts.analysis.ordered_callgraph tests/fixtures/ordered_callgraph/unsequenced.c
python3 -m pytest -q tests/test_ordered_callgraph.py
```

The command prints deterministic JSON to stdout, exits zero on successful
extraction, and exits one with a JSON failure status otherwise. The tests also
need pytest, jsonschema, and the existing analyzer's Python dependencies for
the count-vector comparison. No build, SVF, model, or experiment is launched.

The public Python API is `analyze_source_bytes(source, source_file="candidate.c",
entry_points=("main",))`. It handles one UTF-8 C translation unit. Output fields:

| Field | Meaning |
| --- | --- |
| `schema_version`, `backend` | Independent version 1; `tree_sitter_c_syntax_exploratory`. |
| `status`, `diagnostics` | Explicit extraction outcome; success does not assert compilation or semantic validity. |
| `source_file` | Audit label, excluded from normalized fixture equality. |
| `entry_points` | Sorted configured function names, default `main`; matching definitions carry `entry_point: true`. No matching definition means no identified entry. |
| `functions` | Source-ordered definitions, names, stable ordinal/name IDs, locations, and nested `structure` trees including declarators and bodies. |
| `call_sites` | Every parsed call occurrence within a definition, including repeated calls and calls in conditions or declarators; caller, event reference, name if identifiable, target, resolution, and location. |
| `direct_edges` | Per-occurrence syntax-derived relationships to internal definitions or declared external functions; external targets are null. These are not asserted runtime edges. |
| `unresolved_calls` | References to unresolved call-site IDs, whose resolution fields explain why. |

For the unsequenced fixture, the call records have the following core fields
(locations and event references omitted from this excerpt):

```json
[
  {"id": "c0", "function": "f0:main", "callee_name": "combine", "target": null, "resolution": "external_declared"},
  {"id": "c1", "function": "f0:main", "callee_name": "first", "target": null, "resolution": "external_declared"},
  {"id": "c2", "function": "f0:main", "callee_name": "second", "target": null, "resolution": "external_declared"}
]
```

The `c0` call event contains an `arguments` child with
`ordering: "unsequenced_arguments"`; its children refer to `c1` and `c2`.
The outer event is labeled
`callee_and_arguments_before_invocation_no_sibling_order`. The ordering of IDs
above is source traversal, **not** a runtime trace: `combine` is invoked after
its arguments have been evaluated.

Each structural event contains `id`, Tree-sitter `kind`, parent-field `role`,
`ordering`, `location`, and recursively nested `children`. Operators and leaf
tokens retain expression distinctions. A call event additionally references its
`call_site`. Roles such as `condition`, `consequence`, `alternative`, `body`,
`initializer`, and `update` distinguish nested control regions without
flattening them. The full recursive schema is machine validated by the tests;
referential-integrity assertions supplement what JSON Schema can enforce.

Locations contain zero-based UTF-8 byte offsets (end exclusive), one-based
lines, and zero-based byte columns. IDs use traversal ordinals and human-readable
function names, never line numbers. Comments are excluded before event numbering.
Sorted JSON object keys and deterministic arrays produce repeatable output for
identical input under the same parser versions; no timestamps or absolute tool
paths are added.

`normalized_structure` removes locations, source-file labels, and diagnostics
for fixture equality. It rejects failed extractions. It preserves names,
literals, definition order, and syntax-tree IDs: **it is not graph normalization
or a proposed distance feature vector**. Whitespace between tokens and comments
do not affect this projection. Whitespace inside a string literal remains
content. Phase 2 must choose further normalization explicitly.

## Source order and execution order

The structure is a tree of syntax and local ordering annotations, not a CFG or
an execution trace. Every child array is stored in lexical traversal order;
the array alone never establishes runtime ordering.

- Compound statements retain source statement sequence. Returns, breaks,
  continues, gotos, and labels remain nodes, so later consumers must not assume
  every subsequent statement executes.
- If/else and conditional expressions retain condition and exclusive arms.
  Calls inside conditions remain nested there. `&&` and `||` mark conditional
  evaluation of the right operand after the left.
- For, while, and do loops retain their distinct control roles and repetition
  policy. In a `for` AST the update appears lexically before the body; its role
  and policy identify the body-before-update runtime relationship.
- Switch retains dispatch and case/default regions. Cases allow fallthrough;
  they are not modeled as mutually exclusive completed branches. Break nodes
  remain explicit, but no CFG edge reconstruction is attempted.
- Argument expressions, the callee expression relative to its arguments, and
  ordinary binary/assignment operands have no imposed left-to-right execution
  order. C's rules do not permit inferring one from source coordinates.
  Nested calls retain nesting; annotations do not claim that called function
  bodies interleave. Initializer-list evaluation is marked indeterminately
  sequenced. Comma expressions preserve left-before-right sequencing.
- Size/alignment and generic-selection syntax is retained with unevaluated or
  unresolved-evaluation annotations. A syntactic call occurrence can therefore
  be present without executing. Generic selection and VLA-dependent `sizeof`
  require future semantic treatment. Unrecognized constructs retain their AST
  and explicitly claim no execution-order knowledge.

The parser interprets `sizeof(f())` as a possible abstract function type rather
than a call expression. This prototype rejects size/alignment operands containing
abstract function declarators as `unsupported_input`; it does not repair them.
`sizeof((f()))` unambiguously exposes a call node and is covered by a test.
Other C typedef/expression ambiguities remain a limitation of syntax-only parsing.

## Resolution and failure boundaries

Internal direct resolution requires a bare identifier (possibly parenthesized),
a unique definition in this translation unit, and no detected object binding
for that name. Explicit function declarations without definitions produce
`external_declared` with a null target. Undeclared names produce
`unresolved_name`: they might be external symbols, macros, or invalid C.
Pointer/member/computed callees and identifier calls with object bindings are
`unresolved_indirect`. No points-to, callback, alias, or library-body edge is guessed.

The binding filter deliberately considers all local declarations and parameters
throughout a function, and all top-level object declarations, without precise
lexical lifetime. It can suppress a valid direct edge outside a shadowing block.
It also does not perform C type checking. This conservative under-resolution is
preferable to inventing indirect targets for this prototype.

Only `.c` input is supported. Missing dependencies, parser failures, invalid UTF-8,
ERROR/missing AST nodes, unsupported language, and file-read failures produce
explicit statuses with empty measurement arrays. No failed result can be
normalized into a successful empty representation. A genuinely empty valid
translation unit may successfully have no functions.

Macro definitions and conditional-preprocessor constructs are explicitly
unsupported. Includes are retained only by the source audit; headers are not
expanded, so header-provided macros/types and build configurations remain
unknown. Nested GNU function definitions, duplicate identities, and call syntax
outside definitions also fail explicitly rather than dropping or duplicating
occurrences. This is deliberately a narrow initial extraction domain.

The official semantic backend remains the sole vulnerability-depth backend.
This prototype has no reachability, depth, vulnerability selection, or security
evaluation API. Its `direct_edges` can include unevaluated/dead syntactic calls
and must never be fed into scientific depth computation.

## Construct validation

`tests/fixtures/ordered_callgraph/` contains controlled C fixtures and one
unsupported Rust fixture; `tests/test_ordered_callgraph.py` checks:

| Test | Controlled change and expected result |
| --- | --- |
| A | Analyze identical source twice and invoke separate CLI processes: identical normalized structure and byte-identical JSON for the same input label. |
| B | Forward versus reverse call order: actual existing Tree-sitter count vectors are identical; event sequences differ. This isolates order loss in the count representation. |
| C | Two `validate` calls followed by `write`: all three distinct call IDs, event IDs, and per-site edges survive. |
| D | Move `transform` out of an if and `write` into it: call names remain the same, but their conditionally executed contexts differ. |
| E | Whitespace and comments change: normalized equality holds, including empty blocks with inserted comments; audit locations differ. |
| F | `combine(first(), second())`: all calls survive; argument siblings explicitly have uncertain order, with outer invocation distinguished. |
| G | Malformed C, Rust, and independently missing parser/grammar packages: explicit failure statuses and no successful measurements. |
| Renaming | `helper` versus `renamed`: direct edges point to the corresponding definitions; raw normalized projections still differ. Reserved for Phase-2 name-invariance validation. |
| Nested controls | For/while/do, if/else, short-circuit conditions, ternary branches, and switch cases preserve nesting, roles, and ordering policies. |
| Indirect calls | Parameter shadowing, dereferenced pointers, and global function pointers remain unresolved; declared externals and unknown names remain distinguishable. |
| Additional boundaries | Invalid encoding, preprocessing, duplicate/nested definitions, file-scope call syntax, sizeof ambiguity, parser initialization failure, and CLI I/O failure are explicit. Comma/ordinary binary/unevaluated expression policies and schema/reference integrity are checked. |

These tests establish sensitivity to controlled structural changes and
invariance to presentation changes. They do not establish predictive validity
for independently generated programs, semantic equivalence, or exploit transfer.

Validation run on 2026-10-16 in the existing WSL Python environment:
`python3 -m pytest -q tests/test_ordered_callgraph.py` — **24 passed in 2.73s**.
The working-tree diff check also passed. No full experiments were run.

## Before pairwise distances or clustering

1. Define separate architecture and strategy comparison domains: graph topology
   and decomposition for A; nested operations and partial-order/control structure
   within matched functions for S. Decide whether signatures belong in either.
2. Specify function matching, helper renaming, local identifier and literal
   normalization, external API identity, and invariance to definition ordering.
   Use the renaming fixtures; do not compare audit IDs as substantive features.
3. Define treatment of unsequenced siblings, loop structure, switch fallthrough,
   early exits, unreachable/unevaluated syntax, and expression-versus-type
   ambiguities. Source ordering inside an uncertain group must not automatically
   become guaranteed strategy ordering.
4. Decide multi-file/linkage scope, macro/header policy, precise binding support,
   extraction coverage and missing-result handling, and parser-version provenance.
5. Validate candidate distance definitions on richer controlled examples and
   blinded human architecture/strategy judgments, including semantic-preserving
   refactorings and independent implementations. No arbitrary weights are chosen
   in Phase 1.
6. Only after representation/distance validation, calibrate and freeze any new
   clustering policy independently of the existing confirmatory configuration.
   Specify population/coverage reporting before applying it to experiments.

## Phase 2: exploratory pairwise distances

**Historical Phase-2 policy/results:** the Phase-2.5 section below supersedes
the argument/initializer permutation invariance and automatic unmatched-helper
inclusion described here. `ordered_diversity_pilot_results.json` remains the
original Phase-2 artifact; new results have separate Phase-2.5 filenames.

Phase 2 adds `scripts/analysis/ordered_distances.py` and the controlled runner
`scripts/ordered_diversity_pilot.py`. It leaves the Phase-1 extractor/schema and
all primary analysis code unchanged. The comparison representation is versioned
`ordered-diversity-experimental-v2`, independently of primary schema-v7 results.
The original sections above describe Phase 1; the policies below implement a
specific, deliberately limited subset of its proposed next steps.

### Audit of available information

Phase 1 retains the named syntax tree, not just calls. Function bodies contain
call-free declarations, initializers, assignments, binary/unary operators,
literals, and return/break/continue/goto/label nodes. Phase 2 can distinguish
`x += 2` from `x *= 2` and break from continue. It cannot recover data flow,
aliasing, value semantics, jump destinations as CFG edges, actual reachability,
or all type-dependent evaluation rules. Syntax retains label names, but no
label alpha-normalization or jump analysis is added.

For S, ordinary identifiers (including field/type identifiers) become a generic
identifier token. Consequently `x + x` and `x + y` can coincide. Call-free
operations outside function bodies, signatures, and VLA parameter computations
are outside S. Literals remain exact; mathematically equivalent expressions
can differ. Preprocessing and indirect targets remain unresolved as in Phase 1.
Ordered call sites do **not** represent complete computational strategy.

### Architecture A and function alignment

For a valid extraction define a directed graph G with:

- one vertex per defined function, including isolated and unrooted functions;
- one distinctly named vertex per declared external API actually called;
- one edge per distinct caller-to-target relationship, including recursion.

Repeated calls collapse to one edge. No event order, branch placement, call
counts, source coordinates, helper names, or body tokens enter A. Designated
entry functions retain their configured names and can match only the same
designated entry name. Different configured entry-point policies are incompatible.
Declared external API names are fixed identities. All other function names are
uninterpreted audit labels.

Let P be all partial injective helper correspondences, with shared entry points
anchored. Unmatched helpers and entry functions have side-specific identities.
For p in P, let X_p and Y_p be the corresponding sets of vertex and directed-edge
atoms. Define:

```text
C_A(p) = |X_p symmetric_difference Y_p|
D_A = min_p C_A(p) / (|X_p| + |Y_p|)
```

The denominator is independent of p. If both atom sets are empty, D_A is zero.
This is exact minimum unit graph-atom insertion/deletion discrepancy under
entry-preserving partial matching, normalized by total atom count. A vertex and
an edge each count as one elementary atom; no feature blocks, fitted weights,
or heuristic numerical tradeoffs are introduced. This is a structural edit
convention, not an empirically validated model of human architecture judgments.

All exact minimizing correspondences are retained. Match options (including
null for unmatched), definitely added/removed functions, and ambiguous matches
are reported. An edge change under a fixed match is removal plus insertion.
Source declaration order never selects the scientific match: the bounded search
enumerates every eligible partial injection. API incidence, incoming/outgoing
relationships, recursion, and entry-relative topology provide matching context.
No helper body information can change D_A, so operation order cannot leak into A.

Entry-rooted connectivity is encoded by graph topology, without a separately
weighted reachability feature. The prototype also counts functions not reachable
from an entry. Missing entry definitions are allowed and represented by absent
vertices; the graph can be unrooted. These are syntax relationships, including
dead/unevaluated calls, not the official semantic may-call graph or security depth.

Partial edit correspondences are not proven function homologies. Equal-size,
unrelated functions may be matched because that is a cheaper graph edit.
Symmetric helpers can have several equally good mappings. Structural body edits
resolve ties only for S (below); architecture ambiguity remains visible.

### Fixed strategy scope and renaming

S requires an explicit, fixed `scope_reference` for the entire comparison group.
The reference is classified using the existing case-insensitive strategy-exclusion
regex and explicit forced reference-name includes. Main and designated entry
functions are included. The regex snapshot is tested against
`DEFAULT_STRATEGY_EXCLUDE_REGEX` in the primary analyzer; no production policy
is modified. This prototype does not implement the primary without-main ablation.

Reference classifications transfer to each candidate through **all** minimum-A
reference-to-candidate correspondences. A candidate function must receive the
same classification under every such mapping; disagreement makes S unavailable
with `scope_alignment_ambiguous`. Newly unmatched functions are included by
default and are never classified using their newly invented names. A new
function that might instead match an excluded reference function can therefore
cause explicit ambiguity. Forced includes name reference functions; a missing
reference name is an error, not a silently ignored request.

This reference-bound policy makes a pure internal rename invariant even when
it crosses the exclusion regex or reverses declaration order. It also preserves
the distance to a third candidate under the same fixed reference. The reference
hash, configured regex, forced includes, and transferred memberships are recorded.
Changing the reference changes the policy and must not occur within one matrix.

An important inherited limitation: the existing regex matches `helper` because
it contains `help`. The original Phase-1 renaming fixture therefore excludes
that helper body from S by default. The new multi-helper fixture uses `worker`
for the behavioral helper and `parse_args` for the excluded helper, then renames
them to `parser_name` and `ordinary` respectively. Scope follows the structural
functions, not those misleading new names. Regex classification is still not a
semantic detector of parsing behavior.

### Strategy S and event comparison

S is a forest of normalized, in-scope function **body** trees. Each event label
contains its syntax kind, parent-field role, ordering annotation, operator,
literal/normalized token, and aligned internal target or fixed external API name
when it is a call. A directly resolved callee-expression subtree is omitted
because its target is already represented on the call node. This also removes
incidental callee parentheses. Repeated call nodes remain separate.

Children retain structural nesting. Argument lists, ordinary unsequenced
operands, initializer lists, and callee/argument groups use unordered matching.
Other child lists use ordered dynamic programming over source structure.
Branch roles prevent if/else arms from becoming an execution sequence, and loop
roles retain condition/body/update distinctions. Comparing source order is never
a claim that all syntactically later events execute. No CFG is fabricated for
gotos, returns, short-circuit conditions, or fallthrough.

Define the rooted subtree cost T(x,y):

```text
delete/insert a subtree x: |x|, its number of nodes
relabel a node: 0 for identical composite labels, otherwise 1
T(x,y): minimum of deleting/inserting both whole trees, or
        relabeling the roots plus the optimal child-forest edit
```

Ordered child forests use sequence-edit DP with recursive subtree substitution.
When both parent groups are explicitly unordered, child-forest cost is minimum
partial bipartite assignment with unmatched-subtree insertion/deletion. Field
roles remain labels: `1-2` differs from `2-1` even though operand evaluation order
is uncertain. Argument-list children have no positional roles in this projection,
so `combine(first(),second())` and `combine(second(),first())` coincide. That is
a deliberately lossy permutation invariance, **not** functional equivalence;
preserving argument data roles without inventing execution order needs further
work. Initializer ordering has analogous data-position limitations.

This is a **rooted subtree edit** distance, not unrestricted APTED/Zhang-Shasha
node editing: deleting a node deletes its whole subtree and does not promote
its children. This choice keeps branch/control boundaries explicit. It is
sensitive to syntactic wrappers and has not been calibrated against human
strategy judgments.

For each architecture-optimal mapping p, sum T across matched in-scope functions
and the sizes of all unmatched in-scope body trees. Call this C_S(p). Let N be
the sum of in-scope body-node counts on both sides. Then:

```text
D_S = min_{p in argmin C_A} C_S(p) / N
```

When both scoped forests are empty, D_S is zero. Every body node has unit cost;
there are no separately weighted call/control/count features. The minimum is
an optimistic strategy discrepancy conditional on architecture-optimal alignment.
The report also gives `[minimum, maximum]` over those alignments and the remaining
strategy-minimizing match options. The range is alignment sensitivity, not a
confidence interval. An arbitrary lexicographic or declaration-order tie does
not manufacture strategy diversity.

### Mathematical properties and explicit limits

For successfully completed comparisons under the same fixed scope policy, both
distances are finite in [0,1], symmetric, deterministic, and zero on the diagonal.
Empty versus nonempty representations have distance one. Distinct sources can
have zero distance due to graph isomorphism, scope exclusions, identifier erasure,
and unordered-group normalization. Neither zero distance nor positive distance
asserts functional equivalence or inequivalence.

No metric-space claim is made. A has a concrete triangle-inequality counterexample:
main calling only API a, main calling both a and b, and main calling only b give
distances 1/4, 1/4, and 2/3. The normalized graph discrepancy is Dice-like and
2/3 exceeds 1/4 + 1/4. This is a regression test. S also has no triangle guarantee
because of normalization, architecture-conditioned correspondence sets, scope
transfer, and restricted tree edits. Pairwise correspondences need not be
globally transitive across a population.

Defaults bound exact work at 20,000 helper injections per alignment, 2,000 input
events per extraction, 1,000,000 counted search/DP work units per comparison,
and unordered assignment width 10. Enumeration is combinatorial and suitable
only for small controlled fixtures. A limit never returns a partially optimized
distance. These deterministic work bounds are not a wall-clock timeout; caught
timeout exceptions also produce unavailable status. If A completes but S fails,
the completed A value remains available and S is null.

### Missingness, provenance, and isolation

The comparison validates the Phase-1 JSON contract and call/event/target/edge
references before constructing a graph. Failed extraction, unsupported versions
or language, inconsistent artifacts, and unresolved target calls cannot become
successful empty graphs. This phase conservatively makes **both** A and S
unavailable when any call target is unresolved, even if some substructures could
be compared. Explicit external declarations with null internal targets are
allowed because their API identity is known. Resolution coverage reports call
counts, resolved/unresolved counts, and a fraction (null when there are no calls).

Output records independent A/S status and nullable distance, coverage, comparison
version, method, normalization, limits, scope reference, implementation hashes,
Python and parser/grammar/jsonschema package versions. Package versions describe
the current environment; imported Phase-1 artifacts do not attest the original
parser version. The pilot extracts fresh artifacts in that same environment and
records source SHA-256, manifest/runner hashes, and count-extractor source hash.
No security evaluator is called. Missing jsonschema or analyzer dependencies are
explicit unavailable measurements, not substitutes.

The low-level comparator expects callers to enforce a single C utility/checkpoint
contract; it cannot infer requirements from source text. The pilot enforces C-only
groups and records synthetic utility/checkpoint labels from its checked-in
manifest. It emits no cross-group distances or pooled population summaries.
Malformed C and unsupported Rust are separate negative extraction probes, not
members of a mixed-language matrix.

### Controlled pilot and observed results

Run from the repository root:

```sh
python3 -m pytest -q tests/test_ordered_callgraph.py tests/test_ordered_distances.py
python3 -m scripts.ordered_diversity_pilot --output docs/ordered_diversity_pilot_results.json
```

The full reproducible report is `docs/ordered_diversity_pilot_results.json`.
It contains separately named A, S, and raw Tree-sitter-count cosine matrices,
per-pair alignment diagnostics, statuses, and per-group measurement coverage.
Each synthetic construct group uses one scope reference and one contract.

| Controlled pair | D_A | D_S | Raw count cosine |
| --- | ---: | ---: | ---: |
| Identical | 0 | 0 | 0 |
| Formatting/comments | 0 | 0 | 0.011377 |
| Single internal rename | 0 | 0 | 0.340000 |
| Multi-helper rename, declaration reorder, regex crossing | 0 | 0 | 0.360465 |
| Calls reordered | 0 | 0.083333 | 0 |
| Branch placement changed | 0 | 0.318182 | 0 |
| Work split into a helper | 0.375000 | 0.392857 | 0.152049 |
| Repeated call added | 0 | 0.111111 | 0.008862 |
| Unsequenced argument permutation | 0 | 0 | 0 |
| Call-free operator changed | 0 | 0.041667 | 0.018182 |

The count diagnostic invokes the actual existing `parse_tree_sitter` utility.
It compares raw vectors, **not** primary baseline-relative Clang/Tree-sitter/
GumTree architecture or strategy metrics. Raw counts include comment nodes and
function-name keys, explaining the formatting/comment and renaming sensitivity
here; this is not a claim about the complete primary pipeline. No primary
configurations or clustering thresholds were changed.

Example matrices within the order/decomposition group, rounded to four decimals:
F = forward, R = reverse, P = extra repeated validate, D = decomposed helper.

```text
A       F       R       P       D
F     0       0       0       .3750
R     0       0       0       .3750
P     0       0       0       .3750
D      .3750   .3750   .3750  0

S       F       R       P       D
F     0        .0833   .1111   .3929
R      .0833  0        .1852   .4286
P      .1111   .1852  0        .4516
D      .3929   .4286   .4516  0
```

Additional tests cover added/removed/isolated functions, same-size topology
changes, control transfers and loops, empty inputs, symmetry and bounds,
identity, repeated processes, inherited scope policy, forced includes,
ambiguity, work limits, simulated timeout, corrupt/incomplete artifacts,
unresolved calls, and language-group rejection. The symmetric two-helper fixture
has two architecture-optimal correspondences; S reports its range and selects
the structurally matching one without hiding architecture ambiguity. The indirect
fixture has one successful extraction but zero available A/S comparisons; its
self-distance is null, not zero. Malformed C and Rust remain explicit failures.

Final Phase-2 validation on 2026-10-16: **65 passed in 13.78s**, including all
24 Phase-1 checks. The pilot ran successfully with Python 3.14.4,
tree-sitter 0.26.0, and tree-sitter-c 0.24.2. The saved JSON contains the exact
additional dependency versions and implementation hashes. No formal experiments,
model workloads, SVF builds, commits, or pushes were performed.

These are construct-sensitivity checks, not proofs of functional equivalence,
independence of generated failures, or predictive validity on real populations.

### Recommended Phase 3

Before clustering, evaluate the representation and distance choices on larger,
blinded, human-labeled C refactorings and independently generated candidates
within fixed utility/checkpoint contracts. Prioritize scope-reference stability,
alignment ambiguity, argument-position semantics, identifier/data-flow loss,
call-free operations, and extraction coverage. Compare alternate normalization
and subtree-edit conventions without tuning on confirmatory outcomes. Decide
whether scalable matching can preserve explicit uncertainty and reproducibility.
Only after those checks should an independently calibrated, frozen clustering
policy and complete-population missingness rules be proposed. Keep this work
separate from primary RQ2 and the semantic vulnerability-depth backend.

## Phase 2.5: feasibility, data positions, and uncertainty

The comparison version is now `ordered-diversity-experimental-v2.5`. The
Phase-1 extractor and schema, primary diversity metrics, frozen configurations,
historical results, semantic depth backend, and lineage infrastructure are
unchanged. Changes are confined to experimental comparison/pilot modules,
controlled fixtures/tests, and new documentation artifacts. No weights were
tuned. No compiler, SVF, LLM, experiment, or lineage-generation workload was run.

### Real-source selection and provenance

`scripts/ordered_diversity_feasibility.py` reads the existing
`security/generated_candidate_population.json` manifest. The main group is all
seven recorded successful C `mkdir` candidates at checkpoint `002` (mode), from
`mkdir-qwen38-t1-seed42-low-ctx64k-max64k-n10`. A separate stress group is all ten
successful C `grep` checkpoint `004` candidates from
`grep-qwen38-t1-seed42-low-ctx64k-max64k-n10`. There are no cross-group comparisons
or pooled experimental population statistics. Membership is the manifest's
`public_checkpoint_stage_success` evidence, not a newly inferred success label.
We did not rebuild or rerun functional validation.

Candidate bytes are checked against their recorded SHA-256 before extraction.
This Windows checkout has CRLF differences: the script permits only a verified
CRLF-to-LF hash match, records both hashes and the exact verification status,
and analyzes the **original bytes without rewriting files**. Any other mismatch
aborts the audit. The manifest, audit runner, extractor, schema, comparator,
Python and dependency provenance are recorded in
`docs/ordered_diversity_phase25_feasibility.json`.

The script also makes an explicitly diagnostic census of visible, unpreprocessed
Tree-sitter syntax. On failed extraction this census can count function-definition
nodes, call-expression nodes, and non-comment named function nodes. It does not
recover a successful graph, identify targets, or authorize a distance. Failed
measurements have null function/event/unresolved counts in the measurement
columns; census counts live in a separately labeled object. All 17 census parses
were error-free, but that does not establish type correctness or expanded syntax.

### Real-source coverage and A/S availability

Pairs below are unordered distinct candidate pairs (no diagonals). Function,
event, and unresolved ranges describe **successful extractions only**.

| Population | Candidates | Extracted | Preprocessing failures | Functions | Events | Unresolved occurrences | A available | S available | Capacity over 20,000 injections |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| mkdir / 002 | 7 | 4 | 3 | 5–7 | 1,224–1,599 | 25–44 | 0/21 | 0/21 | 0/21 |
| grep / 004 | 10 | 2 | 8 | 11–13 | 2,156–2,215 | 75–80 | 0/45 | 0/45 | 45/45 |

Every extraction failure is `unsupported_input`, with the diagnostic
`Macro definitions/conditional preprocessing require a future policy`. There
are six mkdir pairs and one grep pair with two successful extractions, but none
has complete resolved targets. Both successful grep extractions also exceed the
2,000-event comparison limit. The JSON records actual first-reported comparison
failures **and** all known candidate blockers; first-failure counts depend on
validation order and must not conceal coexisting unresolved-target/event limits.

Per-source audit, using lineage suffixes within each population:

| Utility | Lineage | Extraction | Functions / events | Unresolved | Diagnostic census functions / events |
| --- | --- | --- | --- | ---: | --- |
| mkdir | 001 | success | 6 / 1224 | 25 | 6 / 1224 |
| mkdir | 003 | success | 7 / 1599 | 42 | 7 / 1599 |
| mkdir | 004 | unsupported preprocessing | NA | NA | 3 / 1413 |
| mkdir | 005 | unsupported preprocessing | NA | NA | 3 / 1280 |
| mkdir | 006 | unsupported preprocessing | NA | NA | 3 / 1360 |
| mkdir | 009 | success | 6 / 1566 | 37 | 6 / 1566 |
| mkdir | 010 | success | 5 / 1390 | 44 | 5 / 1390 |
| grep | 001 | success | 11 / 2215 | 75 | 11 / 2215 |
| grep | 002 | unsupported preprocessing | NA | NA | 16 / 2152 |
| grep | 003 | unsupported preprocessing | NA | NA | 11 / 2460 |
| grep | 004 | unsupported preprocessing | NA | NA | 8 / 1981 |
| grep | 005 | unsupported preprocessing | NA | NA | 12 / 2330 |
| grep | 006 | unsupported preprocessing | NA | NA | 10 / 1814 |
| grep | 007 | success | 13 / 2156 | 80 | 13 / 2156 |
| grep | 008 | unsupported preprocessing | NA | NA | 11 / 2130 |
| grep | 009 | unsupported preprocessing | NA | NA | 10 / 1943 |
| grep | 010 | unsupported preprocessing | NA | NA | 10 / 2292 |

Includes are accepted syntactically but not expanded. The mkdir candidates
include standard/POSIX headers, yet occurrences such as `fprintf`, `mkdir`,
`strerror`, `strcmp`, and `free` remain `unresolved_name` because their declarations
are not present in the parsed translation unit. `S_ISDIR` also appears among
unresolved call-like syntax. There is no whitelist, fabricated external target,
inserted declaration, stripped preprocessor directive, or relaxed missingness.

A further type-awareness issue appears in mkdir lineage-009: the unresolved-name
inventory contains three `mode_t` occurrences. Inspection finds cast syntax such
as `(mode_t)(rwx & 7u)`, which Tree-sitter can interpret as a call when header
typedef information is absent. Merely declaring every unknown identifier an
external API would therefore introduce false edges. The controlled
`header_call.c`/`declared_call.c` probes demonstrate that an included-header call
remains unresolved while an explicitly declared call resolves. The latter is a
separate synthetic input, never a repair applied to real candidates.

**Feasibility conclusion:** the current representation cannot support either
audited experimental population under its current completeness rules. This is
observed zero distance availability, not evidence of zero diversity. Coverage
on other utilities/checkpoints remains unmeasured.

### Argument and initializer data slots

The normalized strategy tree now appends an explicit data-slot label to each
argument and initializer-list element: `(argument_list, ordinal)` or
`(initializer_list, ordinal)`. These labels are derived from non-comment AST
children, never raw source coordinates. The parent remains an explicitly
unordered evaluation group. Assignment matching may not match children across
different slots; it still makes no assertion that slot 0 evaluates first.

Thus `combine(first(), second())` and `combine(second(), first())` both have
the same A topology but now differ in S (**0.125**): the association between
operand computation and parameter slot differs. Neither representation claims
a runtime order between `first` and `second`. This replaces Phase 2's lossy
argument-permutation invariance.

Positional initializer swaps likewise differ (**S=0.0625**) while retaining the
`indeterminately_sequenced_initializers` annotation. Nested initializer lists
carry slots at each level. Explicit field/index designator syntax and its tokens
are retained, so `.x` versus `.y` and `[1]` versus `[2]` remain distinguishable.
This is syntactic position, not type-resolved subobject identity: brace elision,
mixed designated/positional lists, duplicate designators, and equivalent reorderings
can still differ. No unspecified/indeterminate evaluation order is inferred from
these slots. Source-slot association and execution sequencing remain separate.

### Alignment feasibility and alternatives

The exact oracle is unchanged. For n and m non-entry functions, it enumerates

```text
P(n,m) = sum_{k=0..min(n,m)} C(n,k) C(m,k) k!
```

partial injections. Each graph comparison constructs node/edge sets; retaining
all optimum maps also costs memory proportional to the number and size of tied
maps. Strategy and scope require additional comparisons over these maps, so
architecture-only search time is not an end-to-end timing estimate.

The new public `alignment_search_size` exposes this exact preflight calculation.
For the real visible-syntax inventories, mkdir pairs require **7–4,051** mappings,
whereas grep pairs require **1,047,376–2,148,321,709,561**. All grep pairs exceed
the unchanged 20,000 limit. These are capacity diagnostics on visible source
functions, not graph comparisons of failed extractions. No real full alignment
timing can be reported: completeness validation rejects these candidates first.

The audit separately benchmarks the exact matcher on synthetic symmetric star
graphs, with no approximate results substituted for real candidates:

| Helpers on each side | Partial injections | Observed A-oracle seconds | Optimum maps |
| ---: | ---: | ---: | ---: |
| 4 | 209 | about 0.0011 | 24 |
| 5 | 1,546 | about 0.0085 | 120 |
| 6 | 13,327 | about 0.0777 | 720 |
| 7 | 130,922 | not run: search limit | not enumerated |

Exact observed timings are in the JSON and are diagnostic, machine-dependent,
and excluded from distance features. Even six symmetric helpers leave 720
architecture-optimal maps to consider for S. Raising the search cap alone does
not address real graph size or alignment uncertainty.

Alternatives evaluated at the algorithm-design level (none replaces the oracle):

| Candidate approach | Accuracy and uncertainty requirements | Determinism and applicability |
| --- | --- | --- |
| Exact branch-and-bound over partial injections | Preserve the current objective using admissible lower bounds; report certified lower/upper bounds or unavailable if incomplete. A zero optimality gap is needed for an exact scalar. | Canonical structural traversal and deterministic resource budget; potentially prunes sparse asymmetric graphs, but no improvement is assumed on symmetric worst cases. Not benchmarked here. |
| Exact isomorphism fast path for A=0 | A verified entry/API-preserving isomorphism certifies zero A. One isomorphism does not establish S extrema or scope consensus; automorphism ambiguity remains. | Structural refinement may accelerate equality, but refinement colors alone are not proof of isomorphism. Do not restrict positive-distance alignments by heuristic colors. Not benchmarked here. |
| Assignment relaxation plus feasible graph mappings | Unary vertex assignment omits pairwise edge dependencies and therefore is not the same objective. Use a proven lower bound plus a feasible upper bound; label any gap, never silently return the heuristic mapping as exact. | A defined objective, canonical tie policy, oracle-based accuracy study, and uncertainty protocol are prerequisites. No approximate matcher was introduced. |

Any future scalable implementation must agree with the retained small-graph
oracle on exact results, retain all relevant scope/strategy uncertainty, and
report incomplete optimization explicitly. Timing and bound quality must then
be measured on complete real-source graphs, which are currently unavailable.

### Empty-reference scope and reference sensitivity

The Phase-2 rule “include unmatched functions” has been removed. Main and
designated entry functions remain included by explicit policy. Every other
unmatched helper now has **unknown** scope. An unknown-only result raises
`scope_unmatched_functions`; conflicting matched classifications (or matched
versus unknown possibilities) raise `scope_alignment_ambiguous`. Diagnostics
list known decisions, per-function possibilities, and what the candidate-name
regex would have done **for audit only**. Neither candidate naming nor an empty
reference silently supplies a missing classification. Explicit forced includes
continue to apply to matched reference functions.

For a new-source lineage population, the common comparison baseline is empty;
individual trajectories' preceding checkpoint sources are not a shared reference.
An empty reference consequently cannot assign parser/usage roles to new helpers.
The real audit uses an explicitly empty shared scope reference and selects no
arbitrary candidate as authoritative. Since A is unavailable for every real pair,
real reference sensitivity and real alignment-induced S ranges are not estimable.

The controlled `reference_sensitivity` audit compares exactly the same pair using
all specified references, without choosing a favorable one:

| Reference for worker-body repetition pair | Worker included? | S |
| --- | --- | ---: |
| `scope_worker.c` | yes | 0.130435 |
| Structurally equivalent `scope_parser.c` | no | 0 |
| `empty.c` | unknown | unavailable |

This dependence is fundamental to the inherited name regex: a function can be
renamed across its inclusion boundary without changing its syntax/graph. A
classifier cannot both reproduce that name-dependent policy on every source
and be invariant to arbitrary helper renaming. Fixed-reference transfer gives
invariance only **conditional on that fixed reference**. The new probes expose
the incompatibility rather than claiming a canonical reference-free solution.

For future new-source studies, use independently specified, audited function-role
annotations or a validated structural/semantic role classifier with an explicit
unknown category. An all-functions strategy is a different, explicitly labeled
scope estimand; it must not silently replace parser-excluded S. Reference choice
or role annotation must be pre-specified and sensitivity reported. Conflicting
parser/worker matches can make even self-comparisons unavailable under the
scope policy; they are not changed to distance zero.

The order/decomposition controlled group now uses its decomposition fixture as
an explicitly named scope reference, so its helper has a known behavioral role.
That supports a controlled sensitivity test, not a recipe for selecting a
reference from real populations. With a simpler reference that has no such
helper, the added helper's scope is unknown and S is unavailable.

### Alignment ambiguity and conservative reporting

Minimum and maximum S over architecture-optimal maps are retained. Successful
results now carry `distance_interpretation: optimistic_minimum_not_formal_primary`,
`primary_eligible: false`, and either `alignment_invariant` or
`alignment_sensitive`. Any positive spread is flagged; no unvalidated “material”
threshold is tuned to the fixtures. The pilot exports separate interval matrices
and a list of affected non-diagonal pairs.

The two symmetric-helper fixtures have two optimum A alignments and
**S in [0, 0.090909]**, despite the minimum being zero. This is a substantive
controlled sensitivity example: one mapping preserves call correspondence and
the other swaps it. The same ambiguity can appear in the diagonal range even
though the identity mapping gives the expected minimum zero. Real S ranges
cannot currently be evaluated because all real comparisons are unavailable.

Conservative future policy: report the full alignment range and possible function
correspondences. Do not use the optimistic minimum as a formal primary scalar
where alignments disagree. Before any clustering, either establish an independent
alignment rule with validation, or adopt an explicit interval/uncertainty-aware
analysis that only makes conclusions robust to all admissible alignments. Scope
ambiguity is separate missingness; it is not an S confidence interval. No
clustering or thresholds are introduced here.

### Construct outcomes and reproducibility

`docs/ordered_diversity_phase25_construct_results.json` is the new controlled
report. The historical Phase-2 JSON remains untouched. The expanded manifest
keeps each construct in its own C utility/checkpoint group.

| Change | A | S outcome | Interpretation |
| --- | ---: | --- | --- |
| Argument slots swapped | 0 | 0.125, detected | Data association retained without claiming evaluation order. |
| Initializer slots swapped | 0 | 0.0625, detected | Explicit slot labels; designator and nesting tests also pass. |
| `x+x` to `x+y` | 0 | 0, missed | Identifier relationships are erased, not resolved bindings. |
| Helper rename / declaration reorder | 0 | 0 | Invariant with fixed unambiguous scope transfer. |
| Predicate `<` to `>` | 0 | 0.05, detected | Operator syntax retained. |
| Predicate `x<y` to `x<x` | 0 | 0, missed | Same identifier-relationship limitation. |
| Split work into a helper | 0.375 | 0.392857 with declared controlled reference | Unmatched scope without that reference is explicitly unavailable. |
| Break to continue | 0 | 0.038462, detected | Transfer node differs; no destination CFG is inferred. |
| Parser/behavior reference naming | 0 | reference-sensitive | 0 versus 0.130435 versus unknown in the controlled audit. |
| Structurally ambiguous parser/worker matches | 0 | unavailable | Conflicting scope classifications retained. |
| Header-only external declaration | unavailable | unavailable | No name-based fabricated target. |

These are representation-sensitivity tests, not functional equivalence tests.
Known misses are asserted in tests to document the representation's limits;
no numerical weights were adjusted to force positive distances.

Phase-2.5 validation: **84 tests passed**, including the Phase-1 and Phase-2
regression suites with explicit updates for the two changed policies. The
read-only real-source audit and expanded controlled pilot completed successfully.

```sh
python3 -m pytest -q tests/test_ordered_callgraph.py tests/test_ordered_distances.py tests/test_ordered_phase25.py
python3 -m scripts.ordered_diversity_feasibility --output docs/ordered_diversity_phase25_feasibility.json
python3 -m scripts.ordered_diversity_pilot --output docs/ordered_diversity_phase25_construct_results.json
```

### Specific Phase-3 recommendation

**Do not integrate clustering yet.** First run a separately versioned,
build-aware extraction feasibility study on these same fixed populations.
Resolve includes, typedefs and macro expansion using recorded build context,
retain expansion/source provenance, and distinguish declared direct calls from
macro/cast syntax without inventing indirect targets. Keep that extractor
independent of scientific vulnerability-depth analysis; no SVF change is needed.

In parallel, specify a reference-independent scope estimand for new-source
populations, and decide how identifier-binding relationships and control-transfer
targets should be represented. Validate argument/initializer semantics against
compiler-grounded examples. Then benchmark a certified exact/pruned matcher or
explicit bound-producing alternative against the retained small-graph oracle,
including S extrema and scope ambiguity. Only after adequate complete-case
coverage, stable scope, and bounded alignment uncertainty are demonstrated
should blinded human validation and a separately frozen clustering protocol
be considered.
