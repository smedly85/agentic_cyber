# Frozen historical compatibility

Historical measurement is blocked for canonical RUPTA. No historical pointer
analysis or depth calculation was performed, and no historical source,
dependency, manifest, lockfile or provenance was changed.

The existing study uses rustc 1.93.0 and authenticated per-crate editions,
dependency builds and immutable MIR snapshots. RUPTA uses unstable rustc-private
APIs and pins nightly-2024-02-03, rustc 1.77.0-nightly
`bf3c6c5bed498f41ad815641319a1ad9bcecb8e8`, LLVM 17.0.6. Those snapshots cannot
be consumed by a different compiler's private MIR API.

| Specimen | Read-only evidence | Assessment |
|---|---|---|
| 0.2.2, `3a07ffc5a9bd4c283e75afa548ba1f1957bad242` | Root manifest requires Rust 1.85.0; workspace edition 2024; Cargo.lock format 4. Pinned Cargo metadata exits 101 at the edition2024 feature gate. | Incompatible unchanged. No dependency resolution or build was attempted. |
| 0.0.3, `2bb9a85ddedc7b8aa1bd866bd70e41364c8783f7` | Authenticated manifest and older lock are readable by pinned Cargo; frozen, no-dependencies metadata exits 0. | Manifest compatibility only. Locked dependency compilation, proc macros and native dependencies remain untested. |
| 0.5.0, `64203e309810d7e01eaf9c6cc7c21df22a8a896d` | Configuration-only specimen in the frozen population, not a function-depth build context. | No analysis/build performed; no broader compatibility claim. |

`historical_check.py` verifies both manifest and lock hashes against existing
source provenance before invoking `cargo metadata --no-deps --frozen`, then
checks that the files remain byte-identical. Exact argv, output and hashes are
in `build/rupta-v1/historical_metadata.json`. `inspect.py` inventories editions
and minimum versions without editing any files.

No attempt was made to add `cargo-features`, downgrade edition 2024, relax
rust-version, regenerate the lock, upgrade dependencies, or reuse another
compiler's rlibs. Cargo's suggestion to enable edition2024 is not evidence that
this old nightly implements the final language semantics or required APIs.

For a future compatible instrument, Cargo integration must analyze the actual
utility/root crate with the original features and all dependencies compiled
with MIR encoding. Upstream `cargo-pta pta ... -- ...` wraps rustc, compiles
nonselected crates normally, and invokes pta for the selected target. Build
scripts and procedural macros run on the host and must retain their original
inputs/environment; their execution is not a runtime utility call edge.
The wrapper supports optional `PTA_BUILD_STD` to rebuild the standard library.
That changes analysis scope and must be a separately recorded configuration,
not an implicit cure for missing library bodies.

This Linux-only experiment does not establish compatibility for the frozen
macOS-specific observations. Native libraries, build scripts, proc macros,
lock resolution and full multi-crate builds all need independent verification
after compiler compatibility is solved. A newer-compiler port must first be
validated as a separate instrument on the unchanged controlled corpus.
