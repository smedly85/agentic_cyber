# Rust → rustc → MIR → LLVM IR → SVF call-graph experiment, v1

**Status: NOT ACCEPTED for historical depth measurement (STOP, task §11).**
The pipeline is implemented and runs end to end. Bitcode is complete,
verified and fully identity-covered, and the C instrument is provably
unchanged. But under the C study's own SVF configuration the mandatory
trait-object dispatch case still fails, and the failures trace to five
specific, source-proven mismatches between SVF 3.4's memory model and the IR
rustc emits. Three general SVF corrections were built and tested as separate
sensitivity instruments. They repair dynamic dispatch through vtables, but
stack- and heap-held Rust aggregates still produce false or missing targets.
No historical Rust depth, no historical CSV/JSON and no MIR-versus-LLVM/SVF
numeric comparison was produced. They are withheld, not lost.

Evidence:
- `VALIDATION_REPORT.md` (generated tables) and `validation_results.json`
  (machine-readable);
- `entry_probe_results.json` and `mechanism_probe_results.json` (post-hoc
  diagnostics);
- `ACCEPTANCE_CRITERIA.md` and `expectations.json`, preregistered, with
  hashes in `preregistration.json`;
- `AMENDMENTS.md`: harness changes after the first smoke run, and a
  disclosure (A-5) that prior-audit outputs for the `instrument`/`expanded`
  fixtures were read before preregistering. The 15 calibration expectations
  predate this work and give the same decision on their own.

Bitcode, IR, raw helper output and every finalized graph are under
`build/rust-llvm-svf-v1/validation/` (git-ignored).

## 1. What was reused and what was added

Reused unchanged:

- the structured SVF helper `native/semantic_callgraph_svf.cpp` and its
  canonical binary `build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf`
  (SHA-256 `ca8ce8cd…`, SVF 3.4 at `67efb774`, AndersenWaveDiff,
  `-stat=false -ff-eq-base`);
- `backend.finalize_semantic_graph` (deterministic BFS),
  `backend.validate_definition_inventory`, `backend.SVF_HELPER_OPTIONS`;
- `rust_identity.strip_generic_arguments`;
- the Rust 1.93.0 / LLVM 21.1.8 toolchain in `build/rust-mir/toolchain` and
  LLVM 21.1.8 tools in `/usr/lib/llvm-21/bin`;
- the controlled fixtures `tests/fixtures/rust_semantic/{instrument,dependency,expanded}.rs`,
  the 15 frozen C/Rust calibration pairs and their manifest, the committed C
  calibration results (`pair_results.json`), and the hash-authenticated
  scopeguard 1.2.0 dependency;
- the byte-offset SVF patch from the deleted `rust_audit_v2`
  (`git show b7484fa0^:security/semantic_callgraph/rust_audit_v2/svf-byte-offset.patch`),
  restored verbatim.

Added (all in this directory; nothing outside it was modified):

| File | Purpose |
|---|---|
| `pipeline.py` | rustc → bitcode per crate, `llvm-link`, `opt -passes=verify`, `llvm-dis`, helper invocation, definition inventory, finalization |
| `validate.py` | controlled validation: compiles every program fresh, runs every configuration, twice, adjudicates against the preregistration |
| `report.py` | writes `validation_results.json` and `VALIDATION_REPORT.md` |
| `entry_probe.py` | entry-policy diagnostic (`entry_probe_results.json`) |
| `mechanism_probe.py`, `fixtures/mechanism/*.c` | post-hoc F4/F5 probes (`mechanism_probe_results.json`) |
| `fixtures/supplement.rs` | mutual recursion, a 4-level chain, a body-unavailable callee, a pointer from a body-unavailable function |
| `ACCEPTANCE_CRITERIA.md`, `expectations.json`, `preregistration.json` | preregistration |
| `AMENDMENTS.md` | three documented post-smoke harness/instrument amendments |
| `sensitivity_svf/` | `build_sensitivity_svf.sh` and three patches (sensitivity instruments only) |

