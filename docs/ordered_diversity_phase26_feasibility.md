# Phase 2.6: compiler-grounded representation feasibility

## Finding

Clang JSON AST supplies substantially richer structural evidence than the
syntax-only prototype, including header-declared callees, expanded macros,
typedef-aware casts, operators and declaration bindings. **Two of four selected
historically successful candidates extracted successfully using their recorded
flags in the available local environment.** This establishes representation
feasibility, not adequate population coverage. It does not yet justify distances
or clustering. Historical build-environment recovery remains necessary.

This is a bounded C-only investigation. No candidate source was edited, no binary
was built, and no functional tests, lineage generation, LLM work, SVF rebuild,
full experiment, fingerprint or distance computation was performed. The existing
production metrics and strategy scope are unchanged.

## Selection, build context and reproducibility

The four candidates come from the successful populations in
[the Phase-2.5 audit](ordered_diversity_phase25_feasibility.json). The two
utility/checkpoint populations remain separate. Selection is purposeful, not a
coverage estimate for the entire population: mkdir/003 and mkdir/009 expose
typedef/header differences; grep/001 and grep/002 contrast source feature-test
configuration. The latter failed the earlier syntax-only preprocessing policy.

The read-only runner is
[`scripts/ordered_diversity_clang_probe.py`](../scripts/ordered_diversity_clang_probe.py).
It imports and calls the existing, unmodified `parse_clang_ast()` from
`scripts/analyze_experiment.py`. That action runs Clang with `-fsyntax-only` and
`-Xclang -ast-dump=json`, writes the raw dump, and reports compiler or JSON errors.
Its existing count-vector output is not used as structural evidence. In
particular, the probe does not reuse the production source-attribution heuristic
that can accept nodes based on line numbers. It tracks explicit top-level
declaration filename context and selects definitions attributed to the candidate.
This bounded attribution procedure still needs broader macro/include tests before
becoming a general extractor.

Each selected `experiment.json` records this command, with the appropriate utility:

```text
mkdir -p build && cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_<utility>/new_<utility>.c -o build/new_<utility>
```

The probe preserves every recorded compiler flag, including `-Werror`. It replaces
`cc` with local Clang, omits the binary output and shell directory-creation step,
and uses the absolute path to the unchanged candidate snapshot. The production
action supplies `-std=c11` once. No extra include directories, feature-test macros,
header insertion, warning suppression, recovery flags or guessed sysroot are
added. The runner deliberately refuses build commands outside this audited shape.

Compiler used:

```text
Ubuntu clang version 21.1.8 (6ubuntu1)
Target: x86_64-pc-linux-gnu
Thread model: posix
InstalledDir: /usr/lib/llvm-21/bin
```

Execution was under Linux/WSL2. The recorded repository path was
`/Users/sonjabrown/agentic_cyber`; recorded commits were
`95141162f8b622e45123b53a0ec8830fbecfb7a3` (mkdir) and
`150e0aa98d7e32e02c7463954615f9485551bfe1` (grep). Those records do not attest the
original `cc` version, target, SDK/sysroot or header image. **Recorded flags plus
local Clang are not a certified reproduction of that historical environment.**
Compiler-specific diagnostics under `-Werror` can also affect portability.

[The machine-readable evidence](ordered_diversity_phase26_feasibility.json)
records exact candidate and experiment paths, commands, diagnostics, compiler
version, local include-search output, include-related environment variables,
source/experiment/audit/analyzer/runner hashes and source-unchanged checks. Source
bytes were checked against the Phase-2.5 LF-normalized hashes and separately
hashed without normalization. All four source-unchanged checks passed. Raw ASTs
are local ignored artifacts under `build/ordered-diversity-phase26/`; their
locations and hashes are in the evidence report. Compiler-local pointer IDs and
host paths in this audit are provenance, not proposed diversity features. Raw
dumps and this evidence are not promised byte-identical across compiler runs.
The header image is not pinned by this probe; that is a reproducibility gap.

```sh
python3 -m scripts.ordered_diversity_clang_probe
python3 -m pytest -q tests/test_ordered_clang_probe.py tests/test_ordered_callgraph.py tests/test_ordered_distances.py tests/test_ordered_phase25.py
```

