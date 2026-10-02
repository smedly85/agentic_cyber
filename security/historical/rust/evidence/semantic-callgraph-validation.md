# Controlled Rust semantic failure evidence

This is instrument evidence, not vulnerability inclusion/mapping evidence.
The frozen 45-CVE population and functions were not changed.

Rust 1.93.0 emits LLVM 21.1.8 bitcode accepted by LLVM 21.1.8 and the pinned SVF
helper (SVF 3.4 / AndersenWaveDiff). Compilation, linking, disassembly and LLVM
verification all exit zero. The helper exits zero and emits a graph, but its
required trait-object may-target resolution is incomplete.

The synthetic `Operation` trait has `First` and `Second` implementations at
`tests/fixtures/rust_semantic/instrument.rs:59` and `:63`. The controlled entry
passes either object's vtable to `dynamic_dispatch`; the implementations then
call `target` and `alternate`. The expected entry-to-target depth is three.
These expectations define the controlled test, not replacement semantic edges.

The emitted module contains both methods as LLVM definitions with DISubprogram
locations. Its `@vtable.0` and `@vtable.1` constants contain their method pointers.
The dispatcher contains this use of its incoming vtable:

```llvm
%1 = getelementptr inbounds i8, ptr %value.1, i64 24
%2 = load ptr, ptr %1, align 8
%_0 = call i64 %2(ptr align 1 %value.0, i64 %x)
```

The exact cached IR includes debug attachments and call attributes; the excerpt
above omits those only for readability. This IR inspection establishes fixture
preservation, not a source-derived scientific call edge.

SVF emits no resolved-indirect edges from `dynamic_dispatch` and records:

```json
{
  "caller": "tests/fixtures/rust_semantic/instrument.rs::dynamic_dispatch",
  "callsite": {
    "column": 11,
    "line": 73,
    "source_file": "tests/fixtures/rust_semantic/instrument.rs"
  },
  "status": "unresolved_indirect_callsite"
}
```

Both implementation functions are present in the helper output; this particular
failure is not explained by the helper dropping their source identities. All 32
defined LLVM functions are accounted for. Internal SVF cause remains unproven.
No IR rewriting, guessed vtable edges, alternate pointer analysis, lexical
fallback, function contraction or historical measurement was performed to make
this case pass.

The committed `semantic_validation.json` preserves 12 passing cases, this failing
case, the 45-edge graph, all target instances/paths, debug identities, exact
commands (repository prefix tokenized), tool versions and cached artifact hashes.
Per the requested stop condition, pilots and full-population measurement remain
blocked. Nonnumeric accounting is in `semantic_results.json`, and the complete
45-row display is in `final-depth-table.md`.
