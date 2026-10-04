# Controlled MIR cast, constant and aggregate gate

**MIR-CORE-GO — READY FOR CROSS-LANGUAGE CALIBRATION.** This is the controlled core milestone only. Calibration was not run. No historical uutils was built, no historical Rust CVE depth was measured, and the frozen Rust mappings/population and C instrument/results were not modified. The final historical reporting gate remains closed (`accepted_backend: false`; `finalize_accepted` still requires `MIR-GO`).

1. **Original eight-cast ledger.** `cast_gate_baseline.json` was recorded before semantic edits; it freezes the normalized scientific graphs, complete flow outputs and path/gate records of all 27 passing fixtures. `cast_gate_ledger.json` was then produced before fixes from fresh compiler extraction and the solver's fixed-point values. Each entry includes the full calling Instance, source span, MIR rvalue, operand, normalized source/destination types, exact CastKind, abstract values and proposed effects. All eight are **`CastKind::Transmute`**, not unsizing or exposed-provenance casts.

   | Fixture | Calling body | Normalized conversion | Contract |
   |---|---|---|---|
   | box_trait | `core::ptr::const_ptr::<impl *const u8>::addr` | `*const () → usize` | Address bits, no provenance exposure |
   | box_trait | `NonZero::<usize>::get` | `NonZero<usize> → usize` | Pointer-free scalar extraction |
   | box_fnmut | `core::ptr::const_ptr::<impl *const u8>::addr` | `*const () → usize` | Address bits, no provenance exposure |
   | box_fnmut | `NonZero::<usize>::get` | `NonZero<usize> → usize` | Pointer-free scalar extraction |
   | iterator_flat_map | `core::ptr::const_ptr::<impl *const ()>::addr` | `*const () → usize` | Address bits, no provenance exposure |
   | iterator_flat_map | `core::ptr::const_ptr::<impl *const u8>::addr` | `*const () → usize` | Address bits, no provenance exposure |
   | crates_io | `core::ptr::const_ptr::<impl *const ()>::addr` | `*const () → usize` | Address bits, no provenance exposure |
   | crates_io | `core::ptr::const_ptr::<impl *const u8>::addr` | `*const () → usize` | Address bits, no provenance exposure |

   Pointer casts occur at pinned core `ptr/const_ptr.rs:159:18–159:51`; numeric wrapper casts at `num/nonzero.rs:499:18–499:55`. The `u8` receiver is first cast to `*const ()`; the table reports the actual immediate cast operand type. The dependency is authenticated **scopeguard 1.2.0**. Its blockers occur in reached **core bodies**, not unavailable dependency bodies. Dependency MIR remains available and traversed.

2. **Cast contracts.** Address extraction produces a non-dereferenceable `address_bits` token. It neither supplies callable targets nor mutates the referenced allocation or fields (category C, known representation conversion). Numeric extraction requires recursively normalized pointer-free field types and equal compiler layout sizes (category A for the scalar bit value; no graph-relevant payload). This handles `NonZero`'s associated field type and `UsizeNoHighBit`, without names or source heuristics.

   Auditing reconstruction also exposed the pre-existing integer-to-pointer `Transmute` inside `without_provenance_mut`. The pinned core source documents that this creates a pointer **without provenance**. Its separate contract produces a provenance-free token, never an allocation address. `PointerExposeProvenance` and `PointerWithExposedProvenance` remain unsupported (E); transmuting an integer into a callable/reference remains blocking. No generic allow-cast operation exists.

   Existing families remain explicit: `PtrToPtr` preserves addresses and records pointee erasure/restoration (A/D); `FnPtrToPtr`, `ReifyFnPointer` and `UnsafeFnPointer` retain callable values (B); `ClosureFnPointer` resolves the compiler FnOnce adapter Instance (B); `Unsize` retains typed object/Box storage and changes the exposed local type (C); `MutToConstPointer`, `ArrayToPointer`, and `Subtype` preserve the corresponding representation (A). Numeric CastKinds produce scalar results. General aggregate representation transmutes retain the existing conservative allocation-local collapse and precision marker (D). Unknown families remain blockers.