## 2. The existing architecture (task §1)

1. **C → bitcode.** `backend.build_bitcode` runs `clang -std=c11 -g -O0
   -fno-inline -fno-builtin -fno-discard-value-names
   -fdebug-compilation-dir=. -fdebug-prefix-map=<root>=. -emit-llvm -c` once
   per translation unit.
2. **Link/verify.** Modules are combined with `llvm-link` into `linked.bc`.
   The C path relies on `validate_definition_inventory` (every debug-carrying
   definition must be exported). This experiment additionally runs
   `opt -passes=verify` on every Rust module.
3. **AndersenWaveDiff.** The helper calls `LLVMModuleSet::buildSVFModule`,
   builds the SVFIR with `SVFIRBuilder`, then
   `AndersenWaveDiff::createAndersenWaveDiff(pag)`.
4. **Edges.** The helper walks every `CallICFGNode`. A direct call becomes a
   `direct` edge. An indirect call becomes one `indirect_resolved` edge per
   target in `andersen->getIndCSCallees`, with the sorted target set and its
   cardinality.
5. **Unresolved.** An indirect site with no target *that has an identity*
   becomes `unresolved_indirect_callsite`. Calls to functions without an
   identity become `external_or_unavailable_definition`.
6. **Identity.** `source_file::DISubprogram-name`, with `#llvm=<symbol>`
   appended when two definitions share a source identity. Functions with no
   `DISubprogram`, or with an absolute debug path, get no node.
7. **Depth.** `finalize_semantic_graph` sorts edges, BFSes from one entry
   identity, and records depth and one deterministic shortest path per node.
   Maximum depth is the maximum finite BFS distance (computed by consumers).
8. **CVE mapping.** C: `semantic_validation.map_source_identity`, exact
   `source_file` + function name, with ambiguity reported, never resolved by
   symbol order. Rust MIR: `rust_mir_lightweight/mapping.definition_matches`
   (crate, source file, span line, `fn` declaration, DefPath).
9. **Previous Rust LLVM/SVF attempts** (all removed from the work tree in
   `b7484fa0`, recoverable with `git show b7484fa0^:…`):
   - **v1** (`historical/rust/evidence/semantic-callgraph-validation.md`):
     `dynamic_dispatch` unresolved.
   - **`rust_audit_v2`:** the byte-offset patch plus a modified helper; 28/31
     Rust cases passed.
   - **`rust_audit_v3`:** STOP, citing byte-array stack storage, the C++
     vcall heuristic and the allocator boundary.

   This experiment re-tests those claims independently on the live
   toolchain rather than relying on them.
10. **Reusable tests.** See §1. The repository's pre-existing Python
    regression checks are `historical/rust/semantic_gate.py`,
    `rust_mir_lightweight/{verify_results,integrity}.py`, and the pytest files
    `cross_language_calibration/test_revision_freeze.py` and
    `rust_mir/test_dependency_inputs.py`.

## 3. Pipeline as implemented

```
Rust source
  └─ rustc 1.93.0 (254b5960; LLVM 21.1.8): parse → HIR → MIR (rustc-internal) → LLVM IR
       --emit=llvm-bc[,link]  --target=x86_64-unknown-linux-gnu
       -C opt-level=0 -C debuginfo=2 -C codegen-units=1 -C panic=unwind
       --remap-path-prefix=<repo>=.  --remap-path-prefix=<sysroot>/lib/rustlib/src/rust=rust_std
  └─ one .bc per crate (dependencies first, linked via --extern rlibs)
  └─ llvm-link 21.1.8 → linked.bc → opt -passes=verify → llvm-dis (inventory only)
  └─ semantic-callgraph-svf (SVF 3.4 @67efb774, AndersenWaveDiff, -stat=false -ff-eq-base)
  └─ backend.finalize_semantic_graph → BFS depth, shortest path, Dmax
```

Settings and why:

- **`opt-level=0`:** the MIR inliner and LLVM's inliner stay off. Only
  `#[inline(always)]` std bodies (for example `Box::new`) are folded by LLVM's
  always-inliner. This mirrors C's `-O0 -fno-inline`.
- **`codegen-units=1` and no LTO:** one module per crate; LTO would inline and
  merge across crates before SVF sees the IR.
- **`debuginfo=2` plus remaps:** every function gets a relative
  `DISubprogram` identity. Without the std remap, compiled std/core/alloc
  generic bodies would carry absolute paths and be silently dropped by the
  helper; that cut call chains such as `Option::map → closure` in testing.
- **`panic=unwind`:** Cargo's default, and what the frozen historical builds
  used.
- Overflow checks and debug assertions follow the dev-profile defaults.

Tool identities and every hash are recorded in `validation_results.json`
(`toolchain_before` / `toolchain_after`).

Cargo programs, which were *not* executed here: the historical builds in
`build/historical-rust-measurement/method-v1` used the same rustc 1.93.0 and a
`RUSTC_WRAPPER` (`historical/rust/capture_rustc.py`). A future LLVM/SVF run
would add `--emit=llvm-bc,link -C codegen-units=1` in that wrapper for every
*target* crate compilation (excluding build scripts and proc-macros, which run
on the host), then link the application crate, `uucore` and every linked
crates.io dependency. A single crate's `.bc` does not represent the
executable.

## 4. Program scope

| Node class | Included as | Source |
|---|---|---|
| application crate(s) | nodes with bodies | compiled to bitcode |
| dependency crates compiled from source | nodes with bodies | compiled to bitcode |
| std/core/alloc generic code monomorphized for the program | nodes with bodies, `rust_std/library/...` | emitted into the user crate by rustc |
| compiler-generated shims (closure `call_once`, `{{vtable.shim}}`, `drop_in_place`) | nodes with bodies | emitted by rustc, mostly with `rust_std` paths |
| precompiled non-generic std functions (`lang_start_internal`, panics, I/O) | external declarations, no node | std rlibs ship no bitcode |
| allocator shims (`__rust_alloc`), libc, intrinsics | external declarations | — |
| rustc's C-ABI `main` wrapper | **no node** (no `DISubprogram`) | listed in the inventory |

Every LLVM definition is accounted for in each program's inventory. All
debug-carrying definitions were exported (A2 holds), and the only definition
without debug info in a binary is `@main`.

This scope differs structurally from C's. In C, libc bodies are absent (calls
end at `qsort`, `malloc`, …). In Rust, std's *generic* layer is compiled into
the program and becomes part of the graph. The calibration pair
`library_callback` shows the consequence: C's `qsort` comparator is
unreachable (external boundary), while Rust reaches its comparator through
compiled `sort_by` machinery at depth 7 (the committed MIR calibration measurement, made with a rebuilt std, reported 8).

## 5. Function identity and vulnerable-function mapping

A preregistered function label is `(source_file, DISubprogram line, name with
generic arguments stripped)`. All matching LLVM functions are retained, so
every monomorphized instance stays a distinct node. A function's depth is the
minimum over its reachable instances, and each instance's own depth and path
are kept. Closures are `{closure#N}` on their own line. Methods of different
impls are distinguished by definition line.

`rust_identity.py`'s scope-chain grouping would be stronger for historical
mapping (impl/trait scope), but it requires fields only the retired v2 helper
emitted. For a historical run the frozen `vulnerable_function_mappings.json`
would be mapped with the same rule as `rust_mir_lightweight/mapping.py`
(source file + declaration line + name), and ambiguity would be reported,
never resolved by symbol order. This was not executed.

## 6. Depth definitions (unchanged from the C study)

- d(e, v) = length of the shortest directed call path from entry e to v, by
  BFS over the semantic static may-call graph. The entry has depth 0, and each
  call transition (direct, or one resolved indirect target) is one edge.
- For a source function with several instances: the minimum over correctly
  mapped reachable instances, with per-instance results preserved.
