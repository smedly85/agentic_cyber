# Calibration corpus freeze report

**CALIBRATION-CORPUS-REFROZEN — READY FOR RE-AUDIT**

No semantic analyzer was run on this corpus, no analyzer graph output was inspected, no callback trace was collected, and no depth was calculated. This is not CALIBRATION-GO.

Bundle SHA-256: `522fe6d821711beac3cb687aa012823a1332b34ec3ff800bfdc32e821a8a8bda`

The bundle hash binds every source byte plus the complete expectations/mappings/runtime/build manifest, JSON schema, preregistration and source review. All 15 pairs use `entry` as the source-level root; `main` is the excluded runtime harness.

## Source paths and SHA-256 values

| Pair | C source / SHA-256 | Rust source / SHA-256 |
|---|---|---|
| direct_chain | [fixtures/direct_chain/fixture.c](fixtures/direct_chain/fixture.c)<br>`91667abc8215a849571c9956113939b843ea2cdf91c9deffeece371f0fab2d95` | [fixtures/direct_chain/fixture.rs](fixtures/direct_chain/fixture.rs)<br>`1100a0001117b11cbd40aec1782b20cc8a8fcf5c3d3249070deecfaa1d493c89` |
| recursion | [fixtures/recursion/fixture.c](fixtures/recursion/fixture.c)<br>`33e28e6553f0af530c94fd21154576861ce3c29f132cc587d4cced74ee37c29c` | [fixtures/recursion/fixture.rs](fixtures/recursion/fixture.rs)<br>`1beae10ab3ceae44751bad4029650e27a1f5b78557f594039473ae417ff2944c` |
| single_pointer | [fixtures/single_pointer/fixture.c](fixtures/single_pointer/fixture.c)<br>`e88a25192e3fe816a4b615aaa8e9e37debf47001300c927d9f9b4165c9232c6b` | [fixtures/single_pointer/fixture.rs](fixtures/single_pointer/fixture.rs)<br>`69d9c6b5a2db0025181313735a94beb21f12036373eea340e43134f682997eac` |
| multi_pointer | [fixtures/multi_pointer/fixture.c](fixtures/multi_pointer/fixture.c)<br>`447be56e9503bda98c75191452a26638ddfdb98c77785e13d255408f99f56a09` | [fixtures/multi_pointer/fixture.rs](fixtures/multi_pointer/fixture.rs)<br>`75d8c88a3cefa4388ca4b6426dfa186d82783930bde73ea74ffbbcd7be4488fc` |
| first_field | [fixtures/first_field/fixture.c](fixtures/first_field/fixture.c)<br>`83a744b72dc1a3e5935db690496f17d4c1daa663acf0f6c537a7d97f5bc9db91` | [fixtures/first_field/fixture.rs](fixtures/first_field/fixture.rs)<br>`7ed0608bc0aa86e71c0f7d2e4a3f4ad17b38c57a25e274daa71ff0acc8f853f4` |
| non_first_field | [fixtures/non_first_field/fixture.c](fixtures/non_first_field/fixture.c)<br>`81d1c983382dba16ba82468470f6c69b4f94d811099cf8a461dda8301db2fc28` | [fixtures/non_first_field/fixture.rs](fixtures/non_first_field/fixture.rs)<br>`46760f5c859f7861d065d2abef9eb6b19e90b61dbc9a6fc0a592a7870723213e` |
| stack_copy | [fixtures/stack_copy/fixture.c](fixtures/stack_copy/fixture.c)<br>`748e3386b16edbc40dd32f5e7ac8486549cfb723628d9f788019482b78f66b90` | [fixtures/stack_copy/fixture.rs](fixtures/stack_copy/fixture.rs)<br>`e70fc9091e3a201bf84bd2c84cc40332447c49794db9a926ba7828c25719923d` |
| heap_struct | [fixtures/heap_struct/fixture.c](fixtures/heap_struct/fixture.c)<br>`7f62befc9709c77cb9c02061e0b1a54bac2a30eb30c3e8a2aa054751d5ee0b8d` | [fixtures/heap_struct/fixture.rs](fixtures/heap_struct/fixture.rs)<br>`d5577c627e3119a97765a12bbd4d4a1d9758e11aa4138038b8229d42987a1546` |
| generic_specialization | [fixtures/generic_specialization/fixture.c](fixtures/generic_specialization/fixture.c)<br>`f9919da0a86239bfc654bf3fd663f980cbd62431a6918b7cc60d92139b3e7534` | [fixtures/generic_specialization/fixture.rs](fixtures/generic_specialization/fixture.rs)<br>`2d73e47ff815a78833d2ecc469b0527f65cc97ed9f479bbd04041cafc934ccf2` |
| static_dispatch | [fixtures/static_dispatch/fixture.c](fixtures/static_dispatch/fixture.c)<br>`74670e825dcc2ea67c531358c14026285e70cb3b9f19bcc6088f9ff46cd093f8` | [fixtures/static_dispatch/fixture.rs](fixtures/static_dispatch/fixture.rs)<br>`e930cd7716b03766085c08a95ad8307cd92344173c507d88dce90f40bb70172d` |
| dyn_vtable | [fixtures/dyn_vtable/fixture.c](fixtures/dyn_vtable/fixture.c)<br>`f79c7f74ddce2cfb754ca2694f1832be9cbb9a2b07fa4dfdd8bf6c3645163f61` | [fixtures/dyn_vtable/fixture.rs](fixtures/dyn_vtable/fixture.rs)<br>`4554254252497ad1077d7e841e32aff31ea43be5799de3a1453080f991b0f5ef` |
| closure_context | [fixtures/closure_context/fixture.c](fixtures/closure_context/fixture.c)<br>`9b90ae62c4acf65690c2991751520ed2df5f9c2247e2eebcd615c4701dd86898` | [fixtures/closure_context/fixture.rs](fixtures/closure_context/fixture.rs)<br>`2894f8ce9ba26f0587d12cd9fff153da2b5fde0d69e06beeb313574cb6018588` |
| library_callback | [fixtures/library_callback/fixture.c](fixtures/library_callback/fixture.c)<br>`a571db6b5db839afd46f375c7f491155dd0b42279995223e762a9010d92bd195` | [fixtures/library_callback/fixture.rs](fixtures/library_callback/fixture.rs)<br>`21740409c86d497fecb5633c89a2f47959e7921ddf81f89b0181c5eefa19bbe6` |
| mixed_stack_static | [fixtures/mixed_stack_static/fixture.c](fixtures/mixed_stack_static/fixture.c)<br>`7bb08896b11da5bfd3356ac046d612f83b1ce222848caad6b0bde96a5553c942` | [fixtures/mixed_stack_static/fixture.rs](fixtures/mixed_stack_static/fixture.rs)<br>`9dd51e512f026c100fb3860e65ab64b5173e03a4a63cba900de77a22864ede86` |
| mixed_stack_heap | [fixtures/mixed_stack_heap/fixture.c](fixtures/mixed_stack_heap/fixture.c)<br>`b201a29ee68fbede9940cdf82a4eb81b67f3a1acc35e0d94c818466e072634f9` | [fixtures/mixed_stack_heap/fixture.rs](fixtures/mixed_stack_heap/fixture.rs)<br>`377b35c3446acb408353a274c9a21ab8ac40c7ccdba5a3d75599f28448b1f2e3` |

