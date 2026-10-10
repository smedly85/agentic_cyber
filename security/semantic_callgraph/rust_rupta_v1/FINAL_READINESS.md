# Final bounded coverage check: not ready for accepted historical measurement

The fixed primary scope is the utility implementation plus reachable first-party
uucore implementation, including verified generated project code. Utility-only
scope remains a sensitivity. Both depths use the same scoped graph. A nonempty
full-graph path between included functions, with only excluded internal nodes,
counts as **one witnessed implementation transition**. It stops at the next
included function; no missing callback is inferred or inserted.

## Coverage decision

**LazyLock: additional first-party callbacks are missing.** The frozen
`src/uucore/src/lib/lib.rs` defines initializer closures for ARGV (line 320),
UTIL_NAME (322), and EXECUTION_PHRASE (335). Their accessors are reached, but the
initializer closures are absent. The source/compiler-supported route is:
`args_os/util_name/execution_phrase → LazyLock deref/force → OnceForce callback
→ stored initializer function pointer → first-party initializer closure`.
The pinned standard library invokes that pointer at `std/src/sync/lazy_lock.rs:250`.
These are real omitted implementation callbacks, even though their intermediary
library frames would not count toward scoped depth.

**TLS needs a narrower conclusion.** The existing minimal non-const TLS test
demonstrates a missing `LocalKey → generated accessor → initializer → target`
route. In this specimen, however, `locale.rs:109-110` initializes LOCALIZER with
`const { OnceLock::new() }`. That does not establish an additional first-party
runtime initializer. The `init_localization`, `setup_localization`, and
`get_message_internal` with-callbacks are already reached. TLS storage/returned
pointer flow remains unvalidated; it is not reported as proof that those existing
localization callbacks are missing.

The bounded source review confirms ignored constant allocation/aggregate contents,
restricted constant function-instance recovery, and ignored `ThreadLocalRef`.
Changing the latter alone would not restore the demonstrated complete route.
No localized complete correction was established; no constant-memory subsystem
or fixture-specific callback edge was added.

**Formatting: an additional utility-owned method is missing.** `ChmodError`
derives Error/Display at `chmod.rs:24-38`. `Chmoder::chmod` uses `show!` at lines
286/299; `uucore`'s macro at `macros.rs:88-95` formats the error with `eprintln!`.
The route is `Chmoder::chmod → _eprint/formatting dispatch → ChmodError::fmt
→ translate!/uucore::locale::get_message`. No utility-owned fmt method is reached.
The graph records unavailable bodies for `_eprint`, `core::fmt::write`, and
`alloc::fmt::format::format_inner`; the pinned library's `core::fmt::rt::Argument`
invokes the stored formatter at `rt.rs:152`. An argument constructor or an
address-taken formatter is not evidence of invocation. Restoring this route needs
faithful library-body traversal or a separately validated callback model, not
a simple export fix. No replacement formatting analysis was implemented.

The analyzer, including the validated map_err and Once corrections, was unchanged.
The existing minimal tests supplied the controlled evidence; no new correction
was made, so no additional regression fixture was necessary.

## One chmod rerun — diagnostic only

| Scope | Vulnerability depth | Maximum implementation depth | Normalized depth |
|---|---:|---:|---:|
| **Primary: utility + uucore** | **3** | **12** | **0.25** |
| Utility-only sensitivity | 3 | 6 | 0.50 |

Shortest vulnerable path (three transitions):

```text
chmod::main → uu_chmod::uumain → uu_chmod::uumain::uumain → Chmoder::chmod
```

A shortest path attaining the primary maximum (12 transitions; generic arguments
abbreviated, and the functions after the third node belong to
`uucore::mods::clap_localization`):

```text
chmod::main
→ uu_chmod::uumain
→ uu_chmod::uumain::uumain
→ handle_clap_result
→ handle_clap_result_with_exit_code
→ handle_clap_result_with_exit_code::{closure#0} [via Result::map_err]
→ handle_clap_error_with_exit_code
→ {impl#2}::print_error_and_exit
→ {impl#2}::print_error_and_exit_with_callback
→ {impl#2}::handle_invalid_value_with_callback
→ {impl#2}::print_simple_error
→ {impl#2}::print_simple_error_with_callback
→ {impl#2}::print_simple_error::{closure#0}
```

No reachable implementation functions were added or removed: primary 130 nodes,
sensitivity 20. The primary graph has 179 transitions, including 42 mediated
transitions. The full graph remains evidence, not the primary denominator.

The remaining ledger contains 35 recognized zero-target indirect sites and 96
unavailable bodies. It identifies each site's caller, location and the included
functions exposed through excluded-node paths. In particular, LazyLock initializer
and LocalKey pointer calls remain unresolved. Formatting callbacks hidden behind
unavailable bodies are additional omissions, not entries automatically covered
by that 35-site count. Other recognized unresolved sites cannot all be certified
irrelevant to callbacks into implementation code.

**Readiness: stop here; do not run the historical population.** The three-edge
vulnerable path is still observed, but is not promoted to an accepted measurement.
Maximum implementation depth and normalized depth remain explicitly provisional:
the demonstrated omitted implementation callbacks prevent coverage acceptance.
No error bound, completeness claim, or cross-language numerical equivalence is
asserted.

Exact commands, unchanged analyzer/compiler hashes, source evidence hashes, both
full path witnesses, function-set comparison and the site-by-site coverage ledger
are in [FINAL_COVERAGE_RESULTS.json](FINAL_COVERAGE_RESULTS.json). Raw output is in
`build/rupta-v1/drop-trial/compatibility/scope-trial/final-coverage/`; the separate
scoped graph is `scope-trial/final-coverage-scoped.json`. Reproduction uses
`python3 -m security.semantic_callgraph.rust_rupta_v1.final_coverage_check` in a fresh
output directory. Frozen inputs and prior evidence are hash-checked and preserved.
No commits, pushes, population run, or acceptance promotion occurred.
