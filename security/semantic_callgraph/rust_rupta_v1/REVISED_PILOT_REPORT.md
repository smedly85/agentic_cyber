# Implementation-scoped chmod pilot — provisional and coverage-blocked

**Recommendation:** use the callback-preserving project-implementation scope
defined in [SCOPED_POLICY.md](SCOPED_POLICY.md), with a separately reported
utility-crate-only sensitivity. Do not use the dependency graph's Dmax=39 as the
primary denominator. Do not accept this pilot or run the historical population:
initializer and formatting callback omissions remain demonstrated.

## Scope and equivalence to C

The inspected C instrument includes the executable's project objects and extracted
static support-library members, including required generated source. It does not
include source models of libc/startup merely because the executable uses them.
Thus the closest Rust ownership analogue includes `chmod`, `uu_chmod`, and shared
first-party `uucore` implementation, including verified build-generated code.
`uucore` is explicitly in this proposed primary scope; crates.io dependencies and
the standard library are not. If the intended question excludes the shared
framework too, use the utility-only sensitivity below as a separately named
metric; that is narrower than the current C support-library policy.

Both depths count transitions between included function instances. Each projected
edge must have a real full-graph witness whose internal nodes are excluded.
For example, `uucore caller → Result::map_err → uucore closure` becomes one
**implementation transition**, with both original edges retained in its witness.
It is not relabelled as a direct MIR call. Projection stops at each included
function; it cannot bypass owned intermediates. Contexts and monomorphizations
remain separate. Dependency paths ending in unavailable/unresolved calls are
coverage frontiers, not invented callback edges.

Source-level macro-generated `chmod::main`, the `#[uucore::main]` wrapper, and its
inner uumain remain three distinct functions. Source/derived closures and methods
belong to their defining project crate. Compiler glue, shims and static/promoted
pseudo-bodies are excluded from counts and traversed only as intermediates.
Dependency generic instantiations do not become project-owned because they use
project types. The build-generated `get_embedded_locales` function was verified
against uucore's build.rs and include site; its generation/hash provenance is
separate from authenticated release source.

This policy preserves the C principle of explicit project/build scope, but the C
instrument currently counts ordinary may-call edges and has no identical general
callback projection or primary normalized metric. Numerical C/Rust equivalence
has **not** been established. No existing C method or result was changed.

## Bounded review and corrections

Four small Rust programs were added under `fixtures/review/`; the initializer
program covers both LazyLock and TLS. Existing 35-program expectations were not
changed. Both modes produced the same findings:

| Mechanism | Saved analyzer | Separate localized trial |
|---|---|---|
| map_err | Closure target and returned Err function-pointer target both absent | Both reachable; returned indirect target set exact |
| LazyLock / thread-local initialization | Both initializer functions and their returned targets absent | Still absent; failure retained |
| Formatting / Display | Display callback and its target absent | Still absent; failure retained |
| Once / OnceForce | Correct closure chosen, but edge incorrectly attached to application caller | Callback edge belongs to the correct instantiated Once method; no cross-caller attribution |

The map_err repair disables its historical Ok-only summary/precision-critical
override and lets available MIR handle both variants and the callback. The Once
repair moves the existing unavailable-backend callback model into the Once
function's PAG using its formal parameters; ordinary wrapper/backend edges remain.
This is explicitly a **summary callback site**, not a compiler-observed direct
call. The sidecar marks synthetic summary sites, and now exports defining crate
and definition kind for ownership. No solver, context strategy, or fixture-specific
edge insertion was added. Scope projection is separate Python code; it never
repairs missing analysis targets.

The remaining initializer problem reaches constant/aggregate pointer modeling:
`visit_const_value` ignores pointed-to `GlobalAlloc::Memory` contents and returns
an empty constant for `ConstValue::Indirect`. The compiler MIR records the LazyLock
initializer pointer and TLS closure-to-function-pointer route, but neither
initializer is reached by RUPTA. The current constant-function-pointer evaluator
also limits recovered instances to ordinary items. This is not a DOT-only loss.
The bounded trial does not claim that one isolated branch explains every missing
initializer flow; repairing it generally requires handling aggregate allocations
and relevant generated function instances, beyond the two localized corrections.

The formatting test reaches `alloc::fmt::format::format_inner`, whose MIR is
unavailable, and stops before `Value::fmt → display_target`. Merely treating an
argument constructor/address-taken formatter as an executed callback would be
unsound. A faithful encoded-library experiment or separately validated formatting
model would be needed. Neither was attempted in this bounded task.

The original corpus still passes **35/35 in ander and default cs**, with **23/23
designated target sets exact** in each. All eight repeated mechanism outputs are
identical after normalization, including the retained failures. This is not a
claim that the expanded mechanism requirements all pass. Exact checks are in
[scoped_mechanism_results.json](scoped_mechanism_results.json).

## Revised pilot results

Same frozen CVE-2026-35338 mapping and uutils 0.2.2 revision
`3a07ffc5a9bd4c283e75afa548ba1f1957bad242`; source-level main; Andersen mode.
The unique vulnerable match remains `Chmoder::chmod`, compiler identity
`uu_chmod::{impl#1}::chmod`, source `src/uu/chmod/src/chmod.rs:269`, SHA256
`74854b94a97bbf21e855ab4fd386ba9cd4a9c6ec14752dce51d84e347166bb17`.

