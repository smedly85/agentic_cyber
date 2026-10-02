# Rust semantic instrument: stopped before historical measurement

> Revision note: this document and its JSON companions describe the original
> v1 instrument, whose provenance remains unchanged. The correction audit and
> current STOP gate are in
> [rust_audit_v2](../../semantic_callgraph/rust_audit_v2/README.md).
> Use that revision's runner and tests with the patched helper; the v1 runner
> requires its original instrument and is not the current validation command.

The frozen population, mappings, source manifest, mapping evidence and C historical
study are unchanged. Their three canonical JSON fingerprints are checked before
toolchain preparation, controlled execution, or publication. The canonical
encoding is sorted keys, UTF-8, no insignificant whitespace, as in the original
freeze. It is not a raw file-byte hash.

**Required trait-object dispatch validation failed. Historical pilots and
population measurement are prohibited.** This is an instrument compatibility
failure, not evidence that historical vulnerable functions are unreachable.
No historical specimen was built or modified.

## Actual instrument

- Linux x86-64 through WSL; target `x86_64-unknown-linux-gnu`.
- `rustc 1.93.0 (254b59607 2026-01-19)`, compiler revision
  `254b59607d4417e9dffbc307138ae5c86280fe4c`, LLVM **21.1.8**.
- `cargo 1.93.0 (083ac5135 2025-12-15)` recorded, not used in the fixtures.
- Ubuntu LLVM **21.1.8** assembler/linker/verifier.
- Existing SVF **3.4**, revision `67efb7745ce47b2b6853fd5696fc22c83d701e6c`;
  unchanged dedicated helper, AndersenWaveDiff, `-stat=false -ff-eq-base`.
- GNU `c++filt -s rust` for display names only. DISubprogram file/line/scope,
  not demangled names alone, establish controlled source identity.

`semantic_backend.json` pins actual tool outputs, helper hash and official Rust
component archive checksums. No alternate backend or lexical graph was used.

## Controlled extraction, not a historical extraction policy

The two synthetic `no_std` fixture crates are under
`tests/fixtures/rust_semantic/`. They are not cp/mv candidates or uutils source.
They contain a native `main` and independently configured exported case entries;
all case entries are reachable from native main, to rule out entry pruning.
They are compiled as rlibs for instrument testing, not claimed as a linker-exact
historical executable. The explicit fixture scope includes both application
crates and keeps a core panic routine at the system/runtime boundary.

Direct `rustc --emit=llvm-bc` emits each crate's bitcode, followed by `llvm-link`
of exactly those two modules. Flags are edition 2021, opt-level 0, full debuginfo,
one codegen unit, panic abort, embed-bitcode yes, explicit Linux target, and a
repository path remap. Fixture functions use inline-never to preserve controlled
edges. This must not be applied as a source patch to historical specimens.
LLVM disassembly and `opt -passes=verify` both succeed. Every one of the 32 LLVM
definitions has debug metadata and is represented by the helper. There are 45
semantic edges, including four resolved-indirect target edges across three sites,
and one unresolved trait-object site. No node contraction is applied.

The extraction choice is intentionally limited to this controlled experiment:

| Option | Investigation / decision |
| --- | --- |
| `--emit=llvm-bc` | Tested; produces the explicit modules and preserves the controlled functions/debug metadata. |
| `-C embed-bitcode=yes` | Explicitly enabled for the dependency rlib; direct `.bc` output is the analyzed input. This alone does not establish executable link scope. |
| `-C save-temps=yes` | Not needed for the controlled explicit modules; not tested as a historical acquisition mechanism. |
| Fat LTO | Not used; selecting a post-LTO representation could change application call structure. No historical acceptance claim. |
| Linker-plugin LTO | Not used; requires a separately validated link workflow. No historical acceptance claim. |

