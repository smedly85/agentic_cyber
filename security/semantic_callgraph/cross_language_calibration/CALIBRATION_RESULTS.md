# Approved cross-language calibration results

CALIBRATION-FAIL

Frozen bundle: `ed7ea699999445b3db2da1113637b4e19a00c7e07a77277bef48e984d6ca3024`. Sources, manifest, expectations, backends and runtime provenance were not modified.

All 60 individual semantic invocations had a passing live gate immediately before launch with the identical environment/options. Run 1 and run 2 evidence is retained separately.

| Pair | Status | C raw depth(s) | Rust raw depth(s) |
|---|---|---|---|
| direct_chain | EXACT | 2 | 2 |
| recursion | EXACT | 2 | 2 |
| single_pointer | EXACT | 1 | 1 |
| multi_pointer | EXACT | 1, 1 | 1, 1 |
| first_field | EXACT | 1 | 1 |
| non_first_field | EXACT | 1 | 1 |
| stack_copy | EXACT | 1 | 1 |
| heap_struct | STRUCTURALLY_COMPARABLE | 1 | 1 |
| generic_specialization | STRUCTURALLY_COMPARABLE | 2 | 2 |
| static_dispatch | EXACT | 2 | 2 |
| dyn_vtable | STRUCTURALLY_COMPARABLE | 1, 1 | 1, 1 |
| closure_context | STRUCTURALLY_COMPARABLE | 2 | 2 |
| library_callback | FAIL | unreachable | 8 |
| mixed_stack_static | EXACT | 2, 2 | 2, 2 |
| mixed_stack_heap | STRUCTURALLY_COMPARABLE | 2, 2 | 2, 2 |

## Preregistered relations versus measurements

| Pair | C expected relation | C measured relation | Rust expected relation | Rust measured relation | Result |
|---|---|---|---|---|---|
| direct_chain | [('entry', 'helper'), ('helper', 'target')]; [] | [('entry', 'helper'), ('helper', 'target')]; [] | [('entry', 'helper'), ('helper', 'target')]; [] | [('entry', 'helper'), ('helper', 'target')]; [] | EXACT |
| recursion | [('entry', 'recursive'), ('recursive', 'recursive'), ('recursive', 'target')]; [] | [('entry', 'recursive'), ('recursive', 'recursive'), ('recursive', 'target')]; [] | [('entry', 'recursive'), ('recursive', 'recursive'), ('recursive', 'target')]; [] | [('entry', 'recursive'), ('recursive', 'recursive'), ('recursive', 'target')]; [] | EXACT |
| single_pointer | []; [['target']] | [('entry', 'target')]; [['target']] | []; [['target']] | [('entry', 'target')]; [['target']] | EXACT |
| multi_pointer | []; [['target_a', 'target_b']] | [('entry', 'target_a'), ('entry', 'target_b')]; [['target_a', 'target_b']] | []; [['target_a', 'target_b']] | [('entry', 'target_a'), ('entry', 'target_b')]; [['target_a', 'target_b']] | EXACT |
| first_field | []; [['target']] | [('entry', 'target')]; [['target']] | []; [['target']] | [('entry', 'target')]; [['target']] | EXACT |
| non_first_field | []; [['target']] | [('entry', 'target')]; [['target']] | []; [['target']] | [('entry', 'target')]; [['target']] | EXACT |
| stack_copy | []; [['target']] | [('entry', 'target')]; [['target']] | []; [['target']] | [('entry', 'target')]; [['target']] | EXACT |
| heap_struct | []; [['target']] | [('entry', 'target')]; [['target']] | []; [['target']] | [('entry', 'target')]; [['target']] | STRUCTURALLY_COMPARABLE |
| generic_specialization | [('entry', 'helper_i32'), ('helper_i32', 'target')]; [] | [('entry', 'helper_i32'), ('helper_i32', 'target')]; [] | [('entry', 'helper'), ('helper', 'target')]; [] | [('entry', 'helper'), ('helper', 'target')]; [] | STRUCTURALLY_COMPARABLE |
| static_dispatch | [('entry', 'operation'), ('operation', 'target')]; [] | [('entry', 'operation'), ('operation', 'target')]; [] | [('entry', 'First::operation'), ('First::operation', 'target')]; [] | [('First::operation', 'target'), ('entry', 'First::operation')]; [] | EXACT |
| dyn_vtable | []; [['first_operation', 'second_operation']] | [('entry', 'first_operation'), ('entry', 'second_operation')]; [['first_operation', 'second_operation']] | []; [['First::operation', 'Second::operation']] | [('entry', 'First::operation'), ('entry', 'Second::operation')]; [['First::operation', 'Second::operation']] | STRUCTURALLY_COMPARABLE |
| closure_context | [('callback', 'target')]; [['callback']] | [('callback', 'target'), ('entry', 'callback')]; [['callback']] | [('entry', 'entry::closure'), ('entry::closure', 'target')]; [] | [('entry', 'entry::closure'), ('entry::closure', 'target')]; [] | STRUCTURALLY_COMPARABLE |
| library_callback | []; [] | []; [] | []; [] | [('entry', 'target')]; [] | FAIL |
| mixed_stack_static | [('entry', 'invoke')]; [['target_a', 'target_b']] | [('entry', 'invoke'), ('invoke', 'target_a'), ('invoke', 'target_b')]; [['target_a', 'target_b']] | [('entry', 'invoke')]; [['target_a', 'target_b']] | [('entry', 'invoke'), ('invoke', 'target_a'), ('invoke', 'target_b')]; [['target_a', 'target_b']] | EXACT |
| mixed_stack_heap | [('entry', 'invoke')]; [['target_a', 'target_b']] | [('entry', 'invoke'), ('invoke', 'target_a'), ('invoke', 'target_b')]; [['target_a', 'target_b']] | [('entry', 'invoke')]; [['target_a', 'target_b']] | [('entry', 'invoke'), ('invoke', 'target_a'), ('invoke', 'target_b')]; [['target_a', 'target_b']] | STRUCTURALLY_COMPARABLE |

