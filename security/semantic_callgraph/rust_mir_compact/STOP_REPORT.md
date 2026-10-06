# Historical Rust measurement: stopped at exactness gate

The compact solver candidate is rejected. No historical measurement was started and no performance amendment was frozen. The requested historical depth table cannot be produced from this candidate.

The separate candidate implements sparse 256-bit token blocks, shared immutable bitsets, bounded exact-union caching and generation checks. It retains the reference sweep traversal and cap. The reference and previous performance candidate remain unchanged.

## Observed failure

Both clean replicas passed the preceding 23 controlled cases. The first completed `iterator_flat_map` comparison failed. The validation supervisor stopped the remaining replica and mirrored unit run immediately; calibration and remaining adversarial validation were not completed.

Both reference and candidate converged after 45 sweeps, with 1125 cells. The candidate lacks 148 reference points-to facts across 20 cells, with 0 candidate-only facts. Collapsed groups and the cell membership index match. Four non-callable memory-event records also differ in their collapse reasons/source provenance.

The exported semantic graph, target relation, unresolved records, shortest paths and depths for this one fixture are byte-identical. That does not satisfy the requirement to compute the same fixed point: the internal fact relation differs. The comparison was not weakened to accept this candidate, and no fix or second optimization cycle was attempted.

## Consequences

No printenv, mktemp or sort analyzer execution occurred in this task. Historical computational feasibility was therefore not retested. This failure is evidence against this implementation's exactness, not a new proof that every exact implementation is computationally infeasible.

No vulnerability depth, program maximum or distribution is available from this attempt. Missing values remain unavailable, never zero. Method-v1 stays frozen at zero accepted depths; all 45 population members, including unresolved/not-applicable cases, retain their frozen identities and classifications.

Final integrity passed for 33583 protected files, frozen runtimes, mappings, population, classifier, calibration, C artifacts and original extraction/reference sources.

Rejected candidate SHA-256: `32d0a2de4e61904ed1eabf6de08729f61695abd68716ae8ef657c01c532fba7d`

Evidence: `build/rust-mir/solver-compact/validation_stop.json`, `equality_failure_evidence.json`, `state_mismatch_details.json`, the preserved `equality-v1` directories, `integrity_after.json`, and `final_status.json`.

The contingent amendment and study-runner source files were prepared but never executed. They remain guarded by the missing validation/practical-convergence certificates.

**STOP_EXACTNESS_FAILURE**