3. **Box trait result.** Original exact target remains `<crate::First as crate::Action>::operation`. The complete path retains allocation-site Box storage, `PointerCoercion(Unsize, …)`, the exposed dyn local type, moves, dereferences, virtual site, and concrete impl Instance. Concrete heap type/identity survives the fat-pointer relation. The new two-box negative control resolves exactly First and Second, excluding Excluded. It records both allocation sites.

4. **Box FnMut result.** Original exact target remains `crate::boxed_mut::{closure#0}`. Box allocation, concrete closure/environment type, FnMut trait relation and compiler call route are retained. The new two-environment control resolves exactly `boxed_a::{closure#0}` and `boxed_b::{closure#0}`. Fn/FnMut/FnOnce use their compiler trait/Instance identities; they are not flattened to one bare callable. A vtable call may resolve directly to the closure body when rustc supplies that Instance; no synthetic shim is invented. All actual shim nodes remain in the graph.

5. **Iterator flat_map result.** Both blockers were pointer-address extraction in core internals. No flat_map-specific rule was added. `iterator_path`, core iterator adapters, the closure/Fn route and `target` remain on complete raw paths. The gate now passes with no unsupported operation or missing required body.

6. **Crates.io result.** Both blockers were the same core pointer-address extraction operations. `dependency_path → scopeguard bodies/drop route → closure → target` remains traversable. The dependency was not reclassified as an external boundary. `cast_trace_evidence.json` contains full raw shortest paths, all cast transitions, allocations, indirect targets and body ledgers for these four cases.

   | Fixture | Prior blocker | Implemented semantics | Complete gate | Target result |
   |---|---|---|---|---|
   | box_trait | address and NonZero transmute | separate address/scalar contracts | PASS | exactly First impl |
   | box_fnmut | address and NonZero transmute | separate address/scalar contracts | PASS | exactly boxed_mut closure |
   | iterator_flat_map | two address transmutes | non-exposing address extraction | PASS | original closure/target paths unchanged |
   | crates_io | two address transmutes | non-exposing address extraction | PASS | original scopeguard/closure/target paths unchanged |

7. **Constants.** The adapter blockers were a promoted reference to `Ordering::Less`, references to constant panic-format byte arrays, and an inline-const `MaybeUninit<u8>` value in the scratch-array repeat. Pointer-free enum/array/union contents are proven from normalized rustc types; no callable is inferred from their bytes. Function items use `FnDef`/Instance resolution. Function-pointer payloads use `GlobalAlloc::Function` provenance. Aggregate constants use `ConstValue::Indirect` and compiler field offsets; constant references retain a distinct abstract object. Scalar-only slice/string payloads have no callable fields. Zero-sized values are handled without reading bytes; function items are resolved before the zero-size case.

   A constant `&dyn Action` is actually represented in these fixtures as an indirect fat-pointer constant. Its concrete type comes from **`GlobalAlloc::VTable`**, its data pointer from compiler allocation provenance, and its fields from the concrete layout. This evidence also seeds candidate discovery. No arbitrary vtable bytes are parsed as methods. All five constant controls pass: function constant, const struct, static struct, helper transfer, and constant dyn payload. Unjustified constant payloads still block the gate.

8. **Repeated aggregates.** The sort blocker was `Rvalue::Repeat`, constructing `[MaybeUninit<u8>; 4096]`, not a repeated source assignment. The solver copies the operand and its typed subfields to each abstract element. Known `ConstantIndex` projections and index locals proven constant across all writes retain field precision; escaping addresses/call writes invalidate that proof. Variable indices conservatively collapse only the relevant array object. Repeated function-item/function-pointer arrays and mixed arrays pass both known- and variable-index controls. Known mixed index retains only target; variable mixed index retains exactly target and other.