The [official rustc codegen documentation](https://doc.rust-lang.org/rustc/codegen-options/index.html#embed-bitcode)
explains why Cargo may disable embedded bitcode; ordinary Cargo artifacts cannot
be assumed suitable. See also the
[explicit output documentation](https://doc.rust-lang.org/rustc/command-line-arguments.html#--emit-specifies-the-types-of-output-files-to-generate).
No Cargo.lock, Cargo metadata, historical feature selection or historical
link-closure attestation exists yet. No workspace or dependency superset is
misrepresented as linker-exact. These stages were not attempted after the gate
failed.

## Results and stop condition

| Controlled case | Expected | Measured | Result |
| --- | ---: | ---: | --- |
| Direct | 2 | 2 | passed |
| Recursion | 2 | 2 | passed; self-edge retained |
| Function pointer | 2 | 2 | passed |
| Multi-target function pointer | 2 | 2 | passed; both may-targets retained |
| Struct-held function pointer | 2 | 2 | passed |
| Closure | 2 | 2 | passed; closure node retained |
| Generic function | 2 | 2 | passed |
| Static trait | 3 | 3 | passed |
| Dynamic trait object | 3 | — | **failed; unresolved dispatch** |
| Cross-crate direct | 2 | 2 | passed |
| Cross-crate indirect | 2 | 2 | passed |
| Duplicate module-local names | 2 | 2 | passed; distinct debug scopes/lines |
| Multiple LLVM instances | 1 | 1 | passed; both generic instances retained |

The shared function-pointer dispatcher has both targets under context-insensitive
whole-program may-analysis, even when one particular entry supplies only one.
Both edges are retained. The generic u8/u16 instances have identical source
file/line/scope and distinct LLVM symbols; both depths are preserved before MIN.
The closure is not contracted. Assertions validate path edge membership, edge
counts, complete emitted target sets and shortest-distance relaxation.

Full graph, direct/indirect edge provenance, debug scopes, demangled symbols,
per-instance paths, targets and unresolved sites are in `semantic_validation.json`.
`evidence/semantic-callgraph-validation.md` records the failing IR site.
The backend successfully parses this bitcode, but does not meet the required Rust
semantic instrument contract. This does not establish the cause inside SVF or
claim that every possible SVF/Rust configuration fails.

Pilots 35365 (mv), 2021-29934 (od), and 35354 (shared fsxattr) were **not run**.
`semantic_results.json` is explicitly blocked accounting, not historical results.
It preserves every frozen function/executable context with null depth/path and
an explicit reason. The two unresolved CVEs retain partial-location labels and
remain excluded from primary statistics; 35362 remains not applicable.
The [complete 45-CVE table](evidence/final-depth-table.md) has no numeric depths.
There are no historical function-level or CVE-level distributions.

## Reproduction on Linux x86-64

From the repository root, with the pinned existing LLVM21/SVF helper installed:

```sh
python3 security/historical/rust/semantic_gate.py
python3 security/historical/rust/prepare_semantic_toolchain.py
python3 security/historical/rust/validate_semantic_instrument.py
# Expected exit 1: dynamic_trait fails. STOP here; do not build historical sources.
python3 security/historical/rust/publish_semantic_stop.py
python3 security/historical/rust/validate_semantic_artifacts.py
python3 -m pytest -q tests/test_rust_semantic.py tests/test_rust_historical.py
```

Toolchain preparation downloads checksum-verified official rustc/std/cargo into
ignored `build/historical-rust/semantic/`; no system installation or historical
source changes. Full command logs, LLVM IR, bitcode, raw graph and per-entry graph
files remain in its `validation/` subdirectory. Committed commands replace the
machine-local repository prefix with `$REPO`; cached logs preserve exact argv.
The controlled suite uses no Cargo environment flags implicitly. A failed or
interrupted rerun writes a failed initial attestation rather than retaining a
previous success. Offline tests need neither Rust, SVF nor network access.

## Work explicitly deferred

A reviewed resolution of the failed semantic instrument is required before
historical bitcode acquisition, authenticated standalone executable closure,
compiler compatibility of the old specimen, source-instance mapping, or pilots.
There is no functioning population measurement command yet; a failure report is
not completion of those stages.

The future historical entry policy must inspect each standalone native wrapper:
use utility-owned source-qualified `uumain` only for proven mechanical startup;
record the wrapper and preserve substantive dispatch. Do not silently contract
closures/shims. Preserve raw LLVM paths. Rust dependencies linked into a utility
are program inputs, not external libc. Require justified exact scope, debug-backed
identity, complete may-targets and explicit nonnumeric failures.

Once validated, retain every legitimate monomorphized instance, take the minimum
reachable instance depth per executable, then the arithmetic mean across affected
executables for the `(CVE, verified source function)` primary unit. Retain all
function values and CVE min/max separately. No such averages were computed here.
