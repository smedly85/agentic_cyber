# Experimental order-aware RQ2: final implementation decision

**QUALIFIED ACCEPT for bounded exploratory C analysis under
`c11-posix2008-v1`.** The existing Architecture and Strategy objectives now run
on compiler-grounded structures for both requested real pairs. This is ready for
broader *exploratory* use with explicit coverage and budget reporting, not adoption
as frozen primary RQ2 metrics or a definitive clustering input. Broader population coverage
and substantive validity have not been established. No alternative metric,
fingerprint, clustering threshold or production change was introduced.

This document records the implementation sprint's two-pair evidence. The later
[threshold-sensitivity study](ordered_diversity_threshold_decision.md) reports the
complete audited populations and the independent review's **QUALIFIED ACCEPT**:
all 66 comparisons rerun, saved statistics verified, all 21 mkdir A pairs checked
against the exhaustive oracle, and no CRITICAL defects found. Acceptance is for
exploratory reporting, not a frozen primary methodology or calibrated families.

## Actual results

Both extractions in each population succeeded. Fresh ASTs matched the Phase-2.7
ASTs after dump-local ID normalization; compiler, source and header hashes were
verified against that audit. Source bytes remained unchanged. Compiler: Ubuntu
Clang 21.1.8; optimizer: SciPy 1.18.0 / its bundled HiGHS MILP implementation.
Historical compiler/SDK reproduction is not claimed.

| Population and pair | Functions | Exact A | S over all admissible optimal alignments | Admissible alignments | Comparison time |
| --- | --- | ---: | --- | ---: | ---: |
| mkdir/002: lineage-003 vs lineage-009 | 7 vs 6 | 12/82 = **0.1463414634** | 1668/2100 = **0.7942857143**, singleton range | 1 | 0.851 s |
| grep/004: lineage-001 vs lineage-002 | 11 vs 16 | 43/185 = **0.2324324324** | **[0.5873552124, 0.5989382239]** | 4 | 1.024 s |

Grep's S costs are 2434, 2458, 2460 and 2482, each divided by 4144. Its scalar
`distance` is deliberately **null**: the nonzero range is the result, not the
optimistic minimum. Neither pair's experimental S is marked primary-eligible.
No A/S measurement was unavailable in these two runs.

Extraction/adapter/equality-check times were 1.103/0.580 s for mkdir and
0.828/0.952 s for grep. Architecture optimization plus admissible enumeration
took 0.793/0.178 s; subtree comparisons took 0.058/0.845 s. These are observed
local timings, not performance guarantees; file/environment verification and
the additional oracle run are outside the comparison times.

The unchanged exhaustive matcher independently checked mkdir in 0.115 s: 4,051
partial mappings, **six architecture-optimal mappings, only one scope-compatible**,
and exactly the same A. Grep's exhaustive search would contain 45,481,765,921
partial mappings; it was not run or given an increased limit. The MILP proved
the optimum and exhausted its four compatible mappings instead. Incompatible
architecture-optimal mappings also exist for grep; their total is not enumerated.
They are flagged and never used to lower or enlarge the admissible S range.

## Definitions retained

Architecture means **function decomposition and directed call/API connectivity**.
The independent population audit found approximately **61–86% of its atoms are
external API nodes or edges**. This describes atom composition, not the fraction
of a pairwise distance caused by external APIs; A is not purely a measure of
internal organization.

For each graph, let its atoms be one atom per defined function or named external
API node, and one per distinct directed caller/callee edge. Repeated call sites
do not duplicate Architecture edges. Under an entry-anchored partial injection
`m` between internal functions, let `X` and `Y_m` be the relabeled atom sets:

```text
D_A = min_m |X symmetric-difference Y_m| / (|X| + |Y_m|).
```

Internal helper names, source coordinates and call order do not enter this
objective. External API identities remain meaningful. Isolated and unmatched
functions remain node atoms. The zero-size case is defined as zero.