Validation completed: **92 tests passed in 18.66 seconds**, comprising eight
probe checks and the 84 existing experimental regression tests. Probe checks
cover recorded-flag preservation/refusal, callee-only resolution, source filename
attribution, separate macro provenance, control paths, argument slots,
redeclarations and unresolved indirect calls. These validate the evidence
plumbing; they do not establish fingerprint accuracy or behavioral equivalence.

## Extraction coverage and failures

Counts below are for candidate-defined function bodies, including implicit and
macro-expanded AST nodes. They are not Phase-2.5 event counts. A dash means
unavailable, never an empty valid structure or zero unresolved calls.

| Population | Lineage | Clang status | Functions | Body AST nodes | Calls: internal / declared external / unresolved |
| --- | --- | --- | ---: | ---: | --- |
| mkdir/002 | 003 | Failed | — | — | — |
| mkdir/002 | 009 | Success | 6 | 1,567 | 5 / 38 / 0 |
| grep/004 | 001 | Failed | — | — | — |
| grep/004 | 002 | Success | 16 | 2,161 | 27 / 64 / 0 |

* **mkdir/003:** two uses of undeclared `mode_t` at source lines 160 and 270,
  plus an unused `final_mode` parameter diagnostic promoted to an error. The
  source includes `sys/stat.h` but lacks `sys/types.h`; the local strict-C11
  headers do not expose the expected typedef in this context. The report retains
  all three diagnostics without attempting a repair.
* **grep/001:** undeclared `lstat` at line 168 under the recorded C11 flags and
  local headers. No recovery feature-test macro was invented. In contrast,
  grep/002 already defines `_POSIX_C_SOURCE 200809L` in its source.

Both failed invocations produced partial JSON output. Neither output was
summarized or admitted as a valid measurement. Historical functional success is
not revoked by these local extraction failures.

Coverage is **1/2 in each selected population, 2/4 overall**. The overall fraction
describes this extraction probe only; the utilities are not pooled for diversity.
There is no within-population pair with two successful extractions among these
four selections. A/S distances were deliberately not computed; the single
selected off-diagonal pair in each population lacks an extraction prerequisite.
Do not extrapolate availability to all 21 mkdir or 45 grep Phase-2.5 pairs.

## What survives in the successful ASTs

| Information | Observed evidence | Qualification |
| --- | --- | --- |
| Definitions and direct relationships | 6 / 16 candidate definitions; callee `DeclRefExpr` references resolve `FunctionDecl` IDs, including redeclaration chains | Direct calls only; no points-to or may-call analysis |
| Header API identity | 8 / 11 `fprintf` calls reference declarations attributed to `/usr/include/stdio.h` | External declaration does not supply an implementation body |
| Typedef and cast distinction | mkdir/009 has 10 `CStyleCastExpr` nodes typed `mode_t`, with underlying `unsigned int` and alias declaration IDs | No fabricated `mode_t` call; grep/002 has no such casts |
| Macro expansion | `S_ISDIR` yields comparisons/bitwise operations and separate spelling/expansion ranges | 14 / 56 associated expanded nodes, not invocation counts; zero `S_ISDIR` calls |
| Source statement order | `CompoundStmt.inner` preserves statement slots; nested AST paths are retained | Lexical order does not imply every child executes or executes in that order |
| Control nesting | If/for/while/conditional-expression structure; calls have up to 4 / 8 control ancestors | Not path feasibility, a CFG, or call-graph depth |
| Argument positions | `CallExpr` operands distinguish callee and indexed arguments | Argument indices do not order C argument evaluation |
| Operators and call-free work | `opcode`, literals, assignments, declarations and typed expression nodes survive | Future normalization must decide which implicit wrappers/types/literals to retain |
| Declaration/reference relationships | All 328 / 477 `DeclRefExpr` references have declaration IDs found in the dump | IDs are local to this dump, not cross-candidate identities |
| Control transfers | Return/break/continue nodes survive: 24/3/10 and 29/2/8 respectively | No observed goto-based validation here; destination relationships require explicit handling |

