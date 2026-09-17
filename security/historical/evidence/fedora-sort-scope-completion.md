# Fedora sort linker-exact semantic scope completion

This completes the existing pilot instrument; it does not start population v2 or change frozen records, census, source manifest, or reconnaissance.

Primary configuration remains Clang/LLVM 21.1.8, SVF 3.4 commit `67efb7745ce47b2b6853fd5696fc22c83d701e6c`, AndersenWaveDiff, `-stat=false -ff-eq-base`.

Reproduce with `bash scripts/run_fedora_sort_scope_checkpoint.sh` after the existing authenticated Fedora source/build reconstructions are available. Native objects are reused except legitimate generated version inputs; all selected C inputs are separately compiled to LLVM for both comparisons.

## Generated-module provenance

Both configured Makefiles generate build-tree `src/version.c` from `PACKAGE_VERSION`, then compile `src/version.o` and archive it in `src/libver.a`. The recursive 8.17 build executes these rules from its `src` directory; 8.23 uses its nonrecursive root Makefile. GNU ld explicitly extracts `version.o` to satisfy `sort.o`'s `Version` reference.

The two-line generated source includes `<config.h>` and defines `char const *Version` as `8.17` or `8.23`. It is configured build data, not authenticated release source. The generation rule, command, before/after hashes, complete contents, native link recipe and selected archive members are retained in each linker-scope JSON.

Every TU records `source_provenance_kind`, source path/hash, configured object target, direct/archive role, archive membership, compiler dependency mapping, configured Make/compiler recipe, and exact normalized Clang command. Included implementation `.c` files in a dependency list are preserved as include context, not counted as separate compilation units. System startup objects/libraries remain explicit external inputs.

The object/recipe cross-check also exposed a prior 8.23 adapter issue: source-only Makefile matching selected `src/src_libsinglebin_sort_a-sort.o` instead of linked `src/sort.o`. The linker-exact build now binds each recipe to the object proven by the native closure. The retained old-scope comparison still uses its original recipe; no source or pointer-analysis option was changed.

## Coreutils 8.17-7.fc18

Closure: one direct sort object, 44 selected libcoreutils members, and one libver/version member. No release translation unit removed or added; only `generated-config/src/version.c` added.

| Metric | Retained reconstructed scope | Linker-exact scope |
|---|---:|---:|
| source_count | 45 | 46 |
| function_count | 291 | 291 |
| call_edge_count | 683 | 683 |
| resolved_indirect_edge_count | 58 | 58 |
| unresolved_indirect_callsite_count | 5 | 5 |

Full function/edge/unresolved/external graph records identical excluding build provenance: `True`.

### CVE-2013-0221 — src/sort.c::keycompare_mb

old: `resolved_indirect_multi_target`; candidates: 1.

Raw depth 3: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb`.

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5274:13`.
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3369:33`.
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3275:14`; all 2 may-targets: `['src/sort.c::keycompare_mb', 'src/sort.c::keycompare_uni']`.

new: `resolved_indirect_multi_target`; candidates: 1.

Raw depth 3: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb`.

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5274:13`.
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3369:33`.
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3275:14`; all 2 may-targets: `['src/sort.c::keycompare_mb', 'src/sort.c::keycompare_uni']`.

Depth changed: `False`; path changed: `False`; path indirect target sets changed: `False`.

### CVE-2013-0221 — src/sort.c::getmonth_mb

old: `resolved_indirect_multi_target`; candidates: 1.

Raw depth 4: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb -> src/sort.c::getmonth_mb`.

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5274:13`.
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3369:33`.
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3275:14`; all 2 may-targets: `['src/sort.c::keycompare_mb', 'src/sort.c::keycompare_uni']`.
- `src/sort.c::keycompare_mb` --indirect_resolved--> `src/sort.c::getmonth_mb` at `src/sort.c:3134:16`; all 2 may-targets: `['src/sort.c::getmonth_mb', 'src/sort.c::getmonth_uni']`.

new: `resolved_indirect_multi_target`; candidates: 1.