The new optimizer maximizes the equivalent intersection size. Binary `x_ab`
variables encode partial-injection assignments with row/column sums at most one
and fixed entry anchors. Matched internal-node and common external-edge atoms
contribute linear rewards. Matched internal-edge atoms use binary conjunction
variables bounded by the corresponding two assignments. Shared external nodes
are constant. Every reward is an existing unit atom, **not a new feature weight**.
The optimum is checked against actual relabeled atom sets. The MILP uses zero
relative gap; its ordinary numerical tolerances still apply. This is an exact
formulation of the same combinatorial objective, not a polynomial-time promise.

Let `M*` be the architecture-optimal mappings whose matched functions have
compatible Strategy scope. For `m` in `M*`, Strategy retains the existing
ordered rooted-subtree edit recurrence: unit root-label substitution; deletion
or insertion costs the entire subtree size; ordered children use sequence DP;
explicit unordered groups use minimum assignment with argument/initializer slot
constraints. For selected function-body trees:

```text
S_m = (sum of matched-tree edit costs + sizes of unmatched selected trees)
      / (sum of selected tree sizes in both candidates).
S_result = [min_{m in M*} S_m, max_{m in M*} S_m].
```

The original `_tree`, `_tree_distance` and `_size` implementations are reused.
This is rooted-subtree editing, not unrestricted node-splicing tree edit distance.
Empty selected structures use zero. If `M*` is empty, Strategy is unavailable.
Distances are bounded in [0,1] and symmetric under complete comparisons. No
triangle-inequality claim is made. A self-comparison can have minimum zero but a
nonzero maximum across symmetric function alignments; the range is not a metric.

## Clang representation and scope

The adapter preserves candidate-defined functions and direct/internal/declared
external call sites. It retains AST statement sequences, control nesting,
operators, literals, transfers and binding identities. Parameter/local bindings
use lexical declaration slots; uses refer back to those slots, preserving
shadowing and repeated-reference distinctions under consistent renaming.
Declaration-order normalization can nevertheless increase S when an unused
declaration is inserted: subsequent binding slots may shift, changing reference
labels as well as adding the declaration subtree. This is a construct-validity
limitation, not evidence of changed behavior.
Internal function references use the same alignment labels as internal calls;
callback references do not fabricate call edges. Explicit and implicit cast kinds
remain distinct. Header-defined function bodies are excluded from candidate scope.

Argument slots remain labeled within unordered evaluation groups. Binary
operands retain their operand roles; short-circuit and comma ordering remain
distinct. Direct callee syntax is represented by the call label, consistent with
the existing body-tree policy. Coordinates, macro spelling/expansion ranges and
compiler type metadata remain audit information, not arbitrary distance features.
The verified complete AST and Phase-2.7 provenance remain available for inspection.

Scope uses the production default exclusion regex **independently on each
candidate**, always including `main` and configured forced names. The CLI exposes
the regex and repeatable `--strategy-include-function`; these runs used the default
regex and no forced includes. No candidate acts as a reference. This is not the
previously proposed all-functions estimand.

| Candidate | Excluded names |
| --- | --- |
| mkdir/003 | parse_octal_mode, parse_symbolic_clause, parse_symbolic_mode, parse_mode |
| mkdir/009 | parse_octal_mode, parse_symbolic_mode, parse_mode |
| grep/001 | usage |
| grep/002 | usage_exit |

**Renaming across an exclusion boundary can change S.** This inherited name-based
policy is explicit and tested, not claimed rename-invariant. A is unaffected.
The mkdir/002 mode-parsing helpers above are excluded by this inherited regex,
whereas parser code inlined into `main` remains included. Scope compatibility and
helper naming therefore affect Strategy coverage. In the later grep population
audit, 12/13 scope-incompatible pairs involve usage-helper versus
no-excluded-helper differences; absence of an excluded helper does not establish
absence of parser/usage code.
Architecture is optimized without scope restrictions; only its optimal mappings
with matching inclusion decisions enter S. Unmatched included functions incur
full tree costs. Both compatible ambiguity and incompatible correspondence are
reported. For example, mkdir's compatible edit mapping pairs `is_octal_digit`
with `apply_clause`; it is an edit correspondence, not evidence of semantic homology.

## Validation, budgets and remaining coverage

