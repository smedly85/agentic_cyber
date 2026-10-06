"""Publish the failed exactness gate; never execute or repair the solver."""
import datetime
from common import ROOT,HERE,OUT,read,write,sha
failure=read(OUT/'equality_failure_evidence.json');state=read(OUT/'state_mismatch_details.json')['summary']
integrity=read(OUT/'integrity_after.json');assert integrity['status']=='PASS'
assert failure['candidate_sha256']==sha(HERE/'inclusion.py')
assert not (OUT/'validation_complete.json').exists()
assert not (OUT/'historical-diagnostic').exists()
assert not (OUT/'frozen_amendment_pointer.json').exists()
assert not (ROOT/'build/historical-rust-measurement/method-v2-compact').exists()
counts={run:len(read(OUT/'equality-v1'/run/'summary.json')) for run in ('candidate-1','candidate-2')}
result={'status':'STOP_EXACTNESS_FAILURE','candidate_accepted':False,'candidate_sha256':failure['candidate_sha256'],
    'failed_case':'controlled/iterator_flat_map','state_difference':state,'preceding_exact_cases':counts,
    'historical_measurement_attempted':False,'historical_depths_accepted':0,'performance_amendment_frozen':False,
    'historical_feasibility_retested':False,'another_optimization_cycle_started':False,
    'population_preserved':45,'method_v1_accepted_depths_preserved':0,
    'protected_files_unchanged':integrity['protected_files_verified'],
    'depth_distribution':{'n':0,'minimum':None,'mean':None,'median':None,'maximum':None,
        'frequency':{},'proportion_le_1':None,'proportion_le_2':None,'proportion_le_4':None,
        'status':'not_measured_candidate_failed_exactness'},
    'program_max_depth_distribution':{'n':0,'minimum':None,'mean':None,'median':None,'maximum':None,
        'status':'not_measured_candidate_failed_exactness'},
    'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
write(OUT/'final_status.json',result)
lines=['# Historical Rust measurement: stopped at exactness gate','',
    'The compact solver candidate is rejected. No historical measurement was started and no performance amendment was frozen. '
    'The requested historical depth table cannot be produced from this candidate.', '',
    'The separate candidate implements sparse 256-bit token blocks, shared immutable bitsets, bounded exact-union caching and generation checks. '
    'It retains the reference sweep traversal and cap. The reference and previous performance candidate remain unchanged.', '',
    '## Observed failure', '',
    'Both clean replicas passed the preceding 23 controlled cases. The first completed `iterator_flat_map` comparison failed. '
    'The validation supervisor stopped the remaining replica and mirrored unit run immediately; calibration and remaining adversarial validation were not completed.', '',
    f"Both reference and candidate converged after {state['reference_sweeps']} sweeps, with {state['reference_cells']} cells. "
    f"The candidate lacks {state['reference_only_facts']} reference points-to facts across {state['different_cells']} cells, with {state['candidate_only_facts']} candidate-only facts. "
    'Collapsed groups and the cell membership index match. Four non-callable memory-event records also differ in their collapse reasons/source provenance.', '',
    'The exported semantic graph, target relation, unresolved records, shortest paths and depths for this one fixture are byte-identical. '
    'That does not satisfy the requirement to compute the same fixed point: the internal fact relation differs. '
    'The comparison was not weakened to accept this candidate, and no fix or second optimization cycle was attempted.', '',
    '## Consequences', '',
    'No printenv, mktemp or sort analyzer execution occurred in this task. Historical computational feasibility was therefore not retested. '
    'This failure is evidence against this implementation\'s exactness, not a new proof that every exact implementation is computationally infeasible.', '',
    'No vulnerability depth, program maximum or distribution is available from this attempt. Missing values remain unavailable, never zero. '
    'Method-v1 stays frozen at zero accepted depths; all 45 population members, including unresolved/not-applicable cases, retain their frozen identities and classifications.', '',
    f"Final integrity passed for {integrity['protected_files_verified']} protected files, frozen runtimes, mappings, population, classifier, calibration, C artifacts and original extraction/reference sources.", '',
    f"Rejected candidate SHA-256: `{failure['candidate_sha256']}`", '',
    'Evidence: `build/rust-mir/solver-compact/validation_stop.json`, `equality_failure_evidence.json`, '
    '`state_mismatch_details.json`, the preserved `equality-v1` directories, `integrity_after.json`, and `final_status.json`.', '',
    'The contingent amendment and study-runner source files were prepared but never executed. They remain guarded by the missing validation/practical-convergence certificates.', '',
    '**STOP_EXACTNESS_FAILURE**','']
(HERE/'STOP_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
paths=list(p for p in HERE.iterdir() if p.is_file())+[OUT/n for n in ('validation_stop.json','equality_failure_evidence.json','state_mismatch_details.json','integrity_after.json','final_status.json')]
write(OUT/'stop_evidence_manifest.json',{'status':'STOP_EXACTNESS_FAILURE','files':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}})
print('STOP_EXACTNESS_FAILURE; protected files unchanged; no historical measurement',flush=True)
