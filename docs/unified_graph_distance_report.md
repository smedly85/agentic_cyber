# Experimental unified graph distance: specification and bounded validation

Status: **prototype accepted for graph-level regression only; retain A/S pending
compiler-backed population evidence.** This work does not change the accepted
Architecture or Strategy implementation, thresholds, journals, candidate sources,
or benchmark execution.

## Audit of the retained measurements

Architecture A minimizes the symmetric difference of unit atoms (defined-function
nodes, named external-API nodes, and distinct directed caller/callee edges) under
an entry-anchored partial injection. It divides by the sum of atom counts. The
MILP maximizes the equivalent common-atom objective, rechecks the integer result,
and enumerates all scope-compatible A-optimal function mappings.

Strategy S is then evaluated over those mappings. A root-label substitution costs
one. Insertion or deletion costs the size of the entire rooted subtree. Ordered
children use sequence dynamic programming; explicitly unordered groups use
slot-constrained assignment. Unmatched selected functions cost their full trees.
The reported result is the range over admissible A optima, not necessarily a
scalar. This recurrence is the source of the parent-node amplification.

`diversity_validation.apted_distance` uses ordinary node-level APTED and therefore
has the right edit semantics to preserve descendants when a parent is inserted.
The package is not installed in the available Python environment, so no fresh
APTED result is reported here.

The retained Clang adapter provides JSON AST structure, direct calls, API names,
operators, literals, casts, and normalized local bindings. It has no compiler CFG
or basic blocks. The new extractor consequently consumes textual LLVM IR and uses
LLVM basic blocks and terminators as the compiler CFG. It is not an AST-derived
CFG approximation.

All ordered test files named by the historical documentation are absent from this
checkout. The only pre-existing root test is `test_lineage_seed_schedule.py`.
The active reporting consumers remain the final and threshold runners, the
final-checkpoint and longitudinal reporters, and the legacy experiment analyzer's
construct-validation imports. Several historical report scripts rewrite outputs
even in reporting modes and were not run.

The immutable Phase 2.5→2.7 evidence chain, compiler/header hashes, raw and
LF-normalized source identities, pairwise artifacts, and measurement journal were
left unchanged.

## Representation

Schema `unified-program-graph-v1` contains three node kinds:

- function nodes, with entry versus helper labels;
- LLVM basic-block nodes, owned by functions and labeled by terminator category;
- external API nodes, labeled by exact API identity.

Directed labeled edges are `contains`, `entry`, typed CFG edges (`true`, `false`,
`case`, `default`, `normal`, `exception`, and unconditional), and direct call
edges from blocks to functions or APIs. Each block stores an ordered sequence of
canonical LLVM-instruction signatures. Signatures erase SSA/local names but retain
operations, comparison predicates, integer-operation flags, direct external API
identity, argument index/type/value category, PHI arity, and branch category.

The artifact records raw source and LLVM-IR SHA-256 identities, compiler version
and binary hash, command, profile, extractor version, and explicit limitations.
The source-to-IR CLI refuses non-C inputs and refuses to compile outside Docker.
Unsupported extraction is `unavailable`, never an empty graph.

## Mathematical objective

For graph `G`, define

```text
size(G) = |V_G| + |E_G| + number of local instruction atoms.
```

Let `m` be a partial one-to-one correspondence between compatible nodes. Function
entry points of the same identity are anchored when present on both sides; helper
functions may match any helper. A block can match only a block whose owner
functions are matched. API nodes can match other API nodes, with differing API
identity charged as a label substitution.

For a fixed `m`, the edit cost is

```text
C(m) = C_node(m) + C_edge(m) + C_content(m)
C_node = unmatched nodes + unequal labels on matched nodes
C_edge = multiset symmetric difference of directed labeled edges after relabeling by m
```

`C_content` is unit-cost Levenshtein distance over the ordered local-atom sequence
of each matched function, plus all local atoms in unmatched functions. Content is
compared at function scope so inserting a parent that splits a basic block does
not force unchanged instructions to be deleted and recreated. Block ownership,
placement, and control relationships remain observable through block nodes and
edges.

Every primitive costs exactly one: node insertion/deletion/label substitution,
directed labeled edge insertion/deletion, and local-atom insertion/deletion/
substitution. There are no fitted feature weights.

```text
D_U(P,Q) = min_m C(m) / (size(P) + size(Q)).
```

Both-empty representations have distance zero. One empty and one nonempty graph
have distance one. A completed exact comparison is symmetric and lies in `[0,1]`.
No triangle-inequality or identity-of-indiscernibles proof is claimed, so this is
called a distance/objective rather than a mathematical metric.

The implementation uses deterministic constrained exhaustive search, greedy
incumbent ordering, a state limit, node limit, and wall-clock limit. Completion is
reported as exact. Exhaustion returns a `bounded` result with a certified (currently
trivial) lower bound and incumbent upper bound; `distance` remains null. A separate
Cartesian-product oracle checks tiny graphs.

