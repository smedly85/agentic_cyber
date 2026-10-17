# Phase 2.7: reproducible Clang extraction feasibility

## Decision

**Both selected populations now have a complete extracted pair.** A single
declared analysis profile succeeds for all four unchanged sources, twice each.
This supports proceeding to a separately scoped experimental implementation of
independent Architecture and Strategy descriptors. It does not establish full
population coverage, historical build reproduction, behavioral equivalence or
readiness for distances/clustering. No descriptors or distances were implemented.

| Population | Lineage | Profile status | Candidate functions | Body AST nodes | Direct calls | Internal | External declared | Unresolved call expressions |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mkdir/002 | 003 | Success, repeat verified | 7 | 1,598 | 55 | 8 | 47 | 0 |
| mkdir/002 | 009 | Success, repeat verified | 6 | 1,567 | 43 | 5 | 38 | 0 |
| grep/004 | 001 | Success, repeat verified | 11 | 2,183 | 90 | 19 | 71 | 0 |
| grep/004 | 002 | Success, repeat verified | 16 | 2,161 | 91 | 27 | 64 | 0 |

These are two separate populations, with **2/2 extractions and one complete
within-population pair each**. Direct-call counts are occurrences, not unique
edges. Unique caller/callee edges are also saved. Zero unresolved call expressions
does not mean all runtime relationships are known: passing a callback to a library
API does not resolve that API's runtime calls. This is not an SVF may-call graph.

## Historical evidence reviewed

Reviewed the committed Phase-2.6 runner, tests, report and saved evidence; each
original `experiment.json`, `metadata.json`, build/public/held-out logs; available
adjacent security records; and compiler/environment strings in the selected
attempt logs/records. No historical artifacts were modified or validation rerun.

All four experiment records specify:

```text
mkdir -p build && cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_<utility>/new_<utility>.c -o build/new_<utility>
```

Final metadata records build, feature and held-out exit codes of zero and overall
success for all four. The base-test command was empty; its zero exit code is not
additional test coverage. Public logs end in 150/150 passes for mkdir and 113/113
for grep. Held-out logs end in 25/25 and 37/37 respectively. mkdir/009 reached the
successful source at repair loop 2 after two public-test failures; the other
selected sources succeeded at loop 0. Source hashes were verified against the
**successful loop**, not earlier intermediate sources. These are recorded results,
not newly executed functional experiments.

| Candidate | Historical successful-loop SHA-256 (LF source) |
| --- | --- |
| mkdir/003 | `710913f8caa0173457548d4db1ed03aa5fde26dfc8ab3984a71384f0f15ae853` |
| mkdir/009 | `35c6d4b168d33b16ef79d3b134a8480e1e34951212aecf9d0b4de04ed8f17b57` |
| grep/001 | `b2f2229529908630fa814b8753a35b653a37f41f13db2ba687917d71021e2e9d` |
| grep/002 | `0e2b7a2354a5a2af890c2c93af1afc85e5820c5b8ab346d68bd7f5ec419bbc9a` |

The local checked-out files use CRLF. Their actual bytes were **not normalized for
compilation**. Both historical LF-normalized and actual byte hashes are recorded:

| Candidate | Actual extracted source SHA-256 |
| --- | --- |
| mkdir/003 | `4aa712c29698c00cdd908670d1faea3f82be357d187c4508661bd9a77a8d1492` |
| mkdir/009 | `b39f971854de60b78e6f952eb46f662b62dbe5fd50174a58be4e4914c9f1eb73` |
| grep/001 | `603e9d16af80103a82cf32a659573cce092a3a2ca5d760e73852ccdd635f19d8` |
| grep/002 | `59171f4cef4a4bc6eafb91a7b7e0176d59ec80863a383a2046741f1176f84f0c` |

Environment provenance is limited but not wholly absent:

* The experiment records name `cc`, the repository path and commit, build flags
  and validation commands. Build logs contain validation-loop markers without
  compiler banners. Work directories were pruned.
