# Harness amendments after preregistration

The preregistered files (`ACCEPTANCE_CRITERIA.md`, `expectations.json`,
`fixtures/supplement.rs`, and the frozen calibration manifest) were hashed in
`preregistration.json` at 2026-10-08T19:03:37Z and have not been edited since;
`validate.py` refuses to run if any hash changes. One harness smoke run
(`build/rust-llvm-svf-v1/smoke-1`, configuration `P`, one run) exposed two
defects in how the *harness* interpreted those expectations. Both are
corrected in `validate.py` only. Neither changes an expected target, depth,
path or criterion. Both are reported separately so a reader can apply the
unamended reading.

## A-1 Functions absent because rustc never codegened them

The `expanded` program is one binary crate per `cfg(audit_case=...)` value
sharing one function table. rustc's monomorphization collector emits only
items reachable from the crate's roots, so a variant that never calls, say,
`boxed_mut` contains no LLVM definition for it. The smoke harness reported
every such label as `function_not_found`.

Correction: a label is required only if the variant's own sites or cases
reference it, other than in an `unreachable` list. An absent function is
trivially unreachable. Absent, unreferenced labels are listed per program as
`absent_unreferenced_labels`.

## A-2 Source "indirect" sites that rustc emitted as direct LLVM calls

In several calibration fixtures (for example
`single_pointer/fixture.rs:13`, `let callback: fn(i32) -> i32 = target;
callback(10)`), rustc 1.93 at `opt-level=0` emits `call @target(...)`, a
*direct* LLVM call. The function-pointer value is a compile-time constant at
the MIR level. SVF therefore reports a direct edge, and no indirect site
exists to adjudicate. The smoke harness reported `site_not_found`.

Correction: when a preregistered site has no indirect row but direct edges
from the same caller and source line exist, the site is classified
`lowered_to_direct_call_exact` (callee set equals the expected set) or
`lowered_to_direct_call_mismatch`. The amended tally counts the exact form as
passed for A4, because the call site's target set *is* exactly the expected
set. The record also carries `strict_preregistered_passed: false`. These sites
exercise rustc's constant handling, not SVF pointer analysis, so they are
never cited as evidence of indirect-call resolution. The acceptance decision
in `VALIDATION_REPORT.md` is stated under both readings.

## A-3 Additional diagnostic and sensitivity instruments

The smoke runs showed four distinct failure classes. To attribute them
causally instead of by hypothesis, three more separately built SVF 67efb774
instruments were added after preregistration. All use the same
`build_sensitivity_svf.sh`, a fresh tree and the C helper source unchanged:

| Id | Patches | Purpose |
|---|---|---|
| `S-bo` | `svf-byte-offset.patch` only | attribute the vtable / non-first-field failures |
| `S-vg` | `svf-rust-vcall-gate.patch` only | attribute the `Box<dyn …>` failures |
| `S3` | byte-offset + vcall-gate + `svf-allockind-heap.patch` | test whether the heap failures are only the unmodeled Rust allocator |

`svf-allockind-heap.patch` was written after the smoke run. Its basis is
source inspection: SVF recognizes heap allocators only through `extapi.c` name
annotations (`LLVMModuleSet::is_alloc` / `is_realloc`), and Rust's mangled
`__rust_alloc` / `__rust_realloc` declarations instead carry LLVM
`allockind(...)` / `allocsize` attributes. The decision rule is unchanged:
only `P`, the C study's instrument, can authorize historical measurement.
These instruments only explain failures and size the next engineering step.

The first version of `svf-allockind-heap.patch` changed only
`LLVMModuleSet::is_alloc` / `is_realloc`. SVF keeps a second, core-side
annotation store (`ExtAPI::is_alloc` on `FunObjVar`), and that is the store
`SVFIRBuilder::handleExtCall` consults. The first version therefore never
reached SVFIR construction. It was replaced before the final validation run
by the current version, which synthesizes `ALLOC_HEAP_RET` /
`REALLOC_HEAP_RET` entries in `ExtFun2Annotations`, the single map from which
both stores are filled. `S3` in the final results was built from the current
patch. Even so, `heap_struct` stays unresolved. The cause is F5 in
`README.md`: `extractvalue` is modeled as the black hole. An earlier
full run is kept as `build/rust-llvm-svf-v1/validation-superseded-provenance-token`.
It used the first `S3`, and its finalized-graph provenance embedded the
run-specific bitcode path, so its determinism check failed on that provenance
string even though raw helper output was byte-identical. It is not the
evidence of record. A later rerun was stopped part-way when the allocator
patch was corrected, and its partial output was discarded.

## A-4 Byte-identical bitcode across runs

The next complete run (`build/rust-llvm-svf-v1/validation-superseded-compdir`)
had byte-identical raw helper output in every configuration and program.
Its verdicts were the same in both runs. But its Rust `linked.bc` files
differed between runs in exactly one place: rustc records its working
directory as the codegen unit's DWARF compilation directory, and the harness
had compiled inside the run-specific crate output directory. The finalized
graphs differed only in the recorded `linked_bitcode_sha256`, so A8 was
reported false. Rather than normalizing the hash away, `pipeline.py` now runs
rustc with the working directory at the repository root (remapped to `.`).
Two independent compiles then produce byte-identical linked bitcode. The
evidence of record is the run made after this change.

## A-5 Disclosure: prior-audit outputs were read before preregistration

`ACCEPTANCE_CRITERIA.md` says the only analyzer output seen beforehand was
the exploratory `dynamic_dispatch` reproduction. That statement is
incomplete. Before writing the expectations I also read, from git history,
`rust_audit_v3/README.md` and `rust_audit_v3/controlled_results.md`
(`git show b7484fa0^:…`). Those files list observed per-site target sets for
the same `instrument` and `expanded` fixtures under the earlier v2
instrument. Because the preregistered file is hash-frozen, the correction is
recorded here instead.

The expectations in `expectations.json` were derived from the fixture source
(what each call can actually reach at run time), not from those outputs, but
the reader should weigh them as written with that knowledge. The 15
calibration expectations in `fixture_manifest.json` predate this work
entirely. They are the cleanest independent test, and they lead to the same
decision on their own. Under `P`, 4 of the 15 Rust calibration programs fail
under the amended reading (`dyn_vtable`, `heap_struct`, `mixed_stack_heap`,
`mixed_stack_static`), and 8 fail under the strict reading, which also counts
the four direct-lowered sites. All 15 C programs pass.

## A-6 Post-hoc mechanism probes

`mechanism_probe.py` and `fixtures/mechanism/*.c` were added after the
validation of record, to test findings F4 and F5 directly. They are not part
of the acceptance decision. Results are in `mechanism_probe_results.json`.
