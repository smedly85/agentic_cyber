# Pre-v2 semantic scope and identity checkpoint

This is the retained Coreutils 9.7 checkpoint. The subsequent [Fedora sort scope completion](fedora-sort-scope-completion.md) resolves the two scope qualifications shown below; the current six-program classification is in `../source_scope_audit.json`.

The frozen records, census, and source manifest are unchanged. This is a six-program pilot instrument audit, not population v2.

## Scope audit

| Program | Sources | Scope kind | Further exact reconstruction? |
|---|---:|---|---|
| gnu-coreutils/5.2.1/mkdir | 14 | linker_exact | no |
| gnu-coreutils/8.17-7.fc18/sort | 45 | reconstructed_program_scope | yes |
| gnu-coreutils/8.23-9.fc22/sort | 46 | reconstructed_program_scope | yes |
| gnu-coreutils/9.7/sort | 58 | linker_exact | no |
| gnu-grep/2.10/grep | 33 | linker_exact | no |
| gnu-grep/2.21/grep | 43 | linker_exact | no |

The 8.17/8.23 library-member lists match the existing GNU ld maps exactly, but omit generated `src/version.c` from the linked libver archive. They are not silently promoted to complete linker-exact semantic scope. No older program was rebuilt or remeasured.

## Coreutils 9.7

Reproduce with `bash scripts/run_semantic_scope_checkpoint.sh`. It authenticates the source, reconfigures the same GCC build, realizes Automake BUILT_SOURCES, links native sort with a GNU ld map, and runs the unchanged primary Clang/LLVM/SVF configuration on both scopes.

`coreutils_9_7_linker_scope.json` contains the configured variables/link command, complete selected object/source mapping, and exact removed source/object lists. `evidence/coreutils-9.7-linker.map` retains inclusion reasons and LOAD inputs.

Old scope: 329 release C sources. New: 57 release C sources plus generated version.c = 58 translation units/objects. Removed 272 release sources; no release source added. version.c is added because the native link actually extracts version.o, not because of any depth outcome.

| Metric | Archive superset | Linker exact |
|---|---:|---:|
| function_count | 1323 | 337 |
| call_edge_count | 3699 | 767 |
| resolved_indirect_edge_count | 227 | 19 |
| unresolved_indirect_callsite_count | 39 | 11 |

### archive_superset: begfield

Mapping: `resolved_direct_only`; candidates: 1.

Depth: 3. Path: `src/sort.c::main -> src/sort.c::check -> src/sort.c::fillbuf -> src/sort.c::begfield`.

- `src/sort.c::main` --direct--> `src/sort.c::check` at `{'column': 13, 'line': 4872, 'source_file': 'src/sort.c'}`; target cardinality `None`; complete targets `None`.
- `src/sort.c::check` --direct--> `src/sort.c::fillbuf` at `{'column': 10, 'line': 2976, 'source_file': 'src/sort.c'}`; target cardinality `None`; complete targets `None`.
- `src/sort.c::fillbuf` --direct--> `src/sort.c::begfield` at `{'column': 36, 'line': 1837, 'source_file': 'src/sort.c'}`; target cardinality `None`; complete targets `None`.

### linker_exact: begfield

Mapping: `resolved_direct_only`; candidates: 1.

Depth: 3. Path: `src/sort.c::main -> src/sort.c::check -> src/sort.c::fillbuf -> src/sort.c::begfield`.

- `src/sort.c::main` --direct--> `src/sort.c::check` at `{'column': 13, 'line': 4872, 'source_file': 'src/sort.c'}`; target cardinality `None`; complete targets `None`.
- `src/sort.c::check` --direct--> `src/sort.c::fillbuf` at `{'column': 10, 'line': 2976, 'source_file': 'src/sort.c'}`; target cardinality `None`; complete targets `None`.
- `src/sort.c::fillbuf` --direct--> `src/sort.c::begfield` at `{'column': 36, 'line': 1837, 'source_file': 'src/sort.c'}`; target cardinality `None`; complete targets `None`.

Changed reachable indirect callsite target sets/cardinalities: 10. Complete before/after sets are retained in semantic_scope_validation.json; source-qualified memberships and cardinalities are compared, not link-order-dependent LLVM numeric suffixes.

Seven retained reachable callsites have smaller target sets: two hash comparisons, hash's hasher, and three heap comparisons shrink from 25 targets to 2; randread's error callback shrinks from 3 to 1. One hash_free callsite is no longer reachable, and two mcel_tocmp callsites disappear with their definitions. This is a real scope sensitivity of the may-call graph, despite unchanged begfield depth.

## Identity and query guard

Missing and ambiguous source identities are distinct. Ambiguity retains every full candidate row, including LLVM symbol, linkage, source location, reachability, depth, and shortest-path provenance, without choosing one. Gnulib's xstrtol inclusion pattern creates separate static functions from the same source location; translation-unit provenance could distinguish instances but cannot justify selecting one for a source-only query. No automatic disambiguation rule is introduced.

The real archive-superset bkm_scale diagnostic retains four candidates, including the three unreachable instances and one depth-3 instance, as source_identity_ambiguous. The independently derived linker-exact scope has one instance. This is a scope-derived difference, not selection of the reachable candidate.

The fail-closed query guard checks exact per-CVE function membership against records.json and exact source/function pairs against the independently verified milestone location ledger. It also checks program/version and duplicate queries. Records never construct the graph.

The remaining legacy scope qualification is explicit; no historical mean, median, threshold, or expanded-population result is calculated.
