# RUPTA feasibility experiment v1

**STOP: promising indirect-target precision, not ready for historical depths.**
Canonical, unpatched RUPTA builds and resolves all 23 adjudicated resolved-call
target sets exactly in both modes. This includes all five persistent patched
SVF failures. Both modes match the inherited required checks for 33/35 programs,
but omit a scopeguard destructor/callback route and do not satisfy the inherited
external/unresolved reporting contract. Many otherwise matching graphs have
drop or library scope gaps. The pinned compiler also rejects historical uutils
0.2.2's edition-2024 manifest. No historical analysis was performed.

Read [VALIDATION_REPORT.md](VALIDATION_REPORT.md),
[METHOD_COMPARISON.md](METHOD_COMPARISON.md),
[HISTORICAL_COMPATIBILITY.md](HISTORICAL_COMPATIBILITY.md), and
[LIMITATIONS.md](LIMITATIONS.md). Machine-readable results are in
[validation_results.json](validation_results.json); compiler/analyzer hashes
and actual CLI help are in [provenance.json](provenance.json).

## Instrument and installation

- Upstream: <https://github.com/rustanlys/rupta>, commit
  `b19f187e9cbe37b5afb1103d88b663253e1f0a03`.
- Documentation: <https://rustanlys.github.io/rupta/> and checked-out README,
  Cargo.toml, Cargo.lock, rust-toolchain.toml, CLI source and exporter source.
- Toolchain: `nightly-2024-02-03`, rustc `1.77.0-nightly`
  (`bf3c6c5bed498f41ad815641319a1ad9bcecb8e8`), Cargo `1.77.0-nightly`
  (`7bb7b5395`, 2024-01-20), LLVM 17.0.6, x86_64-unknown-linux-gnu.
- Pinned components: rust-src, rustc-dev, llvm-tools-preview, rustfmt-preview,
  clippy-preview, plus the minimal compiler/Cargo/std components.
- Local debug build: `cargo +nightly-2024-02-03 build --locked -j 4`, using
  upstream's lockfile without dependency updates. Build completed in 4m56s.
  No source, algorithm or compatibility patch was necessary.
  This records one successful clean build and a pinned reproduction recipe;
  an independent second clean build/binary-reproducibility check was not run.
- Analyzer SHA256:
  `ee837cc094bf909148b07fd8b8f8dd996654dcf27fbfc02f041cc20c65153395` (`pta`);
  `870cecb4e196394002a113a5b2ab219a356183e42d505abd450cf3be74a47564` (`cargo-pta`).

`setup.sh` installs rustup, compiler components, Cargo caches and build outputs
strictly under ignored `build/rupta-v1`. Its isolated RUSTUP_HOME has its own
default; the user's default toolchain and shell profiles are unchanged.
rustup-init is downloaded over HTTPS and checked against the upstream SHA256;
rustup verifies component checksums. This is checksum/HTTPS provenance, not a
claim of independently verified release signatures. No system packages changed.

The source parser and actual executable help confirm:

```text
pta [OPTIONS] INPUT -- [RUSTC OPTIONS]
--pta-type ander                    # aliases: andersen
--pta-type cs                       # alias/default: callsite-sensitive
--context-depth 1                   # default without rceus
--entry-func NAME                   # unqualified-name lookup; verify selection
--entry-id LOCAL_DEF_INDEX          # compiler-specific local definition index
--dump-call-graph graph.dot         # only call-graph export format
--dump-mir mir.txt
--dump-dyn-calls dynamic.txt        # hidden flag verified in options.rs
--dump-pts points-to.txt
```

Neither stack filtering nor rceus is enabled. cs depth 2 was not run: both
modes already match all designated resolved target sets, and the failures are
not evidence of insufficient context depth. `pta --help` prints RUPTA help to
stderr and then compiler help to stdout; both are preserved in provenance.

Cargo integration is `cargo-pta pta [CARGO OPTIONS] -- [PTA OPTIONS]` with both
executables in the same directory and the pinned toolchain on PATH. The wrapper
uses cargo check/test --no-run, RUSTC_WRAPPER and always-encode-mir. This experiment
uses explicit pta paths and rustc-built local rlibs instead, matching the
existing controlled crate inventory. No historical Cargo analysis was run.

## Architecture and reuse

```text
unchanged fixture source + pinned dependency source
  → pinned rustc/MIR inside canonical pta (ander or cs depth 1)
  → DOT + resolved-dynamic-call dump + reachable-function MIR dump
  → strict adapter with explicit missing/export boundary information
  → unchanged backend.finalize_semantic_graph
  → per-entry BFS paths and maximum finite shortest-path distance
```

The following infrastructure is reused without edits:

- `rust_llvm_svf_v1.validate.controlled_programs`, `calibration_programs`,
  and `verify_preregistration`: the 35-program inventory, unchanged sources,
  frozen dependency and expectations, with prior amendments read explicitly.
- `adjudicate` and `evaluate_case`: exact target sets, independent required
  relations, unreachable targets, generic instance counts and path/depth rules.
- `backend.finalize_semantic_graph`: deterministic BFS. No C/SVF graph supplies
  a RUPTA edge. The adapter corrects backend labels in the returned metadata.
- `rust_identity.strip_generic_arguments`: fixture matching only; normalized
  graph identities retain printed generic arguments. Historical source mapping
  (`rust_mir_lightweight.mapping`) is inspected, not applied or modified.
- Existing MIR and SVF result files: comparison evidence only. The compiler-
  resolved MIR method deliberately reports incomplete known-edge graphs.

