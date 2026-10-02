# Controlled-only MIR spike: acceptance contract

Registered before MIR controlled analysis. No historical source or depth is
an input to this spike. The Rust population and mappings are immutable.

Primary metric, if the instrument is eventually accepted: shortest path in the
raw semantic **instance** graph. Every call transition counts one, including
compiled std/core generics and compiler shims. No shim contraction is primary.
Record raw edge count, std/core nodes and shim nodes separately. Source-level
aggregation must retain all legitimate monomorphized instances. No numeric
historical results may be emitted by this spike.

Required precision is inclusion-based, flow-insensitive, context-insensitive,
and typed-field-sensitive. Propagate function values and receiver allocation
types through actual MIR assignments/copies/arguments/returns. Never use every
type-compatible function or every trait impl as a primary target set.

Identity must separate instance from source: crate identity, DefPath, concrete
substitutions, instance/shim kind, impl type, closure identity and normalized
source span. Session DefId numbers and absolute paths are not scientific IDs.

Use actual rustc 1.93.0 APIs, testing post-drop-elaboration MIR at optimization
level zero, without MIR inlining. Instance bodies require explicit generic
substitution; do not assume a monomorphized MIR body already exists. Preserve
drop/shim nodes and explicit unresolved or external boundaries.

Allocation-site abstractions and typed projections must separate callbacks in
distinct fields. Byte operations/union aliasing/unknown offsets require an
allocation-local conservative merge with a precision-loss record, not silently
precise fields. Missing or unsupported MIR must fail the reporting gate.

All original 31 controlled Rust cases are required, plus Rust-source unsafe
and mixed-object adversaries in the user specification. Dynamic traces must be
subsets of the static graph; traces cannot supply static edges. Two clean runs
must produce byte-identical normalized graphs.

## Cross-language pairs and expected relationships

| Pair | Pre-registered expectation |
| --- | --- |
| Direct chain | entry -> a -> target; both direct transitions retained |
| Recursion | recursive edge and exit target both retained |
| Single pointer | exactly the assigned function |
| Conditional pointer | both assigned functions; no unrelated compatible function |
| First callback field | first-field target only |
| Non-first callback field | second-field target only |
| Stack struct copy | copy preserves field-specific targets |
| Heap struct | allocation-site object preserves field-specific targets |
| Generic / C specialization | distinct concrete instances, grouped source identity only in Rust |
| Static dispatch | concrete implementation target, not same-named other impl |
| dyn / explicit vtable | targets from actual receiver values; no unrelated implementation |
| Closure / context callback | environment-mediated call retained; Rust shim differences reported |
| qsort / sort_by | external C library boundary versus compiled Rust generic path reported, not forced equal |
| Mixed stack/static | union of targets from objects reaching the site, respecting fields |
| Mixed stack/heap | union of targets from reaching allocations, respecting fields |

Compare target-set size distributions, edges, unresolved sites and comparable
paths. Genuine runtime/library/shim structure may differ across languages.
Neither fewer edges nor matching numeric depths establishes equivalence.

MIR-GO requires every semantic, trace, calibration and determinism gate. Any
unimplemented gate is **not run / not accepted**, never an inferred pass.