## Dynamic validation

{
  "C": {
    "complete_soundness_passed": 14,
    "observed_edges": 26,
    "missing_dynamic_edges": 0,
    "proven_missing_boundary_edges": 1,
    "unmapped_edges": 1,
    "runtime_configurations_passed": 17
  },
  "Rust": {
    "complete_soundness_passed": 15,
    "observed_edges": 35,
    "missing_dynamic_edges": 0,
    "proven_missing_boundary_edges": 0,
    "unmapped_edges": 0,
    "runtime_configurations_passed": 17
  }
}

Mapped observations are compared one-way against the static graph. Unmapped boundary edges remain explicit and never become static edges. If a mapped application callee has zero static incoming edges, its observed native entry proves a missing edge even without resolving its external caller. Rebuilt precompiled std libraries are uninstrumented; the native tracer captures generated instrumented code and relevant inline frames, not every library-internal execution.

## Precision

{
  "C": {
    "site_count": 10,
    "exact_target_sets": 10,
    "conservative_supersets": 0,
    "missing_target_failures": 0,
    "mean_target_set_size": 1.4,
    "median_target_set_size": 1.0,
    "maximum_target_set_size": 2
  },
  "Rust": {
    "site_count": 9,
    "exact_target_sets": 9,
    "conservative_supersets": 0,
    "missing_target_failures": 0,
    "mean_target_set_size": 1.4444444444444444,
    "median_target_set_size": 1,
    "maximum_target_set_size": 2
  },
  "assessment": "Both are inclusion-based, context-insensitive and flow-insensitive. Field-specific and object-flow fixtures test field/heap distinctions; results describe this controlled corpus, not universal equivalence. Rust retains typed-place/Instance and compiler/runtime nodes; C uses SVF allocation objects and extapi models. External boundaries remain materially different.",
  "paired_sites": {
    "C": {
      "count": 9,
      "mean_target_set_size": 1.4444444444444444
    },
    "Rust": {
      "count": 9,
      "mean_target_set_size": 1.4444444444444444
    }
  },
  "systematic_overapproximation": "No extra target at any preregistered site in either language. On the nine corresponding indirect sites the target-set sizes agree; the C-only closure callback accounts for the different all-site means."
}

## Per-pair diagnostics

### direct_chain

Preregistered category: `exact_application_structure`. Measured status: EXACT.

C: failures []; decoy None; generic None.

C target: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/direct_chain/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/direct_chain/fixture.c::helper', 'security/semantic_callgraph/cross_language_calibration/fixtures/direct_chain/fixture.c::target']`.

Rust: failures []; decoy None; generic None.

Rust target: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(4297057312217983917, 12353611983048860132)::crate::entry', 'Fingerprint(1648234268717547741, 6984899402934110510)::crate::helper', 'Fingerprint(13582324048853964602, 6549823556232816184)::crate::target']`.

### recursion

Preregistered category: `exact_application_structure`. Measured status: EXACT.

