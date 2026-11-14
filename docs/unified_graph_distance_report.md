# U and S_node: controlled validation and scientific assessment

Status: **experimental**. This work does not alter accepted Architecture (A),
Strategy (S), historical results, thresholds, journals, sources, or benchmark
images. The controlled comparison is deliberately small; no 495-pair historical
experiment was run.

## Audit of the accepted measurements

Architecture A minimizes the symmetric difference of unit atoms (defined
functions, named external APIs, and directed caller/callee relationships) under
an entry-anchored partial injection. The result is divided by the sum of atom
counts. The exact implementation enumerates every scope-compatible A-optimal
function mapping.

Strategy S is evaluated only over those A-optimal mappings. Its labels retain
syntax kinds, operators, normalized binding information, literals, roles, and
call alignment. A root substitution costs one. Its recurrence charges the full
rooted-tree size for an insertion or deletion. Ordered children use sequence
dynamic programming; declared unordered argument, initializer, and related
groups use exact slot-constrained assignment. An unmatched selected function
costs its whole tree. This full-subtree primitive causes the parent-node
amplification under investigation.

The repository's APTED validation baseline is an ordered, node-level tree edit
over tree-sitter named-node kinds. Its node-splicing semantics can retain
descendants after a parent edit, but the baseline does not reproduce S's rich
labels, A-optimal function alignment, or constrained-unordered groups. The
`apted` package is absent from the available environment, so no new APTED number
is represented as evidence here.

The accepted Clang adapter provides JSON ASTs, direct calls, API identities,
operators, literals, casts, and normalized bindings; it does not provide a CFG.
U therefore consumes textual LLVM IR and calls its basic-block graph a compiler
CFG only when that IR was emitted by Clang. Hand-authored IR in the focused tests
is explicitly a graph test double, not a compiler-backed C result.

Existing production consumers remain `ordered_distances.py`, `ordered_exact.py`,
`ordered_thresholds.py`, `ordered_diversity_threshold_study.py`, and the two
checkpoint reporting scripts. None imports `strategy_node.py`. Historical
provenance contracts and artifacts remain unchanged.

## U representation and objective

Schema `unified-program-graph-v2` contains function, basic-block, and external
API nodes. Edges record ownership, entry, direct calls, and typed CFG relations:
unconditional, true, false, exact switch case, default, normal, and exception.
Block content is a canonical sequence of LLVM operation signatures.

Version 2 retains exact integer and floating constants, argument slots, global
identities, arithmetic/comparison operators, and limited CFG-ordered SSA producer
descriptors, including branch conditions, returns, PHIs, calls, stores, and
selects. It erases SSA spellings and local names. This fixes the observed
v1 collisions for `x + 1` versus `x + 9`, different switch constants, and
`x + y` versus `x + x`, without making ordinary variable renaming observable.
This remains limited structural/data-dependency evidence, not a claim of
semantic equivalence or complete data-flow equivalence.

For graph `G`, define

```text
size(G) = |V_G| + |E_G| + number of local operation atoms.
```

An alignment `m` is a partial one-to-one map between compatible nodes. Matching
entry functions are anchored by identity; helpers can match helpers; a block can
match only when its owner functions match; APIs match APIs. For fixed `m`,

```text
C(m) = C_node(m) + C_edge(m) + C_content(m)

C_node    = unmatched nodes + unequal labels on matched nodes
C_edge    = multiset symmetric difference of directed labeled edges after m
C_content = unit Levenshtein edit cost on matched-function operation streams
            + all operations belonging to unmatched functions

D_U(P,Q) = min_m C(m) / (size(P) + size(Q)).
```

Each node insertion, node deletion, node-label substitution, directed labeled
edge insertion/deletion, and local atom insertion/deletion/substitution costs
one. There are no fitted weights. Function operation streams are ordered by a
deterministic CFG traversal, so textual LLVM block order alone does not alter
content distance. Unreachable blocks are appended deterministically.

Both empty graphs have distance zero; exactly one empty graph has distance one.
A completed exhaustive comparison is symmetric and is in `[0,1]`. No triangle
inequality or identity-of-indiscernibles proof is claimed, so U is not called a
mathematical metric.

The diagnostic result now includes the node map, inserted/deleted/substituted
nodes, retained/inserted/deleted relabeled edges, and an explicit local-operation
edit script. These are edit correspondences, not inferred semantic homologies.

### Extraction and validation changes

The v2 extractor fails explicitly on unresolved indirect calls, `callbr` and
other unsupported exceptional terminators, missing or unsupported terminators,
unclosed functions, empty/missing basic blocks, and unsupported instruction
syntax. It no longer silently emits a call to an empty target. Exact switch-case
values are present in signatures and edge labels. `invoke` has normal and
exception edges when its direct target is resolvable.