## Exact source entry and target mappings

Line spans are frozen review spans including function attributes where present; compiler source-definition spans must be matched by containment/overlap plus qualified identity and source file, not by a bare name. Closure identity refers to its literal, not a manufactured function.

| Pair | C entry → source target(s) | Rust entry → source target(s) |
|---|---|---|
| direct_chain | `entry` L13–15 → `target` L3–5 | `entry` L15–18 → `target` L3–6 |
| recursion | `entry` L14–16 → `target` L3–5 | `entry` L16–19 → `target` L3–6 |
| single_pointer | `entry` L8–12 → `target` L3–5 | `entry` L9–14 → `target` L3–6 |
| multi_pointer | `entry` L18–22 → `target_a` L3–5, `target_b` L8–10 | `entry` L21–26 → `target_a` L3–6, `target_b` L9–12 |
| first_field | `entry` L15–19 → `target` L5–7 | `entry` L17–22 → `target` L5–8 |
| non_first_field | `entry` L15–19 → `target` L5–7 | `entry` L17–22 → `target` L5–8 |
| stack_copy | `entry` L15–20 → `target` L5–7 | `entry` L17–23 → `target` L5–8 |
| heap_struct | `entry` L16–25 → `target` L6–8 | `entry` L17–22 → `target` L5–8 |
| generic_specialization | `entry` L13–15 → `target` L3–5 | `entry` L15–18 → `target` L3–6 |
| static_dispatch | `entry` L18–20 → `target` L3–5 | `entry` L28–31 → `target` L5–8 |
| dyn_vtable | `entry` L25–33 → `first_operation` L6–9, `second_operation` L12–15 | `entry` L31–38 → `<First as Action>::operation` L7–10, `<Second as Action>::operation` L15–18 |
| closure_context | `entry` L14–19 → `target` L4–6 | `entry` L9–17 → `target` L3–6 |
| library_callback | `entry` L11–16 → `target` L4–8 | `entry` L9–15 → `target` L3–6 |
| mixed_stack_static | `entry` L27–32 → `target_a` L5–7, `target_b` L10–12 | `entry` L31–37 → `target_a` L5–8, `target_b` L11–14 |
| mixed_stack_heap | `entry` L27–37 → `target_a` L6–8, `target_b` L11–13 | `entry` L30–37 → `target_a` L5–8, `target_b` L11–14 |