- Dmax = max over reachable v of d(e, v): the **maximum finite shortest-path
  distance, not the longest simple path**. Validation records it per case as
  `maximum_finite_shortest_path_depth`.
- An SVF-resolved indirect edge is a possible static target, not proof of
  execution.

## 7. Entry-point policy

| Anchor | Status in the LLVM/SVF graph |
|---|---|
| executable C-ABI `main` (rustc-generated) | **no node**: no `DISubprogram`, so the helper drops it |
| `std::rt::lang_start<()>` (compiled generic wrapper) | has a node, but the user `main` is **unreachable from it in all 18 `expanded` binaries probed** (`entry_probe_results.json`; the 15 calibration binaries were not probed). The route passes through precompiled `lang_start_internal` (external) and a function pointer that SVF cannot resolve (`__rust_begin_short_backtrace`, `call_once<fn()>` are unresolved sites). |
| source-level `fn main` of the binary crate | **primary policy for any future historical run.** This is the analog of C's source `main`. |
| `uumain` (the MIR study's anchor) | sensitivity anchor only; it sits at least one edge below `main` in uutils. Mixing it with C's `main` would compare different entry semantics. |

## 8. Controlled validation

There are 35 Rust programs: 20 controlled ones (`instrument` with its
dependency crate, 18 `expanded` cfg variants with the scopeguard crate, and
`supplement`) plus the Rust halves of the 15 calibration pairs. There are 15 C
programs, the C halves of the same pairs. That covers direct and nested calls, recursion and mutual
recursion, generics with multiple instances, static and dynamic trait dispatch
with one and several impls, function pointers (single, multiple, in structs,
in statics), closures, `dyn Fn`, `Box<dyn Trait>`, `Box<dyn FnMut>`,
cross-crate direct and indirect calls, a crates.io dependency, std adapters
(`Option::map`, `Result::or_else`, `flat_map`), unwind and drop glue,
same-named methods, cfg/platform selection, the outer/inner `uumain` shape, a
body-unavailable callee and a pointer whose only origin is a body-unavailable
function.

Every program was compiled from source, linked, verified, analyzed and
adjudicated twice, in fresh directories, under seven instruments:

| Id | Instrument | Role |
|---|---|---|
| `P` | canonical C helper, `-stat=false -ff-eq-base` | primary (the C study's instrument) |
| `P-noffeq` | canonical, `-stat=false` | `-ff-eq-base` sensitivity |
| `S` / `S-noffeq` | byte-offset + Rust vcall gate | sensitivity |
| `S-bo` / `S-vg` | one patch each | cause attribution |
| `S3` | byte-offset + vcall gate + allocator annotations | sensitivity |

Headline numbers (see `VALIDATION_REPORT.md` for every site and case):

| | `P` (primary) | `S` | `S3` |
|---|---|---|---|
| Rust programs passing all expectations | 20/35 | 30/35 | 30/35 |
| adjudicated Rust indirect sites exact (amended / strict) | 9/24 / 5/24 | 19/24 / 15/24 | 19/24 / 15/24 |
| mandatory `dynamic_dispatch` (line 73) | **missing both targets; target unreachable** | exact, depth 3 | exact, depth 3 |
| C calibration programs passing | 15/15 | 15/15 | 15/15 |
| deterministic over two fresh runs | yes | yes | yes |

*Strict* counts preregistered indirect sites only. *Amended* additionally
counts the four calibration sites that rustc compiled to direct calls to
exactly the expected target (`AMENDMENTS.md` A-2). The decision is the same
under both readings.

## 9. Why it fails: proven causes and hypotheses

Each item is labelled **proven** (source inspection plus an observed
controlled outcome or an ablation) or **hypothesis**.

**F1 — constant byte offsets are discarded (proven; primary-configuration blocker).**
rustc 1.93 addresses every field, vtable slot and spilled pair with
`getelementptr inbounds i8, ptr %p, i64 <bytes>`. In SVF 67efb774,
`SVFIRBuilder::computeGepOffset` takes the single-value-type branch for such
GEPs and leaves the comment "For pointer arithmetic we ignore the byte offset".
`inferFieldIdxFromByteOffset` returns 0. Every nonzero byte offset is
therefore modeled as field 0. The vtable `@vtable.N = <{ [24 x i8], ptr }>`
keeps its method in flattened field 1, and the load at byte offset 24 reads
field 0 (the `[24 x i8]` header), which holds no function. So
`dynamic_dispatch` has an empty target set and is reported unresolved. The
same mechanism returns *the wrong field* for typed statics: `static OPS = Ops
{ a: third, b: target }` read at offset 8 yields `{third}` instead of
`{target}` (`nonfirst_reference`, `static_table`). That is a wrong edge
presented as resolved. Ablation: `S-bo` (byte-offset patch alone) makes
`dynamic_dispatch`, `dyn_one`, `dyn_many`, `dyn_fn` and both statics exact.

**F2 — Rust fat-pointer calls match SVF's C++ virtual-call heuristic (proven).**
`cppUtil::isVirtualCallSite` accepts any indirect call whose callee is
`load(gep(load(...)))` with one GEP index and a pointer first argument. A
trait object spilled to the stack and reloaded has exactly that shape.
`BVDataPTAImpl::onTheFlyCallGraphSolve` then sends the site only to
`resolveCPPIndCalls`, which needs a C++ class hierarchy that Rust does not
have. SVF has no option that disables this routing (`-v-call-cha` only
chooses CHA versus vtable points-to). Ablation: `Box<dyn Trait>`
(`box_trait`) and the calibration `dyn_vtable` fail under `S-bo` and under
`S-vg` alone and pass only with both patches (`S`). The borrowed
`dynamic_dispatch` passes with `S-bo` alone because its vtable is a parameter,
not a load.

**F3 — byte-array storage is field-insensitive, which creates false targets (proven by outcome; mechanism from source).**
rustc lowers every local aggregate to `alloca [N x i8]` (the IR census in
`VALIDATION_REPORT.md` counts them). SVF's object-type inference yields
`[N x i8]`. The byte-offset patch deliberately returns "unknown" for byte
arrays, so the GEP becomes variant and the whole object is merged. Result
under every patched instrument:
- `stack_bytes`: `{target, third}` instead of `{target}`;
- `mixed_stack_static`: `+unrelated`;
- `box_fnmut`: `+FnOnce::call_once{{vtable.shim}}` beside the closure.

These are false may-targets reported as resolved. For a vulnerability depth
d(e, v) an extra edge can only shorten or preserve the distance, or make an
unreachable v reachable. For Dmax the direction is not fixed: an extra edge
can make new, deeper nodes reachable (raising the maximum) or shortcut
existing ones (lowering it). `P-noffeq` "passes" `stack_bytes` only by coincidence: with
first-field/base equivalence off, every nonzero offset aliases one field-0 GEP
object, distinct from the base. It is not separation (the same configuration
still fails `mixed_stack_heap`).

**F4 — Rust's allocator is not modeled (proven by source and by a post-hoc probe).**
SVF creates heap objects only for functions annotated `ALLOC_HEAP_RET` by name
in `extapi.c`. Rust allocates through mangled `…___rust_alloc` declarations
that carry LLVM `allockind`/`allocsize` attributes instead. The `S3` patch
synthesizes the annotations from those attributes; its first version patched
only one of SVF's two annotation stores and was superseded (`AMENDMENTS.md`
A-3). Probe `heap_direct.c` (`mechanism_probe_results.json`) stores and
calls a function pointer through memory from an `allockind` allocator. It is
unresolved under all six other instruments and resolves exactly to `target`
under `S3`, so the patch is effective in isolation.

**F5 — aggregate values become the black hole (proven by source, IR and a post-hoc probe).**
`Global::alloc_impl` returns the allocation as `{ ptr, i64 }`, and the caller
unpacks it with `extractvalue`. `SVFIRBuilder::visitExtractValueInst` assigns
a black-hole address instead of propagating points-to. Probe
`heap_aggregate.c` is `heap_direct.c` with the pointer returned inside a
16-byte struct. Clang lowers that to the same `{ ptr, i64 }` +
`extractvalue` shape, and the call stays unresolved under `S3`, isolating
`extractvalue` as what defeats the allocator fix. Probe `pair_return.c`
returns a function pointer the same way with no heap involved. It is
unresolved under every instrument, *including the canonical C instrument
on C code*. So this is a general SVF limitation, not a Rust artifact. The
construct is rare in C. Rust uses it throughout std: fat pointers (`&dyn`,
`&[T]`, `&str`), `Option`/`Result` scalar pairs and `NonNull<[u8]>` are all
passed as first-class aggregates. This explains why `heap_struct` and the
heap half of `mixed_stack_heap` stay missing under `S3`. That the same
mechanism is the only cause inside the Rust fixtures is inferred from the
matching IR shape; it was not separately ablated there.

*Not* implicated: missing modules (every program links and verifies), the
helper dropping implementation functions (the inventory proves all
debug-carrying definitions exported), the helper misreading SVF's output (the
targets are absent from `getIndCSCallees`), LLVM optimization (`opt-level=0`),
and `-ff-eq-base` for F1/F2 (identical outcomes with and without it).