Graph validation now rejects duplicate node/edge IDs, unknown owners/endpoints,
invalid ownership/entry direction, cross-function CFG edges, invalid call edge
types, incomplete block ownership, and missing or multiple function entries.
The JSON schema rejects undeclared fields and separately specifies success and
unavailable artifacts.

Remaining representation limitations include unresolved dynamic dispatch,
memory aliasing, full def-use graphs, path feasibility, volatile/atomic semantic
detail, inline assembly, and some exceptional LLVM constructs. Producer slots and
compiler canonicalization may still vary when CFG structure or optimization
changes, although textual block serialization alone is covered by regression.

## Experimental S_node

`strategy_node.py` retains the accepted scope rule, comparison trees, labels,
identifier normalization, call alignment, Architecture objective, and all
scope-compatible A-optimal mappings. It emits a separate
`strategy-node-splicing-constrained-unordered-v1` result and never writes S.

Its primitive costs are:

```text
insert one ordinary node and splice its ordered children: 1
delete one ordinary node and splice its ordered children: 1
substitute one node label:                             1
retain equal labels:                                  0
unmatched selected function:             full node count
```

Ordered forests use an exact dynamic program for those primitives. When two
compatible unordered containers align, immediate children use exact subset
assignment under the existing role/slot labels. Slot labels are removed only
inside the assigned child pair, allowing a wrapper to be inserted within an
argument slot. An unmatched unordered-rooted child costs its full size and may
not splice across the frontier. This is an exact algorithm for this documented
frontier-preserving extension; it is not unrestricted unordered tree edit and is
not labeled APTED.

Limits cover events, exact A-optimum enumeration, unordered width, dynamic-
program work, time, and diagnostic size. Limit exhaustion returns unavailable.
If A optimum enumeration is incomplete, S_node is unavailable. When A has
multiple admissible optima, S_node reports the complete range and correspondence
evidence instead of selecting an undisclosed mapping.

## Controlled three-method comparison

`unified_controlled_comparison.py` compares retained A/S, A with S_node, and U on
eight deliberately small cases. A/S and S_node use synthetic Clang-adapter
structures; U uses hand-authored LLVM IR. Thus the table validates algorithms and
construct sensitivity, not compiler normalization. Raw costs and denominators
from different representations are **not interchangeable**.

| Case | A raw/den | S raw/den | S_node raw/den | U node+edge+content / den |
| --- | ---: | ---: | ---: | ---: |
| Parent insertion, 8 retained descendants | 0/2 | 16/19 | **1/19** | 3+5+5 / 37 |
| Helper extraction | 2/4 | 8/12 | 9/12 | 2+3+4 / 19 |
| Inlining | 2/4 | 8/12 | 9/12 | 2+3+4 / 19 |
| Branch predicate change | 0/2 | 1/16 | 1/16 | 0+0+1 / 48 |
| Constant change | 0/2 | 1/8 | 1/8 | 0+0+1 / 12 |
| Operand dependency change | 0/2 | 1/8 | 1/8 | 0+0+1 / 12 |
| Conditional-to-loop CFG restructuring | 0/2 | 1/16 | 1/16 | 0+2+0 / 48 |
| Dead local-operation padding | 0/2 | 1/9 | 1/9 | 0+0+1 / 13 |

All results in this table completed exact search for their stated models.
Helper extraction and inlining illustrate that S_node is not uniformly smaller:
its constrained unordered frontier prevents a cross-function call wrapper from
being treated as a cheap arbitrary splice. Architecture and U also detect the
function/call decomposition change.

For the parent case, U's operation edit script explicitly retains all eight
`add` operations, inserts `icmp`, conditional `br`, unconditional `br`, and
`phi`, substitutes the return dependency from the last `add` to the new `phi`,
and reports no local deletion. Low edit cost is not being used as a substitute
for this correspondence evidence.

The original parent fixture changes output on some inputs and is retained only
as a shape stress test. It is not evidence of semantics-preserving diversity.
`tests/fixtures/unified_diversity/equivalent_transformations.c` independently
checks output equality over 10,000 inputs plus boundary values for:

- a conditional wrapper whose two branches compute the same result;
- helper extraction;
- dead arithmetic/instruction padding; and
- if/else versus switch branch restructuring.

The fixture passes when compiled and executed with strict C11 flags in the
pinned C Docker image. That image has GCC 12.2 and no Clang, so this is executable
functional evidence only; it is not a compiler-backed U extraction. The checks
establish finite-domain construct sensitivity, not proof of semantic equivalence.

## Scalability and compiler environment

U currently enumerates compatible partial node injections. With `n` compatible
nodes on each side, the state population is
`sum(k=0..n) choose(n,k)^2 k!`. It is 1,441,729 at 8 nodes, 234,662,231 at 10,
53,334,454,417 at 12, and about 1.73e21 at 20. The default two-million-state
limit therefore barely covers eight fully compatible nodes.

