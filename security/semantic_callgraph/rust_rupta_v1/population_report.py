"""Separate diagnostic units and preserve every frozen CVE/location/platform."""
from collections import Counter, defaultdict
import csv
import json
import statistics
from .population_runner import BASE, REPORT, ROOT, FROZEN, OLD, HERE, read, write, sha, rel, observe

def stats(values):
    values=[v for v in values if v is not None]
    return dict(n=len(values),frequency=dict(sorted(Counter(values).items())),median=statistics.median(values) if values else None,
                minimum=min(values) if values else None,maximum=max(values) if values else None)

def describe(s):
    def number(v):return format(v,'.6g') if isinstance(v,float) else str(v)
    frequency=', '.join(f'{number(k)}: {v}' for k,v in s['frequency'].items())
    return f"n={s['n']}; median {number(s['median'])}; range {number(s['minimum'])}–{number(s['maximum'])}. Frequency (value: count): {frequency}."

def diagnostic_summary(reason):
    lines=reason.splitlines()
    native=[line.strip() for line in lines if 'Failed to find' in line]
    if native:return native[0]
    for line in lines:
        if line.startswith('{'):
            try:message=json.loads(line)
            except json.JSONDecodeError:continue
            if 'internal compiler error' in message.get('level',''):return message['message']
    selected=[line.strip() for line in lines if any(s in line for s in ('error:', 'AssertionError','panicked','timeout'))]
    return ' '.join(selected[:2]) if selected else reason[-500:]

