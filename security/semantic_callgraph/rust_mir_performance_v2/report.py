"""Assemble diagnostic repair evidence without reading vulnerability depths."""
import argparse, collections, datetime, json
from common import ROOT,HERE,OUT,read,write,sha

def totals(rows):
    result=collections.Counter()
    for row in rows:
        result.update({k:v for k,v in row['operation_counts'].items() if isinstance(v,(int,float))})
    return dict(result)

def gate_audit():
    records={};failures=[]
    def inspect(value,path):
        if isinstance(value,dict):
            if 'status' in value and value['status']!='PASS':failures.append((path,value['status']))
            for child in value.values():inspect(child,path)
        elif isinstance(value,list):
            for child in value:inspect(child,path)
    for name in ('gate.json','gates.json'):
        for p in OUT.rglob(name):
            inspect(read(p),p.relative_to(ROOT).as_posix());records[p.relative_to(ROOT).as_posix()]=sha(p)
    assert records and not failures,failures
    result={'status':'PASS','gate_record_files':len(records),'files':records,'failures':failures}
    write(OUT/'gate_audit.json',result)
    return {'status':'PASS','gate_record_files':len(records),'gate_audit_sha256':sha(OUT/'gate_audit.json')}

def main(verdict,reason):
    equality=read(OUT/'equality_summary.json');units=read(OUT/'unit_mirror_summary.json')
    performance=read(OUT/'performance_summary.json');integrity=read(OUT/'integrity_after.json')
    cold=read(OUT/'cold_extraction_results.json');historical=read(OUT/'historical_diagnostic_results.json')
    assert all(x['status']=='PASS' for x in (equality,units,performance,integrity))
    assert equality['candidate_sha256']==sha(HERE/'inclusion.py')
    assert len(cold)==3 and all(x['matches_frozen_extraction'] and x['cold_reruns_match'] for x in cold)
    counts={mode:totals(read(OUT/'performance'/mode/'results.json')) for mode in ('reference-counted','candidate')}
    diagnostic_rows=[]
    for context in historical:
        for replica in ('candidate-a','candidate-b'):
            folder=OUT/'historical-diagnostic'/context['utility']/replica
            if not folder.exists():continue
            row=read(folder/'result.json')
            if (folder/'completion.json').exists():row.update(read(folder/'completion.json'))
            else:
                lines=(folder/'progress.jsonl').read_text().splitlines()
                row['last_progress']=json.loads(lines[-1]) if lines else None
            diagnostic_rows.append(row)
    progress_comparison=[]
    for context in historical:
        folder=OUT/'historical-diagnostic'/context['utility']/'candidate-a'
        samples=[json.loads(s) for s in (folder/'progress.jsonl').read_text().splitlines()]
        for prior in context['prior_reference_trials']:
            p=ROOT/prior['path']/'progress.jsonl'
            old_samples=[json.loads(s) for s in p.read_text().splitlines()]
            old=next(s for s in reversed(old_samples) if 'points_to_facts' in s)
            reached=next((s for s in samples if s['operation_counts'].get('points_to_additions',0)>=old['points_to_facts']),None)
            progress_comparison.append({'utility':context['utility'],'reference_trial':prior['path'],
                'reference_last_sample_seconds':old['elapsed_seconds'],'reference_observed_facts':old['points_to_facts'],
                'candidate_first_recorded_threshold_seconds':reached['elapsed_seconds'] if reached else None,
                'interpretation':'Fact-count progress proxy only; not fixed-point equality or convergence speedup. Prior reference sampling overhead is included.',
                'reference_progress_sha256':sha(p)})
    if verdict=='PERFORMANCE-REPAIR-GO':
        assert all(c['first'] and c['first']['converged'] and c['second'] and c['second']['converged'] for c in historical)
    gates=gate_audit()
    report={'verdict':verdict,'reason':reason,'diagnostic_only':True,'historical_depths_accepted':0,'gates':gates,
        'candidate_sha256':equality['candidate_sha256'],'reference_sha256':equality['reference_sha256'],
        'equality':equality,'unit_tests':units,'performance':performance,'operation_totals':counts,
        'historical_diagnostics':diagnostic_rows,'historical_progress_comparison':progress_comparison,'cold_extraction':cold,
        'integrity_status':integrity['status'],'protected_files_verified':integrity['protected_files_verified'],
        'historical_reference_equality_established':False,
        'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    write(OUT/'final_verdict.json',report)
    lines=['# Rust MIR performance-only repair', '',verdict,'',reason,'',
        'This is a separate diagnostic candidate. The original solver remains the reference/default backend. '
        'Method-v1 remains frozen with zero accepted historical depths. No historical vulnerability depth was calculated or accepted by these diagnostics.',
        '', '## Hot paths and repair', '',
        '`analyze.collapse` repeatedly unions all sets belonging to the same local, even after collapse. '
        '`copy`/`store` repeatedly transfer complete sets and scan field projections. '
        '`locations`, pointer metadata and dyn-receiver handling repeatedly filter token sets. '
        'The preimplementation engineering note records the exact scans and proof obligations.', '',
        'The candidate performs the original union on first collapse and retains all provenance updates thereafter; '
        'post-collapse writes already canonicalize to the root. It maintains append-only fact logs and exact source/destination transfer cursors, '
        'lazy token-kind indexes updated on every insertion, and field-prefix snapshots invalidated by membership growth. '
        'No fields collapse before the original rule calls collapse. Constraints, abstract values, required-body handling and finalization are unchanged.', '',
        'The original full sweeps, convergence test and 256-sweep fail-closed cap remain. There is no new worklist or heuristic termination rule.', '',
        '## Exact equality and replication', '',
        f"All {equality['cases']} cases passed exact scientific-file and internal points-to-state comparisons against the reference. "
        'Two independent candidate output directories matched. Tests also cover cap exhaustion, late empty collapse members, field-membership growth and transfer fanout.', '',
        '| Suite | Cases | Result |','|---|---:|---|']
    for name,count in equality['case_counts'].items():lines.append(f'| {name} | {count} | exact |')
    lines += ['',f"Unit mirror: {len(units['reports'])} tests passed; {units['mirrored_analyzer_calls']} analyzer calls compared reference and candidate, with separate live gates.", '',
        'Every Rust calibration normalized graph and inclusion result matches the frozen artifact. '
        'Frozen pair statuses and dynamic inputs remain unchanged; the C qsort boundary failure and CALIBRATION-FAIL verdict remain intact. '
        'No C analyzer rerun was needed.', '',
        'An initial reference-only harness comparison encountered Python tuple versus JSON list representation. '
        'The newly serialized and frozen inclusion files had identical SHA-256. The preserved harness note documents this non-scientific issue; '
        'the clean rerun uses canonical JSON and byte equality. No candidate scientific mismatch occurred.', '',
        '## Solver-only performance', '',
        '| Mode | Wall seconds | CPU seconds | Worker peak RSS GiB |', '|---|---:|---:|---:|']
    for mode in ('reference','candidate'):
        r=performance[mode];lines.append(f"| {mode} | {r['wall_seconds']:.6f} | {r['cpu_seconds']:.6f} | {r['peak_RSS_KiB']/1048576:.3f} |")
    lines += ['',f"Aggregate wall speedup: {performance['wall_speedup']:.3f}x; CPU speedup: {performance['cpu_speedup']:.3f}x. "
        f"Candidate/reference peak RSS ratio: {performance['candidate_to_reference_peak_RSS_ratio']:.3f}.", '',
        'Timing excludes extraction, input loading, live gates and serialization. Peak memory is the independent worker peak across the complete suite, '
        'not a per-case allocation measurement. Small-case timings are sensitive to timer noise. '
        'Reference operation counts come from a separate in-memory observational AST pass, whose outputs matched the uninstrumented reference; '
        'its overhead is excluded from speed comparisons.', '',
        '| Operation counter | Reference observed | Candidate |', '|---|---:|---:|']
    for name in sorted(set(counts['reference-counted'])|set(counts['candidate'])):
        lines.append(f"| {name} | {counts['reference-counted'].get(name,'not instrumented')} | {counts['candidate'].get(name,'not applicable / zero')} |")
    lines += ['', 'Token-filter scan and kind-index-build counters measure different implementation operations; they are not interchangeable semantic counts. '
        'There is no worklist-operation count because both implementations retain full sweeps.', '',
        '## Selected historical-scale diagnostics', '',
        'Selection is inherited unchanged from the earlier pre-solver size rule: printenv, mktemp, sort. '
        'Each run uses an immutable extracted snapshot, a fresh process, the same 900-second wall budget and the live gate. '
        'A 24-GiB RSS safety stop and 2-GiB host-memory floor protect the diagnostic host; these are not approved measurement limits. '
        'Historical graph hashes cover unchanged inclusion/export output only. No historical BFS, mapped-target resolution or vulnerability depth runs.', '',
        '| Context/run | Outcome | Process seconds | Solver seconds | Peak RSS GiB | Sweeps |', '|---|---|---:|---:|---:|---:|']
    for r in diagnostic_rows:
        count=r.get('operation_counts') or (r.get('last_progress') or {}).get('operation_counts',{})
        peak=max(r.get('peak_RSS_KiB',0),r['observed_peak_RSS_KiB'])/1048576
        lines.append(f"| {r['utility']}/{r['replica']} | {r['outcome']}; converged={r.get('converged',False)} | {r['process_elapsed_seconds']:.3f} | {r.get('solver_wall_seconds','unavailable')} | {peak:.3f} | {count.get('sweeps','unknown')} |")
    lines += ['', 'The following counters are final only for completed runs; otherwise they are the last recorded progress sample before termination. '
        'A timeout has no final fixed point, final graph hash or convergence-determinism result.', '',
        '| Context/run | Sample seconds | CPU seconds | Constraints | Point additions | Collapse calls | Copy calls | Delta tokens considered |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in diagnostic_rows:
        sample=r.get('last_progress') or {}
        count=r.get('operation_counts') or sample.get('operation_counts',{})
        lines.append(f"| {r['utility']}/{r['replica']} | {r.get('solver_wall_seconds',sample.get('elapsed_seconds','unknown'))} | "
            f"{r.get('solver_cpu_seconds',sample.get('cpu_seconds','unknown'))} | {count.get('constraints_processed','unknown')} | "
            f"{count.get('points_to_additions','unknown')} | {count.get('collapse_calls','unknown')} | {count.get('copy_calls','unknown')} | {count.get('delta_tokens_considered','unknown')} |")
    lines += ['', 'Reference baselines: printenv 900s / 6.86 GiB; mktemp 900s / 7.03 GiB; sort 900s / 9.10 GiB; '
        'printenv 1800s / 9.71 GiB. All timed out while making progress. Original input, solver and Python executable identities are bound in the diagnostic results. '
        'No converged historical reference output exists, so historical-scale exact reference equality is not established. '
        'Complete controlled/calibration equality cannot prove equality for every possible historical input. ', '',
        ('None of the selected candidate contexts converged, so no longer reference run was warranted and no historical graph determinism claim is made.'
         if not any(c['first'] and c['first']['converged'] for c in historical) else
         'Converged candidate replicas are compared by full inclusion and exported graph hashes; reference-scale equality remains unestablished.'), '',
        '## Cold replication and remaining scope', '',
        'Two independent incremental-disabled extraction replays for each selected utility match the frozen normalized raw MIR exactly. '
        'Only the incremental argument was removed, CARGO_INCREMENTAL=0 was set and output directories were redirected. '
        'Dependencies remained frozen and read-only; this does not establish whole-dependency cold rebuild equivalence. '
        'Future measurement needs an additive approved amendment and independent extraction/solver output directories.', '',
        'Addition logs, transfer cursors and indexes add memory. Full constraint sweeps and non-specialized operand unions remain possible scaling costs. '
        'No unvalidated optimization is deployed. od remains separate (133 unsupported intrinsic Instances and 19 required identities absent); '
        'chcon remains separate (selinux-sys 0.6.14, missing selinux/selinux.h). No policy waiver or system installation was made.', '',
        '## Integrity and artifacts', '',
        f"All {gates['gate_record_files']} saved gate-record files passed their component checks. "
        f"Final integrity passed for {integrity['protected_files_verified']} protected files, immutable extracted inputs, "
        'all frozen runtime identities and 159 protected C files. Calibration, mappings, population, classifier, C results/instrument, '
        'reference solver and accepted extraction semantics remain unchanged.', '',
        f"Reference SHA-256: `{equality['reference_sha256']}`", '',f"Candidate SHA-256: `{equality['candidate_sha256']}`", '',
        'Evidence is in build/rust-mir/solver-v2-performance: equality-v1, unit-mirror, performance, historical-diagnostic, cold-extraction, '
        'preservation_before.json, integrity_after.json and final_verdict.json. Source selection is exposed only through the separate solve.py command. '
        'No historical scientific result file is populated by this task.', '',verdict,'']
    (HERE/'PERFORMANCE_REPAIR_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    files={p.relative_to(ROOT).as_posix():sha(p) for p in HERE.glob('*') if p.is_file()}
    for name in ('equality_summary.json','unit_mirror_summary.json','performance_summary.json','historical_diagnostic_protocol.json',
                 'historical_diagnostic_results.json','cold_extraction_protocol.json','cold_extraction_results.json','integrity_after.json','gate_audit.json','final_verdict.json'):
        files[(OUT/name).relative_to(ROOT).as_posix()]=sha(OUT/name)
    write(OUT/'repair_evidence_manifest.json',{'files':files,'historical_depths_accepted':0,'verdict':verdict})
    print(verdict,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verdict',required=True,choices=['PERFORMANCE-REPAIR-GO','PERFORMANCE-REPAIR-INSUFFICIENT'])
    p.add_argument('--reason',required=True);a=p.parse_args();main(a.verdict,a.reason)
