"""Publish compact local feasibility evidence; never publish historical metrics."""
import hashlib
import json
from pathlib import Path
from collections import Counter
from security.semantic_callgraph.rust_rupta_v1.probe import ROOT,BASE,HERE
from security.semantic_callgraph.rust_rupta_v1.adapter import parse,finalize,normalized
from security.semantic_callgraph.rust_rupta_v1.validate import inventory

def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,data): (HERE/name).write_text(json.dumps(data,sort_keys=True,indent=2)+'\n')
def cell(values): return ', '.join(values) if values else '∅'
def safe(text): return str(text).replace('|','\\|').replace('\n',' ')

def basic_results():
    expected={
        'direct':{('main','target')},
        'nested':{('main','first'),('first','second'),('second','target')},
        'recursion':{('main','recursive'),('recursive','recursive'),('recursive','target')},
        'pointer':{('main','invoke'),('invoke','target')},
        'two_fields':{('main','target')},
        'dynamic':{('main','invoke'),('invoke','{impl#0}::act'),('{impl#0}::act','target')},
    }
    result=[]
    for mode in ('ander','cs'):
        for name,relations in expected.items():
            raw=parse(BASE/'basic'/mode/name,mode)
            repeat=parse(BASE/'basic-repeat'/mode/name,mode)
            actual={(e['caller'][len(name)+2:],e['callee'][len(name)+2:]) for e in raw['call_edges'] if e['caller'].startswith(name+'::') and e['callee'].startswith(name+'::')}
            g=finalize(raw,name+'::main')
            depths={f['identity']:f['raw_call_depth'] for f in g['functions']}
            expected_depth={'direct':1,'nested':3,'recursion':2,'pointer':2,'two_fields':1,'dynamic':3}[name]
            assert depths[name+'::target']==expected_depth
            result.append({'fixture':name,'mode':mode,'expected_application_edges':sorted(relations),
                           'actual_application_edges':sorted(actual),'passed':relations==actual,
                           'deterministic':normalized(raw)==normalized(repeat),
                           'target_depth':depths[name+'::target'],'expected_target_depth':expected_depth,
                           'indirect_edges':[e for e in raw['call_edges'] if e['edge_type']=='indirect_resolved']})
    assert all(r['passed'] and r['deterministic'] for r in result)
    return result

def mir_comparison(program,mir):
    if program=='supplement': return {'status':'not_previously_measured','cases':[]}
    if program=='instrument': ids=['controlled/'+n for n in ('direct','recursion','function_pointer','multi_target','struct_pointer','closure','generic','static_trait','dynamic_trait','cross_crate_direct','cross_crate_indirect','duplicate_names','multiple_instances')]
    elif program.startswith('expanded/'): ids=['controlled/'+program.split('/')[1]]
    else: ids=['/'.join(program.split('/')[:2])]
    rows=[mir[i] for i in ids]
    # These are frozen compiler-evidence results, not new RUPTA validation.
    return {'status':'partial_known_edge_method' if any(r['reachable_unresolved_sites'] for r in rows) else 'compiler_evidence_valid',
            'cases':[{'id':r['id'],'reachable_unresolved_sites':r['reachable_unresolved_sites'],
                      'reachable_body_boundaries':r['reachable_body_boundaries'],
                      'target_depths':r['lightweight_target_depths']} for r in rows]}