| Graph policy / analyzer | Vulnerability depth | Maximum utility depth | Normalized d/Dmax | Reachable included nodes |
|---|---:|---:|---:|---:|
| Project implementation, saved analyzer | 3 | 8 | 0.375 | 95 |
| **Project implementation, localized trial** | **3** | **12** | **0.25** | **130** |
| Utility crates only, localized trial (sensitivity) | 3 | 6 | 0.50 | 20 |

Both metrics in each row use the same graph, entry and unit. Maximum means maximum
finite shortest-path distance, not longest path. The map_err correction exposes
additional uucore error-handling functions and increases the scoped denominator:
the stable vulnerable path alone would not have detected the previous error.

Shortest vulnerable path, three transitions (generic arguments abbreviated only
in this report; complete instance keys remain in the JSON):

```text
chmod::main
→ uu_chmod::uumain
→ uu_chmod::uumain::uumain
→ Chmoder::chmod
```

A shortest path attaining the primary maximum of 12:

```text
chmod::main
→ uu_chmod::uumain
→ uu_chmod::uumain::uumain
→ uucore::clap_localization::handle_clap_result
→ handle_clap_result_with_exit_code
→ handle_clap_result_with_exit_code::{closure#0}  [via Result::map_err]
→ handle_clap_error_with_exit_code
→ {impl#2}::print_error_and_exit
→ {impl#2}::print_error_and_exit_with_callback
→ {impl#2}::handle_invalid_value_with_callback
→ {impl#2}::print_simple_error
→ {impl#2}::print_simple_error_with_callback
→ {impl#2}::print_simple_error::{closure#0}
```

The utility-only deepest path has six transitions:

```text
chmod::main → uu_chmod::uumain → uu_chmod::uumain::uumain
→ Chmoder::chmod → Chmoder::chmod_file
→ Chmoder::chmod_file_internal → Chmoder::change_file
```

The primary projection contains 130 nodes and 179 relations, 42 dependency-mediated.
Simply deleting excluded nodes would leave only 66 reachable nodes; projection
preserves all 130 full-graph-reachable included nodes. The narrow sensitivity has
20 nodes/24 relations, nine mediated; deletion alone reaches only 11. This is why
dependency nodes cannot simply be discarded. Witness paths and full-edge indices
are saved in [project_implementation_graph.json](project_implementation_graph.json)
and [utility_crates_only_sensitivity_graph.json](utility_crates_only_sensitivity_graph.json).

## Limits and acceptance decision

The new full graph is preserved: 7,432 nodes, 18,918 edges, 35 recognized zero-target
indirect callsites, and 96 unavailable bodies. Its Dmax remains 39 and is evidence
only. Ninety-two included primary-scope functions have an excluded-interior
frontier containing unresolved calls or unavailable bodies (15 in the narrow
sensitivity). These are exposure counts, not 92 independently proved missing
callback targets. The recognized-site ledger is not globally complete.

The outstanding mechanisms are relevant to this specimen: uucore locale handling
uses thread-local storage, and `ChmodError` derives Error/Display in the utility
source. No utility-owned fmt method appears among the 20 reached utility nodes.
Thus excluding library nodes does not establish completeness even for the narrow
scope. Missing or false callback edges can change reachability, shorter routes,
Dmax and the normalized ratio. No error bound or monotonic bound is claimed.
The vulnerable mapping/path remains provisional rather than automatically accepted.

Recommendation: retain this explicit scope policy and evidence, but **stop analyzer
development here and keep historical measurement blocked**. The remaining decision
is whether to authorize a bounded encoded-standard-library/constant-pointer
feasibility check; do not proceed to population measurements or accept 0.25/0.50
as historical estimates on the current coverage evidence.

## Reproduction and preservation

Separate source is under `build/rupta-v1/drop-trial/compatibility/scope-trial/source`.
Apply [scoped_callback_overlay.patch](scoped_callback_overlay.patch) after the
existing `modern_overlay.patch` on fork commit
`66e29895748bd7a289b448a875d198711f1382dd`, nightly-2026-08-21. Exact patch/binary/
compiler hashes are in [scoped_provenance.json](scoped_provenance.json).

From the repository root in WSL/Linux, the recorded module actions are:

```text
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_trial mechanisms baseline
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_trial prepare
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_trial build
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_trial mechanisms patched
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_trial assess
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_trial regression
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_trial repeat
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_trial inspect-mir
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_trial evidence
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_trial pilot
python3 -m security.semantic_callgraph.rust_rupta_v1.utility_scope baseline
python3 -m security.semantic_callgraph.rust_rupta_v1.utility_scope patched
python3 -m security.semantic_callgraph.rust_rupta_v1.scoped_report
```

Fresh output directories are required; do not remove prior evidence to rerun.
The diagnostic pilot replays the saved chmod rustc invocation with the new PTA
binary and separate output files, referencing the previously built immutable
dependency metadata. Its exact command/environment is saved. The first replay
inherited the old pilot's incremental-cache argument; the reproduction helper
now redirects that cache to its own output directory as well. No frozen source,
dependency versions, lockfile, mapping, or source provenance was changed.

The pilot completed in 57.54 seconds, peak RSS 567,412 KiB. All 1,778 authenticated
specimen source files matched their pre-build hashes. Earlier full/scoped pilot
results remain separate, including preliminary generated-source audit projections.
Thirteen Python adapter, projection/ownership and existing preservation regression
tests passed; no tracked preexisting repository file was modified.
The complete structured report is [scoped_pilot_results.json](scoped_pilot_results.json).
No historical population run, acceptance promotion, commit or push was performed.