* Both mkdir attempts' saved `security_results.json` record `/usr/bin/cc` and
  **Apple clang version 21.0.0 (clang-2100.1.1.101)**. This is adjacent evidence from
  the separate sanitizer compilation, whose flags differ from the functional
  build. It narrows the environment evidence beyond Phase 2.6, but does not certify
  which executable the functional shell resolved or its effective configuration.
* No corresponding compiler-version record was found for these grep attempts.
  Historical target triples, SDK versions, sysroots, effective include paths,
  header bytes, builtin macros and ambient include variables remain unattested.
* grep/002 explicitly defines `_POSIX_C_SOURCE 200809L` before its includes. The
  other three sources do not. No command-line feature-test definition is recorded
  in any of their functional build commands. This does not establish which
  features the historical headers exposed by default.

No historical compiler or macro setting is inferred from exit-code success.

## Fixed analysis profile and technical rationale

Profile **`c11-posix2008-v1`** uses Ubuntu Clang 21.1.8 (6ubuntu1), target
`x86_64-pc-linux-gnu`, with the local Linux headers. Its sole compiler-flag addition
to the recorded flags is **`-D_POSIX_C_SOURCE=200809L`**, uniformly applied to both
candidates in each population (and to both populations). This is an explicit
analysis choice, not a recovered historical setting.

```text
/usr/bin/clang -std=c11 -Wall -Wextra -Werror -pedantic -O2 -D_POSIX_C_SOURCE=200809L -fsyntax-only -Xclang -ast-dump=json <absolute-unchanged-candidate-path>
```

As in Phase 2.6, `cc` is replaced with the available Clang, binary output/shell
directory creation are omitted, and the source path points to the saved snapshot.
The new experimental runner executes this bounded syntax-only command directly so
it can retain exit status and stderr even on success; it reuses the Phase-2.6 AST
summary/attribution utilities. Production `parse_clang_ast()` is unchanged.

Local `sys/stat.h` exposes `mode_t` under `__USE_XOPEN || __USE_XOPEN2K` and `lstat`
under `__USE_XOPEN_EXTENDED || __USE_XOPEN2K`. The declared POSIX.1-2008 profile
activates the applicable header guards through the public feature-test macro;
it does not directly define private `__USE_*` macros. No guessed typedefs,
declarations, forced includes or warning suppressions are inserted. All recorded
warning flags, including `-Werror`, remain enabled.

The recorded-flags controls reproduce both previous local failures. Under the
profile, mkdir/003's `mode_t` casts resolve and its unused-parameter diagnostic
also disappears without suppression. This is consistent with a cascading
diagnostic from the failed cast: `final_mode` is used inside that cast. grep/001's
`lstat` resolves to the real header declaration. All eight profile invocations
return zero with empty stderr.

The subprocess environment clears CPATH, C_INCLUDE_PATH, CPLUS_INCLUDE_PATH,
OBJC_INCLUDE_PATH, SDKROOT, MACOSX_DEPLOYMENT_TARGET and CCC_OVERRIDE_OPTIONS, and
sets `LC_ALL=C`. Removed values are recorded. Exact commands, effective driver
configuration (`-###`), compiler version and binary hash are saved. Preprocessing
is separately captured with `-E -dD` (active expanded text, directives and source
line markers) and `-E -dM` (final active macro table), under the same flags.
Every readable source/header input named by those line markers is hashed. This
records the local toolchain; it is not an archived hermetic compiler image.
Future reproductions must check compiler/header manifests rather than assuming
the profile name alone guarantees identical extraction on another machine.

## Structural effect and provenance

For mkdir/009 and grep/002, the **entire selected candidate FunctionDecl subtrees
are equal** between recorded-flags and profile ASTs after consistent replacement
of dump-local pointer IDs. This comparison retains types, operators, ordered
children, attributes, bindings, locations and implicit nodes. Their function,
call, node-kind, operator, control and transfer summaries also match the saved
Phase-2.6 evidence. No candidate structural changes were observed in these two
successful controls.