C: failures []; decoy None; generic None.

C target: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/recursion/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/recursion/fixture.c::recursive', 'security/semantic_callgraph/cross_language_calibration/fixtures/recursion/fixture.c::target']`.

Rust: failures []; decoy None; generic None.

Rust target: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(5934120214003160220, 15079435405992437758)::crate::entry', 'Fingerprint(8688867381788860490, 2894138834448566951)::crate::recursive', 'Fingerprint(16960514319802935472, 10791300061770200733)::crate::target']`.

### single_pointer

Preregistered category: `equivalent_indirect_target_set`. Measured status: EXACT.

C: failures []; decoy None; generic None.

C target: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/single_pointer/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/single_pointer/fixture.c::target']`.

Rust: failures []; decoy None; generic None.

Rust target: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(6454402729821658345, 9329464837715034929)::crate::entry', 'Fingerprint(4256372852410081190, 1515918725566429510)::crate::target']`.

### multi_pointer

Preregistered category: `equivalent_indirect_target_set`. Measured status: EXACT.

C: failures []; decoy {'decoy': 'unrelated', 'present_in_compiled_inventory': True, 'tested_targets': ['target_a', 'target_b'], 'excluded_at_tested_relation': True}; generic None.

C target_a: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/multi_pointer/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/multi_pointer/fixture.c::target_a']`.

C target_b: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/multi_pointer/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/multi_pointer/fixture.c::target_b']`.

Rust: failures []; decoy {'decoy': 'unrelated', 'present_in_compiled_inventory': True, 'tested_targets': ['target_a', 'target_b'], 'excluded_at_tested_relation': True}; generic None.

Rust target_a: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(10879310329974805760, 1292325543348639070)::crate::entry', 'Fingerprint(12761283465093516183, 544474225877624069)::crate::target_a']`.

Rust target_b: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(10879310329974805760, 1292325543348639070)::crate::entry', 'Fingerprint(9069607345761000198, 14273616735444852598)::crate::target_b']`.

### first_field

Preregistered category: `equivalent_indirect_target_set`. Measured status: EXACT.

C: failures []; decoy None; generic None.

C target: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/first_field/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/first_field/fixture.c::target']`.

Rust: failures []; decoy None; generic None.

Rust target: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(11821994158870312719, 3764179339922171700)::crate::entry', 'Fingerprint(12910834887773845851, 10546707923214756632)::crate::target']`.

### non_first_field

Preregistered category: `equivalent_indirect_target_set`. Measured status: EXACT.

C: failures []; decoy None; generic None.

C target: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/non_first_field/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/non_first_field/fixture.c::target']`.

Rust: failures []; decoy None; generic None.

Rust target: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(3117720948759984719, 11769964724313286122)::crate::entry', 'Fingerprint(13248332312471426976, 5091041095916660766)::crate::target']`.

### stack_copy

Preregistered category: `equivalent_indirect_target_set`. Measured status: EXACT.

C: failures []; decoy None; generic None.

C target: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/stack_copy/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/stack_copy/fixture.c::target']`.

Rust: failures []; decoy None; generic None.

Rust target: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(16528247934361799266, 12112795933876417652)::crate::entry', 'Fingerprint(18082146420005639604, 15709105505637553574)::crate::target']`.

### heap_struct

Preregistered category: `equivalent_application_transition_with_runtime_nodes`. Measured status: STRUCTURALLY_COMPARABLE.

C: failures []; decoy None; generic None.

C target: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/heap_struct/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/heap_struct/fixture.c::target']`.

Rust: failures []; decoy None; generic None.

Rust target: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(404663768796613146, 12910999751865212788)::crate::entry', 'Fingerprint(766551708005927760, 11869872777859744512)::crate::target']`.

### generic_specialization

Preregistered category: `equivalent_application_transition_with_runtime_nodes`. Measured status: STRUCTURALLY_COMPARABLE.

C: failures []; decoy None; generic None.

C target: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/generic_specialization/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/generic_specialization/fixture.c::helper_i32', 'security/semantic_callgraph/cross_language_calibration/fixtures/generic_specialization/fixture.c::target']`.

Rust: failures []; decoy None; generic {'helper_concrete_instances': ['Fingerprint(18077007828411768182, 15818851702052155903)::crate::helper::<i32>'], 'instance_count': 1, 'source_observations': 1}.

Rust target: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(265041159061734637, 3841483341929546818)::crate::entry', 'Fingerprint(18077007828411768182, 15818851702052155903)::crate::helper::<i32>', 'Fingerprint(5630288484157774978, 12608037749607369523)::crate::target']`.

