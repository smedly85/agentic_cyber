# Calibration corpus preregistration

Source-only design, frozen before semantic measurement. Exactly the original 15 categories; no analyzer output informed these programs. Independent preregistration audit is pending.

The source-level root is `entry`. `main` is a runtime harness. Edge lists describe intended application relations, not contracted raw graphs. No numeric depth is preregistered.

| Pair | Concept | C construct | Rust construct | Expected application relationship | Expected special difference |
|---|---|---|---|---|---|
| direct_chain | Direct chain | direct calls | direct calls | entry → helper; helper → target | No application-structure difference intended. |
| recursion | Recursion | recursive function | recursive function | entry → recursive; recursive → recursive; recursive → target | The recursive self-edge is required. Runtime recursion count is not the metric. |
| single_pointer | Single pointer | function pointer | fn value | entry → {target} | No application-structure difference intended. |
| multi_pointer | Conditional pointer | runtime-selected pointer | runtime-selected fn value | entry → {target_a, target_b} | Selection is a runtime entry parameter, supplied by command-line argument presence. Both branches have prescribed executions. |
| first_field | First callback field | stack struct | Copy struct | entry → {target} | The other callback field contains other; it must not enter the called field target set. |
| non_first_field | Non-first callback field | stack struct | Copy struct | entry → {target} | The other callback field contains other; it must not enter the called field target set. |
| stack_copy | Stack struct copy | stack struct assignment copy | Copy struct assignment copy | entry → {target} | The other callback field contains other; it must not enter the called field target set. |
| heap_struct | Heap struct | malloc/initialize/free | Box<Ops> | entry → {target} | Allocator/library/drop internals are not expected to be structurally identical. Runtime configurations assume successful allocation. C reports failure; Rust allocation failure diverges. Neither failure path is a callback path. |
| generic_specialization | Generic / C specialization | hand-specialized i32-to-i64 helper | helper::<i32> with Into<i64> | entry → helper_i32; helper_i32 → target | Latest corpus instruction requests one concrete instantiation. Into<i64> may add core conversion nodes; C uses a cast. |
| static_dispatch | Static dispatch | ordinary direct function | known concrete trait method | entry → operation; operation → target | No C vtable or function pointer; Rust dispatch is static. |
| dyn_vtable | dyn / explicit vtable | explicit context + method pointer | &dyn Action | entry → {first_operation, second_operation} | Exactly two receivers are possible. References/context pointers remain valid throughout entry. Raw vtable/shim node identity is not required. |
| closure_context | Closure / context callback | callback + explicit Environment | capturing closure | callback → target; entry → {callback} | The Rust closure call is statically known, not forced into a fn pointer. Preserve actual compiler Fn/shim transitions. C passes the environment explicitly. |
| library_callback | qsort / sort_by | libc qsort | slice sort_by | entry → sorting library → target comparator (boundary-mediated) | No equal raw path or depth is preregistered. Library callback bindings are not application indirect callsites. Expected dynamic callback set is {target}; callback invocation count is not specified. Comparator results and sorted values agree. |
| mixed_stack_static | Mixed stack/static | stack + static objects | stack + static objects | entry → invoke; invoke → {target_a, target_b} | Both objects reach the same invoke callback site in one execution, in explicit statement order. Expected site targets are exactly target_a and target_b; unrelated is confined to the other field. This is the preregistered mixed stack/static category. |
| mixed_stack_heap | Mixed stack/heap | stack + malloc objects | stack + Box objects | entry → invoke; invoke → {target_a, target_b} | Both objects reach the same invoke callback site in one execution, in explicit statement order. Expected site targets are exactly target_a and target_b; unrelated is confined to the other field. Allocator/drop internals may differ; normal runtime assumes allocation succeeds. |

## Frozen interpretation rules

- Exact indirect sets concern the declared application callsites. A callback argument binding to qsort/sort_by is recorded separately; it is not an invented source-level indirect site.
- The library pair requires explicit later adjudication of runtime edges crossing unmodeled libc. A known boundary must never silently turn missing dynamic coverage into a pass.
- Raw std/core, Fn/closure/vtable shim, allocator and drop transitions remain visible. There is no depth correction factor or equal-raw-path requirement.
- Generic helper has exactly one requested concrete instantiation, helper::<i32>, and one source observation. This follows the latest corpus instruction while retaining the registered Instance/source distinction.
- Multi-pointer and dyn pairs execute with no arguments and with choose_b. Other pairs use one default run; mixed-object pairs invoke both targets in separate statements.
- Smoke runs check exit status and output only. Expected callbacks are hand-written predictions; no callback tracing or semantic graph measurement occurs in this pass.
- OOM behavior is not structurally equalized: C checks malloc, Rust Box may diverge on failure. The runtime configurations assume successful allocation.
- Source spans, all source functions (including harness and closure), exact targets, field indices, receiver types and build flags are in fixture_manifest.json.
- Semantic labels in comments support human review and source-integrity validation only. The scientific backends must not consume them as graph facts.

