"""One bounded, unchanged-analyzer chmod replay and coverage ledger."""
import hashlib
import json
from pathlib import Path
from .scoped_trial import HERE, WORK, OUT, ROOT, run
from .modern_trial import env
from .patched_adapter import parse
from .utility_scope import derive


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    out=WORK/'final-coverage'
    old=OUT/'historical-pilot'
    provenance=json.loads((HERE/'scoped_provenance.json').read_text())
    binary=WORK/'target/debug/pta'
    assert sha(binary)==provenance['sha256'][str(binary.relative_to(ROOT))]
    build=json.loads((OUT/'historical-build/result.json').read_text())
    checkout=Path(build['cwd'])
    assert all(sha(checkout/p)==h for p,h in build['source_manifest_before'].items())
    preserved=[WORK/'pilot/normalized.json',WORK/'pilot/graph.dot.depth.json',
               WORK/'patched-scoped.json',HERE/'scoped_callback_overlay.patch',
               HERE/'modern_overlay.patch',HERE/'scoped_pilot_results.json',binary]
    before={str(p.relative_to(ROOT)):sha(p) for p in preserved}
    invocation=json.loads((old/'analysis-command.json').read_text())
    command=[str(binary),*invocation['argv'][5:]]
    command[command.index('--out-dir')+1]=str(out)
    command=[('incremental='+str(out/'incremental')) if a.startswith('incremental=') else a for a in command]
    environment=dict(env(),PTA_LOG='info',PTA_FLAGS=json.dumps(['--pta-type','ander','--entry-func','main',
        '--dump-call-graph',str(out/'graph.dot'),'--dump-dyn-calls',str(out/'dynamic.txt')]))
    result=run(command,out,600,environment,Path(invocation['cwd']))
    result.update(accepted_historical_measurement=False,analyzer_changed=False,
        provenance=provenance,environment={k:environment[k] for k in ('PTA_FLAGS','LD_LIBRARY_PATH','RUSTUP_HOME')})
    if result['status']!='completed':
        (HERE/'FINAL_COVERAGE_RESULTS.json').write_text(json.dumps(result,indent=2)+'\n')
        raise RuntimeError(result['status'])
    raw,full,_=parse(out,'ander')
    for name,data in (('normalized.json',raw),('graph.json',full)):
        (out/name).write_text(json.dumps(data,indent=2,sort_keys=True))
    scoped=derive(out,'final-coverage')
    previous=json.loads((WORK/'patched-scoped.json').read_text())
    names={f['identity']:f['name'] for f in raw['functions']}
    result['policies']={}
    for policy,g in scoped['policies'].items():
        prior=previous['policies'][policy]
        now_ids={f['identity'] for f in g['functions']}
        prior_ids={f['identity'] for f in prior['functions']}
        result['policies'][policy]={k:g[k] for k in ('vulnerability_depth','maximum_utility_depth',
            'normalized_vulnerability_depth','vulnerable_path_names','deepest_path_names','deepest_endpoint_count')}
        result['policies'][policy].update(owned_nodes=len(now_ids),projected_edges=len(g['scoped_edges']),
            mediated_edges=sum(e['dependency_mediated'] for e in g['scoped_edges']),
            added_implementation_functions=[names[k] for k in sorted(now_ids-prior_ids)],
            removed_implementation_identities=sorted(prior_ids-now_ids),
            coverage_exposed_implementation_functions=len(g['coverage_frontiers']))
        by_pair={(e['caller'],e['callee']):e for e in g['scoped_edges']}
        for field in ('vulnerable_path','deepest_path'):
            result['policies'][policy][field+'_witnesses']=[dict(
                caller=names[u],callee=names[v],
                full_route=[names[k] for k in by_pair[u,v]['witness_nodes']],
                full_edges=[raw['call_edges'][i] for i in by_pair[u,v]['witness_edge_indices']])
                for u,v in zip(g[field],g[field][1:])]
    primary=scoped['policies']['project_implementation']
    result['unresolved_callsites']=[]
    for index,s in enumerate(raw['unresolved_indirect_callsites']):
        exposed=[names[f['owner']] for f in primary['coverage_frontiers'] if index in f['unresolved_site_indices']]
        result['unresolved_callsites'].append(dict(index=index,caller=names[s['caller']],kind=s['kind'],
            callsite=s['callsite'],exposed_implementation_functions=exposed))
    result['body_unavailable']=[dict(name=f['name'],source=f['source']) for f in raw['functions'] if not f['body_available']]
    result['source_callback_audit']={
        'LazyLock':{
            'implementation_sources':['src/uucore/src/lib/lib.rs:320 (ARGV initializer closure)',
                                      'src/uucore/src/lib/lib.rs:322 (UTIL_NAME initializer closure)',
                                      'src/uucore/src/lib/lib.rs:335 (EXECUTION_PHRASE initializer closure)'],
            'matching_reachable_callbacks':[n for n in names.values() if n.startswith(('uucore::ARGV::','uucore::UTIL_NAME::','uucore::EXECUTION_PHRASE::'))],
            'route':'args_os/util_name/execution_phrase -> LazyLock deref/force -> OnceForce callback -> stored fn() initializer -> first-party initializer closure',
            'status':'additional included callbacks missing; no localized complete correction established'},
        'TLS':{
            'source':'src/uucore/src/lib/mods/locale.rs:109-110',
            'initializer':'const { OnceLock::new() }',
            'matching_reachable_callbacks':sorted({n.split('<')[0] for n in names.values() if n.startswith((
                'uucore::mods::locale::init_localization::{closure#1}',
                'uucore::mods::locale::setup_localization::{closure#1}',
                'uucore::mods::locale::get_message_internal::{closure#0}'))}),
            'status':'generic non-const TLS test fails, but this const initializer does not establish an additional first-party initialization function; existing locale with-callbacks are reached; TLS storage flow remains unvalidated'},
        'Display':{
            'source':'src/uu/chmod/src/chmod.rs:24-38 and show! sites at 286/299; uucore/src/lib/macros.rs:88-95',
            'route':'Chmoder::chmod -> show!(ChmodError) -> eprintln/_eprint -> formatting dispatch -> <ChmodError as Display>::fmt -> translate!/uucore::locale::get_message',
            'matching_reachable_callbacks':[n for n in names.values() if n.startswith('uu_chmod::') and n.split('<')[0].endswith('::fmt')],
            'status':'additional utility-owned derived Display method missing; printing/formatting body boundary prevents traversal'},
    }
    result['source_evidence_sha256']={str(p.relative_to(checkout)):sha(p) for p in [
        checkout/'src/uucore/src/lib/lib.rs',checkout/'src/uucore/src/lib/macros.rs',
        checkout/'src/uucore/src/lib/mods/locale.rs',checkout/'src/uu/chmod/src/chmod.rs']}
    result['full_graph']={'nodes':len(raw['functions']),'edges':len(raw['call_edges']),
        'unresolved_count':len(raw['unresolved_indirect_callsites']),
        'unavailable_bodies':len(result['body_unavailable']),
        'normalized_sha256':sha(out/'normalized.json'),
        'identical_to_previous_normalized_graph':sha(out/'normalized.json')==sha(WORK/'pilot/normalized.json'),
        'artifact_directory':str(out.relative_to(ROOT))}
    assert all(sha(checkout/p)==h for p,h in build['source_manifest_before'].items())
    assert all(sha(ROOT/p)==h for p,h in before.items())
    result['preservation']={'authenticated_source_files_checked':len(build['source_manifest_before']),
                            'changed_files':[],'previous_evidence_sha256':before}
    result['readiness']='blocked; all metrics remain diagnostic, especially Dmax and d/Dmax'
    (out/'result.json').write_text(json.dumps(result,indent=2))
    (HERE/'FINAL_COVERAGE_RESULTS.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'graph':result['full_graph'],'policies':{k:{x:v[x] for x in (
        'vulnerability_depth','maximum_utility_depth','normalized_vulnerability_depth','owned_nodes',
        'added_implementation_functions','removed_implementation_identities')} for k,v in result['policies'].items()}},indent=2),flush=True)


if __name__=='__main__': main()