For example, mkdir/009's `S_ISDIR` expansion has a spelling location in
`/usr/include/x86_64-linux-gnu/sys/stat.h` and expansion at candidate line 174.
The AST includes `==` and `&` operations rather than a spurious call to the macro.
`(mode_t)val` is a cast with alias information, and a `fprintf` argument referring
to `stderr` carries its own macro spelling/expansion provenance. The JSON report
retains these raw ranges separately, plus original-source excerpts or expansion
tokens. Clang can omit repeated filenames; the probe does not invent missing
filenames in individual raw ranges. Macro spans may identify only the invocation
token, not a complete original expression. This is not a complete nested macro
expansion trace.

Thus the previously problematic `fprintf`, `S_ISDIR` and `mode_t` are correctly
distinguished in the successful compiler context. Active preprocessing is handled
by Clang; inactive branches and unused macro definitions are absent from the
expanded AST. Header/compiler/configuration changes can change this representation
without an intentional candidate strategy change.

The successful sources supply evidence for ordered statements, branches, loops,
argument slots, operators and bindings. They do not validate every C construct.
Initializer lists require a separate check: syntactic and semantic initializer
forms, designated positions, implicit fill and evaluation sequencing cannot be
inferred merely from child indices. Likewise `ForStmt` can contain empty operand
slots; semantic child roles need kind-specific decoding. Calls through pointers
must remain unresolved. Zero unresolved calls in these two sources is not a
general guarantee. This extractor would remain separate from the scientific
Clang/LLVM/SVF vulnerability-depth may-call backend.

## Simpler representations: feasibility, not implementation

### Architecture recommendation

Use a directed, unweighted, deduplicated call graph with one node per
candidate-defined function, a distinguished entry point, and labeled external
API nodes. Retain isolated/unreachable functions and report entry reachability,
components and strongly connected components. Multiple identical caller/callee
occurrences do not create extra topology edges. Preserve unresolved-call coverage
separately without guessing target nodes.

A feasible fingerprint is iterative directed neighborhood refinement: initialize
internal nodes with generic/entry labels and external nodes with meaningful API
identities, then canonically encode each node's prior color and the multisets of
incoming/outgoing neighbor colors. Collect color histograms by refinement round
and explicit connectivity summaries. Function declaration order, helper spelling,
coordinates and call-site ordering do not enter this representation. No matching
of helpers across candidates is required. The iteration radius and aggregation
policy still need validation; no numerical feature weights are selected here.

This preserves local topology, decomposition size, external connectivity and the
explicit global summaries. It loses exact function correspondence and can merge
non-isomorphic graphs whose refinement colors and summaries coincide. More rounds
or component counts do not turn refinement into an isomorphism certificate.
Canonical encodings should also distinguish structural indistinguishability from
ordinary hash collisions. A graph fingerprint is evidence of structural
similarity, not a proof of identity or behavioral equivalence.

### Strategy recommendation

Use **all candidate-defined function bodies**. Within each body, retain a typed,
role-labeled AST with operator information, declaration bindings, explicit casts,
argument/initializer positions, ordered statement slots, control constructs and
transfer nodes. Audit coordinates and macro provenance stay outside comparison
features. Prefer the compiler-expanded active-code tree for the minimal prototype,
under a controlled compiler/header configuration; keep original spelling and
expansion metadata for interpretation.

A candidate can be represented independently by a multiset of normalized
function-body descriptors: bounded structural paths, ordered local statement
sequences and rooted control-context/subtree descriptors. Preserve multiplicity.
Function aggregation is order-invariant, while sequences *inside* functions
remain ordered. Label argument roles independently of sequencing: swapping
`first()` and `second()` between argument slots changes data association without
claiming which executes first. Model guaranteed sequencing only for supported C
constructs; annotate unsequenced/conditional contexts explicitly.

Use external API labels directly. Internal calls could carry Architecture
neighborhood colors, avoiding arbitrary helper names and exhaustive alignment.
Color-equivalent helpers remain indistinguishable; this limitation must be tested
and reported. Bounded paths/windows also lose some distant ordering and whole-tree
relationships. Bag aggregation can dilute small changes, and moving code between
functions changes decomposition and potentially both A and S. These are not
guaranteed independent axes. No full-tree edit distance or new pairwise score is
implemented here.