A read-only size audit of the existing successful C population found 137
eligible representations, 1--16 functions (mean 7.04), and 143--2,762 accepted
AST events (mean 1,199). A U graph additionally contains blocks and API nodes.
The present exhaustive aligner is therefore not a realistic engine for the
historical population. The limit was not raised, and no historical pair was run.

The most viable exact replacement is a pinned mixed-integer model with binary
node-pair variables, owner/entry compatibility constraints, edge conjunction
variables, and precomputed node-label/content rewards, modeled after the exact A
solver. Solver bounds must be reported when time expires. Branch-and-bound/A*
with admissible label, ownership, and edge lower bounds is another exact option.
Greedy matching, WL-style embeddings, or relaxed assignment can supply an
explicit incumbent upper bound, but must be labeled heuristic and never exact.

Compiler-backed U requires a separate analysis image, not a benchmark-image
change. It must pin an immutable digest; Clang/LLVM version (the current accepted
analysis contract names 21.1.8), binary hash, target triple, headers, C profile,
optimization level, and LLVM emission flags; run without network access; record
source and IR hashes and the full command; and pass deterministic repeat checks.
The existing pinned C and Rust images contain no Clang, so the extractor honestly
returns `clang_unavailable_in_docker`.

## Scientific assessment

1. **Parent amplification:** S_node directly removes the artifact: 16 edits become
   one parent insertion while nine unchanged nodes remain matched. U also avoids
   recreating unchanged local operations, but still charges real CFG structure.
2. **Function decomposition:** A already measures it transparently. S_node retains
   A's alignment and U observes function, ownership, and call changes.
3. **Local distinctions:** S_node retains accepted syntax labels and detects the
   tested branch, constant, operand, and padding changes. U v2 detects the tested
   instruction/CFG forms, but is incomplete as a data-flow model.
4. **Manipulation:** U is intentionally sensitive to dummy blocks and instruction
   padding. Kelpie motivates this adversarial test but does not define U. S_node
   is also sensitive when padding survives the source AST. Neither implies a
   behavior, exploit-independence, or attack-difficulty result.
5. **Compiler stability:** U remains unvalidated across optimization levels,
   targets, and Clang versions. S_node inherits the already pinned source-AST
   extraction contract and has the smaller new validity burden.
6. **Information tradeoff:** A/S preserves two interpretable estimands. U combines
   function, CFG, and local evidence into one denominator; diagnostics do not make
   those scientific constructs interchangeable. S_node loses S's intentional
   full-subtree penalty but preserves labels and unordered role boundaries.
7. **Evidence still required:** compiler-backed equivalent C pairs, exact solver/
   tiny-oracle agreement, optimization/version sensitivity, broader alignment-
   ambiguity tests, adversarial padding, and then a preregistered historical run.
8. **Other languages:** Rust needs pinned rustc/LLVM or MIR CFG extraction with
   monomorphization, trait/dynamic dispatch, panic/unwind, and instance provenance.
   Python needs a pinned bytecode CFG with exception edges, dynamic call policy,
   closures/comprehensions, and opcode-version normalization. Neither is supported.

## Verification and environmental blockers

The focused Python suite contains 28 passing tests covering U extraction,
validation, collision regressions, textual block-order invariance, tiny-oracle
agreement, bounded outcomes, operation correspondence, S_node node splicing,
constrained unordered groups, alignment-sensitive ranges, and the controlled
comparison. Python byte-compilation and Draft 2020-12 schema validation pass.

The equivalent-transformation C fixture passes strict C11 compilation and its
finite-domain output checks at both `-O0` and `-O2` in pinned image
`sha256:02cf23e5c3273ff2969f25010e79346dfbd98ae51499e04996ba802d49f99ad7`.
Full `unittest` discovery reaches all new tests but cannot import the pre-existing
`test_lineage_seed_schedule.py` because `pytest` is not installed in the host
Python environment. No dependency was installed. The absent pinned Clang and
absent `apted` package remain scientific blockers described above.

## Recommendation

The evidence supports **keeping Architecture and replacing only Strategy with
S_node as the preferred experimental direction**, subject to compiler-backed
controlled validation before changing the paper's accepted measurement. S_node
fixes the identified recurrence artifact directly while preserving A's clear
function/call interpretation and accepted alignment policy.

U should continue as a potential replacement research track, not be adopted now.
Its representation is more discriminating than v1 and its parent correspondence
is credible, but exhaustive alignment is unscalable, compiler stability is
untested, dummy padding is an exposed manipulation surface, and a single scalar
does not yet justify discarding the separate A/S constructs. No U threshold or
historical A threshold transfer is scientifically warranted.

