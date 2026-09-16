# Official scientific semantic call-depth instrument

Tree-sitter-derived call relationships are no longer the scientific source of
call-graph edges or depth.  Tree-sitter remains useful for syntax-level source
descriptors, source-location work, and comparison with the former prototype.
The historical 3/9 numeric observations, generated depth counts (0: 140,
1: 456, 2: 386, 3: 18), and Flawfinder-by-prototype-depth results are preserved
as provenance but are provisional and are not final semantic measurements.

The official scientific instrument is:

```text
C source and frozen build configuration
  -> Clang LLVM bitcode per translation unit
  -> llvm-link whole-program bitcode
  -> SVF AndersenWaveDiff whole-program pointer analysis
  -> direct plus resolved-indirect static may-call graph
  -> shortest edge path from the configured entry function
  -> raw call depth
```

A direct or SVF-resolved indirect may-call edge contributes one unit of depth.
All possible targets of a resolved indirect callsite are retained; an edge
does not assert that its target executes on every run.  Every edge carries its
callsite and backend/configuration provenance.  Cycles do not increase the
shortest already-known depth.

Missing evidence is never imputed.  Results distinguish direct-only paths,
paths with indirect edges, paths with multi-target indirect edges, semantic
unreachability, unresolved indirect callsites, unavailable external
definitions, unavailable builds/IR, and analysis failure.  Raw depth is the
primary value and is not normalized.

The primary configuration is Clang/LLVM 21.1.8 and repository-local SVF 3.4 at
pinned commit
`67efb7745ce47b2b6853fd5696fc22c83d701e6c` now builds against LLVM 21.1.8.
The controlled suite validates direct calls, local/parameter/global/struct-held
function pointers, multi-target may-calls, recursion, external definitions,
multi-translation-unit linking, and duplicate static names. The live invocation
uses AndersenWaveDiff with `-ff-eq-base` for first-field/base equivalence in
opaque-pointer IR and `-stat=false` to reserve stdout for JSON. Historical
validation resolves all nine frozen vulnerable-function observations,
including all six formerly nonnumeric observations. Removing only
`-ff-eq-base` changes none of the nine historical outcomes. The Coreutils 9.7
reconstruction now succeeds after configured Automake
`BUILT_SOURCES` are generated before Clang compilation; the authenticated
historical source and frozen historical-v1 records remain unchanged.

All earlier Tree-sitter-derived depths, including the 3/9 historical numeric
results, the generated counts (0: 140, 1: 456, 2: 386, 3: 18), and their
Flawfinder localization are retained as **prototype / superseded semantic
measurement** provenance. Tree-sitter remains valid for source parsing,
function spans, descriptor extraction, AST measurements, and source-location
mapping, but not for scientific call-graph edges or depth.

Future historical reporting will include both vulnerable-function observation
statistics and per-CVE summaries so CVEs with several verified functions do not
automatically dominate.  No final mean or distribution is calculated until
both the semantic instrument and population v2 are frozen.