For ordinary renaming, map declaration IDs to deterministic lexical binding
tokens: parameters by position, locals by structural declaration traversal within
their scope, and each use to its defining token. Preserve shadowing and repeated
uses, so `x+x` differs from `x+y` while consistent alpha-renaming does not. Do not
use raw Clang IDs or helper names as features. This approach is feasible because
the observed references resolve to declarations, but it is not implemented in
this probe. Globals, struct members, typedef identities, labels, redeclarations,
implicit declarations and macro-generated bindings require separate policies.
Reordering declarations can alter a traversal-based canonicalization even when
behavior is unchanged; validate that limitation rather than assuming arbitrary
refactor invariance.

### Comparison with exhaustive alignment

| Approach | Cost and uncertainty | Preserves / loses |
| --- | --- | --- |
| Existing partial-injection graph alignment | Enumerates up to `sum(k=0..min(n,m)) binom(n,k) binom(m,k) k!` helper mappings before constraints; hard limits remain explicit | Exact optimum under its defined cost only when completed; tied mappings can give different S values |
| Directed neighborhood fingerprint | Per candidate, approximately `O(h(V+E))` refinement work plus canonical multiset sorting (at most `O(h E log V)` for simple graphs) | Scalable, deterministic given policy; no helper correspondence or isomorphism guarantee |
| Bounded AST paths/local sequences | Approximately linear in AST size for fixed path/window bounds, plus descriptor aggregation/sorting | Retains local order/control/bindings; loses some long-range structure; no execution-equivalence guarantee |

The successful ASTs have 1,567 and 2,161 body nodes, with 6 and 16 functions.
Those are modest independent extraction/descriptor inputs, while exhaustive
helper matching scales combinatorially. These complexity estimates are analytical;
no fingerprint implementation, accuracy benchmark or performance timing was run.
Retain the existing small-graph exact matcher as a later validation oracle, not
as a prerequisite for fingerprint extraction. Its edit optimum is not a universal
ground truth for a different representation. Fingerprint comparison also avoids
the old alignment interval by changing the estimand, not by resolving uncertain
function homology. Mathematical metric properties remain unspecified until a
distance is actually defined.

## Reference-independent strategy scope

All-functions S is a **different estimand** from the existing parser/usage-excluded
strategy metric: it measures organization of the complete candidate program,
including argument parsing and usage handling. It needs neither a baseline nor
a selected reference, so empty-baseline new-source populations no longer require
unmatched-helper scope transfer. Entry identity remains explicit. This is an
experimental proposal only; the production policy is unchanged.

Parser/usage contribution can be a separate descriptive diagnostic. The current
name-regex hint identifies `parse_octal_mode`, `parse_symbolic_mode`, `parse_mode`
in mkdir/009 (210 of 1,567 nodes), and `usage_exit` in grep/002 (13 of 2,161).
These hints exclude nothing. They are name-sensitive and miss parser code mixed
into `main`; they cannot be promoted to a rename-invariant scope classifier.
Reference independence alone does not cure that problem. A future diagnostic
could use a fixed, independently specified annotation protocol or explicit API
evidence, report mixed/unknown roles and its coverage, and assess rename
sensitivity. Do not silently assign a semantic role based on a chosen candidate
reference. Do not subtract these hints from the primary all-functions descriptor.

## Next bounded steps

1. Recover or explicitly standardize the compiler/target/header environment using
   recorded evidence. Retest the two failures without guessed flags or source
   repairs. Missing historical settings remain missing. Only then expand the
   read-only coverage audit separately within each existing population.
2. Implement a small, versioned experimental AST normalization layer: source-body
   attribution, direct/external/unresolved calls, declaration binding tokens,
   kind-specific child roles and sequencing, plus separate source/macro audit
   provenance. Test argument swaps, initializer designators, repeated references,
   renaming/shadowing, transfers and macro/header configuration sensitivity.
3. Prototype the independently computed Architecture fingerprint and all-functions
   Strategy descriptors on controlled fixtures. Measure false equalities and
   sensitivities, determinism, compiler portability and runtime against the small
   exact-alignment oracle where applicable. Keep parser diagnostics separate.
4. After representation and coverage validation, specify candidate comparison and
   missingness policies. Only a subsequent separately authorized phase should
   evaluate distances, human judgments and eventual clustering.

Recommendation: proceed with this bounded compiler-grounded representation
prototype, **not Phase 3 clustering**. The available evidence supports richer
structure extraction and avoiding exhaustive matching in principle; it does not
yet support real-population diversity measurements.