### static_dispatch

Preregistered category: `exact_application_structure`. Measured status: EXACT.

C: failures []; decoy {'decoy': 'second_operation', 'present_in_compiled_inventory': True, 'tested_targets': ['operation'], 'excluded_at_tested_relation': True}; generic None.

C target: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/static_dispatch/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/static_dispatch/fixture.c::operation', 'security/semantic_callgraph/cross_language_calibration/fixtures/static_dispatch/fixture.c::target']`.

Rust: failures []; decoy {'decoy': 'Second::operation', 'present_in_compiled_inventory': True, 'tested_targets': ['First::operation'], 'excluded_at_tested_relation': True}; generic None.

Rust target: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(4425045119941842083, 4271621792337467850)::crate::entry', 'Fingerprint(10329959975824597431, 6156691809424745557)::<crate::First as crate::Action>::operation', 'Fingerprint(11409217189171445147, 14874652157542246255)::crate::target']`.

### dyn_vtable

Preregistered category: `equivalent_application_transition_with_runtime_nodes`. Measured status: STRUCTURALLY_COMPARABLE.

C: failures []; decoy {'decoy': 'third_operation', 'present_in_compiled_inventory': True, 'tested_targets': ['first_operation', 'second_operation'], 'excluded_at_tested_relation': True}; generic None.

C first_operation: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/dyn_vtable/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/dyn_vtable/fixture.c::first_operation']`.

C second_operation: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/dyn_vtable/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/dyn_vtable/fixture.c::second_operation']`.

Rust: failures []; decoy {'decoy': 'Third::operation', 'present_in_compiled_inventory': True, 'tested_targets': ['First::operation', 'Second::operation'], 'excluded_at_tested_relation': True}; generic None.

Rust First::operation: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(8596723557034935233, 8715615655770297303)::crate::entry', 'Fingerprint(2820893641448092129, 16181352129596078074)::<crate::First as crate::Action>::operation']`.

