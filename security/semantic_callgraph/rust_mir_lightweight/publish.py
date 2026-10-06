import collections,csv,statistics
from common import ROOT,HERE,OUT,OLD,RESULTS,read,write,sha

def distribution(values):
    values=sorted(values)
    return {'n':len(values),'minimum':min(values) if values else None,'mean':statistics.mean(values) if values else None,
        'median':statistics.median(values) if values else None,'maximum':max(values) if values else None}
def csvfile(name,rows,columns):
    with (RESULTS/name).open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');writer.writeheader()
        for row in rows:writer.writerow({k:row.get(k) for k in columns})

def main():
    assert read(OUT/'historical_complete.json')['status']=='PASS'
    assert read(OUT/'integrity_after.json')['status']=='PASS'
    RESULTS.mkdir(parents=True,exist_ok=False)
    (RESULTS/'VALIDATION_REPORT.md').write_bytes((HERE/'VALIDATION_REPORT.md').read_bytes())
    rows=read(OUT/'historical_observations.json');contexts=read(OUT/'historical_contexts.json')
    mappings=read(ROOT/'security/historical/rust/vulnerable_function_mappings.json')['records']
    for m in mappings:
        if m['mapping_status']=='verified':continue
        for i,target in enumerate(m['vulnerable_functions'] or [{}]):
            rows.append({'cve':m['cve_id'],'utility':','.join(target.get('affected_executables',[])) or 'not applicable',
                'function':target.get('function') or 'not applicable','source_file':target.get('source_file'),
                'observation_id':m['cve_id']+':'+str(i),'release':m['affected_version'],'revision':m['affected_revision'],
                'status':'not_applicable' if m['mapping_status']=='not_applicable' else 'unresolved_mapping',
                'vulnerability_depth':None,'max_depth':None,'comparability':'Rust-only; no C/Rust comparison'})
    assert len({r['cve'] for r in rows})==45
    measured=[r for r in rows if r['vulnerability_depth'] is not None]
    indirect=[r for r in rows if r['status']=='unresolved_with_indirect_boundary']
    values=[r['vulnerability_depth'] for r in measured];stats=distribution(values)
    stats['frequency_by_depth']=dict(sorted(collections.Counter(values).items()))
    stats.update({'proportion_le_'+str(k):sum(v<=k for v in values)/len(values) if values else None for k in (1,2,4)})
    maxima=distribution([r['max_depth'] for r in contexts if r['max_depth'] is not None])
    cves=[]
    for m in mappings:
        relevant=[r for r in rows if r['cve']==m['cve_id']];finite=[r['vulnerability_depth'] for r in relevant if r['vulnerability_depth'] is not None]
        status='measured' if len(finite)==len(relevant) else 'partially_measured' if finite else ','.join(sorted({r['status'] for r in relevant}))
        cves.append({'cve':m['cve_id'],'mapping_status':m['mapping_status'],'status':status,'function_context_rows':len(relevant),
            'measured_rows':len(finite),'minimum_depth':min(finite) if finite else None,'maximum_depth':max(finite) if finite else None})
    counts={'population_CVEs':45,'verified_function_records':49,'verified_function_executable_contexts':51,
        'measured_CVEs_any_function':len({r['cve'] for r in measured}),
        'fully_measured_CVEs':sum(c['status']=='measured' for c in cves),
        'measured_function_records':len({r['observation_id'] for r in measured}),
        'measured_function_context_rows':len(measured),
        'unresolved_with_indirect_boundary_function_rows':len(indirect),
        'unresolved_with_indirect_boundary_CVEs':len({r['cve'] for r in indirect}),
        'status_counts':dict(collections.Counter(r['status'] for r in rows)),
        'indirect_attribution_note':'No known-edge path reaches these mapped targets and unresolved indirect sites are entry-reachable. Which missing indirect edge would reach a target is not proven; no targets were invented.'}
    result={'method':'rust-only-lightweight-v1','method_fingerprint':read(OUT/'method_freeze.json')['fingerprint'],
        'metric_scope':'Shortest BFS distances and maximum finite shortest distance in the retained compiler-resolved MIR graph',
        'whole_program_may_call_completeness_claimed':False,'C_Rust_comparability_claimed':False,
        'points_to_solver_used':False,'counts':counts,'vulnerability_distribution':stats,'program_max_distribution':maxima,
        'statistics_unit':'Frozen vulnerable source function / executable-platform context; executable maxima counted once',
        'observations':rows,'program_contexts':contexts,'cve_summary':cves,
        'determinism':read(OUT/'historical_complete.json'),'integrity':{'status':'PASS','protected_files':read(OUT/'integrity_after.json')['protected_files_verified']}}
    write(RESULTS/'semantic_results.json',result);write(RESULTS/'depth_distribution.json',{'vulnerability_depth':stats,'program_max_depth':maxima})
    write(RESULTS/'measurement_failures.json',[r for r in rows if r['vulnerability_depth'] is None])
    write(RESULTS/'instrument_provenance.json',{'method_freeze':read(OUT/'method_freeze.json'),
        'input_inventory':read(OUT/'historical_input_inventory.json'),'validation_summary_sha256':sha(OUT/'validation_summary.json'),
        'frozen_build_provenance':read(OLD/'complete_build_provenance.json'),'integrity_after_sha256':sha(OUT/'integrity_after.json'),
        'compilation':'Frozen MIR reused; no dependencies, source editions or build configuration changed',
        'graph_replication':'Two independent graph processes/output directories, same immutable extracted MIR',
        'points_to_solver_used':False})
    csvfile('function_results.csv',rows,['cve','utility','function','vulnerability_depth','max_depth','status','coverage','source_file','target','release','revision',
        'entry','target_instance_count','reachable_unresolved_indirect_calls','reachable_body_boundaries','graph_artifact'])
    csvfile('program_max_depths.csv',contexts,['release','revision','utility','entry','max_depth','reachable_instances','coverage',
        'reachable_unresolved_indirect_calls','reachable_body_boundaries','deterministic','graph_artifact'])
    csvfile('cve_summary.csv',cves,list(cves[0]))
    tracker=[{'CVE':r['cve'],'Utility':r['utility'],'Vulnerable function':r['function'],'Vulnerability depth':r['vulnerability_depth'],
        'Max depth':r['max_depth'],'Status':r['status']} for r in rows]
    csvfile('tracker_ready.csv',tracker,list(tracker[0]))
    show=lambda v:'unavailable' if v is None else str(v)
    lines=['# Historical Rust-only lightweight MIR depths','',
        'These are depths in the retained compiler-resolved MIR call graph. No inclusion/points-to solver was used. '
        'They are not complete whole-program may-call depths and are not directly comparable to C results. '
        'Unresolved calls can hide routes or shortcuts; a maximum over the retained graph is not a longest path or a bound on the complete graph maximum.', '',
        f"Method fingerprint: `{result['method_fingerprint']}`.", '',
        f"Measured {counts['measured_function_context_rows']} of 51 verified executable/function observations, "
        f"representing {counts['measured_function_records']} of 49 verified source-function records and {counts['measured_CVEs_any_function']} of 45 CVEs.", '',
        '| CVE | Utility | Vulnerable function | Vulnerability depth | Max depth | Status |','|---|---|---|---:|---:|---|']
    for r in rows:
        function=r['function']+(' [Windows]' if '/windows.rs' in (r.get('source_file') or '') else '')
        lines.append('| '+' | '.join(show(v).replace('|','\\|') for v in [r['cve'],r['utility'],function,r['vulnerability_depth'],r['max_depth'],r['status']])+' |')
    lines += ['', '## Descriptive statistics','',f'Vulnerability depths: `{stats}`.', '',f'Program maximum depths: `{maxima}`.', '',
        f"Unresolved with entry-reachable indirect boundaries: {len(indirect)} function-context rows across {counts['unresolved_with_indirect_boundary_CVEs']} CVEs. "
        'This counts absent known-edge routes in contexts containing unresolved indirect calls; it does not prove which indirect call reaches a missing target.', '',
        f"Status counts: `{counts['status_counts']}`.", '',
        'measured_partial_graph means a concrete known-edge path exists, but reachable unresolved calls or body boundaries limit whole-program coverage. '
        'A missing path is never encoded as zero. The two frozen unresolved mappings and the not-applicable CVE retain their prior classifications.', '',
        '## Validation and provenance','',
        'All 103 existing controlled/focused/adversarial/calibration inputs were tested twice. Required concrete-call paths match frozen controls; '
        'each retained edge has compiler evidence. Unresolved function-pointer/dyn relations remain explicit. See VALIDATION_REPORT.md for construct coverage.', '',
        f"Historical graph reruns are byte-identical. Final preservation check passed for {result['integrity']['protected_files']} files. "
        'The C results, original instruments, calibration, classifier, mappings, population, method-v1 and prior solver-failure evidence remain unchanged.', '',
        'Original compiler-extracted MIR and build/dependency/edition provenance were reused by hash. No historical source was recompiled in this run. '
        'Fresh lightweight graph processes were gated individually. Known unavailable-body Instances are retained as explicit boundary nodes with no invented outgoing edges.', '',
        'Files: semantic_results.json, function_results.csv, tracker_ready.csv, cve_summary.csv, program_max_depths.csv, '
        'depth_distribution.json, measurement_failures.json and instrument_provenance.json. Raw input hashes, gates, graphs, selected paths and maxima are in build/rust-mir/lightweight-v1.', '']
    (RESULTS/'HISTORICAL_RUST_RESULTS.md').write_text('\n'.join(lines),encoding='utf-8')
    write(RESULTS/'artifact_hashes.json',{'files':{p.name:sha(p) for p in RESULTS.iterdir() if p.is_file()}})
    print(counts,flush=True);print('VULNERABILITY',stats,flush=True);print('MAXIMA',maxima,flush=True)
if __name__=='__main__':main()
