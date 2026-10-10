"""Read-only postprocessing of saved historical evidence; Python 3 standard library.

Run from any directory. Outputs are confined to this script's directory.
The first run pins input hashes; subsequent runs fail if evidence has changed.
No analyzer imports, builds, network access, or graph measurement runs.
"""
from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json
import statistics as st
import io
import tarfile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
RBASE = Path('security/semantic_callgraph/rust_rupta_v1/historical-diagnostic-v1')
INPUTS = {}
AUTHENTICATED = {}


def read_bytes(path):
    path = Path(path)
    path = path if path.is_absolute() else ROOT / path
    data = path.read_bytes()
    key = path.relative_to(ROOT).as_posix()
    digest = hashlib.sha256(data).hexdigest()
    if key in AUTHENTICATED:
        assert digest == AUTHENTICATED[key], ('Checkout differs from authenticated archive', key)
    assert key not in INPUTS or INPUTS[key] == digest
    INPUTS[key] = digest
    return data


def read(path):
    return json.loads(read_bytes(path))


def source(path):
    return read_bytes(path).decode('utf-8').splitlines()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def csv_save(name, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with (OUT / name).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows({k: json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v
                     for k, v in row.items()} for row in rows)


def summary(values):
    v = sorted(values)
    if not v:
        return dict(n=0, mean=None, median=None, minimum=None, maximum=None, frequency={})
    return dict(n=len(v), mean=st.fmean(v), median=st.median(v), minimum=v[0], maximum=v[-1],
                sample_sd=st.stdev(v) if len(v) > 1 else None,
                frequency=dict(sorted(Counter(v).items())))


def base_key(f):
    return json.dumps([f['def_path_hash'], f['generic_args'], f['promoted'], f['shim']], separators=(',', ':'))


def compiler_index(sidecar):
    counts = Counter(base_key(f) for f in sidecar['functions'])
    ids = {f['id']: base_key(f) + (' @ exported ' + f['id'] if counts[base_key(f)] > 1 else '')
           for f in sidecar['functions']}
    compiler = {ids[f['id']]: f for f in sidecar['functions']}
    edges = {(ids[e['caller']], ids[e['callee']], e['location']) for e in sidecar['edges']}
    return compiler, edges


def def_path(f):
    # Compiler-emitted DefId path, not the display name (whose type arguments can contain Closure).
    return f['def_id'].split(' ~ ', 1)[1][:-1]


def validate_path(path, compiler, exported_edges):
    fs, edges = path['functions'], path['transitions']
    assert len(edges) == len(fs) - 1
    for f in fs:
        assert f['identity'] in compiler
        assert compiler[f['identity']]['name'] == f['name']
        assert compiler[f['identity']]['source'] == f['source']
    for i, e in enumerate(edges):
        assert (e['caller'], e['callee']) == (fs[i]['identity'], fs[i+1]['identity'])
        full = e['full_call_edges']
        assert full and full[0]['caller'] == e['caller'] and full[-1]['callee'] == e['callee']
        assert all(a['callee'] == b['caller'] for a, b in zip(full, full[1:]))
        assert all((e['caller'], e['callee'], e['callsite']['mir_location']) in exported_edges for e in full)


def contract_closures(path, compiler):
    """Erase closure frames only with an earlier lexical parent in this witness.

    This is a path-counting sensitivity, not a quotient-graph shortest distance.
    Ordinary named helpers remain, even when they invoke a closure as a callback.
    """
    fs = path['functions']
    removals = []
    for i, f in enumerate(fs[1:-1], 1):
        c = compiler[f['identity']]
        if c['def_kind'] != 'Closure':
            continue
        parent = def_path(c).rsplit('::', 1)[0]
        matches = [p for p in fs[:i] if def_path(compiler[p['identity']]) == parent]
        assert matches, ('Closure parent absent from saved witness', c['def_id'])
        p = matches[-1]
        assert p['source']['file'] == f['source']['file']
        removals.append(dict(path_index=i, closure_identity=f['identity'], parent_identity=p['identity'],
                             compiler_definition=c, parent_compiler_definition=compiler[p['identity']]))
    return removals


def entry_count(o, path, compiler, checkout, program):
    fs = path['functions']
    assert fs[0]['identity'] == program['entry']['identity']
    entry = program['entry_source']
    b = read_bytes(checkout / entry['path'])
    assert hashlib.sha256(b).hexdigest() == entry['sha256']
    generator = (entry.get('wrapper_evidence') or {}).get('generator', 'src/uucore/src/lib/lib.rs')
    b = read_bytes(checkout / generator)
    if entry.get('wrapper_evidence'):
        assert hashlib.sha256(b).hexdigest() == entry['wrapper_evidence']['sha256']
    assert compiler[fs[0]['identity']]['def_kind'] == 'Fn'
    if o['release'] == '0.0.3':
        assert o['executable'] == 'od'
        assert 'uucore_procs::main!(uu_od)' in '\n'.join(source(checkout / entry['path']))
        assert 'let code = #f' in b.decode() and '#expr(uucore::args_os())' in b.decode()
        assert compiler[fs[1]['identity']]['def_kind'] == 'Fn'
        assert fs[1]['name'].startswith('uu_od::uumain<')
        assert 'pub fn uumain' in source(checkout / fs[1]['source']['file'])[fs[1]['source']['line']-1]
        return 1
    assert o['release'] == '0.2.2'
    assert f"uucore::bin!(uu_{o['executable']})" in '\n'.join(source(checkout / entry['path']))
    assert 'let code = $util::uumain(uucore::args_os());' in b.decode()
    proc = '\n'.join(source(checkout / 'src/uucore_procs/src/lib.rs'))
    assert '#stream' in proc and 'let result = uumain(args);' in proc
    outer, inner = fs[1:3]
    assert all(compiler[f['identity']]['def_kind'] == 'Fn' for f in (outer, inner))
    assert def_path(compiler[inner['identity']]) == def_path(compiler[outer['identity']]) + '::uumain'
    assert outer['source']['file'] == inner['source']['file']
    lines = source(checkout / outer['source']['file'])
    assert '#[uucore::main]' in lines[outer['source']['line']-1]
    assert 'fn uumain' in lines[inner['source']['line']-1]
    return 2


def aggregate(rows, metrics):
    grouped = defaultdict(list)
    for r in rows:
        if r['source_identity']:
            grouped[(r['cve_id'], r['source_identity'])].append(r)
    functions = []
    for (cve, identity), rr in sorted(grouped.items()):
        f = dict(cve_id=cve, source_identity=identity, contexts=[r['observation_id'] for r in rr],
                 planned_contexts=len(rr), measured_contexts=sum(r['raw_depth'] is not None for r in rr))
        for metric in metrics:
            vals = [r[metric] for r in rr if r[metric] is not None]
            f[metric] = st.fmean(vals) if vals else None
        functions.append(f)
    cves = []
    for cve in sorted({r['cve_id'] for r in rows}):
        ff = [f for f in functions if f['cve_id'] == cve]
        c = dict(cve_id=cve, functions=ff)
        for metric in metrics:
            vals = [f[metric] for f in ff if f[metric] is not None]
            c[metric] = st.fmean(vals) if vals else None
        cves.append(c)
    distinct = {}
    for r in rows:
        if r['raw_depth'] is None:
            continue
        key = (r['executable_graph'], r['source_identity'])
        if key in distinct:
            assert all(distinct[key][m] == r[m] for m in metrics)
        else:
            distinct[key] = r
    deduplicated = []
    for (graph, identity), r in sorted(distinct.items()):
        associated = [x for x in numeric_rows(rows) if (x['executable_graph'], x['source_identity']) == (graph, identity)]
        deduplicated.append(dict(executable_graph=graph, source_identity=identity,
            associated_cves=sorted({x['cve_id'] for x in associated}),
            observation_ids=[x['observation_id'] for x in associated], **{m: r[m] for m in metrics}))
    out = dict(function_observations=functions, cves=cves, deduplicated_measurements=deduplicated, summaries={})
    for name, rr in [('executable_function', rows), ('deduplicated_function_executable', list(distinct.values())),
                     ('cve_function', functions), ('cve_weighted', cves)]:
        out['summaries'][name] = {m: summary([r[m] for r in rr if r[m] is not None]) for m in metrics}
    # Conservative connected components: same CVE, saved graph, or source-qualified vulnerable function.
    numeric = [r for r in rows if r['raw_depth'] is not None]
    parent = list(range(len(numeric)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, r in enumerate(numeric):
        for tag in [('cve', r['cve_id']), ('graph', r['executable_graph']), ('function', r['source_identity'])]:
            if tag in seen:
                parent[find(i)] = find(seen[tag])
            seen[tag] = i
    groups = defaultdict(list)
    for i, r in enumerate(numeric):
        groups[find(i)].append(r)
    components = sorted(groups.values(), key=lambda rr: min(r['observation_id'] for r in rr))
    out['dependence_components'] = [[r['observation_id'] for r in rr] for rr in components]
    deletion = {}
    for metric in metrics:
        estimates = []
        for rr in components:
            omit = {r['cve_id'] for r in rr}
            remaining = [c[metric] for c in cves if c['cve_id'] not in omit and c[metric] is not None]
            if remaining:
                estimates.append(st.fmean(remaining))
        deletion[metric] = dict(minimum=min(estimates), maximum=max(estimates), deleted_components=len(estimates))
    out['leave_one_component_out_cve_weighted_mean'] = deletion
    return out


def numeric_rows(rows):
    return [r for r in rows if r['raw_depth'] is not None]


def main():
    rust = read(RBASE / 'historical_rupta_results.json')
    original_csv = list(csv.DictReader(io.StringIO(read_bytes(RBASE / 'historical_rupta_observations.csv').decode())))
    c = read('security/historical/v2_semantic_results.json')
    cstats = read('security/historical/v2_statistics.json')
    cmappings = read('security/historical/v2_vulnerable_function_mappings.json')
    for p in ['security/historical/v2_statistics.py', 'security/historical/v2_protocol.json',
              'security/historical/v2_reporting_gate.json', 'security/historical/v2_population.json']:
        read_bytes(p)
    programs = {p['key']: p for p in rust['programs']}
    checkouts = {}
    for release in ('0.0.3', '0.2.2'):
        p = read(f'build/historical-rust-measurement/method-v1/{release}/source_provenance.json')
        checkouts[release] = Path(p['checkout'])
        archive = read_bytes(p['archive']['cache_path'])
        assert hashlib.sha256(archive).hexdigest() == p['archive']['sha256']
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    rel = member.name.split('/', 1)[1]
                    AUTHENTICATED[(checkouts[release] / rel).as_posix()] = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
    compiler_cache = {}
    evidence = dict(rust={}, c={}, entry_policy='Verified prefix only; entry at handwritten utility body',
                    closure_policy='Compiler Closure + exact lexical DefId parent earlier in witness; preserve named helpers',
                    sensitivity_estimand='Frame counts on the saved shortest witnesses, not reoptimized quotient-graph distances')
    rows_r = []
    for o, original in zip(rust['observations'], original_csv):
        assert o['observation_id'] == original['observation_id']
        row = dict(original)
        row.update(source_identity=o.get('authenticated_source_identity') or o.get('frozen_mapping', {}).get('source_identity'),
                   executable_graph=o.get('graph_artifact') or o['group'], raw_depth=o['depth'], entry_aligned_depth=None,
                   closure_collapsed_raw_depth=None, entry_and_closure_depth=None, entry_removed=None, closure_removed=None)
        if o['depth'] is not None:
            assert int(original['depth']) == o['depth']
            graph = Path(o['graph_artifact'])
            sidecar = graph.parent / 'graph.dot.depth.json'
            if str(sidecar) not in compiler_cache:
                compiler_cache.clear()  # keep memory bounded; grouping below is not assumed
                compiler_cache[str(sidecar)] = compiler_index(read(sidecar))
            compiler, exported_edges = compiler_cache[str(sidecar)]
            path = o['shortest_path']
            validate_path(path, compiler, exported_edges)
            assert len(path['transitions']) == o['depth']
            wrappers = entry_count(o, path, compiler, checkouts[o['release']], programs[o['group']])
            closures = contract_closures(path, compiler)
            row.update(entry_aligned_depth=o['depth']-wrappers,
                       closure_collapsed_raw_depth=o['depth']-len(closures),
                       entry_and_closure_depth=o['depth']-wrappers-len(closures),
                       entry_removed=wrappers, closure_removed=len(closures))
            assert min(row[k] for k in ('entry_aligned_depth', 'closure_collapsed_raw_depth', 'entry_and_closure_depth')) >= 0
            evidence['rust'][o['observation_id']] = dict(sidecar=str(sidecar), path=path,
                verified_entry_functions=[compiler[f['identity']] for f in path['functions'][:wrappers+1]],
                removed_entry_transitions=path['transitions'][:wrappers], closure_contractions=closures,
                retained_entry_and_closure_path=[f for i, f in enumerate(path['functions'])
                    if i >= wrappers and i not in {x['path_index'] for x in closures}])
        rows_r.append(row)
    assert len(rows_r) == len(original_csv) == len(rust['observations'])
    # Only observed C intermediate library frames are fts_read and fts_build.
    fts = Path('security/historical/sources/v2/coreutils-8.4/lib/fts.c')
    gnulib = Path('security/historical/sources/v2/coreutils-8.4/m4/gnulib-comp.m4')
    assert 'lib/fts.c' in '\n'.join(source(gnulib))
    fts_text = '\n'.join(source(fts))
    assert 'fts_read (' in fts_text and 'fts_build (' in fts_text
    rows_c = []
    for member in c['members']:
        for i, o in enumerate(member['observations']):
            path = o.get('shortest_semantic_path') or {}
            functions = path.get('function_identities', [])
            depth = o['raw_call_depth']
            removed = []
            if depth is not None:
                assert len(functions)-1 == depth
                edges = path['edges']
                assert len(edges) == depth
                assert all((e['caller'], e['callee']) == (functions[j], functions[j+1]) for j, e in enumerate(edges))
                for j, f in enumerate(functions[1:-1], 1):
                    if f in ('lib/fts.c::fts_read', 'lib/fts.c::fts_build'):
                        assert o['specimen_id'] == 'coreutils-8.4/rm'
                        removed.append(dict(path_index=j, source_identity=f, source_file=str(fts), gnulib_manifest=str(gnulib)))
            oid = f"{member['cve_id']}:{i}:{o['specimen_id']}"
            row = dict(observation_id=oid, cve_id=member['cve_id'], source_identity=o['source_identity'],
                executable_graph=o['specimen_id'], raw_depth=depth,
                library_contracted_depth=depth-len(removed) if depth is not None else None,
                library_removed=len(removed) if depth is not None else None,
                source_scope_kind=o['source_scope_kind'], analysis_status=member['analysis_status'],
                disposition=member['disposition'], reuse_status=o.get('reuse_status'),
                validation_status='canonical_saved_C_result; independent depth verification not inferred',
                mapping_status=o.get('mapping', {}).get('semantic_mapping_status'),
                shortest_path=functions, removed_library_frames=removed,
                evidence_reference=f"security/historical/v2_semantic_results.json:{member['cve_id']}:observations:{i}")
            rows_c.append(row)
            evidence['c'][oid] = dict(path=path, library_contractions=removed,
                retained_path=[f for j, f in enumerate(functions) if j not in {x['path_index'] for x in removed}])
        # Preserve nonnumeric mapped functions and population members without executable observations.
        mapped = next(m for m in cmappings['members'] if m['cve_id'] == member['cve_id'])
        observed = {r['source_identity'] for r in rows_c if r['cve_id'] == member['cve_id']}
        missing = [f['source_identity'] for f in mapped['functions'] if f['source_identity'] not in observed]
        if not member['observations'] and not missing:
            missing = [None]
        for i, identity in enumerate(missing):
            rows_c.append(dict(observation_id=f"{member['cve_id']}:unmeasured:{i}", cve_id=member['cve_id'],
                source_identity=identity, executable_graph=None, raw_depth=None, library_contracted_depth=None,
                library_removed=None, disposition=member['disposition'], analysis_status=member.get('analysis_status')))
    rm = ['raw_depth', 'entry_aligned_depth', 'closure_collapsed_raw_depth', 'entry_and_closure_depth']
    cm = ['raw_depth', 'library_contracted_depth']
    ar, ac = aggregate(rows_r, rm), aggregate(rows_c, cm)
    for population_cve in rust['cves']:
        if population_cve['cve_id'] not in {r['cve_id'] for r in ar['cves']}:
            ar['cves'].append(dict(cve_id=population_cve['cve_id'], functions=[], **{m: None for m in rm}))
    ar['cves'].sort(key=lambda r: r['cve_id'])
    assert len(ar['cves']) == 45 and len(ar['function_observations']) == 59
    assert ar['summaries']['executable_function']['raw_depth']['n'] == 55
    assert ar['summaries']['deduplicated_function_executable']['raw_depth']['n'] == 45
    assert ar['summaries']['cve_weighted']['raw_depth']['n'] == 42
    for unit, reference in [('cve_function', 'primary_function_observation_statistics'), ('cve_weighted', 'cve_weighted_statistics')]:
        for k in ('n', 'mean', 'median', 'minimum', 'maximum'):
            assert abs(ac['summaries'][unit]['raw_depth'][k] - cstats[reference][k]) < 1e-12
    assert {(x['cve_id'], x['source_identity']): x['raw_depth'] for x in ac['function_observations']} == {
        (x['cve_id'], x['source_identity']): x['function_level_depth'] for x in cstats['primary_function_observations']}
    associations = defaultdict(list)
    for r in rows_r:
        if r['raw_depth'] is not None:
            associations[(r['executable_graph'], r['source_identity'])].append(r['cve_id'])
    for r in rows_r:
        r['associated_cves'] = sorted(set(associations.get((r['executable_graph'], r['source_identity']), [])))
        r['repeated_measurement'] = len(r['associated_cves']) > 1
    result = dict(version=1, rust=ar, c=ac,
        population_accounting=dict(rust_cves=len(rust['cves']), rust_mapping_records=sum(x['source_function_records'] for x in rust['cves']),
            rust_observations=len(rows_r), rust_numeric_rows=55, rust_independently_verified_depths=0,
            rust_missing_cves=[x for x in rust['cves'] if not x['numerical_observations']],
            rust_cve_ledger=rust['cves'], c=cstats['population_accounting']),
        changes=dict(rust_entry=summary([r['entry_removed'] for r in rows_r if r['raw_depth'] is not None]),
            rust_closure=summary([r['closure_removed'] for r in rows_r if r['raw_depth'] is not None]),
            rust_closure_changed=sum(bool(r['closure_removed']) for r in rows_r),
            c_library_changed=sum(bool(r['library_removed']) for r in rows_c)),
        uncertainty=dict(confidence_intervals=None,
            reason='Frozen purposive populations and incomplete graph evidence have no justified sampling/error model. Component-deletion ranges quantify influence, not sampling confidence or graph-error bounds.',
            component_rule='Transitive union of shared CVE, executable graph, or source-qualified vulnerable function (conservatively across C versions). Residual shared implementation/analyzer dependence remains.'),
        diagnostic_only=dict(rust_programs=rust['programs'],
            deepest_witness_endpoint_source_counts=dict(Counter(p['deepest_path']['functions'][-1]['source']['file']
                for p in rust['programs'] if p['maximum_depth'] is not None)),
            note='Original Dmax and normalized depths preserved only. No equivalent validated C Dmax. No cross-language ratio comparison.'),
        sensitivity_estimand=evidence['sensitivity_estimand'])
    manifest = OUT / 'input_sha256.json'
    if manifest.exists():
        assert json.loads(manifest.read_text()) == INPUTS, 'Saved input evidence changed; do not silently revise v1'
    else:
        save('input_sha256.json', INPUTS)
    # Verify all consumed files are still unchanged before publishing derived outputs.
    for p, digest in INPUTS.items():
        assert hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == digest, p
    csv_save('rust_aligned_depths.csv', rows_r)
    with (OUT / 'rust_aligned_depths.csv').open(newline='', encoding='utf-8') as f:
        reloaded = list(csv.DictReader(f))
    assert len(reloaded) == len(original_csv)
    assert all(all(new[k] == v for k, v in old.items()) for old, new in zip(original_csv, reloaded))
    csv_save('c_aligned_depths.csv', rows_c)
    save('alignment_evidence.json', evidence)
    save('aligned_summary.json', result)
    write_reports(result, rows_r, rows_c)
    print(json.dumps(dict(rust_cve_function=ar['summaries']['cve_function'],
        c_cve_function=ac['summaries']['cve_function'], changes=result['changes']), indent=2))


def write_reports(result, rr, cr):
    lines = ['# C/Rust historical depth alignment v1', '',
        'Separate statistical postprocessing of saved evidence. Canonical data and analyzers are unchanged. '
        'All Rust values remain provisional observations of known-incomplete graphs; zero Rust depths are independently verified.', '',
        '## Units and distributions', '',
        'The C rule is `security/historical/v2_statistics.py:build_statistics`: arithmetic mean over measured executable contexts '
        'within each `(CVE, source-qualified vulnerable function)`, followed by equal function weights within each CVE. '
        'We reproduce the canonical C statistics before deriving sensitivities. Missing values are excluded from arithmetic, '
        'never replaced by zero. A CVE mean retains every measured mapped function; it is not the shallowest location. '
        'Partially mapped CVEs retain their original qualification. The selected 38 single-valued Rust CVEs are not used.', '',
        '| Language / unit | Policy | N | Mean | Median | Range |', '|---|---|---:|---:|---:|---|']
    for lang in ('c', 'rust'):
        for unit, ss in result[lang]['summaries'].items():
            for policy, s in ss.items():
                lines.append(f"| {lang} / {unit} | {policy} | {s['n']} | {s['mean']:.6f} | {s['median']:.6g} | {s['minimum']:.6g}–{s['maximum']:.6g} |")
    lines += ['', '### Exact frequencies at the C-aligned `(CVE,function)` unit', '']
    for lang in ('c', 'rust'):
        for policy, s in result[lang]['summaries']['cve_function'].items():
            lines += [f"- {lang} {policy}: {json.dumps(s['frequency'], sort_keys=True)}"]
    lines += ['', '### Rust original-row frequencies (55 measured rows)', '']
    for policy, s in result['rust']['summaries']['executable_function'].items():
        lines += [f"- {policy}: {json.dumps(s['frequency'], sort_keys=True)}"]
    lines += ['', '## Entry and closure sensitivities', '',
        'The entry sensitivity counts transitions from the handwritten utility entry body. The verified 0.2.2 prefix is '
        '`bin!`-generated binary main → `#[uucore::main]`-generated outer uumain → handwritten inner uumain. '
        'Saved compiler DefIds, source locations, source hashes and full transition witnesses are checked per observation. '
        'The 0.0.3 od procedural macro calls handwritten uumain directly: only one transition is removed (6 → 5). '
        'This is not an unconditional subtraction. Every adjusted depth is checked nonnegative.', '',
        'Closure identification requires compiler `def_kind == Closure` and the exact lexical parent in the compiler DefId '
        'path earlier in the saved witness, with the same source file. Generic arguments containing the word Closure are '
        'not classification evidence. Each closure frame is attributed to that defining parent; ordinary named helpers, '
        'including callback-invoking helpers, remain. Full witnesses and exact compiler identities are in `alignment_evidence.json`.', '',
        '**Sensitivity estimand:** these are frame-count contractions on the saved original shortest-path witnesses. '
        'They are not newly optimized shortest distances in a quotient graph. Alternate paths could become shorter after '
        'contraction; no claim of exhaustiveness or exact graph-policy equivalence is made. This paired witness analysis '
        'isolates counting choices while retaining the original graph depths as primary evidence.', '',
        f"Closure contraction changes {result['changes']['rust_closure_changed']} of 55 measured rows; reduction distribution: "
        f"{result['changes']['rust_closure']['frequency']}. Entry reduction distribution: {result['changes']['rust_entry']['frequency']}.", '',
        '### Every closure-changed observation', '', '| Observation | Raw | Entry aligned | Entry + closure | Closure frames removed |', '|---|---:|---:|---:|---:|']
    for r in rr:
        if r['closure_removed']:
            lines += [f"| {r['observation_id']} | {r['raw_depth']} | {r['entry_aligned_depth']} | {r['entry_and_closure_depth']} | {r['closure_removed']} |"]
    lines += ['', '## C library sensitivity', '',
        'The saved C paths contain intermediate gnulib frames only in the rm observation below. '
        '`m4/gnulib-comp.m4` lists `lib/fts.c`; definitions and saved SVF function identities support removing '
        '`fts_read` and `fts_build` as intermediates. Vulnerable endpoints `opendirat`, `parse_datetime`, and `make_path` '
        'are retained, including when they belong to lib/. Ordinary src/ helpers remain.', '']
    for r in cr:
        if r['library_removed']:
            lines += [f"- {r['observation_id']}: {r['raw_depth']} → {r['library_contracted_depth']}; "
                      f"path: {' → '.join(r['shortest_path'])}; removed: "
                      + ', '.join(x['source_identity'] for x in r['removed_library_frames']) + '.']
    lines += ['', 'Exact ownership symmetry is **not established**: gnulib is bundled into the C source tree, '
        'whereas Rust retains uucore as project implementation but contracts external dependencies. Treat gnulib contraction '
        'as a separate library-scope sensitivity, not a validated equivalent instrument.', '', '## Difference decomposition', '']
    for unit in ('cve_function', 'cve_weighted'):
        r, c = result['rust']['summaries'][unit], result['c']['summaries'][unit]
        gap = r['raw_depth']['mean'] - c['raw_depth']['mean']
        shift = r['raw_depth']['mean'] - r['entry_aligned_depth']['mean']
        lines += [f"- {unit}: raw Rust−C mean difference {gap:.6f}; verified entry counting removes {shift:.6f} "
            f"({100*shift/gap:.2f}% of that descriptive gap), leaving {gap-shift:.6f}. "
            f"Entry+closure Rust minus original C: {r['entry_and_closure_depth']['mean']-c['raw_depth']['mean']:.6f}; "
            f"versus library-contracted C: {r['entry_and_closure_depth']['mean']-c['library_contracted_depth']['mean']:.6f}."]
    lines += ['', 'These are within-data arithmetic changes, not causal attribution to programming language.', '',
        '## Reproduction and preservation', '',
        'Run `python3 security/analysis/c-rust-depth-alignment-v1/regenerate.py` from the repository (or run the script by absolute path). '
        'Python standard library only; saved build evidence must be present. No RUPTA/SVF execution, compilation, network, or canonical writes. '
        '`input_sha256.json` pins every consumed input; regeneration fails if evidence changes. '
        'The Rust CSV preserves every original field and all 61 rows (55 numeric, six nonnumeric), adds aligned values and repeated-CVE associations. '
        'The C CSV includes numeric contexts and nonnumeric population/mapping placeholders. '
        'The summary contains all function and CVE aggregates, all four reporting units, dependence components, original program Dmax evidence, '
        'and population ledgers. `alignment_evidence.json` contains every transformed path and its original witness.', '',
        'See `DEPENDENCE_AND_LIMITATIONS.md` for uncertainty and paper-use qualifications.', '']
    (OUT / 'C_RUST_DEPTH_ALIGNMENT.md').write_text('\n'.join(lines), encoding='utf-8')
    limitations = ['# Dependence and limitations', '',
        '## Population accounting', '',
        f"Rust: {result['population_accounting']['rust_cves']} frozen CVEs; 42 with numeric observations; "
        '59 frozen mapping records; 61 planned context rows, 55 numeric and six nonnumeric; '
        '45 distinct measured function/executable pairs. Ten extra rows repeat measurements across CVE associations. '
        'Deduplication uses saved graph identity and authenticated source-function identity, not equality of depth. '
        'Multiple executable contexts remain distinct; generic instances are already reduced by the saved diagnostic mapping policy. '
        'Every mapped function is retained in the function/CVE ledgers, including missing ones. Configuration-only CVEs have no numeric depth.', '',
        f"C frozen accounting: `{json.dumps(result['population_accounting']['c'], sort_keys=True)}`.", '',
        '## Dependence and uncertainty', '',
        'Repeated vulnerable functions, multiple locations in one CVE, and multiple CVEs on the same executable graph are dependent. '
        'CVE weighting fixes contribution weights; it does not create independence. We connect rows sharing a CVE, executable graph, '
        'or source-qualified vulnerable function, transitively. C function identities are conservatively joined across historical versions. '
        'The summary lists every component. Shared non-vulnerable helper code, releases and analyzer mechanisms create additional dependence.', '',
        'No confidence intervals or hypothesis tests are calculated. These frozen purposive populations are not random language samples, '
        'and no calibrated model exists for incomplete graphs or missing mappings. Row-wise bootstrap intervals would be misleading. '
        'Instead we report leave-one-connected-component-out ranges of the CVE-weighted mean: remove all connected CVEs together, '
        'then recompute equal-CVE weighting. These are influence/robustness ranges, not 95% confidence intervals, sampling uncertainty, '
        'or bounds on the unknown true depth. There is no resampling unit because there is no bootstrap.', '']
    for lang in ('c', 'rust'):
        limitations += [f"- {lang}: {len(result[lang]['dependence_components'])} components; deletion ranges: "
                        + json.dumps(result[lang]['leave_one_component_out_cve_weighted_mean'], sort_keys=True)]
    limitations += ['', '## Evidence strength and missingness', '',
        'Rust has zero independently verified vulnerability depths. All 55 measurements are provisional known-incomplete-graph '
        'observations despite authenticated source/compiler matches and full path witnesses. The independent methodological audit '
        'reported no numerical errors; that is not graph validation. Missing callback coverage can alter observed shortest depths '
        'and discover additional functions. No statistical adjustment repairs this.', '',
        'C retains its canonical SVF status and scope fields, including any legacy scope qualifications and pilot reuse status. '
        'Independent mapping review is distinct from independent depth validation; this analysis does not promote C results or '
        'Rust results to a new validation tier. No accepted-C/provisional-Rust pooling is performed.', '',
        'Missing Rust measurements, partially mapped CVEs, unsupported platforms and the differing historical packages/versions '
        'are explicit in the retained population ledger. A numerical CVE mean is conditional on measured mapped locations. '
        'Unknown locations are not silently assigned a minimum or zero; their effects cannot be bounded from this evidence.', '',
        '## Maximum depth diagnostics only', '',
        'Original Rust per-row Dmax and normalized depths remain in the Rust CSV; original per-program evidence and deepest witnesses '
        'remain in aligned_summary.json under diagnostic_only. They are not aligned cross-language outcomes. '
        'Closure frames increase counted depths along deepest witnesses and can change which endpoint maximizes shortest depth; '
        'a path-level closure correction cannot be assumed to give a corrected Dmax. Shared uucore error/formatting paths dominate '
        'many executable maxima, so those maxima are not independent utility-specific complexity measures. '
        'Omitted initializer/formatting callbacks undermine coverage of both numerator and denominator. '
        'There are no equivalent validated C Dmax measurements. Neither Dmax nor normalized depth supports a quantitative '
        'cross-language claim here.', '',
        '## Paper use', '',
        'Suitable for a carefully qualified descriptive/methodological paper section if it explicitly adopts the incomplete-graph '
        'observed-path estimand. Report C-aligned function and CVE-weighted units, denominators, missingness, original raw evidence, '
        'and paired counting sensitivities together. Label Rust provisional and distinguish C scope/validation. '
        'The observed mean gap partly reflects entry counting; remaining differences cannot be assigned to language. '
        'Close means or medians do not demonstrate statistical similarity or equivalence. No causal language-effect claim, '
        'population generalization, equivalence test, validated-depth claim, or normalized-depth comparison is supported.', '']
    (OUT / 'DEPENDENCE_AND_LIMITATIONS.md').write_text('\n'.join(limitations), encoding='utf-8')


if __name__ == '__main__':
    main()