## 10. `-ff-eq-base` for Rust IR

The option makes a struct's first field share the base object. That is a
C-layout fact clang relies on. Rust gives no field-order guarantee unless
`repr(C)`, and rustc reorders fields. Under `P` it neither causes nor repairs
F1 or F2. Under the patched instruments `S` and `S-noffeq` give identical
outcomes. Its only observable effect is the coincidental `stack_bytes`
difference explained in F3. The primary configuration keeps it for parity
with C; no Rust-specific justification for it was found.

## 11. Acceptance decision and withheld outputs

Configuration `P` fails A3 (mandatory dispatch) and A4–A7 (15 of 35 Rust
programs). It satisfies A1 (instrument hashes unchanged), A2 (verified
bitcode, complete identity coverage), A8 (determinism) and A9 (C unchanged).
Per the preregistered decision rule and task §11, the backend is **not
accepted**. Therefore:

- no historical Rust specimen was rebuilt, linked or analyzed;
- no per-CVE vulnerability depth, per-executable Dmax, shortest-path or
  mapping evidence was produced;
- no MIR-versus-LLVM/SVF comparison table exists, because there are no valid
  LLVM/SVF observations to match against `rust-only-lightweight-v1`;
- the frozen population, mappings, provenance, C results, MIR results and
  calibration results were not modified.

