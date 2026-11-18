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

## Program scope is part of the measurement

Use linker-exact program scope whenever it can be reconstructed faithfully
from the historical configured build. Use a conservative source/archive
superset only when linker-exact scope cannot be recovered, and label that
condition explicitly. Scope is selected from build evidence, never from a
preferred depth or pointer-analysis result. Additional translation units can
contribute address-taken functions, enlarge may-target sets, and shorten a
may-call path.

Every historical semantic program result carries `source_scope_kind`:

- `linker_exact`: configured program objects plus the static archive members
  actually extracted by a successful native link (or an equivalently proven
  closure), mapped to their source/compile instances. Include required
  generated translation units. Record external system-library/startup inputs
  separately; this does not claim a source model of libc or the loader.
- `reconstructed_program_scope`: a historically justified narrow program
  scope whose complete linked source/compile-instance closure has not yet
  been proven or fully realized in the semantic analysis. This is
  an explicit intermediate state, not a synonym for linker-exact.
- `archive_superset`: the conservative configured source/archive superset,
  including potentially unextracted members. Record why exact recovery was
  unavailable. A retained sensitivity/control run can use this kind even
  when exact recovery is available, but cannot silently remain primary.

Preserve scope derivation, object/source correspondence, configured link
command, and source fingerprints. Future aggregates must not silently pool
incompatible scope kinds; unresolved scope reconstruction must be reported
before a population's measurement plan is frozen. No population statistics
are calculated in this checkpoint.

The five older pilot scopes have archived GNU ld member-closure evidence.
The frozen 8.17 and 8.23 sort lists omit the linked generated `version.o`
data module and remain `reconstructed_program_scope` as retained comparison
measurements. Their separate `fedora_sort_scope_validation.json` completion
experiment reconstructs the complete native object closure and independently
remeasures the generated-module-inclusive scopes. A successful completion,
not merely adding a filename, supplies their new primary scope classification.
The separate Coreutils 9.7 scope experiment supersedes the old 329-file
archive-superset measurement as its primary scope, without rewriting the
frozen source manifest, records, or CVE census. See
[`source_scope_audit.json`](../security/historical/source_scope_audit.json) and
[`semantic_scope_validation.json`](../security/historical/semantic_scope_validation.json).

The completed pilot audit establishes linker-exact primary scopes for all six
programs: mkdir 5.2.1 (14 TUs), grep 2.10 (33), grep 2.21 (43), sort 8.17 (46),
sort 8.23 (47), and sort 9.7 (58). The latter three counts include configured
build-generated `version.c`. The Fedora completions changed neither graph
records nor vulnerable-function depths/paths/target sets; this is an observed
scope-sensitivity result, not a scope-selection criterion. See the
[completion report](../security/historical/evidence/fedora-sort-scope-completion.md).

### Generated translation-unit provenance

`historical_linker_scope.schema.json` freezes the object/source model used for
the Fedora scope completions. Each TU records its source path and SHA-256,
configured object target, object name, archive (or null for a direct object),
link role, compiler dependency evidence, and compile recipe provenance. The
latter contains the normalized configured Make invocation, compiler recipe,
working directory, and exact Clang command. Object/source mappings are checked
against both compiler-generated dependencies and configured Automake metadata.
An included `.c` implementation is include context, not another TU.
When Automake has several object recipes for one source (for example normal
`src/sort.o` and a single-binary archive variant), the linker-exact build uses
the object established by the link evidence, not the first source-name match.

`source_provenance_kind` has two distinct values:

- `authenticated_historical_tree`: distributed source in the immutable,
  verified historical tree, including an authenticated downstream patch
  reconstruction. The original tree fingerprint is unchanged.
- `configured_build_generated`: a legitimate product of that configured
  build. Its path uses the separate `generated-config/` namespace; generation
  rule, configuration inputs, contents/hash, and compiler recipe are recorded
  independently. It is never represented as authenticated release source.

The two Fedora builds generate `src/version.c` from `PACKAGE_VERSION`, compile
it to `src/version.o`, and extract it from `src/libver.a` to satisfy the native
sort link's `Version` reference. Regeneration occurs only in the build tree.
The configured values are upstream versions `8.17` and `8.23`, not the Fedora
package-release suffixes. Normalized specimen/source/object provenance, not a
host-specific absolute path or LLVM numeric suffix, identifies a compilation
instance. This provenance does not automatically disambiguate a source-only
vulnerable-function query; all existing ambiguity/query guards remain active.

## Source identity and fail-closed historical queries

`source_file` plus source function name is a historical query, not necessarily
a unique compiler function. No matches means `source_identity_not_found`;
multiple matches means `source_identity_ambiguous`, with no selected function
and no imputed depth. Preserve every candidate's run-local semantic identity,
LLVM symbol, definition location, linkage, reachability, semantic status,
depth, and complete shortest path. Sorting candidates makes serialization
deterministic; it must not select the first, reachable, or shallowest one.

In gnulib, multiple translation units include `lib/xstrtol.c` under different
type macros. Distinct static `bkm_scale` definitions consequently share a
source location. LLVM's `.NNN` renaming suffix is link-order-dependent and is
only an artifact-local identifier, not a stable historical identity. Original
translation unit plus source/include instance, linkage, and a normalized
compile-command fingerprint could provide stable *instance* provenance.
That still does not decide which instance a source-only vulnerability mapping
intends. This checkpoint retains explicit ambiguity rather than introducing
an unvalidated disambiguation rule. None of the nine verified queries is
ambiguous.

Pre-link LLVM 21 disassembly confirms four `bkm_scale` definitions at
`lib/xstrtol.c:47`, with `DISPFlagLocalToUnit` and distinct `DICompileUnit`
source files: `lib/xstrtoimax.c`, `lib/xstrtol.c`, `lib/xstrtoul.c`, and
`lib/xstrtoumax.c`. Their retained modules are respectively `tu-0319.bc`,
`tu-0321.bc`, `tu-0323.bc`, and `tu-0324.bc` in this archive-superset run.
These module ordinals are build artifacts, not identities. A future helper
could expose the existing `DISubprogram::getUnit()` provenance without
guessing from numeric suffixes. The real diagnostic retains all four
candidates (three unreachable and one at depth 3) as ambiguous; no
reachable-candidate preference is used.

Before analysis, `verify_frozen_queries` requires exact per-CVE equality
between query metadata, `records.json` vulnerable function names, and the
milestone's independently verified location ledger
`semantic_query_locations.json`. The companion ledger is necessary because
the frozen records contain function names but no structured source-file
field. Missing/extra queries, wrong locations, duplicates, or a mismatched
program/version fail closed. Records and location mappings select only which
function to query; they never define edges, target sets, analysis options,
scope construction, or shortest paths.

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