## Manual source review

All pairs were reviewed for helper count, selection branches, callback placement, possible targets, object lifetimes and stack/static/heap storage. No wrappers were inserted to equalize raw depth. Legitimate differences and source review declarations are recorded in source_review.json.

## Freeze and audit boundary

fixture_hashes.json binds the complete manifest, every C/Rust source, schema, this document and source review. Any source, expectation, mapping, runtime input or build-policy change invalidates the bundle. Existing preflight null measurements remain unchanged. The first semantic run is prohibited until independent audit approves this frozen bundle.

## Independent audit corrections R1-R5

Prior bundle `065751bf5cfbd7233583fb123fc04fb5f22b2c02f035234a54ae12668ec5830a` is `superseded_before_measurement`, reason: `independent preregistration audit corrections R1-R5`. Its original sources, metadata, and hashes are archived in provenance. No analyzer output ever existed for it.

R1: Third::operation / third_operation is materialized and invoked through a separate trait object / context-method object in main. R2: unrelated is materialized and called through a separate same-signature pointer in main. R3: Second::operation / second_operation is directly called in main. Every decoy returns 13 and is checked in each prescribed run. None is passed to entry or writes shared state. Original entry bodies and target sets are unchanged. Decoy observations belong solely to the harness, outside the entry root.

R4 (expectation only): Exactly one concrete Rust monomorphized Instance, helper::<i32>, corresponds to the one hand-specialized C helper_i32. Source-level aggregation treats that Instance as the concrete realization of one generic source function helper; no multiple concrete instances are claimed. Superseded wording is retained verbatim in revision_provenance.json and the archived preregistration.

Equivalence of preregistered APPLICATION-LEVEL semantic nodes/relationships inside the entry root. Equality is not required for compiler-generated Rust shims, std/core nodes, allocator internals, or runtime/startup implementation nodes. All actual raw nodes remain uncontracted in any later authorized measurement.

c_external_boundaries, rust_external_boundaries and special_semantics.external_boundaries list external body-unavailable calls directly originating from application source inside the entry root (including entry-reachable application helpers), not every external function reachable transitively. Calls to compiled Rust std/core generic bodies are not external boundaries; harness calls and transitive allocator/runtime calls are excluded.

R5: The manifest independently freezes Rust semantic extraction from the accepted cast-final-v2 canonical command argv and std configuration, fingerprinted in semantic_extraction_canonical.json. rustc 1.93.0, edition 2021, x86_64-unknown-linux-gnu, opt-level=0, codegen-units=1, panic=unwind, mir-opt-level=0, inline-mir=no, always-encode-mir, rebuilt-std noprelude extern and dependency flags, unstable-options, remap-path-prefix, -A dead_code and --emit=link are bound. The rustc_driver Probe configuration uses RUSTC_BOOTSTRAP=1, MIR_PROBE_TRANSITIVE=1 and Compilation::Stop; driver/compiler/library fingerprints and canonical build records are bound. No driver is executed in this pass.

C extraction freezes canonical backend DEFAULT_CFLAGS, debug path mappings, -emit-llvm -c, AndersenWaveDiff, and helper options -stat=false -ff-eq-base. Extraction intentionally uses the pinned compiler host-default x86_64-pc-linux-gnu target; smoke explicitly specifies the same triple. Full extraction and ordinary build configurations are separate manifest fields, both covered by the aggregate.

Pair-specific reviews describe analogue fairness, legitimate differences, target rationale, and storage/runtime distinctions. Source spans were recomputed from every definition/callsite anchor in all six edited sources. No analyzer or graph output was used.

## Final dynamic runtime provenance correction

R1-R4 and every pair/source/expectation/build/runtime field are unchanged. Full C and Rust analyzer/compiler dynamic dependency closures, canonical paths, SONAME/RPATH/RUNPATH metadata, SHA-256 values, exact Clang resolution and the selected SVF external model are bound in semantic_extraction_configuration.

C requires LD_LIBRARY_PATH and SVF_DIR unset, no extapi override, and no library substitution. The verifier repeats actual loader candidate resolution and external-model precedence from repository-root cwd. Rust uses the direct pinned toolchain/sysroot (no rustup selector), the existing exact two-directory LD_LIBRARY_PATH, RUSTC_BOOTSTRAP=1 and MIR_PROBE_TRANSITIVE=1. Both reject LD_PRELOAD/LD_AUDIT and verify the full dependency closure.

Before each future separately authorized calibration analyzer run, call runtime_provenance.pre_measurement_gate with the exact launch environment and helper options; abort on any error and do not change them after verification. This gate validates the bundle and resolved inputs, never launches an analyzer. verify_instruments now also reports expected/resolved paths and expected/actual hashes.

Both earlier bundles remain superseded_before_measurement, with no analyzer outputs. The latest supersession reason is: final independent preregistration audit identified incomplete dynamic analysis-runtime fingerprinting. See final_runtime_provenance.json.