Even the best sensitivity instrument (`S` / `S3`) could not authorize
historical use. It still fails A4 (false targets from F3, missing targets from
F5), and it is not the C study's instrument.

## 12. Cross-language comparability (task §8)

| Condition | Status |
|---|---|
| Same analysis backend | **Yes** under `P`: identical helper binary, SVF libraries, algorithm and options. A9 re-verified C against the committed calibration results, and every sensitivity instrument produced byte-identical helper output to `P` on all 15 C fixtures in both runs, so none of the three patches changes these C results. |
| Comparable measurement definitions | **Yes**: same BFS finalizer, edge counting, Dmax definition |
| Comparable analyzed program scope | **No**: Rust compiles std's generic layer into the graph, while C's libc is external (`library_callback`: C unreachable, Rust depth 7). Rust's executable `main` has no node, so the entry must be the source `fn main`, and `uumain` is a different anchor. |
| Demonstrated semantic coverage | **No for Rust**: dynamic dispatch, non-first fields, heap-held and stack-held function pointers fail (F1–F5); C passes 15/15 on the same calibration fixtures |
| Directly comparable numerical results | **No**, and not claimable from backend identity alone. The same SVF instrument models C's typed IR field-sensitively and Rust's byte-addressed IR not at all. Its errors would bias Rust measurements in directions that differ by construct and by metric. For vulnerability depth, missing dispatch or heap edges (F1, F2, F5) lengthen paths or make targets unreachable, and false targets (F1 wrong-field, F3) shorten them. For Dmax, missing edges shrink the reachable set (usually lowering the maximum, though removing a shortcut can raise it), and false edges can raise or lower it. No single correction factor exists. |