The expanded header configuration does change for mkdir/009: additional POSIX
declarations/macros become available, including time/stat interfaces, without
changing its candidate function trees. grep/002 already requests the same POSIX
level, so its final macro table has no changes. The report lists every final
macro-table delta for all four candidates. For previously failed candidates,
there is no valid baseline AST measurement to compare; partial failed ASTs are
not treated as an earlier strategy. A future population with feature-conditional
candidate code could change its active computation under this profile and needs
the same explicit audit.

All four successful ASTs retain direct API declarations, source-ordered statement
children, branch/loop nesting, argument slots, operators, variable-reference IDs,
and source/macro ranges. `fprintf` counts are 12, 8, 4, 11 in table order;
`mode_t` cast counts are 2, 10, 0, 0. `S_ISDIR` contributes 14, 14, 56, 56 expanded
nodes, respectively (not invocation counts), and no fabricated macro calls.
Spelling locations and expansion locations remain distinct; original source
excerpts and macro tokens are audit data. AST child order remains distinct from
C runtime evaluation order. Inactive preprocessing branches remain absent.

## Validation and reproducibility limits

* All four raw source hashes match Phase 2.6 before extraction and remain identical
  afterward. LF-normalized hashes match the original successful-loop metadata.
* Two fresh profile invocations per candidate produce equal **full translation-unit
  ASTs** after replacing dump-local address identifiers with deterministic tokens.
  Repeated-reference relationships are retained. Raw pointer addresses are not
  expected to be byte-identical. This is an audit equality operation, not a graph
  fingerprint, name normalizer or diversity representation.
* All selected definition-name offsets point to the corresponding token in the
  candidate bytes. Top-level filename attribution excludes all 12 header-defined
  inline function bodies in each candidate's translation unit. Header declarations
  (317, 243, 327, 252 respectively, including those bodies) are not counted as
  candidate functions. A controlled test also checks header/source attribution.
* Nonzero/terminated/timed-out compiler results cannot yield an eligible AST, even
  when stdout contains parseable JSON. Invalid JSON or a non-translation-unit root
  is rejected. Failed controls have no structural measurements. Preprocessing
  failure or failed repeatability/source-attribution checks prevents pair admission.
* Implicit nodes remain identifiable rather than discarded: there are 412, 440,
  635, 691 `ImplicitCastExpr` nodes in the four candidate bodies. Explicit casts
  have a different kind. `isImplicit` is retained where emitted, but its absence
  does not establish source authorship. Compiler kind/role and spelling/expansion
  provenance must inform any later source/implicit classification.

**102 tests passed:** the unchanged 92-test suite plus ten new
checks for failed/invalid output rejection, pointer-ID equality preserving
bindings and ordering, header attribution, implicit nodes and macro deltas.
No full functional experiments were run.

## Artifacts and next step

* Runner: [`scripts/ordered_diversity_clang_repro.py`](../scripts/ordered_diversity_clang_repro.py)
* Tests: [`tests/test_ordered_clang_repro.py`](../tests/test_ordered_clang_repro.py)
* Evidence: [`ordered_diversity_phase27_feasibility.json`](ordered_diversity_phase27_feasibility.json)
* Raw AST/preprocessor artifacts: ignored local `build/ordered-diversity-phase27/`;
  paths and hashes are recorded in the evidence JSON.

```sh
python3 -m scripts.ordered_diversity_clang_repro
python3 -m pytest -q tests/test_ordered_clang_repro.py tests/test_ordered_clang_probe.py tests/test_ordered_callgraph.py tests/test_ordered_distances.py tests/test_ordered_phase25.py
```

There are no extraction blockers for these two selected pairs under the recorded
analysis environment. Proceed next to **independent experimental descriptors**
with versioned source/implicit/binding normalization and explicit sequencing;
retain the all-functions Strategy estimand as separate from production scope.
Before scaling, archive or pin the compiler/header environment and audit profile
sensitivity and coverage across each population. Indirect targets, callbacks,
general macro attribution and unseen C constructs still require explicit coverage
policies. No production metrics, analyzer, historical results, security-depth
backend or lineage infrastructure were changed. No commit or push was made.
