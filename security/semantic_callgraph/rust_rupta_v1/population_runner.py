"""Frozen-population diagnostic collection. No analyzer or historical-input edits."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time

from .scoped_trial import ROOT, HERE, WORK, OUT, SYSROOT, env, run
from .population_adapter import parse, identity_keys
from .utility_scope import project
from security.semantic_callgraph.rust_identity import declaration_line

OLD = ROOT / 'build/historical-rust-measurement/method-v1'
FROZEN = ROOT / 'security/historical/rust'
BASE = ROOT / 'build/rupta-v1/historical-diagnostic-v1'
REPORT = HERE / 'historical-diagnostic-v1'
PTA = WORK / 'target/debug/pta'
TARGET = 'x86_64-unknown-linux-gnu'
FLAGS = '-Copt-level=0\x1f-Cpanic=unwind\x1f-Zalways-encode-mir'

def read(p): return json.loads(p.read_text())
def write(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix(p.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temp.replace(p)
def sha(p):
    with p.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
def rel(p): return str(p.relative_to(ROOT))

def guard():
    """Protect all pre-existing tracked research files, not only three manifests."""
    manifest = BASE / 'preservation.json'
    if not manifest.exists():
        names = subprocess.check_output(['git', 'ls-files', '-z', 'security', 'tests', 'native', 'docs'], cwd=ROOT).decode().split('\0')
        with ThreadPoolExecutor(max_workers=16) as pool:
            write(manifest, dict(pool.map(lambda n:(n,sha(ROOT/n)),[n for n in names if n and (ROOT/n).is_file()])))
    with ThreadPoolExecutor(max_workers=16) as pool:
        changed = [n for n,ok in pool.map(lambda item:(item[0],(ROOT/item[0]).is_file() and sha(ROOT/item[0])==item[1]),read(manifest).items()) if not ok]
    assert not changed, ('preserved research changed', changed)
    for name,h in read(HERE/'scoped_provenance.json')['sha256'].items():
        assert sha(ROOT/name) == h, name
    return sha(manifest)

def plan():
    records = read(FROZEN/'vulnerable_function_mappings.json')['records']
    population = read(FROZEN/'population.json')['records']
    assert len(records) == 45
    # Population may carry excluded discovery records: mappings are the frozen included ledger.
    assert all(any(r.get('cve_id', r.get('cve')) == m['cve_id'] for r in population) for m in records)
    groups = {}
    observations = []
    for r in records:
        for index, f in enumerate(r['vulnerable_functions']):
            for utility in f['affected_executables']:
                platform = ('windows' if '/windows.rs' in f['source_file'] else
                            'macos' if '/macos.rs' in f['source_file'] else
                            'other_unix' if '/other_unix.rs' in f['source_file'] else 'linux')
                key = f['affected_version'] + '/' + utility
                row = dict(observation_id=f"{r['cve_id']}:{index}:{utility}:{platform}",
                           cve_id=r['cve_id'], mapping_index=index, utility=utility, executable=utility,
                           platform=platform, target=TARGET if platform=='linux' else None,
                           group=key, revision=f['affected_revision'], release=f['affected_version'],
                           frozen_mapping_status=r['mapping_status'], function_mapping_status=f['mapping_status'],
                           mapping_completeness=r.get('mapping_completeness'), frozen_mapping=f)
                observations.append(row)
                if platform == 'linux': groups[key] = dict(key=key, release=row['release'], revision=row['revision'], utility=utility, target=TARGET)
    # Verify executable associations against original build observations, rather than inventing consumers.
    for g in groups.values():
        old = OLD/g['release']/'build-attempts-2'/g['utility']/'result.json'
        if not old.exists(): old = OLD/g['release']/'build-attempts'/g['utility']/'result.json'
        assert old.exists(), ('no authenticated build association', g)
        b = read(old)
        assert b['utility']==g['utility'] and b['revision']==g['revision'] and b['target']==TARGET
        g['prior_build_record'] = rel(old)
        g['prior_build_record_sha256'] = sha(old)
    return records, observations, groups

def specimen(release):
    provenance = read(OLD/release/'source_provenance.json')
    source = BASE/'specimens'/release/('coreutils-' + provenance['revision'])
    if not source.exists():
        archive = ROOT/provenance['archive']['cache_path']
        archive_hash=sha(archive)
        assert archive_hash == provenance['archive']['sha256']
        frozen_manifest = read(FROZEN/'source_manifest.json')
        assert any(e['sha256']==archive_hash for e in frozen_manifest['evidence_cache'])
        source.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, 'r:gz') as tar: tar.extractall(source.parent, filter='data')
    verify_source(source, provenance)
    assert provenance['cargo_lock_present'], 'No frozen dependency lock; do not reconstruct silently'
    return source, provenance

def verify_source(source, provenance):
    changed = [n for n,h in provenance['source_tree_sha256'].items() if not (source/n).is_file() or sha(source/n)!=h]
    assert not changed, ('specimen source changed', changed)

def function_metadata(sidecar):
    keys=identity_keys(sidecar['functions'])
    return {keys[f['id']]:f for f in sidecar['functions']}

def ownership(raw, sidecar, source, provenance, utility, shared):
    meta = function_metadata(sidecar)
    included = set(); inventory = []; generated = {}
    crates = {utility.replace('-', '_'), 'uu_' + utility.replace('-', '_')}
    if shared: crates.add('uucore')
    for f in raw['functions']:
        m = meta[f['function_identity']]
        name = (f.get('source') or {}).get('file','').replace('\\','/')
        p = Path(name)
        source_name = name if name.startswith('src/') else str(p.relative_to(source)) if p.is_relative_to(source) else None
        authenticated = source_name in provenance['source_tree_sha256'] if source_name else False
        if not authenticated and m['crate']=='uucore' and p.name=='embedded_locales.rs' and p.is_file() and p.is_relative_to(ROOT/'build'):
            generator = source/'src/uucore/build.rs'
            include = source/'src/uucore/src/lib/mods/locale.rs'
            if generator.exists() and include.exists() and 'embedded_locales.rs' in generator.read_text() and 'embedded_locales.rs' in include.read_text():
                assert sha(generator)==provenance['source_tree_sha256']['src/uucore/build.rs']
                generated[name] = dict(sha256=sha(p),generator='src/uucore/build.rs',generator_sha256=sha(generator),include_source_sha256=sha(include))
                authenticated = True
        if m['shim']!='None' or m['drop_glue']: reason='compiler_glue_or_shim'
        elif m['promoted']!='None' or m.get('def_kind','').startswith(('Const','Static','AnonConst','InlineConst')): reason='constant_or_static_pseudo_body'
        elif m['crate'] not in crates: reason='outside_selected_ownership'
        elif not authenticated: reason='unverified_source_span'
        elif not m['body_available']: reason='owned_body_unavailable'
        else: reason='included'; included.add(f['identity'])
        inventory.append(dict(identity=f['identity'],name=f['name'],crate=m['crate'],source=name,decision=reason))
    assert raw['entry'] in included, 'source-level main absent from owned set'
    return included, inventory, generated

def resolve_source(f, source):
    """Use an authenticated, unique declaration; ambiguity never uses graph depth."""
    p = source/f['source_file']
    assert sha(p)==f['source_sha256'], 'mapping source hash mismatch'
    text = p.read_text()
    short = f['function'].split('::')[-1]
    owner = f['function'].rsplit('::',1)[0] if '::' in f['function'] else None
    try: line = declaration_line(text, short)
    except ValueError as e:
        # Conservative support for the frozen, top-level rustfmt-style impls.
        # Only declarations directly indented in an impl of the named receiver
        # qualify. Unrecognized layout or multiple methods remains ambiguous.
        candidates=[]
        if owner:
            receiver=re.escape(owner.split('<')[0])
            for block in re.finditer(r'(?ms)^impl\b([^\{]+)\{(.*?)^\}',text):
                header=block[1].strip()
                receiver_matches=(re.search(r'\bfor\s+'+receiver+r'\b',header) if re.search(r'\bfor\b',header)
                                  else re.match(r'(?:<.*>\s*)?'+receiver+r'\b',header))
                if receiver_matches:
                    for method in re.finditer(r'(?m)^    (?:pub(?:\([^\n]*\))?\s+)?(?:unsafe\s+)?fn\s+'+re.escape(short)+r'\s*(?:<|\()',block[2]):
                        candidates.append(text[:block.start(2)+method.start()].count('\n')+1)
        if len(candidates)!=1:return dict(status='ambiguous_source_declaration',reason=str(e),owner_candidates=candidates)
        line=declaration_line(text,short,occurrence_line=candidates[0])
    # The unique declaration plus frozen owner identity identifies the source definition;
    # record the surrounding impl header for review, without decoding rustc impl ordinals.
    headers = list(re.finditer(r'(?m)^\s*impl\b[^\n]*', '\n'.join(text.splitlines()[:line])))
    header = headers[-1][0].strip() if headers else None
    if owner and (not header or not re.search(r'\b'+re.escape(owner.split('<')[0])+r'\b', header)):
        return dict(status='owner_confirmation_needed',line=line,impl_header=header)
    return dict(status='authenticated_unique_declaration',line=line,impl_header=header,
                declaration=text.splitlines()[line-1].strip(),source_sha256=sha(p))

def compiler_method_matches(metadata, short):
    # DefId's definition path has no instantiated type arguments. The display
    # name instead uses f<T>, not necessarily Rust source's f::<T> spelling.
    return metadata.get('def_kind') in ('Fn','AssocFn') and metadata['def_id'].endswith('::'+short+')')

def path_record(graph, ids, raw):
    if ids is None: return None
    nodes = {f['identity']:f for f in raw['functions']}
    edges = {(e['caller'],e['callee']):e for e in graph['scoped_edges']}
    return dict(functions=[dict(identity=k,name=nodes[k]['name'],source=nodes[k].get('source')) for k in ids],
                transitions=[dict(edges[(a,b)], full_call_edges=[raw['call_edges'][i] for i in edges[(a,b)]['witness_edge_indices']]) for a,b in zip(ids,ids[1:])])

def process_graph(group, directory, source, provenance):
    raw, full, identity_audit = parse(directory,'ander')
    write(directory/'normalized.json', raw)
    sidecar = read(directory/'graph.dot.depth.json')
    nodes = {f['identity']:f for f in raw['functions']}
    assert nodes[raw['entry']]['name'] == group['utility'].replace('-','_')+'::main'
    main = source/f"src/uu/{group['utility']}/src/main.rs"
    assert main.exists(), 'entry source missing'
    entry_text=main.read_text()
    wrapper_evidence=None
    if re.search(r'uucore_procs::main!\s*\(\s*uu_'+re.escape(group['utility'])+r'\s*\)',entry_text):
        generator=source/'src/uucore_procs/src/lib.rs'
        assert sha(generator)==provenance['source_tree_sha256']['src/uucore_procs/src/lib.rs']
        assert 'fn main()' in generator.read_text() and '#expr(uucore::args_os())' in generator.read_text()
        wrapper_evidence=dict(kind='authenticated_project_proc_macro_main',generator='src/uucore_procs/src/lib.rs',sha256=sha(generator))
    else:
        assert re.search(r'\bfn\s+main\b|uucore::bin!\s*\(',entry_text), 'unreviewed main wrapper'
    result = dict(group=group,graph_sha256=sha(directory/'normalized.json'),entry=nodes[raw['entry']],
                  entry_source=dict(path=str(main.relative_to(source)),sha256=sha(main),wrapper_evidence=wrapper_evidence),policies={})
    for shared in (True,False):
        key = 'primary' if shared else 'utility_only'
        included, inventory, generated = ownership(raw,sidecar,source,provenance,group['utility'],shared)
        graph = project(raw,included)
        graph.update(ownership_inventory=inventory,generated_source_provenance=generated)
        write(directory/(key+'-graph.json'), graph)
        result['policies'][key] = dict(maximum_depth=graph['maximum_utility_depth'],reachable_implementation_functions=graph['projected_reachable'],
            implementation_transitions=len(graph['scoped_edges']),mediated_transitions=sum(e['dependency_mediated'] for e in graph['scoped_edges']),
            deepest_path=path_record(graph,graph['deepest_path'],raw),graph_artifact=rel(directory/(key+'-graph.json')))
    unavailable = [f for f in raw['functions'] if not f.get('body_available',True)]
    names = [f['name'] for f in raw['functions']]
    coverage = dict(key=group['key'],graph_completeness='known_incomplete',inventory_complete=False,
        identity_export_audit=identity_audit,
        full_nodes=len(raw['functions']),full_edges=len(raw['call_edges']),
        recognized_unresolved_callsites=raw['unresolved_indirect_callsites'],unavailable_bodies=unavailable,
        primary_frontiers=read(directory/'primary-graph.json')['coverage_frontiers'],
        lazylock_exposure=[n for n in names if 'LazyLock' in n or 'lazy_lock' in n],
        tls_exposure=[n for n in names if 'LocalKey' in n or 'thread_local' in n],
        formatting_boundaries=[f for f in unavailable if any(s in f['name'] for s in ('fmt::','_print','_eprint'))],
        ownership_exclusions_requiring_review=[f for f in read(directory/'primary-graph.json')['ownership_inventory']
                                             if f['decision'] in ('unverified_source_span','owned_body_unavailable')],
        summary_callsites=[s for s in sidecar['callsites'] if s.get('summary_site')],
        limitations=['LazyLock/TLS initializer storage and callback omissions remain unresolved.',
                    'Formatting/Display callbacks may be omitted behind unavailable bodies.',
                    'Recognized zero-target sites are not an exhaustive missing-call inventory.',
                    'Omissions may change shortest paths, reachability and Dmax; no numerical error bounds are claimed.'])
    write(directory/'coverage.json', coverage)
    result['coverage_artifact']=rel(directory/'coverage.json')
    result['recognized_unresolved_count']=len(coverage['recognized_unresolved_callsites'])
    result['unavailable_body_count']=len(unavailable)
    write(directory/'graph-summary.json', result)
    return result

def observe(row, program, source):
    f = row['frozen_mapping']
    out = dict(row, depth=None,maximum_depth=None,normalized_depth=None,utility_only_depth=None,
               utility_only_maximum_depth=None,utility_only_normalized_depth=None,shortest_path=None,
               instances=[],accepted_historical_measurement=False,independently_verified=False,
               mapping_status='pending',build_status=program.get('build_status','not_run'),
               analysis_status=program.get('analysis_status','not_run'),reachability_status='not_assessed',
               graph_completeness='not_assessed',measurement_validity='not_measured')
    out['utility_only_status']='shared_target_excluded_from_sensitivity_scope' if f.get('crate_or_package')=='uucore' else 'not_assessed'
    resolution = resolve_source(f,source)
    out['source_resolution']=resolution
    if row['platform']!='linux':
        out.update(build_status='platform_not_built',analysis_status='not_run',mapping_status='frozen_source_qualified',measurement_validity='unsupported_platform')
        return out
    out['mapping_status']=resolution['status']
    if program.get('analysis_status')!='completed':
        out['measurement_validity']='build_or_analysis_failure'
        out['failure_reason']=program.get('failure_reason')
        return out
    directory = ROOT/program['analysis_directory']
    raw = read(directory/'normalized.json'); meta=function_metadata(read(directory/'graph.dot.depth.json'))
    graphs = {p:read(directory/(p+'-graph.json')) for p in ('primary','utility_only')}
    out.update(maximum_depth=graphs['primary']['maximum_utility_depth'],utility_only_maximum_depth=graphs['utility_only']['maximum_utility_depth'],graph_completeness='known_incomplete',
               coverage_key=row['group'],coverage_artifact=rel(directory/'coverage.json'),graph_artifact=rel(directory/'normalized.json'))
    if resolution['status']!='authenticated_unique_declaration':
        out['measurement_validity']='mapping_ambiguous'; return out
    candidates = []
    for n in raw['functions']:
        m = meta[n['function_identity']]; span=n.get('source') or {}
        source_path=span.get('file','').replace('\\','/')
        if (m['crate']==f['crate_or_package'] and (source_path==f['source_file'] or source_path==str(source/f['source_file']))
            and span.get('line')==resolution['line'] and m['shim']=='None' and m['promoted']=='None'
            and compiler_method_matches(m,f['function'].split('::')[-1])):
            candidates.append(n)
    definitions={meta[n['function_identity']]['def_path_hash'] for n in candidates}
    if len(definitions)>1:
        out.update(mapping_status='ambiguous_compiler_definitions',measurement_validity='mapping_ambiguous'); return out
    if not candidates:
        out.update(mapping_status='authenticated_source_not_in_graph',reachability_status='unknown_absent_from_incomplete_graph',measurement_validity='no_observed_target'); return out
    out['mapping_status']='authenticated_compiler_definition'
    for p,g in graphs.items():
        lookup={n['identity']:n for n in g['functions']}
        instances=[dict(identity=n['identity'],name=n['name'],compiler_definition=meta[n['function_identity']],
                        depth=lookup.get(n['identity'],{}).get('scoped_depth'),
                        path=path_record(g,lookup.get(n['identity'],{}).get('scoped_path'),raw)) for n in candidates]
        eligible=[i for i in instances if i['depth'] is not None]
        # Minimum over instances of ONE authenticated definition, never ambiguous definitions.
        chosen=min(eligible,key=lambda i:(i['depth'],i['identity'])) if eligible else None
        if p=='primary':
            out['instances']=instances
            out.update(depth=chosen['depth'] if chosen else None,shortest_path=chosen['path'] if chosen else None,
                       normalized_depth=chosen['depth']/out['maximum_depth'] if chosen and out['maximum_depth'] else None)
        else:
            out.update(utility_only_depth=chosen['depth'] if chosen else None,
                       utility_only_normalized_depth=chosen['depth']/out['utility_only_maximum_depth'] if chosen and out['utility_only_maximum_depth'] else None)
            if f['crate_or_package']!='uucore':out['utility_only_status']='observed_reachable' if chosen else 'no_observed_scoped_target'
    out.update(reachability_status='observed_reachable' if out['depth'] is not None else 'mapped_not_reached_in_observed_graph',
               measurement_validity='provisional_graph_observed' if out['depth'] is not None else 'observed_unreachable_incomplete_graph')
    out['validity_assessment']=dict(shortest_path='Every transition has an observed full-graph callsite witness; source/compiler identity authenticated; no independent exhaustiveness proof.',
        maximum_depth='Provisional: reachable initializer/formatting boundaries may conceal additional included functions.',
        normalized_depth='Provisional numerator and denominator; not a bound or confirmed population estimate.',
        vulnerability_coverage='partial_frozen_mapping' if row['frozen_mapping_status']=='unresolved' else 'frozen_verified_locations')
    if out['depth'] is not None:
        g=graphs['primary'];by_id={n['identity']:n for n in raw['functions']}
        path_ids={n['identity'] for n in out['shortest_path']['functions']}
        frontier={n['owner']:n for n in g['coverage_frontiers']}
        sites=sorted({i for k in path_ids if k in frontier for i in frontier[k]['unresolved_site_indices']})
        bodies=sorted({i for k in path_ids if k in frontier for i in frontier[k]['body_unavailable_nodes']})
        out['validity_assessment'].update(
            shortest_path_frontier_owners=[by_id[k]['name'] for k in sorted(path_ids & frontier.keys())],
            exposed_unresolved_site_indices=sites,
            exposed_initializer_sites=[i for i in sites if any(s in str(raw['unresolved_indirect_callsites'][i]) for s in ('lazy_lock','thread/local','thread_local','LocalKey'))],
            exposed_formatting_boundaries=[by_id[k]['name'] for k in bodies if any(s in by_id[k]['name'] for s in ('fmt::','_print','_eprint'))],
            shallower_implementation_owners_with_boundaries=sum(n['identity'] in frontier and n['scoped_depth'] is not None and n['scoped_depth']<out['depth'] for n in g['functions']),
            attribution_limit='These are observed dependency-interior exposures from path owners or shallower owners, not proof that a particular omitted callback reaches this vulnerable definition. Off-path omissions can also change shortest distances.')
    return out

def analyze(group):
    source, provenance = specimen(group['release'])
    fingerprint = dict(group=group,source_provenance_sha256=sha(OLD/group['release']/'source_provenance.json'),
        analyzer_sha256=sha(PTA),compiler_sha256=sha(SYSROOT/'bin/rustc'),
        patch_sha256=sha(HERE/'scoped_callback_overlay.patch'),base_patch_sha256=sha(HERE/'modern_overlay.patch'),
        cargo_lock_sha256=sha(source/'Cargo.lock'),target=TARGET,mode='ander',entry='main',flags=FLAGS,
        cargo_configuration='check --locked -p uu_UTILITY --bin UTILITY; package default features',
        wrapper_sha256=sha(HERE/'population_wrapper.py'))
    key=digest(fingerprint)
    directory=BASE/'runs'/group['release']/group['utility']/key
    if (directory/'result.json').exists():
        result=read(directory/'result.json')
        if result.get('analysis_status')=='completed':
            assert sha(ROOT/result['analysis_directory']/'normalized.json')==result['graph']['graph_sha256']
        return result,source
    directory.mkdir(parents=True,exist_ok=True)
    write(directory/'fingerprint.json',fingerprint)
    attempt=directory/('attempt-'+str(len(list(directory.glob('attempt-*')))+1))
    capture=attempt/'capture'; capture.mkdir(parents=True)
    wrapper=HERE/'population_wrapper.py'; wrapper.chmod(0o755)
    environment=env()
    for k in ('RUSTFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTUP_TOOLCHAIN','PTA_BUILD_STD'):environment.pop(k,None)
    environment.update(RUSTC=str(SYSROOT/'bin/rustc'),RUSTDOC=str(SYSROOT/'bin/rustdoc'),
        CARGO_HOME=str(BASE/'cargo-home'),CARGO_TARGET_DIR=str(BASE/'targets'/group['release']),
        CARGO_ENCODED_RUSTFLAGS=FLAGS,RUSTC_WRAPPER=str(wrapper),RUPTA_CAPTURE=str(capture),
        RUPTA_EXECUTABLE=group['utility'].replace('-','_'),CARGO_NET_RETRY='1')
    # Share immutable registry archives from the previously authenticated locked builds.
    cargo_home=BASE/'cargo-home';cargo_home.mkdir(exist_ok=True)
    registry=cargo_home/'registry'
    if not registry.exists(): registry.symlink_to(OLD/'cargo-home/registry',target_is_directory=True)
    argv=[str(SYSROOT/'bin/cargo'),'check','--locked','--manifest-path',str(source/'Cargo.toml'),
          '-p','uu_'+group['utility'],'--bin',group['utility'],'--target='+TARGET,'-j','2','-v']
    write(attempt/'environment.json',{k:environment[k] for k in environment if k.startswith(('RUST','CARGO','RUPTA','LD_LIBRARY'))})
    print('BUILD',group['key'],flush=True)
    build=run(argv,attempt/'build',timeout=900,environment=environment,cwd=source)
    verify_source(source,provenance)
    result=dict(group=group,fingerprint=key,build_status='completed' if build['status']=='completed' else build['status'],
                analysis_status='not_run',build=build,build_directory=rel(attempt/'build'),
                source_directory=rel(source),source_tree_unchanged=True,accepted_historical_measurement=False)
    command_file=capture/'binary-command.json'
    # A resumed attempt may find Cargo's binary metadata already fresh. Reuse
    # only a successful capture under this exact authenticated cache key.
    if build['status']=='completed' and not command_file.exists():
        for previous in sorted(directory.glob('attempt-*/capture/binary-command.json')):
            command=read(previous)
            if (command.get('returncode')==0 and command.get('cwd')==str(source)
                and command.get('crate')==group['utility'].replace('-','_')
                and command.get('crate_type')=='bin' and command.get('argv',[None])[0]==str(SYSROOT/'bin/rustc')):
                shutil.copy2(previous,command_file)
                result['captured_command_reused_from']=rel(previous)
                break
    if build['status']=='completed' and command_file.exists():
        command=read(command_file); assert command['returncode']==0
        args=command['argv'][1:]
        analysis=attempt/'analysis'
        for flag in ('--out-dir',):
            if flag in args: args[args.index(flag)+1]=str(analysis)
        args=[('incremental='+str(analysis/'incremental')) if a.startswith('incremental=') else a for a in args]
        environment.pop('RUSTC_WRAPPER',None)
        environment['PTA_FLAGS']=json.dumps(['--pta-type','ander','--entry-func','main','--dump-call-graph',str(analysis/'graph.dot'),'--dump-dyn-calls',str(analysis/'dynamic.txt')])
        environment['PTA_LOG']='info'
        externs={}
        for i,a in enumerate(args):
            if a=='--extern':
                v=args[i+1].split('=',1)
                if len(v)==2 and Path(v[1]).is_file():externs[v[1]]=sha(Path(v[1]))
        write(attempt/'compiler-inputs.json',dict(command=command,extern_sha256=externs,environment={k:environment[k] for k in ('PTA_FLAGS','PTA_LOG','LD_LIBRARY_PATH')}))
        print('ANALYZE',group['key'],flush=True)
        run_result=run([PTA,*args],analysis,timeout=600,environment=environment,cwd=source)
        result.update(analysis_status=run_result['status'],analysis=run_result,analysis_directory=rel(analysis))
        if run_result['status']=='completed':
            try:result['graph']=process_graph(group,analysis,source,provenance)
            except Exception as e:result.update(analysis_status='export_or_mapping_failure',failure_reason=repr(e))
        else:result['failure_reason']=(analysis/'stderr.txt').read_text(errors='replace')[-6000:]
    else:
        result['failure_reason']=(attempt/'build/stderr.txt').read_text(errors='replace')[-6000:]
        if build['status']=='completed':result.update(build_status='capture_missing',failure_reason='Cargo did not emit an authenticated binary invocation; no graph assumed.')
    verify_source(source,provenance)
    write(directory/'result.json',result)
    print('RESULT',group['key'],result['build_status'],result['analysis_status'],flush=True)
    return result,source

def pilot(groups, observations):
    group=groups['0.2.2/chmod']
    build=read(OUT/'historical-build/result.json')
    source=Path(build['cwd']); provenance=read(OLD/'0.2.2/source_provenance.json')
    verify_source(source,provenance)
    old=WORK/'final-coverage'; directory=BASE/'pilot-replay'
    assert sha(old/'normalized.json')==read(HERE/'FINAL_COVERAGE_RESULTS.json')['full_graph']['normalized_sha256']
    directory.mkdir(parents=True,exist_ok=True)
    for name in ('graph.dot','graph.dot.depth.json'):
        dest=directory/name
        if dest.exists():assert sha(dest)==sha(old/name)
        else:shutil.copy2(old/name,dest)
    graph=process_graph(group,directory,source,provenance)
    assert read(directory/'normalized.json')==read(old/'normalized.json'), 'replayed graph differs from authenticated final pilot'
    program=dict(group=group,build_status='completed',analysis_status='completed',graph=graph,analysis_directory=rel(directory),source_directory=rel(source),
                 cached_pilot_evidence=rel(old),cached_pilot_sha256=sha(old/'normalized.json'),accepted_historical_measurement=False)
    program['cache_provenance']=dict(source_provenance_sha256=sha(OLD/group['release']/'source_provenance.json'),
        analyzer_provenance=read(HERE/'scoped_provenance.json'),original_analysis_record_sha256=sha(old/'result.json'),
        original_graph_sha256=sha(old/'normalized.json'),group=group,mode='ander',entry='main')
    program['fingerprint']=digest(program['cache_provenance'])
    rows=[observe(r,program,source) for r in observations if r['group']==group['key']]
    assert all(r['depth']==3 and r['maximum_depth']==12 and r['normalized_depth']==.25 and r['measurement_validity']=='provisional_graph_observed' for r in rows),rows
    write(BASE/'pilot-gate.json',dict(status='PASS',program=program,observations=rows))
    return program

def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=('pilot','smoke','population','report','refresh'));args=p.parse_args()
    BASE.mkdir(parents=True,exist_ok=True);REPORT.mkdir(exist_ok=True)
    preservation=guard()
    records,observations,groups=plan()
    write(REPORT/'plan.json',dict(cve_count=len(records),groups=groups,observations=observations,
          frozen_input_sha256={n:sha(FROZEN/n) for n in ('population.json','vulnerable_function_mappings.json','source_manifest.json')},preservation_sha256=preservation))
    if args.phase=='pilot':
        pilot(groups,observations);guard();print('PILOT GATE PASS',flush=True);return
    assert read(BASE/'pilot-gate.json')['status']=='PASS'
    programs=read(BASE/'programs.json') if (BASE/'programs.json').exists() else {}
    programs['0.2.2/chmod']=read(BASE/'pilot-gate.json')['program']
    selected=['0.2.2/mkfifo','0.2.2/chown'] if args.phase=='smoke' else sorted(groups)
    if args.phase=='population':assert read(BASE/'smoke-gate.json')['status']=='PASS'
    if args.phase=='refresh':
        for key,program in programs.items():
            if program.get('analysis_status')!='export_or_mapping_failure' or program.get('analysis',{}).get('status')!='completed':continue
            directory=ROOT/program['analysis_directory'];source=ROOT/program['source_directory']
            provenance=read(OLD/program['group']['release']/'source_provenance.json');verify_source(source,provenance)
            write(directory/'previous-postprocessing-failure.json',program)
            program['graph']=process_graph(program['group'],directory,source,provenance)
            program.update(analysis_status='completed',failure_reason=None,postprocessing_replayed_without_analyzer_rerun=True)
            write(directory.parent.parent/'result.json',program)
            print('REFRESH',key,'completed',flush=True)
    elif args.phase!='report':
        for key in selected:
            if key=='0.2.2/chmod':continue
            program,source=analyze(groups[key]);programs[key]=program
            write(BASE/'programs.json',programs)
            rows=[observe(r,program,source) for r in observations if r['group']==key]
            write(BASE/'observations'/key/'observations.json',rows)
            print('OBSERVATIONS',key,Counter(r['measurement_validity'] for r in rows),flush=True)
            failures=sum(x['analysis_status']!='completed' for x in programs.values())
            if len(programs)>=6 and failures>len(programs)/2:
                write(BASE/'population-stop.json',dict(reason='majority_of_attempted_specimens_failed',attempted=len(programs),failures=failures));break
        if args.phase=='smoke':
            rows=[r for k in selected for r in read(BASE/'observations'/k/'observations.json')]
            assert all(r['depth'] is not None and r['mapping_status']=='authenticated_compiler_definition' for r in rows),rows
            write(BASE/'smoke-gate.json',dict(status='PASS',groups=selected,observations=rows))
    write(BASE/'programs.json',programs)
    guard()
    from .population_report import publish
    publish(records,observations,groups,programs)

if __name__=='__main__':main()