The IR census quantifies the representation gap that drives this
(`VALIDATION_REPORT.md`, "LLVM IR shape census"):

| Language | Constant nonzero `i8` GEPs | Typed aggregate GEPs | `[N x i8]` allocas | Typed allocas |
|---|---|---|---|---|
| Rust (all 35 programs) | 641 | 4 | 2364 | 0 |
| C (all 15 programs) | 0 | 28 | 0 | 94 |

These are the same controlled source constructs. SVF 67efb774 models the C
column field-sensitively. It maps every entry of the first Rust column to
field 0 (F1). With the byte-offset patch it can model the third Rust column
only field-insensitively (F3).

## 13. Threats to validity and limitations

- The controlled corpus is synthetic. Passing fixtures never establishes
  completeness, and failing ones establish defects, not their historical
  prevalence. Bias magnitude in real uutils graphs is unmeasured.
- The amended reading (A-2) counts direct-lowered sites. The strict reading
  is reported alongside it.
- The sensitivity patches are local, unreviewed by SVF upstream, and only
  validated on these fixtures plus C byte-equality.
- Unadjudicated runtime indirect sites (for example inside `lang_start`) are
  counted, not judged.
- Scope boundary: precompiled std is external, so paths through
  non-generic std (for example I/O callbacks) are invisible, as libc is for C.
- The calibration Rust fixtures were measured with stock std (not the
  rebuilt-std MIR configuration). The expectations are source-level and
  configuration-independent.

## 14. Smallest next engineering steps

1. **Unblocks the most: a byte-interval memory model for `[N x i8]` objects**
   (fields keyed by byte offset and width, byte-range-aware memcpy, an
   explicit merge with precision-loss provenance on unknown offsets). This
   addresses F1 and F3 together. The design notes in `rust_audit_v3/README.md`
   (`git show b7484fa0^:…`) remain applicable.
2. Field-sensitive `insertvalue` / `extractvalue` (F5).
3. Upstream-quality versions of the vcall gate (F2) and attribute-based
   allocator recognition (F4).
4. Re-run this validation unchanged. If an instrument passes, re-validate the
   C controlled fixtures and C historical replays on that same instrument
   before any historical Rust run, then capture whole-program bitcode via the
   Cargo wrapper (§3) and use the §7 entry policy.

## 15. Reproduction (Linux/WSL, from the repository root)

```sh
# preservation checks (were run before and after; all pass)
python3 security/historical/rust/semantic_gate.py
PYTHONPATH=. python3 -m pytest -q -p no:cacheprovider \
  security/semantic_callgraph/cross_language_calibration/test_revision_freeze.py \
  security/semantic_callgraph/rust_mir/test_dependency_inputs.py
(cd security/semantic_callgraph/rust_mir_lightweight && PYTHONPATH=$PWD/../../.. \
  python3 verify_results.py --output ../../../build/rust-llvm-svf-v1/regression-x/verify_results.json && \
  PYTHONPATH=$PWD/../../.. python3 integrity.py --output ../../../build/rust-llvm-svf-v1/regression-x/integrity.json)

# sensitivity instruments (separate trees; never touches build/semantic-toolchain)
S=security/semantic_callgraph/rust_llvm_svf_v1/sensitivity_svf/build_sensitivity_svf.sh
bash $S                                                     # S: byte-offset + vcall gate
RUST_LLVM_SVF_SENSITIVITY_ROOT=build/rust-llvm-svf-v1/svf-byte-offset-only SVF_PATCHES=svf-byte-offset.patch bash $S
RUST_LLVM_SVF_SENSITIVITY_ROOT=build/rust-llvm-svf-v1/svf-vcall-gate-only SVF_PATCHES=svf-rust-vcall-gate.patch bash $S
RUST_LLVM_SVF_SENSITIVITY_ROOT=build/rust-llvm-svf-v1/svf-sensitivity-3 \
  SVF_PATCHES="svf-byte-offset.patch svf-rust-vcall-gate.patch svf-allockind-heap.patch" bash $S

# controlled validation (2 fresh runs x 7 instruments), report, entry probe
PYTHONPATH=. python3 -m security.semantic_callgraph.rust_llvm_svf_v1.validate --output build/rust-llvm-svf-v1/validation --runs 2
PYTHONPATH=. python3 -m security.semantic_callgraph.rust_llvm_svf_v1.report --results build/rust-llvm-svf-v1/validation/results.json
PYTHONPATH=. python3 -m security.semantic_callgraph.rust_llvm_svf_v1.entry_probe --validation build/rust-llvm-svf-v1/validation
PYTHONPATH=. python3 -m security.semantic_callgraph.rust_llvm_svf_v1.mechanism_probe --output build/rust-llvm-svf-v1/mechanism-probe
python3 security/semantic_callgraph/rust_mir/dependency_inputs.py   # re-authenticates scopeguard 1.2.0
```