**126 tests passed**: all 102 existing tests plus 24 integration tests. The final
model-size guard was additionally checked by rerunning all 24 integration tests.
Tests cover identical structures, helper/local renaming, ordering, repetitions,
decomposition, branches, argument positions, changed bindings, implicit nodes,
callback references, scope boundaries/forced inclusion, ambiguous S ranges,
failure rejection and budgets. Eight small graph cases match the exhaustive
objective **and full optimum sets**, including cycles/self-edges. A compiler-based
small case also agrees with the existing Strategy recurrence. These are construct
sensitivity checks, not proofs of functional equivalence.

Defaults: 45 s for optimization/enumeration, 128 admissible optima, 100,000 model
variables (conservative preconstruction bound), 45 s/2,000,000 work units for S,
10,000 audited candidate nodes, unordered width 10. The exhaustive oracle's
20,000-mapping limit is unchanged. If optimization stops early, solver dual and
feasible-incumbent objectives provide explicit A bounds where available; otherwise
A is unavailable. A remains exact if only optimum enumeration fails, while S is
unavailable rather than an incomplete extrema estimate. Resource/dependency/
extraction failures never become zero distances.

Coverage limitations: this sprint validates only four sources in two separate C
populations; the linked threshold study reports subsequent population coverage.
Compiler/header changes invalidate the saved profile checks.
Unresolved indirect calls block comparisons; declared library callbacks are not
semantic may-call edges. Active preprocessing only is measured. Generic selection,
inline assembly, atomic builtins, and initializer `array_filler` forms currently
fail explicitly because their extra child/selection semantics are not decoded;
none occurs in the selected candidate bodies. Field names and external globals
retain spelling; global/local declaration reordering is not a promised invariant.
Type metadata is audited rather than a complete type-sensitive Strategy metric.
The representation is richer than call ordering but does not capture complete
computational behavior, dataflow or path feasibility. Large or highly symmetric
programs may still exhaust exact optimization/enumeration budgets.

The populations are success-conditioned and use a single model/configuration.
Pairs sharing candidates are statistically dependent, not independent replicates.
Results do not support cross-utility causal or inferential comparisons, and
structural diversity does not establish exploit independence.

The later Architecture threshold study finds six implementations plus one
singleton for mkdir at 0.30, with that partition approximately on
**[0.17671253, 0.34181367)**. Grep's three-family partition exists only approximately
on **[0.29814588, 0.30127843)** (about [0.29815, 0.30128)). Continuous merge-height
intervals expose sensitivity hidden by grid-level counts. The legacy 0.30 is a
comparison reference, not an independently calibrated threshold.

## Deliverables and reproduction

Added `scripts/analysis/clang_ordered.py`, `scripts/analysis/ordered_exact.py`,
`scripts/ordered_diversity_final.py`, `tests/test_ordered_clang_integration.py`,
this decision document and
[`ordered_diversity_final_results.json`](ordered_diversity_final_results.json).
The JSON records commands, source/profile provenance, implementation hashes,
scope, integer costs, all evaluated compatible mappings and timings.

Raw source SHA-256 values identify the actual extracted bytes; LF-normalized
hashes used for manifest verification are separate identities after CRLF-to-LF
conversion. Checkout line-ending conversion can change raw hashes and offsets.
Report byte identity is checkout-dependent; paths and fresh-run timings can also
differ. The later study's byte-identical report regeneration was a same-checkout
check using saved measurements, not a guarantee across checkouts or fresh runs.

```sh
python3 -m scripts.ordered_diversity_final
python3 -m pytest -q tests/test_ordered_clang_integration.py tests/test_ordered_clang_repro.py tests/test_ordered_clang_probe.py tests/test_ordered_callgraph.py tests/test_ordered_distances.py tests/test_ordered_phase25.py
```

Requires the Phase-2.7 recorded Clang/header environment plus NumPy/SciPy for the
MILP backend; missing optimizer dependencies remain unavailable, with no fallback
scalar. The exact matcher and primary metrics are unchanged. No full experiments,
LLMs, lineage work, semantic depth changes, clustering, commits or pushes occurred.
This sprint ends with working real comparisons and the QUALIFIED ACCEPT above;
it does not initiate another methodology phase.