def csv_file(name, rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with (REPORT/name).open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        writer.writerows({k:json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)

def publish(records, planned, groups, programs):
    observations=[];program_rows=[];coverage={}
    for row in planned:
        program=programs.get(row['group'],{})
        source=ROOT/program['source_directory'] if program.get('source_directory') else ROOT/read(OLD/row['release']/'source_provenance.json')['checkout']
        result=observe(row,program,source)
        if not program and row['platform']=='linux':
            result.update(measurement_validity='pending_or_infrastructure_blocked',build_status='not_attempted',analysis_status='not_run')
        observations.append(result)
    for key,g in groups.items():
        p=programs.get(key,{})
        row=dict(key=key,release=g['release'],revision=g['revision'],executable=g['utility'],platform='linux',target=g['target'],
                 build_status=p.get('build_status','not_attempted'),analysis_status=p.get('analysis_status','not_run'),
                 maximum_depth=None,utility_only_maximum_depth=None,graph_completeness='not_assessed',measurement_validity='not_measured',
                 independently_verified=False,accepted_historical_measurement=False,failure_reason=p.get('failure_reason'),
                 analyzer_fingerprint=p.get('fingerprint'),analysis_directory=p.get('analysis_directory'),
                 cached_pilot_evidence=p.get('cached_pilot_evidence'),cache_provenance=p.get('cache_provenance'),
                 prior_build_record=g['prior_build_record'])
        if p.get('analysis_directory'):
            resources=ROOT/p['analysis_directory']/'resources.txt'
            if resources.exists():
                import re
                rss=re.search(r'Maximum resident set size \(kbytes\):\s*(\d+)',resources.read_text())
                row['analysis_peak_rss_kib']=int(rss[1]) if rss else None
            row['analysis_wall_seconds']=p.get('analysis',{}).get('wall_seconds')
        if p.get('analysis_status')=='completed':
            summary=p['graph']; primary=summary['policies']['primary']; secondary=summary['policies']['utility_only']
            row.update(maximum_depth=primary['maximum_depth'],utility_only_maximum_depth=secondary['maximum_depth'],
                       graph_completeness='known_incomplete',measurement_validity='provisional_graph_observed',
                       reachable_implementation_functions=primary['reachable_implementation_functions'],
                       deepest_path=primary['deepest_path'],utility_only_deepest_path=secondary['deepest_path'],
                       recognized_unresolved_count=summary['recognized_unresolved_count'],unavailable_body_count=summary['unavailable_body_count'],
                       graph_sha256=summary['graph_sha256'],entry=summary['entry'],entry_source=summary['entry_source'])
            c=read(ROOT/summary['coverage_artifact'])
            # Full repeated owner->frontier relationships remain in build; compact ledger
            # retains all sites/bodies once, with a hashed full frontier artifact reference.
            frontiers=c.pop('primary_frontiers')
            c.update(full_frontier_artifact=summary['coverage_artifact'],full_frontier_artifact_sha256=sha(ROOT/summary['coverage_artifact']),
                     exposed_owner_count=len(frontiers),validity='provisional; omissions can affect both metrics')
            coverage[key]=c
        else: coverage[key]=dict(build_status=row['build_status'],analysis_status=row['analysis_status'],failure_reason=row['failure_reason'])
        program_rows.append(row)
    cves=[]
    for record in records:
        rows=[r for r in observations if r['cve_id']==record['cve_id']]
        measured=[r for r in rows if r['depth'] is not None]
        if record['mapping_status']=='not_applicable':status='not_applicable_configuration_only'
        elif measured:status='provisional_mapped_subset' if record['mapping_status']=='unresolved' or len(measured)<len(rows) else 'provisional_all_listed_locations_observed'
        elif record['mapping_status']=='unresolved':status='incomplete_mapping_no_observed_depth'
        else:status='no_numerical_observation'
        cves.append(dict(cve_id=record['cve_id'],revision=record['affected_revision'],release=record['affected_version'],
                         frozen_mapping_status=record['mapping_status'],classification=status,
                         source_function_records=len(record['vulnerable_functions']),executable_function_observations=len(rows),
                         numerical_observations=len(measured),independently_verified_depths=0,
                         observed_depth_values=sorted(set(r['depth'] for r in measured)),
                         observed_normalized_values=sorted(set(r['normalized_depth'] for r in measured if r['normalized_depth'] is not None)),
                         observed_primary_maximum_values=sorted(set(r['maximum_depth'] for r in rows if r['maximum_depth'] is not None)),
                         observation_ids=[r['observation_id'] for r in rows],
                         missing_observations=[dict(id=r['observation_id'],function=r['frozen_mapping']['function'],platform=r['platform'],reason=r['measurement_validity'],
                                                   build=r['build_status'],mapping=r['mapping_status'],reachability=r['reachability_status']) for r in rows if r['depth'] is None],
                         mapping_coverage='partial' if record['mapping_status']=='unresolved' else 'not_applicable' if not rows else 'frozen_verified_locations',
                         note=record.get('unresolved_reason') or record.get('depth_nonapplicability_reason'),accepted_historical_measurement=False))
    measured=[r for r in observations if r['depth'] is not None]
    by_function=defaultdict(list)
    for r in measured:by_function[(r['cve_id'],r['mapping_index'])].append(r['depth'])
    summary=dict(population_cves=len(cves),applicable_cves=sum(c['frozen_mapping_status']!='not_applicable' for c in cves),
        attempted_executable_groups=len(programs),planned_executable_groups=len(groups),
        collection_status='complete_diagnostic_attempts' if len(programs)==len(groups) else 'partial_collection',
        frozen_source_function_records=sum(c['source_function_records'] for c in cves),
        verified_source_function_records=sum(c['source_function_records'] for c in cves if c['frozen_mapping_status']=='verified'),
        partially_mapped_source_function_records=sum(c['source_function_records'] for c in cves if c['frozen_mapping_status']=='unresolved'),
        distinct_source_definitions=len({(r['revision'],r['frozen_mapping']['source_identity']) for r in observations}),
        planned_executable_function_observations=len(observations),numerical_executable_function_observations=len(measured),
        cves_with_numerical_observations=sum(bool(c['numerical_observations']) for c in cves),independently_verified_cves=0,
        provisional_cves=sum(bool(c['numerical_observations']) for c in cves),
        cve_classifications=dict(Counter(c['classification'] for c in cves)),
        observation_classifications=dict(Counter(r['measurement_validity'] for r in observations)),
        source_function_records_with_observations=len(by_function),
        executable_function_depth_distribution=stats([r['depth'] for r in measured]),
        executable_function_normalized_distribution=stats([r['normalized_depth'] for r in measured]),
        utility_only_function_depth_distribution=stats([r['utility_only_depth'] for r in measured]),
        utility_only_function_normalized_distribution=stats([r['utility_only_normalized_depth'] for r in measured]),
        executable_primary_maximum_distribution=stats([r['maximum_depth'] for r in program_rows]),
        executable_utility_only_maximum_distribution=stats([r['utility_only_maximum_depth'] for r in program_rows]),
        cve_depth_profile_distribution=dict(Counter(','.join(map(str,c['observed_depth_values'])) for c in cves if c['observed_depth_values'])),
        cve_normalized_profile_distribution=dict(Counter(json.dumps(c['observed_normalized_values']) for c in cves if c['observed_normalized_values'])),
        cves_with_single_observed_depth_distribution=stats([c['observed_depth_values'][0] for c in cves if len(c['observed_depth_values'])==1]),
        cves_with_single_observed_normalized_distribution=stats([c['observed_normalized_values'][0] for c in cves if len(c['observed_normalized_values'])==1]),
        source_function_depth_profiles=dict(Counter(','.join(map(str,sorted(set(v)))) for v in by_function.values())),
        utility_breakdown={u:dict(observations=len(rs),measured=sum(r['depth'] is not None for r in rs),depths=stats([r['depth'] for r in rs]))
                           for u in sorted({r['utility'] for r in observations}) for rs in [[r for r in observations if r['utility']==u]]},
        platform_breakdown={p:dict(observations=len(rs),statuses=dict(Counter(r['measurement_validity'] for r in rs)))
                            for p in sorted({r['platform'] for r in observations}) for rs in [[r for r in observations if r['platform']==p]]})
    for row in observations:
        row['vulnerable_function']=row['frozen_mapping']['function']
        row['authenticated_source_identity']=row['frozen_mapping']['source_identity']
        row['source_sha256']=row['frozen_mapping']['source_sha256']
    with (FROZEN/'results/rust-only-lightweight-v1/tracker_ready.csv').open(newline='') as f:
        mir_rows=list(csv.DictReader(f))
    mir_measured=[r for r in mir_rows if r['Vulnerability depth']!='']
    results=dict(dataset='historical-rupta-diagnostic-v1',accepted=False,mode='ander',summary=summary,cves=cves,observations=observations,programs=program_rows,
        policy='SCOPED_POLICY.md: utility + reachable uucore + authenticated generated project code; witnessed excluded-interior paths count one transition; distinct instances retained.',
        instance_aggregation='Source-function depth is minimum among reached instances of one authenticated compiler definition. Every instance and path is retained. Ambiguous definitions never yield a depth.',
        cve_aggregation='Each CVE contributes one set of observed depths to the CVE profile histogram. No arbitrary shallowest-location selection. Numeric median is for the explicitly single-valued CVE subset only.',
        canonical_mir_baseline=dict(path='security/historical/rust/results/rust-only-lightweight-v1',
            tracker_sha256=sha(FROZEN/'results/rust-only-lightweight-v1/tracker_ready.csv'),
            program_depths_sha256=sha(FROZEN/'results/rust-only-lightweight-v1/program_max_depths.csv'),
            numerical_table_rows=len(mir_measured),depth_distribution=stats([int(r['Vulnerability depth']) for r in mir_measured]),
            warning='Separate compiler-resolved MIR baseline, inner uumain entry and different scope. No baseline edge used in RUPTA.'),
        analyzer_provenance=read(HERE/'scoped_provenance.json'),preservation=dict(manifest=rel(BASE/'preservation.json'),sha256=sha(BASE/'preservation.json')))
    results['collector_sha256']={rel(HERE/n):sha(HERE/n) for n in ('population_runner.py','population_wrapper.py','population_report.py','population_adapter.py','utility_scope.py','patched_adapter.py')}
    results['host_provenance']=dict(path=rel(REPORT/'host_provenance.json'),sha256=sha(REPORT/'host_provenance.json')) if (REPORT/'host_provenance.json').exists() else None
    results['gates']={name:dict(path=rel(BASE/name),sha256=sha(BASE/name),status=read(BASE/name)['status']) for name in ('pilot-gate.json','smoke-gate.json') if (BASE/name).exists()}
    write(REPORT/'historical_rupta_results.json',results)
    write(REPORT/'historical_rupta_coverage.json',coverage)
    csv_file('historical_rupta_cves.csv',cves)
    table=[]
    for r in observations:
        item={k:v for k,v in r.items() if k not in ('frozen_mapping','instances','shortest_path','validity_assessment')}
        item['shortest_path_names']=[n['name'] for n in r['shortest_path']['functions']] if r['shortest_path'] else None
        item['instance_and_callsite_witness_record']='historical_rupta_results.json:observations:'+r['observation_id']
        item['mapped_instance_count']=len(r['instances'])
        table.append(item)
    csv_file('historical_rupta_observations.csv',table)
    table=[]
    for r in program_rows:
        item={k:v for k,v in r.items() if k not in ('deepest_path','utility_only_deepest_path','entry')}
        item['deepest_path_names']=[n['name'] for n in r.get('deepest_path',{}).get('functions',[])]
        item['entry_identity']=r.get('entry',{}).get('identity')
        item['path_witness_record']='historical_rupta_results.json:programs:'+r['key']
        table.append(item)
    csv_file('historical_rupta_program_depths.csv',table)
    lines=['# Historical RUPTA diagnostic distribution — NOT ACCEPTED', '',
        f"Collection status: **{summary['collection_status']}** ({len(programs)}/{len(groups)} executable groups).", '',
        f"All **45 CVEs** are retained. **{summary['cves_with_numerical_observations']} CVEs** have numerical graph observations; **0** have independently verified depths. All numerical depths, maximum depths and ratios are provisional.", '',
        f"Units: {summary['frozen_source_function_records']} frozen CVE/source-function mapping records ({summary['verified_source_function_records']} in verified CVEs and {summary['partially_mapped_source_function_records']} in partially mapped CVEs), {summary['distinct_source_definitions']} distinct source definitions, {len(observations)} executable/function/platform observations, {len(groups)} planned Linux executable graphs. {len(measured)} observations have numerical depths. The two partially mapped CVEs retain that classification even when individual frozen locations are measured.", '',
        '## Distribution and counting', '',
        '**CVE-level depth profiles (one contribution per CVE):** '+str(summary['cve_depth_profile_distribution'])+'. A profile such as `4,6` retains both depths; it does not select the shallower vulnerability.', '',
        '**Single-valued observed CVE subset:** '+describe(summary['cves_with_single_observed_depth_distribution'])+' This is a selected observed subset, not an estimate of the frozen population.', '',
        '**Executable/function-level raw vulnerability depths:** '+describe(summary['executable_function_depth_distribution']), '',
        '**Executable-level primary maximum depths:** '+describe(summary['executable_primary_maximum_distribution']), '',
        '**Executable/function-level normalized depths:** '+describe(summary['executable_function_normalized_distribution'])+' Displayed ratios are rounded; JSON/CSV retain full precision.', '',
        '**Single-valued observed CVE normalized subset:** '+describe(summary['cves_with_single_observed_normalized_distribution'])+' Multi-valued CVE profiles remain explicit in the CVE ledger and JSON.', '',
        'All histograms include only numerical observations. Missing measurements are null, never zero. Repeated CVEs/functions sharing an executable do not multiply the executable Dmax distribution. Utility and platform breakdowns are in the results JSON.', '',
        '## Complete CVE ledger', '', '| CVE | Observed depths | Measured / planned locations | Status |', '|---|---|---:|---|']
    lines += [f"| {c['cve_id']} | {', '.join(map(str,c['observed_depth_values'])) or '—'} | {c['numerical_observations']}/{c['executable_function_observations']} | {c['classification']} |" for c in cves]
    lines += ['', '## Missing observations', '']
    for c in cves:
        for r in c['missing_observations']:lines.append(f"- {c['cve_id']} `{r['function']}` ({r['platform']}): {r['reason']}; build={r['build']}, mapping={r['mapping']}, reachability={r['reachability']}.")
    lines += ['', 'Failed executable diagnostics (complete commands and stderr are retained under build):', '']
    for r in program_rows:
        if r.get('failure_reason'):
            lines.append(f"- `{r['key']}`: `"+diagnostic_summary(r['failure_reason'])+'`')
    lines += ['', '## Validity and comparison', '',
        'Every numerical observation identifies an authenticated source declaration and compiler definition, retains all monomorphized instances, and has callsite witnesses for its shortest path. Program records retain a shortest path attaining Dmax. This validates the observed paths, not their global minimality under omitted calls. No numerical observation has been independently promoted.', '',
        'Each executable has a separate coverage ledger listing recognized unresolved sites, unavailable bodies, reachable LazyLock/TLS mechanisms and formatting boundaries. Full owner-to-boundary exposure is preserved in hashed build artifacts. Initializer and Display omissions can hide implementation callbacks and can affect either metric; an absent mapped function in an incomplete graph is not declared semantically unreachable. No exact error bounds follow from these omissions.', '',
        'Primary scope and entry match the preregistered RUPTA policy: selected utility plus reachable first-party uucore and authenticated generated project code, rooted at source main. A witnessed path through excluded dependencies counts one implementation transition and stops at the next included function. Both metrics use that same graph. Utility-only sensitivity is separate. Full dependency graphs remain supporting evidence.', '',
        'Canonical Rust MIR files are unchanged and separately fingerprinted; they use a different entry and retained compiler-resolved graph. Existing C/SVF results are unchanged. Different analyzers, call resolution, wrapper/instance treatment and dependency-mediated projection prevent a claim of direct C/Rust numerical equivalence.', '',
        f"Separately labeled canonical MIR baseline: {len(mir_measured)} numerical table rows; raw depth frequency {results['canonical_mir_baseline']['depth_distribution']['frequency']}. This is not the same scope/entry or a repair source for RUPTA, and the two distributions are not interchangeable.", '',
        '**Readiness:** suitable as a reproducible diagnostic dataset with explicit missingness, not accepted historical findings. Before substantive paper comparisons, review frozen-function/compiler matches and graph scope, then establish that omitted implementation callbacks cannot materially change the reported metrics (or adopt an explicitly justified incomplete-graph estimand). Validate the cross-language counting policy separately. No new pointer-analysis development was performed.', '',
        'See `REPRODUCTION.md`, the three CSV tables, `historical_rupta_results.json`, and `historical_rupta_coverage.json`.']
    (REPORT/'HISTORICAL_RUPTA_DISTRIBUTION.md').write_text('\n'.join(lines)+'\n')
    print('SUMMARY',json.dumps({k:v for k,v in summary.items() if not isinstance(v,dict)}),flush=True)