9. **Additional intrinsic contracts.** Exact compiler registration (`tcx.intrinsic`) determines these identities. All eight lack ordinary MIR bodies and retain their incoming Instance edges. Full per-Instance records are in `cast_intrinsic_ledger.json`.

   | Intrinsic | Contract and graph effect | Validation |
   |---|---|---|
   | `saturating_sub` | scalar arithmetic leaf; no callable/memory effect | sort adapter |
   | `ctlz` | scalar leading-zero count leaf | sort adapter |
   | `ctlz_nonzero` | scalar leading-zero count leaf with intrinsic precondition | sort adapter |
   | `ptr_offset_from_unsigned` | scalar distance leaf; no memory mutation | sort adapter |
   | `cold_path` | compiler hint leaf; no semantic graph effect | sort adapter |
   | `select_unpredictable` | union both alternatives and corresponding subfields | sort adapter and exact two-field control |
   | `arith_offset` | preserve allocation may-addresses and conservatively collapse offset-sensitive contents | sort adapter and independent callable/isolation test |
   | `typed_swap_nonoverlapping` | bidirectional union of corresponding pointed-to fields, preserving objects | sort adapter and callback-field swap control |

   The public select helper's separate `MaybeUninit` union route can still conservatively widen fields with explicit precision-loss records. The direct intrinsic control distinguishes that pre-existing union policy from the select contract, which retains exact corresponding fields. Both complete sort/boxed-adapter probes now have zero unsupported operations and zero unresolved sites, and retain std/core bodies.

10. **Complete static gate: 31/31.** Original semantic assertions: 31/31. Required-body accounting remains 511 available, 44 contracted intrinsic occurrences, 17 legitimate external boundaries, zero missing/unsupported required bodies. All 27 frozen normalized scientific outputs are unchanged, including function inventories, edges, target sets, body dispositions, precision records, shortest paths and status. The complete flow objects also match, a stronger check than the requested subsets.

11. **Dynamic validation: 31/31.** Both fresh runs satisfy observed semantic edges ⊆ static semantic edges, with no missing observed edge. Native entry traces and DWARF mapping remain independent of static target discovery. This is executed-path validation, not exhaustive dynamic coverage. `cast_target_changes.json` records **zero added or removed static targets across all original 31 fixtures**. The new two-target controls add only the two targets justified by their flows.

12. **Determinism.** The final paired clean roots are `continuation/cast-final-v2/run-1` and `run-2`. Complete extraction/flow records, serialized graphs, body/intrinsic accounting, precision records, paths and dynamic comparisons are identical. Focused, memory, new operation controls and both adapter runs are also deterministic. Scientific identities and source remapping were not relaxed.

13. **Regression totals.** Focused 30/30, memory 12/12, new compiler-backed operation controls 13/13, both adapter paths complete. Heap 5/5, dyn 6/6, closure/Fn 10/10, unsafe 5/5, mixed 4/4 are covered by the focused suite. **Python regressions: 75 passed**, covering the existing MIR/semantic tests plus seven independent transfer/negative tests. The publication-integrity check now verifies the current core milestone and still requires historical/backend acceptance to be false.

14. **C frozen.** Fresh controlled checks 11/11; authenticated historical C bitcode replays 9/9; all 159 protected artifacts unchanged. Canonical helper SHA-256 remains `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2`. Replay outputs are in a fresh root; the frozen C scientific instrument and results were not rewritten.

15. **Decision: MIR-CORE-GO.** Ready for cross-language calibration when authorized. Still not ready for historical CVE measurements. Unknown required operations and constant payloads continue to fail closed; this milestone does not claim complete Rust-language coverage.

Machine-readable publication: `instrument.json`, `cast_*_results.json`, the baseline/cast/intrinsic ledgers, trace evidence, target-change comparison and `cast_evidence_manifest.json`. Previous milestone reports and evidence remain archived separately.