Rust Second::operation: raw depth 1; decomposition {'user_application': 1, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(8596723557034935233, 8715615655770297303)::crate::entry', 'Fingerprint(10778473888840773752, 6058164972515072957)::<crate::Second as crate::Action>::operation']`.

### closure_context

Preregistered category: `equivalent_application_transition_with_runtime_nodes`. Measured status: STRUCTURALLY_COMPARABLE.

C: failures []; decoy None; generic None.

C target: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/closure_context/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/closure_context/fixture.c::callback', 'security/semantic_callgraph/cross_language_calibration/fixtures/closure_context/fixture.c::target']`.

Rust: failures []; decoy None; generic None.

Rust target: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(12614540765990450970, 6302036626961940647)::crate::entry', 'Fingerprint(16965684957973869103, 5564333595794391593)::crate::entry::{closure#0}', 'Fingerprint(8830726593464822445, 1495034038004605431)::crate::target']`.

### library_callback

Preregistered category: `expected_library_boundary_difference`. Measured status: FAIL.

C: failures ['Observed application callback entry has no incoming static edge from any caller']; decoy None; generic None.

C target: raw depth None; decomposition {'user_application': 0, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement True.
Path: `None`.

Rust: failures []; decoy None; generic None.

Rust target: raw depth 8; decomposition {'user_application': 1, 'std_core': 6, 'compiler_shim': 1, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(16120160203061477195, 13656217800991200196)::crate::entry', "Fingerprint(13771831578452267302, 8265746557652350525)::alloc::slice::<impl [i32]>::sort_by::<for<'a, 'b> fn(&'a i32, &'b i32) -> core::cmp::Ordering {crate::target}>", "Fingerprint(16269529683094544467, 16808300396037429887)::alloc::slice::stable_sort::<i32, {closure@alloc::slice::<impl [i32]>::sort_by<for<'a, 'b> fn(&'a i32, &'b i32) -> core::cmp::Ordering {crate::target}>::{closure#0}}>", "Fingerprint(710629572050017081, 15428215355245813747)::core::slice::sort::stable::sort::<i32, {closure@alloc::slice::<impl [i32]>::sort_by<for<'a, 'b> fn(&'a i32, &'b i32) -> core::cmp::Ordering {crate::target}>::{closure#0}}, alloc::vec::Vec<i32>>", "Fingerprint(3126373018546727306, 7431263139998942039)::core::slice::sort::shared::smallsort::insertion_sort_shift_left::<i32, {closure@alloc::slice::<impl [i32]>::sort_by<for<'a, 'b> fn(&'a i32, &'b i32) -> core::cmp::Ordering {crate::target}>::{closure#0}}>", "Fingerprint(14914804297398693023, 16978418131463710072)::core::slice::sort::shared::smallsort::insert_tail::<i32, {closure@alloc::slice::<impl [i32]>::sort_by<for<'a, 'b> fn(&'a i32, &'b i32) -> core::cmp::Ordering {crate::target}>::{closure#0}}>", "Fingerprint(3776541781850782503, 12952921512223195799)::alloc::slice::<impl [i32]>::sort_by::<for<'a, 'b> fn(&'a i32, &'b i32) -> core::cmp::Ordering {crate::target}>::{closure#0}", "Fingerprint(11184942525165259685, 3863723252724130199)::<for<'a, 'b> fn(&'a i32, &'b i32) -> core::cmp::Ordering {crate::target} as core::ops::function::FnMut<(&i32, &i32)>>::call_mut - shim(for<'a, 'b> fn(&'a i32, &'b i32) -> core::cmp::Ordering {crate::target})", 'Fingerprint(302220533241447900, 7355903412365449795)::crate::target']`.

### mixed_stack_static

Preregistered category: `equivalent_indirect_target_set`. Measured status: EXACT.

C: failures []; decoy None; generic None.

C target_a: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_static/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_static/fixture.c::invoke', 'security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_static/fixture.c::target_a']`.

C target_b: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_static/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_static/fixture.c::invoke', 'security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_static/fixture.c::target_b']`.

Rust: failures []; decoy None; generic None.

Rust target_a: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(5082903973860075473, 16220277494055082369)::crate::entry', 'Fingerprint(15394549205853099533, 13612886713328090211)::crate::invoke', 'Fingerprint(13137806790841379872, 10795130568048887469)::crate::target_a']`.

Rust target_b: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(5082903973860075473, 16220277494055082369)::crate::entry', 'Fingerprint(15394549205853099533, 13612886713328090211)::crate::invoke', 'Fingerprint(9686818714613534464, 13154581462431233460)::crate::target_b']`.

### mixed_stack_heap

Preregistered category: `equivalent_application_transition_with_runtime_nodes`. Measured status: STRUCTURALLY_COMPARABLE.

C: failures []; decoy None; generic None.

C target_a: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_heap/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_heap/fixture.c::invoke', 'security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_heap/fixture.c::target_a']`.

C target_b: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_heap/fixture.c::entry', 'security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_heap/fixture.c::invoke', 'security/semantic_callgraph/cross_language_calibration/fixtures/mixed_stack_heap/fixture.c::target_b']`.

Rust: failures []; decoy None; generic None.

Rust target_a: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(2525510355140070291, 4619315542966870097)::crate::entry', 'Fingerprint(3274240716120667402, 8634450290116574666)::crate::invoke', 'Fingerprint(17078693649253252261, 8575324925916974589)::crate::target_a']`.

Rust target_b: raw depth 2; decomposition {'user_application': 2, 'std_core': 0, 'compiler_shim': 0, 'drop_glue': 0}; external boundary involvement False.
Path: `['Fingerprint(2525510355140070291, 4619315542966870097)::crate::entry', 'Fingerprint(3274240716120667402, 8634450290116574666)::crate::invoke', 'Fingerprint(3800929733638476189, 4604256857364775520)::crate::target_b']`.

## Interpretation and limitations

The library_callback C graph exposes entry → external qsort and a comparator definition without any incoming static comparator edge; no C raw comparator depth is manufactured. Native execution records three comparator entries. Although the libc caller symbol is unresolved, zero static incoming edges proves those observed entries cannot be covered by this graph. Under the requested strict dynamic-subset rule this pair is FAIL, overriding its otherwise expected library-boundary classification. This is a boundary-coverage failure, not evidence that an internal C pointer target was lost. Rust represents compiled generic sorting/Fn structure.

dyn_vtable compares actual receivers and preserves any raw compiler transitions. closure_context compares C explicit context/callback with Rust capturing-closure structure; no raw path contraction is used. Generic helper count is evaluated as one concrete Instance and one source observation.

Deterministic replication: True. See deterministic_replication.json for byte comparisons of node/edge graphs, targets, shortest paths, depths and dynamic comparisons.

Post-measurement corpus and instrument verification passed before authorized result files replaced their preserved null snapshots. No historical Rust measurement was performed.

CALIBRATION-FAIL