## Parent-node regression and construct sensitivity

On an abstract eight-descendant tree, the retained rooted-subtree recurrence gives
sizes 9 and 10 and cost **16/19 = 0.8421** for inserting one parent. The descendants
are involved in the charged delete/insert alternatives.

On the attributed-graph regression with eight unchanged arithmetic operations and
an inserted conditional, U is **12/37 = 0.3243**:

| Diagnostic | Unit cost |
| --- | ---: |
| Node edits | 3 |
| Directed edge edits | 5 |
| Local-content edits | 4 |
| Total | 12 |

The local cost is exactly the four introduced IR atoms and does not grow with the
eight unchanged operations. The new blocks and CFG relationships remain visible.
The reverse removal has the same exact distance. Tests also show zero for identical
and SSA/local renaming cases, and nonzero changes for comparison predicates,
arithmetic operations, external APIs, helper extraction/inlining, loop edges,
instruction order/content, and unreachable padding. These are hand-authored LLVM
IR test doubles for algorithm validation, not compiler-backed C construct results
or evidence of semantic equivalence.

The referenced Kelpie paper motivates testing both CFG and instruction features:
it inserts opaque-predicate dummy blocks and dead instructions to mimic target
binaries. It does **not** define this objective or algorithm. The same attack shows
that U can be manipulated: padding deliberately changes exactly the block, edge,
and local atoms U observes. U measures representation difference, not behavior,
exploit independence, or attack difficulty. See the [Kelpie paper](https://arxiv.org/pdf/2605.18231).

## Historical comparison coverage

The read-only journal contains 140 candidates in 18 populations and 495 pairs:
480 exact A outcomes and 363 available S outcomes. Of 140 AST extractions, 137 are
comparison-eligible. None has a saved LLVM IR/CFG artifact. Docker Desktop was
started successfully, but inspection of both immutable local C and Rust images
found no Clang binary; the pinned C image contains GCC 12.2. Substituting GCC or
downloading an unpinned toolchain would violate the extraction contract. The
extractor returns `clang_unavailable_in_docker`. Therefore fresh U coverage is
**0/495**.

No U means, distributions, rank correlations, disagreements, or pair-ranking
changes are reported. Reporting numerical comparisons from ASTs as if they were
compiler CFGs would violate the representation contract. Historical A/S files and
the journal were not modified. The old 0.30 Architecture threshold is not applied
to U.

## Scientific assessment

1. **Parent amplification:** graph-level evidence is positive. Unchanged local
   atoms remain aligned across a block split; only the parent-related content and
   graph structure are charged. Compiler-backed C validation remains outstanding.
2. **Function decomposition:** retained through function nodes, ownership, entry,
   and direct call edges. Helper extraction/inlining is detected.
3. **Local strategy:** operations, predicates, API identities, argument roles, and
   order are detected at LLVM-IR granularity. Data flow and path feasibility are
   not modeled.
4. **Manipulability:** dummy branches, unreachable blocks, and dead-instruction
   padding change U. Kelpie makes this an important validity threat, not a corner
   case.
5. **Compiler stability:** untested here. O0/O2, Clang versions, target triples,
   lowering, inlining, and dead-code elimination can change every component.
6. **Information lost versus A/S:** source-level nesting, declaration/binding
   details, implicit casts, and A's easily interpretable pure call-graph objective
   are less separable in one scalar. Diagnostic components help but do not restore
   two independently interpretable estimands.
7. **Replacement evidence needed:** Docker-pinned extraction of all controlled C
   pairs; exact/oracle agreement; broad historical coverage; correlation and
   disagreement analysis; compiler/optimization sensitivity; adversarial padding
   analysis; and preregistered interpretation/threshold validation.
8. **Cross-language consistency:** Rust needs a pinned rustc/LLVM or MIR-to-CFG
   extractor with monomorphization, trait/dynamic dispatch, panic/unwind, and
   source-to-instance provenance. Python needs a pinned interpreter bytecode CFG
   with exception edges, dynamic call-resolution policy, closures/comprehensions,
   and version-specific opcode normalization. Neither is implemented or claimed.

Replacing only S with a node-splicing tree edit (such as APTED with richer labels)
is lower risk: it directly fixes the known recurrence artifact while preserving
A's interpretation and existing function alignment. U may ultimately capture
richer CFG and local structure, but combining everything into one scalar is not
automatically scientifically superior.

## Recommendation and blockers

**Retain A/S pending further evidence**, while prioritizing an experiment that
retains A and replaces only S's rooted-subtree recurrence with labeled node-level
tree edit. Do not adopt U or transfer any clustering threshold yet.

Remaining blockers are the absent pinned Clang CFG environment,
missing APTED dependency, absent historical LLVM IR, zero historical U coverage,
no compiler-setting sensitivity run, and the exponential exact alignment search
(larger cases will be bounded/unavailable). These are measurement limitations, not
silent approximations.