`validate.py` refuses to run if any preregistered file's hash changed, and
refuses to reuse an output directory.

Recorded for the evidence of record (2026-10-08):

- **Raw results.** `build/rust-llvm-svf-v1/validation/results.json`,
  SHA-256 `a0b8f1bc0e343ae12547f65a27074ff3fb48afca8fab94df3810b563d4d97dc9`.
- **Inputs.** scopeguard 1.2.0 archive
  `94143f37725109f92c262ed2cf5e59bce7498c01bcc1502d7b9afe439a4e9f49`,
  re-authenticated file by file. All 30 calibration sources match their
  manifest hashes (checked separately; `validate.py` itself does not check
  them).
- **Harness.** SHA-256 over LF-normalized bytes:

  | File | SHA-256 |
  |---|---|
  | `pipeline.py` | `b9e037252343126df9a3c35e8b86b06a6236bfba37223b038aa2f88462c679a7` |
  | `validate.py` | `1035e0ab5aca613b83bf1785cad6d16b64ff974d06f91ba1ccef90627f204605` |
  | `report.py` | `a7333b4b65ad664bb714228dc6bb1aa1fb4beb057ebd3857b488e5c1aec503d5` |
  | `entry_probe.py` | `a47c6aff9012fe3ceee0260c21aa10e17c50c682de1f6c93077eaaab704023d1` |
  | `mechanism_probe.py` | `69279abaa7848da70d6b5ae5230193463f0cbce82416bdb83634713f865164b3` |
  | `build_sensitivity_svf.sh` | `65e6455750671e3ac0a71bddac277e55150488cf649436699555861f50ffd341` |
  | `svf-byte-offset.patch` | `644d6ffacfac03d0e0452e900bf38eda78397c0f7e267405a187d2f92e7df607` |
  | `svf-rust-vcall-gate.patch` | `f005fa88bf639cc90b183715019bf6fb42ee0007255b26173c1b93c6d8044e2c` |
  | `svf-allockind-heap.patch` | `e6f74e212a82740788f863b9bbeccf32f72046b1c7fcc0c3df4c7ca77803f516` |

  `report.py` was last changed after the validation run, to print counts in
  the inventory table. It only summarizes `results.json`.
- **Preservation.** `semantic_gate.py`, the 4 existing pytest tests,
  `rust_mir_lightweight/verify_results.py` (28 graphs, 45 CVEs) and
  `integrity.py` passed before any change and again after the final run. The
  canonical helper, `libSvfCore.so.3.4`, `libSvfLLVM.so.3.4`, `extapi.bc`,
  `backend.py` and `native/semantic_callgraph_svf.cpp` hashes are identical
  before and after (`build/rust-llvm-svf-v1/regression-{before,after}/`).
  Nothing outside this directory was modified.
