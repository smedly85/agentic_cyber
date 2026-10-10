# Diagnostic historical RUPTA v1

This directory is a new diagnostic dataset, not the canonical historical MIR
dataset. The current population task authorizes collection despite the earlier
pilot reports' historical-population stop recommendation. It does not authorize
acceptance of incomplete graphs. Analyzer algorithms and prior artifacts remain
unchanged.

Run from the repository root in Linux/WSL, with the existing isolated toolchains
and authenticated archive cache available:

```sh
python3 -m security.semantic_callgraph.rust_rupta_v1.population_runner pilot
python3 -m security.semantic_callgraph.rust_rupta_v1.population_runner smoke
python3 -m security.semantic_callgraph.rust_rupta_v1.population_runner population
python3 -m security.semantic_callgraph.rust_rupta_v1.population_runner refresh
python3 -m security.semantic_callgraph.rust_rupta_v1.population_runner report
python3 -m security.semantic_callgraph.rust_rupta_v1.verify_population
python3 -m pytest -q security/semantic_callgraph/rust_rupta_v1/test_population_adapter.py security/semantic_callgraph/rust_rupta_v1/test_population_runner.py security/semantic_callgraph/rust_rupta_v1/test_utility_scope.py security/semantic_callgraph/rust_rupta_v1/test_patched_adapter.py security/semantic_callgraph/rust_rupta_v1/test_adapter.py security/semantic_callgraph/cross_language_calibration/test_revision_freeze.py security/semantic_callgraph/rust_mir/test_dependency_inputs.py
```

The pilot gate independently re-normalizes and scopes the saved final chmod
analyzer output, authenticates source and compiler matches through the generic
runner, and requires depth 3, Dmax 12 and ratio 0.25, all provisional. This avoids
another expensive identical analyzer invocation. Smoke gates analyze mkfifo and
chown; the latter authenticates the shared uucore vulnerable definition.
The generic matcher uses the compiler DefId definition path, not the display
name's generic-argument spelling. The older 0.0.3 `uucore_procs::main!` generator
is authenticated separately from 0.2.2's `uucore::bin!`. `refresh` reprocesses
successful raw analyzer exports that failed an earlier collector check; it does
not rerun pointer analysis and preserves the prior postprocessing failure.

The analyzer is the existing rust-2026 fork
`66e29895748bd7a289b448a875d198711f1382dd`, with the separately recorded
Drop/reporting and map_err/Once overlays. Compiler: nightly-2026-08-21. Exact
binary, compiler and patch hashes are in `../scoped_provenance.json` and repeated
in the results JSON. The canonical original nightly-2024-02-03 baseline is
unchanged. No LazyLock/TLS/formatting repair is attempted.

Large evidence lives under ignored `build/rupta-v1/historical-diagnostic-v1/`:
authenticated extracted specimens, captured Cargo/rustc commands, resources,
full DOT and structured call graphs, normalized graphs, scoped graphs with
witnesses, and per-executable coverage frontiers. Existing build association
records determine package/bin/default-feature/target configuration; source
manifests and frozen mapping hashes are checked. Cargo uses the frozen lockfile.
The registry cache shares the existing locked-build cache; no dependency
versions or historical manifests are rewritten.

Each source/executable/target/configuration has one cache fingerprint covering
source provenance, lockfile, analyzer, compiler, patches and wrapper. Multiple
CVEs reuse that executable's graph. Completed and failed attempts are retained;
interrupted runs resume from completed results. Reproduction on fresh hardware
uses a fresh build root and the same authenticated inputs. Exact command arrays,
environment flags and direct dependency artifact hashes are in each attempt.
Each build has a 900-second timeout; analysis has 600 seconds and the existing
16-GiB address-space limit. No global toolchain or system packages are changed.

Source mapping uses authenticated path/hash, defining crate, source declaration
line and compiler DefPathHash. A narrow top-level impl recognizer disambiguates
same-named methods only when the frozen receiver identifies one declaration;
otherwise mapping fails closed. Function instances are preserved; a source
definition's depth is the minimum across its legitimate reached instances, with
all instance depths and paths retained. Multiple compiler definitions are
ambiguous, never resolved by taking the shallowest one. No MIR graph supplies
RUPTA edges.

The population reader omits the old adapter's fixture-only union-by-display-label
view. Historical dependency items can have equal display labels, and some
generic argument strings omit type/crate disambiguators. When the exported
definition/type/shim tuple collides, the reader appends the already exported
FuncId to retain the distinct upstream nodes and their exact edges. It does not
merge nodes, change target sets, or invent type information. The per-executable
identity audit records these collisions. Such suffixes are local to that analysis;
cross-run identity stability for those nodes is not established. The primary
scope projection still follows the original node topology. Context-sensitive
inputs are explicitly rejected by this ander-only reader, never flattened.

Windows, macOS and other-Unix source locations retain separate unsupported rows;
the Linux graph cannot supply their depths. Partially mapped CVEs retain their
incomplete classification, even for individually verified mapped locations.
Configuration-only CVEs have no function observation and remain in the CVE table.
Shared-uucore targets are outside the utility-only sensitivity scope; their
sensitivity depths and ratios are undefined, with an explicit exclusion status.

All depth histograms identify their unit. CVE profiles retain every distinct
observed depth and count each CVE once; no shallowest-location CVE distribution
is fabricated. Ratios use the same primary scoped graph and main entry for both
metrics. Source-function and executable/function units remain separate.