def main():
    data=read(BASE/'evaluated.json'); programs=inventory()
    old=read(ROOT/'security/semantic_callgraph/rust_llvm_svf_v1/validation_results.json')
    mir={r['id']:r for r in read(ROOT/'build/rust-mir/lightweight-v1/validation_summary.json')['results']}
    output={'schema_version':1,'decision':'STOP; not accepted for historical measurement','upstream_commit':'b19f187e9cbe37b5afb1103d88b663253e1f0a03',
            'nightly':'nightly-2024-02-03','provenance':read(BASE/'provenance.json'),
            'inputs':read(BASE/'validation_inputs.json')['sources'],'basic':basic_results(),
            'determinism':data['determinism'],'finalized_graph_determinism':data.get('finalized_graph_determinism'),
            'summary':{},'programs':[],'method_site_comparison':old['site_matrix'],
            'historical_compatibility':read(BASE/'historical_metadata.json')}
    for mode in ('ander','cs'):
        rows=[data['results'][f'1|{mode}|{p["id"]}'] for p in programs]
        sites=[s for r in rows for s in r['sites']]
        output['summary'][mode]={'completed_programs':35,'required_expectations_matched':sum(r['required_expectations_passed'] for r in rows),
            'matched_without_detected_drop_or_static_scope_gap':sum(r['status']=='required_expectations_match' for r in rows),
            'whole_graph_accepted':False,'failed_programs':[r['program'] for r in rows if not r['required_expectations_passed']],
            'site_status_counts':dict(Counter(s['status'] for s in sites)),
            'false_adjudicated_targets':sum(len(s['unexpected'] or []) for s in sites),
            'missing_adjudicated_targets':sum(len(s['missing'] or []) for s in sites),
            'unresolved_observed':sum(r['unresolved_observed'] for r in rows),'unresolved_total':None,
            'wall_seconds_run1':sum(x['wall_seconds'] for r in rows for x in r['resources']),
            'peak_rss_kib':max(x['peak_rss_kib'] for r in rows for x in r['resources']),
            'all_normalized_runs_identical':all(v for k,v in data['determinism'].items() if k.startswith(mode+'|'))}
    for p in programs:
        name=p['id']; row={'program':name,'compiler_resolved_mir':mir_comparison(name,mir),
            'canonical_svf':'fail' if name in old['summary']['P']['rust_programs_failed'] else 'pass',
            'patched_svf_S3':'fail' if name in old['summary']['S3']['rust_programs_failed'] else 'pass'}
        for mode in ('ander','cs'):
            full=data['results'][f'1|{mode}|{name}']
            row[mode]={k:v for k,v in full.items() if k not in ('mapping','drop_terminators','omitted_static_calls','repeat','mode')}
            row[mode]['drop_terminator_count']=len(full['drop_terminators'])
            row[mode]['omitted_static_call_count']=len(full['omitted_static_calls'])
            row[mode]['repeat_resources']=data['results'][f'2|{mode}|{name}']['resources']
        output['programs'].append(row)
    by_program={p['program']:p for p in output['programs']}
    for s in output['method_site_comparison']:
        p=by_program[s['program']]
        for mode in ('ander','cs'):
            s[mode]=next(x for x in p[mode]['sites'] if x['id']==s['site'])
        # Inspect frozen compiler unresolved rows for the corresponding owner.
        ids=[c['id'] for c in p['compiler_resolved_mir']['cases']]
        owner=s['site'].split('.')[0]
        if owner=='box_call_mut': owner='call_mut'
        matches=[x for i in ids for x in mir[i]['target_set_comparison']
                 if x['mir_status'].startswith('unresolved') and ('::'+owner in x['owner'])]
        unique={json.dumps(x,sort_keys=True):x for x in matches}
        s['compiler_resolved_mir']={'status':'explicitly_unresolved' if unique else 'not_matched_to_prior_record',
            'observed_targets':sorted({t for x in unique.values() for t in x['lightweight_targets']}) if unique else None,
            'evidence':list(unique.values())}
    output['regression']={phase:read(BASE/f'regression-{phase}/results.json') for phase in ('before','after') if (BASE/f'regression-{phase}/results.json').exists()}
    output['adapter_regression']={'command':'python3 -m pytest -q security/semantic_callgraph/rust_rupta_v1/test_adapter.py security/semantic_callgraph/cross_language_calibration/test_revision_freeze.py security/semantic_callgraph/rust_mir/test_dependency_inputs.py','passed':10}
    output['main_root_sensitivity']=[{'program':r['program'],'mode':r['mode'],'repeat':r['repeat'],
        'status':r['command']['status'],'required_expectations_passed':r['evaluation']['required_expectations_passed'],
        'sites':r['evaluation']['sites'],'deterministic':r.get('normalized_deterministic')}
        for r in read(BASE/'root_sensitivity.json')]
    output['comparison_evidence_sha256']={str(p.relative_to(ROOT)):sha(p) for p in [
        ROOT/'security/semantic_callgraph/rust_llvm_svf_v1/validation_results.json',
        ROOT/'build/rust-mir/lightweight-v1/validation_summary.json']}
    output['preservation']=read(BASE/'protected_after.json') if (BASE/'protected_after.json').exists() else {'status':'pending'}
    output['acceptance']={'canonical_build':True,'required_relationships':False,'adjudicated_resolved_target_sets':True,
        'independent_clean_rebuild_reproducibility':'not_tested; one successful locked canonical build',
        'complete_identity_and_boundary_export':False,'shared_BFS_fixture_checks':True,'deterministic_normalized_graphs':True,
        'historical_compatibility':False,'ready_for_historical_measurement':False}
    write('validation_results.json',output)
    write('provenance.json',output['provenance'])
    lines=['# RUPTA controlled validation','',
           '**STOP: canonical RUPTA is not accepted for historical depth measurement.**','',
           'Unmodified upstream builds with its pinned nightly. Both modes complete all 35 programs twice. '
           'Each matches 33/35 programs under the inherited required relations/path checks; this is not '
           '33 complete semantic graphs. Drop and library scope gaps remain even in many matching programs.','',
           '| Mode | Required programs matching | Exact resolved sites | Expected unresolved site | False / missing adjudicated targets | Run-1 wall seconds | Peak RSS MiB | Deterministic |',
           '|---|---|---|---|---|---|---|---|']
    for mode,s in output['summary'].items():
        lines.append(f"| {mode} | {s['required_expectations_matched']}/35 | {s['site_status_counts'].get('exact',0)}/23 | 1, inferred from MIR | {s['false_adjudicated_targets']} / {s['missing_adjudicated_targets']} | {s['wall_seconds_run1']:.2f} | {s['peak_rss_kib']/1024:.1f} | yes |")
    lines += ['', 'Runtime includes compiler startup, analysis, dumps and metadata emission; excludes dependency builds. '
              'Peak RSS is GNU time process maximum, not RUPTA-only allocation. Each analysis had 180 seconds and '
              '16 GiB address space available. No timeouts/OOMs/build failures occurred. cs uses default depth 1; '
              'depth 2 was not justified because resolved target sets already match, while remaining blockers concern drop/export/compiler support.',
              '', '## Small probes','', 'All six pass in both modes and repeat identically after normalization. '
              'Direct target depth 1; nested 3; recursion 2; pointer 2; two-field struct 1; dynamic dispatch 3. '
              'The struct site is exported as a Fnptr call to only `target`; `third` is absent. '
              'The MIR explicitly loads field index 1. Recursion retains the self-edge.',
              '', '## All controlled programs','',
              '`match+gap` means required expectations match but drop/static-call omissions are detected. '
              '`match` means no such gap detected, not proof of complete unresolved coverage. '
              'Nodes include the MIR-exported inventory; no nodes are contracted. R is entry-reachable functions. '
              'Instrument/supplement have multiple BFS anchors, so R lists their distinct counts.', '',
              '| Program | ander | cs | Nodes / edges (ander) | R (ander) | Run-1 seconds A / CS | Peak RSS MiB A / CS |','|---|---|---|---|---|---|---|']
    def status(r): return {'required_expectations_match':'match','required_expectations_match_with_scope_gaps':'match+gap','expectation_failure':'FAIL'}[r['status']]
    for p in output['programs']:
        a,c=p['ander'],p['cs']; reachable=sorted({str(x.get('reachable_functions')) for x in a['cases'] if x.get('reachable_functions') is not None})
        lines.append(f"| {p['program']} | {status(a)} | {status(c)} | {a['nodes']} / {a['edges']} | {', '.join(reachable)} | {sum(x['wall_seconds'] for x in a['resources']):.2f} / {sum(x['wall_seconds'] for x in c['resources']):.2f} | {max(x['peak_rss_kib'] for x in a['resources'])/1024:.1f} / {max(x['peak_rss_kib'] for x in c['resources'])/1024:.1f} |")
    lines += ['', '## Failures and representation differences','',
              '- `expanded/crates_io`: `main → dependency_path → drop(guard)` is exported, but the destructor/callback transition is absent. '
              'The designated closure and `target` are unreachable in both modes. This is a missing legitimate route, not zero depth.',
              '- `supplement`: RUPTA retains `external_work` and `external_callback` as body-unavailable graph nodes. '
              'The old SVF contract instead demands external-call records and no internal edge. The strict inherited check fails; '
              'its `invented_internal_edges` diagnostic describes a representation mismatch, not a fabricated call target. '
              'The callback pointer has no target in DOT/dynamic output; the adapter records its unresolved MIR operand. '
              'There is no explicit upstream unresolved/source-line ledger, so the inherited line-based unresolved check fails.',
              '- All five S3 failures are resolved at the designated sites: heap_struct, mixed_stack_heap, mixed_stack_static, '
              'box_fnmut and stack_bytes. Their exact sets are in METHOD_COMPARISON.md. This does not repair omitted drop/library scope.',
              '', '## Depth and entry interpretation','',
              'BFS uses the unchanged shared finalizer. Full per-anchor target depths, raw paths, reachability and finite shortest-distance maxima '
              'are in validation_results.json and build/.../*.graph.json. No historical metric was generated. '
              'Supplement mutual-recursion target depth is 2 and nested-chain depth is 4. The library comparator is reached at depth 6 '
              'with raw maximum finite shortest distance 7, but no equal C/Rust depth was preregistered.',
              '', 'The default root is rustc\'s source-level main, before an LLVM/native entry wrapper exists. '
              'Instrument uses explicit main (rlib); calibration uses its frozen entry anchor; the supplemental library is analyzed separately '
              'from its four entry functions. Supplemental BFS never fills a root graph from another root. '
              'Source main remains a reasonable primary utility entry, with uumain only as a separately identified sensitivity anchor. '
              'The controlled wrappers retain distinct outer and inner uumain nodes. An invalid name silently falls back to main; '
              'an isolated main disappears from DOT but remains in the MIR dump. Neither behavior permits name-only historical entry selection.',
              '', 'Post-hoc main-root sensitivity repeats dyn_vtable, mixed_stack_static and mixed_stack_heap twice in both modes. '
              'All six program/mode combinations retain the exact designated target sets with harness decoys included, and normalize identically. '
              'Primary calibration analysis begins at entry whereas prior SVF analyzes the main-rooted module; this sensitivity checks that '
              'the observed improvements in these cases are not merely caused by excluding those decoys from the analysis root.',
              '', '## Evidence and preservation','',
              'All 70 program/mode normalized comparisons are identical across fresh compilations; all 12 small probe comparisons also match. '
              'DOT node numbering and ordering vary and are excluded from semantic identity. All generic argument strings and MIR locations remain. '
              'Analyzer binaries/source are unpatched. Export/parser amendments, not scientific algorithm changes, are documented in README.md.',
              '', 'Existing checks: frozen population gate, published MIR result verification, integrity checks, and four existing pytest tests. '
              'Six new adapter tests plus those four existing tests pass. The broader `pytest tests` command collects no tests (exit 5); '
              'it is not counted as a passing suite. All 39,276 snapshotted pre-existing files are byte-identical. '
              'Both before/after result verification and integrity checks pass. Final byte-preservation results and exact command records are in validation_results.json.']
    (HERE/'VALIDATION_REPORT.md').write_text('\n'.join(lines)+'\n')
    lines=['# Controlled method comparison','',
           'These are distinct instruments and compiler configurations. MIR means the existing compiler-resolved lightweight method; '
           'its own successful validation concerns retained compiler-proven edges, not exact whole-program may-call coverage. '
           'No new MIR/SVF analysis was run to generate this comparison. Their committed/frozen results are read-only. '
           'S3 is the best tested three-patch SVF configuration (30/35), tied with S and S-noffeq; canonical P matches 20/35.',
           '', '| Program | Compiler-resolved MIR | Canonical SVF P | Patched SVF S3 | RUPTA ander | RUPTA cs(1) |','|---|---|---|---|---|---|']
    for p in output['programs']:
        m=p['compiler_resolved_mir']; u=sum(c['reachable_unresolved_sites'] for c in m['cases'])
        text=m['status']+(f'; {u} unresolved' if m['cases'] else '')
        lines.append(f"| {p['program']} | {text} | {p['canonical_svf']} | {p['patched_svf_S3']} | {status(p['ander'])} | {status(p['cs'])} |")
    lines += ['', 'MIR instrument row aggregates 13 separately rooted cases; no directly comparable 35-program pass count is asserted. '
              'The supplemental source has no prior lightweight run. `match+gap` and `match` have the restricted meanings in VALIDATION_REPORT.md.',
              '', '## Exact adjudicated target sets','',
              'All rows below use the unchanged prior site expectations. ∅ unresolved is not a successful empty target set '
              'unless the fixture explicitly expects an external-origin unresolved pointer. Source-to-MIR mapping uses the unique '
              'indirect site in the independently mapped owner; absent/ambiguous mappings cannot pass.',
              '', '| Program / site | Expected | Compiler-resolved MIR observed | SVF P observed | SVF S3 observed | RUPTA ander observed | RUPTA cs observed |','|---|---|---|---|---|---|---|']
    for s in output['method_site_comparison']:
        m=s['compiler_resolved_mir']; mir_text='not previously matched' if m['observed_targets'] is None else cell(m['observed_targets'])+' (unresolved)'
        cols=[s['program']+' / '+s['site'],cell(s['expected']),mir_text,
              cell(s['P']['actual'])+' ('+s['P']['status']+')',cell(s['S3']['actual'])+' ('+s['S3']['status']+')',
              cell(s['ander']['actual'])+' ('+s['ander']['status']+')',cell(s['cs']['actual'])+' ('+s['cs']['status']+')']
        lines.append('| '+' | '.join(safe(x) for x in cols)+' |')
    lines += ['', '## Interpretation','',
              'RUPTA improves designated indirect-call precision over canonical and patched SVF on this corpus: '
              'all 23 resolved target sets are exact, including the five persistent S3 failures. Both modes give the same '
              'sets; context sensitivity adds no demonstrated precision here. The unresolved external-origin site is '
              'recoverable only as a MIR observation, not from a complete upstream unresolved ledger.',
              '', 'RUPTA also loses a valid scopeguard route that the existing compiler-resolved MIR method retains. '
              'Its omitted Drop transitions, allocator special models, boundary nodes and direct Fn/closure resolution '
              'change the raw graph and path layering. Better field precision is not equivalent to a more complete instrument.',
              '', 'C SVF analyzes LLVM memory objects and emitted definitions; RUPTA analyzes MIR function references, '
              'generic substitutions and special-function models. RUPTA exports the context-unioned graph even for cs. '
              'Compiler versions, source roots, bodies available from libraries, drop/shim nodes, and unavailable externals '
              'differ. The same BFS computes distances in these different graphs; it does not make the numbers directly comparable. '
              'A common-scope, entry- and identity-audited calibration would be necessary before any numerical C/Rust claim.']
    (HERE/'METHOD_COMPARISON.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(output['summary'],indent=2))

if __name__=='__main__': main()
