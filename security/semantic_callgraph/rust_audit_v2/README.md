# Rust semantic instrument correction audit (v2)

This is a new, explicitly local instrument revision. The original SVF and Rust
v1 provenance records and all C/Rust frozen historical artifacts remain intact.
**No Rust historical specimen is compiled, queried, or measured by these scripts.**
The final disposition is STOP, not permission to run pilots.

## Byte-offset defect and patch

Pinned SVF revision: `67efb7745ce47b2b6853fd5696fc22c83d701e6c` (SVF 3.4).
At the audit, upstream master `6a4bb08f11c121e6ea57fae6bc1a5b785a7cd663`
still returned zero from `inferFieldIdxFromByteOffset` and ignored constant byte
offsets in scalar GEPs. The upstream file and
[issue 524](https://github.com/SVF-tools/SVF/issues/524) are cached with URL,
retrieval date and SHA-256. No directly applicable upstream repair was found;
this is **a local patch**, not an upstream fix or wholesale upgrade.

`svf-byte-offset.patch` handles i8 byte GEPs using existing SVF object-type
inference, LLVM DataLayout/StructLayout offsets, and SVF flattened element
indices. It descends known aggregate layouts without rewriting LLVM IR, guessing
Rust source types or hardcoding vtable offsets. Negative, variable, out-of-layout,
interior-scalar and unstructured-byte-array cases become variant GEPs rather than
silently claiming field zero. Zero-offset pointers preserve base identity.
Other typed GEP handling remains unchanged.

This patch is not a general proof of correct field-sensitive Rust analysis:
SVF's object-type inference itself can choose one inferred layout. Heterogeneous
layout merges require further validation. Raw `[N x i8]` stack storage cannot be
treated as a recovered Rust struct. The explicit 16-byte/two-pointer fixture
shows **two actual targets versus one expected**, including the wrong first-field
target. The extra edge is a conservative false may-target, not an unresolved
site. It can shorten apparent paths (downward-depth bias); no historical bias
magnitude is estimated. `Box<dyn Trait>` and `Box<dyn FnMut>` also retain missing
dispatch targets. These defects are sufficient to block pilots.

## Compiled runtime nodes and definition inventory

The helper now retains definitions that previously vanished because their debug
filenames were absolute. `/rustc/<hash>/library/...` becomes `rust_std/...`.
These nodes are labeled `compiled_rust_runtime`; declarations without bodies
remain external, and runtime nodes are not automatically vulnerability candidates.
Unremapped absolute filenames receive retained-but-ineligible source identities;
matching them requires a real provenance remap. No-debug definitions receive
LLVM-qualified identities, preserving shims without pretending to know their
source location. Colliding source labels retain distinct LLVM instance suffixes.

`backend.analyze_build` independently inventories LLVM definitions with debug
metadata using the matching `llvm-dis`. Missing exported definitions cause an
explicit `analysis_failure`. External declarations are not required to have
bodies. This textual LLVM inspection inventories symbols only; it creates no
scientific call edges. All such edges still come from SVF AndersenWaveDiff.

## Rust source identity and entry policy

`rust_identity.py` uses crate, normalized file, full debug scope chain, declaration
line and balanced-generic-stripped source name. Impl/type scopes remain separate.
Every matching LLVM instance is retained in a deterministic group. Incomplete
or incompatible identities fail rather than selecting the first/reachable match.
Compiled std/core generics remain in paths through Option, Result and iterators.

Entry preparation locates authored declarations, requires a reviewed line/scope
when multiple `uumain`s exist, checks the forwarding wrapper's actual LLVM body,
and verifies the chain against SVF direct edges. A mechanical wrapper may have
argument/debug spills and one directly returned forwarding call; branching,
extra semantic operations and unreviewed unwind logic fail closed. The synthetic
outer/inner fixture proves two startup edges; unit tests also cover one and three.
Counts are computed, not historical-version constants. Raw graph edges stay
intact; entry selection records excluded startup edges separately.

**Historical 0.0.3/0.2.2 wrapper layers are not asserted as measured here.** Their
actual source/debug/body evidence must be supplied during a later authorized
build. This task validates the deterministic mechanism with representative
synthetic source, not the forbidden od/mv pilots.

## Controlled validation

There are 31 Rust cases: the original 13 plus 18 expanded probes. They cover
non-first fields, static tables, Drop, one/multiple trait arguments, boxed traits,
Fn/FnMut, Option/Result/flat_map, outer/inner generic entry wrappers, unwind IR,
scopeguard 1.2.0 from crates.io, static/dynamic method use, cfg branches, stack
byte storage and distinct impl methods. The fixture dependency is checksum-verified
and cached; subsequent runs and offline unit tests do not access the network.

Each adjudicated indirect site records expected/actual/unexpected/missing target
sets. Exact detectors reject supersets. Other runtime/startup/inline-assembly
sites are explicitly marked not adjudicated, never counted as proof of complete
instrument soundness. Expected source paths are asserted for the original cases
and Option/Result paths; all recorded path edge counts and membership are checked.
`results.json` preserves target instances, shortest paths, site verdicts and
failure details; full LLVM/graphs/logs remain under ignored build cache.

The instrument gate remains STOP for any failing detector, missing required
proof, or changed C result. Passing a subset is not sufficient for readiness.

## C compatibility

`run_c_regressions.py` runs the complete original 11-case C manifest, without
changing expected results. It also replays the exact frozen-hash-authenticated
LLVM modules for all nine original C historical validation observations.
This isolates the instrument change; it is not a fresh source-build claim.
Copies are analyzed outside the historical cache; input hashes are rechecked.
Depth, full shortest path, direct/indirect composition and target sets, reachability
and mapping status must agree exactly. The original 9.7 archive-superset bitcode
was relocated to the later scope-checkpoint cache; only its exact frozen SHA-256
allows use. No scope relabeling or C golden changes are made.

See `results.json` and the final audit summary for actual C comparison outcomes.

## Missing test audit

Commit `aa56f2e902dc01f84f33e42c16580426575c0390` deleted
`tests/test_aider_output.py` and `tests/test_rust_lineages.py` without replacement
or a documented supersession. The controller scripts they exercise are unchanged
from `6d08be35`; these still-relevant tests were restored from that revision.
`tests/test_rust_semantic.py` and `tests/test_rust_historical.py` never appeared in
committed history despite README references. New offline replacements cover the
frozen invariants, identity/entry/inventory guards and audited instrument evidence.
No controller implementation or cp/mv prompt/corpus was changed.

## Reproduction (Linux x86-64, LLVM 21.1.8)

```sh
python3 security/historical/rust/semantic_gate.py
python3 security/semantic_callgraph/rust_audit_v2/acquire.py  # explicit network preparation only
python3 security/semantic_callgraph/rust_audit_v2/build_instrument.py
python3 security/semantic_callgraph/rust_audit_v2/run_rust.py
python3 security/semantic_callgraph/rust_audit_v2/run_c_regressions.py
python3 security/semantic_callgraph/rust_audit_v2/publish.py
python3 -m pytest -q tests -rs
```

Rust is the isolated 1.93.0 / LLVM 21.1.8 compiler. Existing probes use panic abort;
expanded binary probes use panic unwind. Flags, command logs, bitcode/module
hashes, actual helper/library hashes, dependency evidence and patch identity are
recorded separately. No LLVM input rewriting, manually injected targets, MIR or
Tree-sitter-derived edges are used. Original provenance is not overwritten.

## Future linker-exact scope checklist — preparation only

No Rust historical scope is labeled linker-exact here. Future acceptance requires:

- exact Cargo and per-crate rustc argv, crate type/source root, resolved features,
  target, edition, panic strategy, codegen units and cfg/platform ledger;
- Cargo.lock bytes/identity, or explicit authenticated absence and resolution
  provenance; Cargo metadata and all `--extern` relationships;
- exact final linker argv, executable hash and symbol/link-map evidence tying
  each compiled crate/codegen unit to linked code, not merely workspace presence;
- standalone utility versus multicall executable classification and reviewed
  entry-wrapper provenance;
- build-script environment and generated-output manifests/hashes; proc-macro
  and build-host tooling excluded from target executable scope;
- project and crates.io runtime dependencies included when linked; explicit
  std/runtime/CRT/system boundaries, without dropping compiled generic bodies.

Incomplete evidence must remain reconstructed scope/dependency superset and must
not receive primary linker-exact numeric reporting.