Raw depth 4: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb -> src/sort.c::getmonth_mb`.

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5274:13`.
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3369:33`.
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3275:14`; all 2 may-targets: `['src/sort.c::keycompare_mb', 'src/sort.c::keycompare_uni']`.
- `src/sort.c::keycompare_mb` --indirect_resolved--> `src/sort.c::getmonth_mb` at `src/sort.c:3134:16`; all 2 may-targets: `['src/sort.c::getmonth_mb', 'src/sort.c::getmonth_uni']`.

Depth changed: `False`; path changed: `False`; path indirect target sets changed: `False`.

## Coreutils 8.23-9.fc22

Closure: one direct sort object, 45 selected libcoreutils members, and one libver/version member. No release translation unit removed or added; only `generated-config/src/version.c` added.

| Metric | Retained reconstructed scope | Linker-exact scope |
|---|---:|---:|
| source_count | 46 | 47 |
| function_count | 293 | 293 |
| call_edge_count | 688 | 688 |
| resolved_indirect_edge_count | 58 | 58 |
| unresolved_indirect_callsite_count | 5 | 5 |

Full function/edge/unresolved/external graph records identical excluding build provenance: `True`.

### CVE-2015-4041 — src/sort.c::keycompare_mb

old: `resolved_indirect_multi_target`; candidates: 1.

Raw depth 3: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb`.

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5402:13`.
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3449:33`.
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3355:14`; all 2 may-targets: `['src/sort.c::keycompare_mb', 'src/sort.c::keycompare_uni']`.

new: `resolved_indirect_multi_target`; candidates: 1.

Raw depth 3: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb`.

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5402:13`.
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3449:33`.
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3355:14`; all 2 may-targets: `['src/sort.c::keycompare_mb', 'src/sort.c::keycompare_uni']`.

Depth changed: `False`; path changed: `False`; path indirect target sets changed: `False`.

### CVE-2015-4042 — src/sort.c::keycompare_mb

old: `resolved_indirect_multi_target`; candidates: 1.

Raw depth 3: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb`.

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5402:13`.
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3449:33`.
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3355:14`; all 2 may-targets: `['src/sort.c::keycompare_mb', 'src/sort.c::keycompare_uni']`.

new: `resolved_indirect_multi_target`; candidates: 1.

Raw depth 3: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb`.

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5402:13`.
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3449:33`.
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3355:14`; all 2 may-targets: `['src/sort.c::keycompare_mb', 'src/sort.c::keycompare_uni']`.

Depth changed: `False`; path changed: `False`; path indirect target sets changed: `False`.

## Final pilot scope audit

| Program | TUs | Kind | Generated module included | Evidence |
|---|---:|---|---|---|
| gnu-coreutils/5.2.1/mkdir | 14 | linker_exact | none required | build/coreutils-5.2.1-mkdir-scope/src/mkdir.map |
| gnu-coreutils/8.17-7.fc18/sort | 46 | linker_exact | generated-config/src/version.c | security/historical/coreutils_8_17_linker_scope.json |
| gnu-coreutils/8.23-9.fc22/sort | 47 | linker_exact | generated-config/src/version.c | security/historical/coreutils_8_23_linker_scope.json |
| gnu-coreutils/9.7/sort | 58 | linker_exact | generated-config/src/version.c | security/historical/coreutils_9_7_linker_scope.json |
| gnu-grep/2.10/grep | 33 | linker_exact | none required | build/grep-2.10-scope/src/grep.map |
| gnu-grep/2.21/grep | 43 | linker_exact | none required | build/grep-2.21-scope/src/grep.map |

All classifications refer to separately validated primary scopes. The old semantic milestone retains its original 45/46-file reconstructed scopes and the 9.7 archive-superset scope with explicit supersession pointers; it is not relabeled.

A resolved indirect edge remains a possible static may-call target, not guaranteed runtime execution. No candidate is chosen from an ambiguous source identity, and the frozen-query consistency guard remains active. No population mean, median, or threshold is calculated.