## Expected targets and cross-language correspondence

| Pair | C exact application indirect targets | Rust exact application indirect targets | Cross-language expectation |
|---|---|---|---|
| direct_chain | No application indirect site; direct/closure relations are in manifest | No application indirect site; direct/closure relations are in manifest | `exact_application_structure` |
| recursion | No application indirect site; direct/closure relations are in manifest | No application indirect site; direct/closure relations are in manifest | `exact_application_structure` |
| single_pointer | `entry.callback` → {target} | `entry.callback` → {target} | `equivalent_indirect_target_set` |
| multi_pointer | `entry.callback` → {target_a, target_b} | `entry.callback` → {target_a, target_b} | `equivalent_indirect_target_set` |
| first_field | `entry.callback` → {target} | `entry.callback` → {target} | `equivalent_indirect_target_set` |
| non_first_field | `entry.callback` → {target} | `entry.callback` → {target} | `equivalent_indirect_target_set` |
| stack_copy | `entry.callback` → {target} | `entry.callback` → {target} | `equivalent_indirect_target_set` |
| heap_struct | `entry.callback` → {target} | `entry.callback` → {target} | `equivalent_application_transition_with_runtime_nodes` |
| generic_specialization | No application indirect site; direct/closure relations are in manifest | No application indirect site; direct/closure relations are in manifest | `equivalent_application_transition_with_runtime_nodes` |
| static_dispatch | No application indirect site; direct/closure relations are in manifest | No application indirect site; direct/closure relations are in manifest | `exact_application_structure` |
| dyn_vtable | `entry.dispatch` → {first_operation, second_operation} | `entry.dispatch` → {First::operation, Second::operation} | `equivalent_application_transition_with_runtime_nodes` |
| closure_context | `entry.callback` → {callback} | No application indirect site; direct/closure relations are in manifest | `equivalent_application_transition_with_runtime_nodes` |
| library_callback | library callback binding: {target}; internal site unmeasured | library callback binding: {target}; internal site unmeasured | `expected_library_boundary_difference` |
| mixed_stack_static | `invoke.callback` → {target_a, target_b} | `invoke.callback` → {target_a, target_b} | `equivalent_indirect_target_set` |
| mixed_stack_heap | `invoke.callback` → {target_a, target_b} | `invoke.callback` → {target_a, target_b} | `equivalent_application_transition_with_runtime_nodes` |

## Validation and review

- Ordinary source smoke tests: **30/30 compilations; 34/34 prescribed runtime configurations**. Results check exit code/stdout/stderr and return-value assertions only. Predicted callback identities were not traced or measured.
- Source/schema/freeze validation: **15 pairs, 30 sources**. Validator/tamper-rejection tests: **32 passed**. Every requested scientific input is tested for aggregate change and rejection. See validator_test_results.json and tests/test_calibration_corpus.py.
- C/Rust helper-layer, branch, callback, lifetime and storage review is recorded in source_review.json. Independent audit remains pending.
- C helper SHA-256 unchanged: `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2`.
- Rust calibration-start fingerprint unchanged: `514e397d83f9fd2be32e42b69970861036c7251dd2a2dbf38591a6ad7ec76e20`.
- Backend/compiler/driver source and binary hashes were checked before and after smoke execution. Rebuilt Rust libraries were hash-verified before each compilation. All 159 protected C artifacts remain unchanged.
- Existing preflight reports, fingerprints and null measurement files remain byte-identical. fixture_bundle_pointer.json is additive; it points to this corpus without turning null measurements into observations.
- No scientific backend was modified. No historical uutils specimen was built; no historical Rust CVE measurement, frozen-population edit or mapping edit occurred.