`adapter.py` reads only RUPTA artifacts when constructing nodes/edges. It
rejects duplicate display identities and unknown DOT syntax, checks the dynamic
dump against DOT, and classifies other edges only with matching static MIR call
evidence. Unknown edge kinds block shared finalization. MIR may add an isolated
reachable node or a boundary observation, never an invented edge. Static
calls with no exported edge and Drop terminators are preserved as scope evidence.
Unresolved observations are explicitly incomplete; a missing total is null.

The upstream exporter already unions contexts by FuncId before writing DOT.
This adapter does not claim to recover contexts or flatten source functions.
Each printed monomorphization remains separate. BFS is over the upstream
function-reference projection, including all exported library nodes and
body-unavailable boundary nodes. Projection may join incompatible contexts
and shorten paths. Equal BFS code does not establish equal scientific metrics.

Fixture label mapping is deliberately restricted to the authenticated, small
source files: crate ownership, frozen declaration lines, lexical module/impl
scope, and qualified closure/nested-function names. The dynamic callsite is
matched only when exactly one indirect MIR site exists in that mapped owner.
No expected target is used to choose the observed site. Ambiguous/absent matches
fail. This is not a production historical mapping implementation: exports lack
full compiler identity and source spans.

`main` is explicit for instrument/expanded; calibration retains its frozen
scientific `entry`; supplemental library entries are analyzed independently.
For historical utility design, source main is the appropriate proposed primary
anchor, with separately authenticated outer/inner uumain sensitivity anchors.
Unqualified name lookup is unsafe: invalid names fall back to main and duplicate
names can select the last match. Compiler entry wrappers are not MIR source main.

## Reproduction

Run under WSL/Linux from the repository root. A fresh checkout/output directory
is required for analysis commands: they refuse to reuse per-run folders. Existing
outputs can be re-adjudicated/reported without recompilation. Do not rerun old
historical publishers or change frozen toolchain directories.

```bash
git clone https://github.com/rustanlys/rupta.git build/rupta-v1/upstream
git -C build/rupta-v1/upstream checkout --detach b19f187e9cbe37b5afb1103d88b663253e1f0a03
bash security/semantic_callgraph/rust_rupta_v1/setup.sh
python3 security/semantic_callgraph/rust_rupta_v1/inspect.py before
python3 security/semantic_callgraph/rust_rupta_v1/regression.py before
python3 -m security.semantic_callgraph.rust_rupta_v1.provenance
python3 -m security.semantic_callgraph.rust_rupta_v1.probe
python3 -m security.semantic_callgraph.rust_rupta_v1.probe basic-repeat
python3 -m security.semantic_callgraph.rust_rupta_v1.validate
python3 -m security.semantic_callgraph.rust_rupta_v1.evaluate
python3 -m security.semantic_callgraph.rust_rupta_v1.entry_probe
python3 -m security.semantic_callgraph.rust_rupta_v1.root_sensitivity
python3 security/semantic_callgraph/rust_rupta_v1/historical_check.py
python3 -m pytest -q security/semantic_callgraph/rust_rupta_v1/test_adapter.py \
  security/semantic_callgraph/cross_language_calibration/test_revision_freeze.py \
  security/semantic_callgraph/rust_mir/test_dependency_inputs.py
python3 security/semantic_callgraph/rust_rupta_v1/inspect.py after
python3 security/semantic_callgraph/rust_rupta_v1/regression.py after
python3 -m security.semantic_callgraph.rust_rupta_v1.report
```

Every analyzer invocation has `command.json` with exact argv, working directory,
explicit environment, status, timeout and resource cap. Source inputs and hashes
are in `build/rupta-v1/validation_inputs.json`; GNU time output, stderr, stdout,
raw DOT, dynamic dump, MIR, normalized graph and finalized graphs remain under
`build/rupta-v1`. Setup transcript is `logs/setup.log`. Large binaries, compiler
installations, cloned source and temporary analysis artifacts are all ignored.
The reports retain compact outcomes and provenance for local review.

## Disclosed harness refinements

Acceptance criteria were written before building/running RUPTA. They inherit
the earlier expectations, whose disclosure/amendments are preserved unchanged.
New basic probes are derived from the user's explicitly specified relationships;
their automated summary was added after examining their output.

During adapter testing, MIR function-pointer casts with `->` in their types
were initially mistaken for calls, and appended MIR FOR CTFE bodies initially
overwrote runtime basic-block locations. The parser was corrected to require a
call terminator and to use the first runtime body. Diverging calls printed as
`-> bbN` were added to the grammar. These corrections use only exported syntax;
no analyzer output, source, expected target or algorithm was changed. Six
focused adapter/BFS tests exercise these issues and rejection of unsafe mappings.

Post-corpus entry diagnostics demonstrate invalid-name fallback and isolated
entry omission. A separate main-root sensitivity checks dynamic dispatch and
mixed stack/static and stack/heap fixtures with their harness decoys included;
it does not replace primary entry-root results. No deeper-context or algorithm
sensitivity was used to rescue a failed fixture.

## Decision and next step

Do not advance to historical measurements. The smallest useful engineering
experiment is a separate, validated drop/callback and structured-export design:
retain full rustc function-instance/context identity, source locations, explicit
unresolved calls and missing-body boundaries, with isolated-entry support. Keep
that instrument distinct from the canonical evidence here. A separately
validated port to a compiler supporting the frozen programs is also necessary.
Neither an exporter fix nor higher context depth alone solves all blockers.

No existing research file was intentionally changed; preservation verification
and regression outcomes are recorded in validation_results.json. No commits or
pushes were made.
