# Byte-storage and Box diagnostic follow-up

Verdict: **STOP — backend unsuitable** for the proposed population-wide Rust
depth study with this instrument. This is not a claim that LLVM can never
support a suitable Rust analysis. No historical Rust pilot was run. No Rust
historical depth was computed. No semantic patch was applied in this follow-up.

The unchanged instrument fingerprint is
`3eee651972af243bd522ec2383d33ccc15b84271d0001e101fde8641dbc26146`.
`preserved_v2.json` records the prior results and authenticated artifact hashes;
the audit-v2 provenance was not overwritten. The separate `audit_manifest.json`
fingerprints this diagnostic package, not a new semantic instrument.

## Stack failure: exact chain

The original `stack_fields` fixture constructs `Ops { a: third, b: target }`,
then `by_reference` calls `b`. The compiler emits `%ops = alloca [16 x i8]`,
stores `third` at offset 0 and `target` at offset 8, and loads the call target
from offset 8. Size 16, alignment 8, store widths 8, and both offsets are known.

This is intentional compiler lowering, not an optimization that removed only
this fixture's type. In the exact compiler revision, `Builder::alloca(size,
align)` constructs `type_array(type_i8(), size.bytes())`, then sets alignment.
See the [pinned compiler source](https://github.com/rust-lang/rust/blob/254b59607d4417e9dffbc307138ae5c86280fe4c/compiler/rustc_codegen_llvm/src/builder.rs)
and the cached-source hashes in `compiler_evidence.json`.

Debug metadata **does** retain this particular source layout: `!191` describes
local `ops`, type `!32` is `Ops` (128 bits), and its members have 64-bit size and
offsets 0/64. `dbg_declare` associates it with the alloca. That is not an LLVM
aggregate pointee type, nor a general aliasing specification for all accesses.
The current SVF object-type inference takes the alloca's LLVM allocation type;
it does not reconstruct this DICompositeType.

The v2 `inferFieldIdxFromByteOffset` explicitly returns unknown for byte arrays.
`computeGepOffset` consequently emits a variant GEP for offset 8. In
`Andersen::processGepPts`, that marks the base object field-insensitive and
schedules all its fields for collapse. Raw WPA shows:

- stack object 173 (`ops`);
- pointer 222 (offset-8 GEP) points to object 173;
- pointer 223 (loaded function pointer) points to function objects 177 (`third`)
  and 181 (`target`);
- raw WPA and the helper both resolve the indirect call to both functions.

This is a false field-crossing target under the fixture contract, not a genuine
conditional target. The wrong target is presented as resolved, without a
precision-loss marker. Both targets remain with `-ff-eq-base=false`.
`-ff-eq-base` is therefore not the cause. The official options were not changed.

## Why a local offset-number tweak is not a defensible fix

The known-layout v2 patch translates physical offsets into SVF's flattened
**type field indexes**, not byte ranges. Array elements are modeled as the base
by default (`ModelArrays=false`). `SVFIR::getGepObjVar` further applies the
object's maximum field limit through `IRGraph::getModulusOffset`, potentially
clamping/modulo-mapping an invented offset. Returning byte offset 8 as field
index 8 would mix coordinate systems and does not establish separation.

A plausible generic redesign would use `(allocation identity, byte interval)`:

1. Derive allocation extent and access width from DataLayout and allocation
   evidence. Identify pointer accesses from LLVM operations, not slot size.
2. Compose offsets in byte coordinates, including nested GEPs and all possible
   base objects. Do not translate a single inferred type into an object-wide
   truth when several allocation layouts can flow to the same pointer.
3. Separate disjoint, in-bounds, constant ranges. Handle overlapping ranges and
   unions conservatively; partial byte writes cannot simply leave an old pointer
   value valid. Propagate byte copies with their lengths and source/destination
   offsets. Preserve address-space/non-integral-pointer constraints.
4. Unknown extents, nonconstant offsets, out-of-bounds accesses, and unknown
   copies require explicit conservative summaries/merges with precision-loss
   provenance. Never choose arbitrary field zero or manufacture exact targets.
5. Reconcile typed global initializers and byte-addressed accesses in the same
   representation. Preserve alias relationships to base pointers, and propagate
   any later merge through existing points-to constraints.

The existing flattened-field abstraction and load/store constraints do not
implement that byte-width/overlap model. Debug layout alone does not supply the
missing memory semantics. This requires a validated memory-model change, not
removing the byte-array check or enabling an option. No such unvalidated patch
was installed. Fixability is **not demonstrated**, rather than proven impossible.

## Box failures: two distinct losses

Both original Box fixtures use zero-sized payloads (`First` and a noncapturing
closure). Allocation wrappers are present in the module; the source passes
size 0 to `exchange_malloc`. These are not evidence that a missing heap object
alone explains dynamic dispatch failure.

`boxed` spills data/vtable components into `%a = alloca [16 x i8]` at offsets
0/8. The first precision loss is that storage collapse. WPA object 203 contains
vtable object 37; both data and vtable loads point to 37. The method-offset GEP
also becomes variant, collapsing the vtable. Function pointer 236 points to
drop glue 216, `First::operation` 495, and `First::multiple` 509. Nevertheless
the call target set is empty.

The additional, decisive dispatch failure is `cppUtil::isVirtualCallSite`:
it recognizes any pointer-receiver call whose called operand is a load from a
single-index GEP whose base is another load. This matches the spilled Rust fat
pointer. `BVDataPTAImpl::onTheFlyCallGraphSolve` routes it exclusively to
`resolveCPPIndCalls`, which uses C++ class/vtable information instead of normal
function-pointer resolution. Rust supplies no corresponding C++ hierarchy.
The expected method already exists in the raw points-to set; helper filtering
did not remove it. The passing borrowed-trait fixture supplies its vtable as a
parameter, so its method lookup does not match that load-based C++ heuristic.

For Box FnMut the retained `alloc::boxed::FnMut::call_mut` shim loads the two
components, computes vtable offset 32, and calls the loaded pointer. WPA pointer
312 reaches vtable 35; pointer 315 contains both the FnOnce vtable shim 488 and
the closure 503. The same C++ heuristic prevents any resolved call edge. This
is not a missing closure definition or a reason to discard compiler shims.
Removing the C++ misclassification alone could expose both same-arity targets;
it would not fix field contamination. Both failures persist without first-field
equivalence. Neither Box case is repaired in this pass.

## Allocator boundary

SVF has heap-return models (`ALLOC_HEAP_RET`, allocation-size annotations) for
functions such as malloc. LLVM's emitted Rust allocator declarations include
`allocsize(0)` and allocation-kind/family attributes, but the inspected SVF
`LLVMModuleSet::is_alloc` uses its external-function annotations. The external
model file has no entry for these revision-specific Rust allocator symbols.
An attribute-backed allocator model is a plausible future change, provided
zero-size, failure, zeroing, reallocation, and deallocation are distinguished.
No allocator model was added here. The malloc-based adversary still merges
fields even with an existing heap model, so allocation modeling alone is not
a sufficient remedy. Nonzero captured Box environments remain unvalidated.

## Validation and limits

`controlled_results.md` lists every Rust fixture and every exported indirect
site (including explicitly unadjudicated runtime sites), plus adversarial
expected/actual/missing/unexpected sets. Original Rust: **28 passed, 3 failed**.
The 12 independent LLVM adversaries cover both slots, three slots, reverse
stores, overwrite, same-slot conditional union, separate slots, intervening
bytes, partial identity byte-copy overlap, variable index, stack and malloc
heap. **1 passed, 11 failed**. These are additional controlled memory-model
inputs, not rewrites of Rust-produced IR. The generator is in `audit.py`.

The overwrite fixture also exercises flow-insensitive accumulation; the stale
same-slot target must be distinguished from cross-slot contamination. The
conditional fixture legitimately permits second/third but not first. The
variable fixture legitimately permits first/second and passes. The partial
copy preserves the same bytes; arbitrary corruption followed by an indirect
call was intentionally not used as an exact-target oracle.

Raw WPA/SVFIR and helper evidence is cached under `build/rust-instrument-v3`;
`cache_manifest.json` authenticates it. All twelve adversarial helper target
sets agree exactly with separately run raw WPA (`agreement.json` per case).
Disabling first-field equivalence was
diagnostic only. C controlled **11/11** and historical observations **9/9** were
rerun; exact shortest paths, edge kinds, target sets, depth and reachability
checks remain unchanged. No C expected result was adjusted.

The wrong-edge problem occurs in ordinary Rust stack lowering. There is no
validated detector here that reliably bounds all affected paths, including
copies/unknown aliases. Therefore this is **not** a bounded-unsupported GO
workaround. Population-wide measurement remains prohibited.

## Future alternatives (not implemented)

- A whole-program rustc MIR may-call analysis could retain places, projections,
  monomorphization and trait resolution; it still needs validated alias/unsafe,
  closure, cross-crate, and foreign-boundary handling.
- Compiler borrow/Polonius information could inform such an analysis, but does
  not by itself constitute a whole-program indirect may-call graph.
- Another LLVM pointer-analysis backend would need demonstrated byte-range
  separation, overlap/copy semantics and Rust dynamic dispatch on these cases;
  switching framework names is not validation.
- A separately validated Rust semantic backend could export the same abstract
  may-call relation and provenance for the existing shortest-path/reporting
  layer. It must not substitute lexical call edges.

## Reproduction (Linux, existing authenticated toolchain/cache)

```sh
python3 security/semantic_callgraph/rust_audit_v3/audit.py --diagnose --adversaries --wpa --replay-rust
python3 security/semantic_callgraph/rust_audit_v3/run_c_regressions.py
python3 security/semantic_callgraph/rust_audit_v3/audit.py --publish
python3 -m pytest -q tests
```

Optional compiler-source acquisition is `audit.py --acquire-compiler`; unit
tests and controlled replay do not require network access.
