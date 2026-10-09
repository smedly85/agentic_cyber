# Provisional chmod pilot — not an accepted historical measurement

The controlled and compatibility gates passed before this single specimen was
analyzed. No other historical specimen was measured in this follow-up.

## Frozen input and mapping

- CVE: `CVE-2026-35338`; utility/package: `chmod` / `uu_chmod`.
- Frozen uutils version: 0.2.2; revision:
  `3a07ffc5a9bd4c283e75afa548ba1f1957bad242`.
- Authenticated source archive SHA256:
  `79c2961d512e213cf7b40a06c23634120239dd23bbf5d46b260cb5a5e83a8fe2`.
- Frozen source identity: `src/uu/chmod/src/chmod.rs::Chmoder::chmod`.
- Source SHA256:
  `74854b94a97bbf21e855ab4fd386ba9cd4a9c6ec14752dce51d84e347166bb17`.
- Cargo.lock SHA256:
  `b235b16cb9c929e1f4ac71635927d4618d23e2bf430c7d584089528d09fb588e`.

The existing frozen mapping was read, not rewritten. A unique `impl Chmoder`
method declaration at line 269, the authenticated source hash, crate, function
suffix and compiler source span identify `uu_chmod::{impl#1}::chmod`. Exactly one
analyzed instance matched, with its body available. This bridges RUPTA's anonymous
impl numbering to the existing nominal-type mapping without borrowing edges from
MIR/SVF. It remains subject to mapping review.

## Instrument and commands

Fork commit `66e29895748bd7a289b448a875d198711f1382dd`, separate
`modern_overlay.patch`, nightly-2026-08-21; exact hashes are in
[FOLLOWUP_REPORT.md](FOLLOWUP_REPORT.md) and `followup_results.json`.
Mode: `ander`; entry: source-level `chmod::main`. The binary source uses
`uucore::bin!(uu_chmod)`, so main's compiler source span points to the macro
definition in `src/uucore/src/lib/lib.rs:180`. This is the macro-generated Rust
main, not a runtime entry wrapper or the separate uumain anchor.

The isolated build used absolute pinned Cargo/rustc paths:

```text
cargo build --locked --manifest-path <fresh authenticated source>/Cargo.toml -p uu_chmod --bin chmod --target=x86_64-unknown-linux-gnu -j 2
cargo check --frozen --manifest-path <same source>/Cargo.toml -p uu_chmod --bin chmod --target=x86_64-unknown-linux-gnu -j 2 -v
```

Both used `CARGO_ENCODED_RUSTFLAGS` for `-Copt-level=0`, `-Cpanic=unwind`, and
`-Zalways-encode-mir`. Separate Cargo homes/targets under build preserved original
historical caches and binaries. Source-tree hashes before and after matched.
The pilot's `RUSTC_WRAPPER` forwards every compiler invocation unchanged except
the selected `chmod` binary, where it invokes the pinned PTA executable with the
same rustc arguments and:

```text
PTA_FLAGS=["--pta-type","ander","--entry-func","main","--dump-call-graph","<pilot>/graph.dot","--dump-dyn-calls","<pilot>/dynamic.txt"]
```

This small wrapper avoids the upstream cargo-pta metadata step that does not
forward the lock constraint. It neither changes dependency selection nor analyzes
host build scripts as program entry points. Full invocations are saved in
`historical-pilot/analysis-command.json` and `result.json`; the run had a 600-second
timeout and a 16-GiB address-space ceiling.

## Provisional observed graph

| Quantity | Observed |
|---|---:|
| Vulnerability shortest-call depth | 3 |
| Maximum finite shortest-call depth | 39 |
| Function-instance nodes / reachable nodes | 7,222 / 7,222 |
| Callsite-bearing edges | 17,919 |
| Body-unavailable nodes | 92 |
| Edges to unavailable bodies | 668 |
| Special-model nodes | 69 |
| Recognized zero-target indirect callsites | 35 |
| PTA wall time / peak RSS | 50.05 s / 509,320 KiB |
| Entire Cargo/analysis/adapter pilot wall time | 95.33 s |

Observed shortest path (all three edges classified direct):

```text
chmod::main
  → uu_chmod::uumain<Cloned<slice::Iter<OsString>>>
  → uu_chmod::uumain::uumain<Cloned<slice::Iter<OsString>>>
  → uu_chmod::{impl#1}::chmod
```

Callsites are `src/uucore/src/lib/lib.rs:198`,
`src/uu/chmod/src/chmod.rs:110`, and `src/uu/chmod/src/chmod.rs:171`.
The wrapper and inner uumain are retained as distinct instantiated functions.
The maximum is a BFS distance, not a longest-path computation. Its graph scope
includes reachable standard-library/dependency functions, shims, drop glue and
unavailable-body endpoints. This is not automatically comparable to prior compiler
versions or a source-only graph. All exported nodes being reachable is not a
claim of whole-program semantic coverage.

## Coverage gate and evidence

There are 20 zero-target DynamicDispatch sites, one DynamicFnTrait site and 14
FnPtr sites. Ten are instantiated `Any` dispatch sites at `core/src/any.rs:201`;
others include boxed callable dispatch, Fluent/library trait dispatch, lazy/TLS
initializers, clap and other library function pointers. Exact callers, source
locations and kinds are preserved in `followup_results.json` under
`pilot_unresolved_callsites`. The analyzer also emitted resolution warnings;
their log is preserved. A site with some targets can still have missing targets,
so this zero-target list is not a universal unresolved-call inventory.

Completion with exit zero does not establish graph soundness. Missing edges can
alter shortest paths or hide reachable functions; false edges can shorten paths.
Therefore depth 3 and Dmax 39 describe the exported graph only. They are **not
accepted historical measurements**, and no claim that Dmax is accurate for the
whole historical program is made. This pilot was run once; controlled determinism
was tested, historical repeat determinism was not.

All raw evidence is under
`build/rupta-v1/drop-trial/compatibility/historical-pilot/`: `graph.dot`,
`graph.dot.depth.json`, `normalized.json`, `graph.json`, `dynamic.txt`,
`analysis-command.json`, `analysis-exit.json`, `analysis.resources.txt`,
`stdout.log`, `stderr.log`, and `result.json`. The adjacent `historical-build/`
contains build-only logs and source authentication. `followup_results.json`
preserves the mapping, path, metrics, coverage, provenance and explicit
`accepted_historical_measurement: false` outside ignored build artifacts.

The next step is review of this mapping and graph scope, focusing on the saved
35 unresolved sites and 92 unavailable bodies. Bulk measurement remains blocked
until their effect is judged acceptable or the instrument is shown inadequate
for the requested metric. No broad pointer-analysis development is proposed.