## Stop point

Stop here for independent preregistration audit. The first C/SVF or Rust/MIR semantic run on these fixtures must follow that audit and separate authorization.


## Audit revisions R1-R5

Prior bundle `065751bf5cfbd7233583fb123fc04fb5f22b2c02f035234a54ae12668ec5830a` is `superseded_before_measurement`; reason: `independent preregistration audit corrections R1-R5`. No semantic analyzer output ever existed for it. Its full source freeze is preserved under provenance/065751bf5cfbd7233583fb123fc04fb5f22b2c02f035234a54ae12668ec5830a.

R1: dyn_vtable adds Third::operation / third_operation and a main-local live trait object / context-method object. R2: multi_pointer adds same-signature unrelated and a main-local live callback. R3: static_dispatch adds Second::operation / second_operation called directly in main. Each decoy call checks result 13; none is passed to entry or writes shared state. The original entry bodies and exact target sets remain unchanged. All six source spans were recomputed.

R4, expectation-only: Exactly one concrete Rust monomorphized Instance, helper::<i32>, corresponds to the one hand-specialized C helper_i32. Source-level aggregation treats that Instance as the concrete realization of one generic source function helper; no multiple concrete instances are claimed. Prior wording is preserved verbatim in revision_provenance.json.

R5: Complete extraction configuration is frozen in fixture_manifest.json, independently of smoke flags. The accepted Rust canonical argv and rebuilt-std configuration are fingerprinted in semantic_extraction_canonical.json; canonical provider/build records, driver/compiler/library fingerprints and driver environment are also bound. C canonical backend flags/helper options are bound; its intentional host-default extraction target is explicitly documented.

Exact Rust settings: rustc 1.93.0; edition 2021; x86_64-unknown-linux-gnu; opt-level=0; codegen-units=1; panic=unwind; mir-opt-level=0; inline-mir=no; always-encode-mir; rebuilt-std noprelude extern/dependency flags; unstable-options; remap-path-prefix; -A dead_code; --emit=link. Compiler-internal rustc_driver Probe uses RUSTC_BOOTSTRAP=1, MIR_PROBE_TRANSITIVE=1 and stops after analysis. No semantic invocation occurred.

Equivalence of preregistered APPLICATION-LEVEL semantic nodes/relationships inside the entry root. Equality is not required for compiler-generated Rust shims, std/core nodes, allocator internals, or runtime/startup implementation nodes. All actual raw nodes remain uncontracted in any later authorized measurement.

c_external_boundaries, rust_external_boundaries and special_semantics.external_boundaries list external body-unavailable calls directly originating from application source inside the entry root (including entry-reachable application helpers), not every external function reachable transitively. Calls to compiled Rust std/core generic bodies are not external boundaries; harness calls and transitive allocator/runtime calls are excluded.

Runtime evidence: all separate harness decoy checks passed; both selector configurations passed in multi_pointer and dyn_vtable. Distinct return values and source non-flow establish the intended targets; no callback tracing or semantic graph inspection was performed.

## Changed source hashes

- security/semantic_callgraph/cross_language_calibration/fixtures/multi_pointer/fixture.c: `447be56e9503bda98c75191452a26638ddfdb98c77785e13d255408f99f56a09`
- security/semantic_callgraph/cross_language_calibration/fixtures/multi_pointer/fixture.rs: `75d8c88a3cefa4388ca4b6426dfa186d82783930bde73ea74ffbbcd7be4488fc`
- security/semantic_callgraph/cross_language_calibration/fixtures/static_dispatch/fixture.c: `74670e825dcc2ea67c531358c14026285e70cb3b9f19bcc6088f9ff46cd093f8`
- security/semantic_callgraph/cross_language_calibration/fixtures/static_dispatch/fixture.rs: `e930cd7716b03766085c08a95ad8307cd92344173c507d88dce90f40bb70172d`
- security/semantic_callgraph/cross_language_calibration/fixtures/dyn_vtable/fixture.c: `f79c7f74ddce2cfb754ca2694f1832be9cbb9a2b07fa4dfdd8bf6c3645163f61`
- security/semantic_callgraph/cross_language_calibration/fixtures/dyn_vtable/fixture.rs: `4554254252497ad1077d7e841e32aff31ea43be5799de3a1453080f991b0f5ef`

CALIBRATION-CORPUS-REFROZEN — READY FOR RE-AUDIT
