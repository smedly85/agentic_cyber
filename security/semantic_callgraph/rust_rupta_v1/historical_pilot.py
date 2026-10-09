"""One gated, provisional historical specimen. Never publishes accepted depths."""
import hashlib
import json
import os
import re
import signal
import subprocess
import time
from .probe import ROOT,limit
from .modern_trial import OUT,SYSROOT,TARGET,env
from .patched_adapter import parse

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    records=json.loads((OUT/'modern-validation-results.json').read_text())
    for repeat in (1,2):
        for mode in ('ander','cs'):
            rows=[r for r in records if r['repeat']==repeat and r['mode']==mode]
            assert len(rows)==38 and len({r['program'] for r in rows})==35
            assert all(r['status']=='completed' and r['evaluation']['required_expectations_passed'] for r in rows)
            assert sum(len([s for s in r['evaluation']['sites'] if s['expected'] and s['passed']]) for r in rows)==23
            if repeat==2: assert all(r['deterministic'] for r in rows)
    build=json.loads((OUT/'historical-build/result.json').read_text())
    assert build['status']=='built' and build['source_tree_unchanged']
    checkout=__import__('pathlib').Path(build['cwd'])
    mapping=build['selected_mapping']['vulnerable_functions'][0]
    source=checkout/mapping['source_file']
    assert sha(source)==mapping['source_sha256']
    assert mapping['function']=='Chmoder::chmod'
    declarations=list(re.finditer(r'(?m)^impl Chmoder\s*\{\s*\n\s*fn chmod\(',source.read_text()))
    assert len(declarations)==1, 'pilot mapping must be source-unique'
    method_start=source.read_text().index('fn chmod',declarations[0].start())
    method_line=source.read_text()[:method_start].count('\n')+1
    out=OUT/'historical-pilot'
    out.mkdir(exist_ok=False)
    wrapper=ROOT/'security/semantic_callgraph/rust_rupta_v1/pilot_wrapper.py'
    wrapper.chmod(0o755)
    environment=env()
    for key in ('RUSTFLAGS','RUSTC_WORKSPACE_WRAPPER','PTA_BUILD_STD'): environment.pop(key,None)
    environment.update(RUSTC=str(SYSROOT/'bin/rustc'),RUSTDOC=str(SYSROOT/'bin/rustdoc'),
        CARGO_HOME=build['environment']['CARGO_HOME'],CARGO_TARGET_DIR=str(out/'target'),
        CARGO_ENCODED_RUSTFLAGS=build['environment']['CARGO_ENCODED_RUSTFLAGS'],
        RUSTC_WRAPPER=str(wrapper),RUPTA_PILOT_OUTPUT=str(out),RUPTA_PILOT_PTA=str(TARGET/'debug/pta'),
        PTA_FLAGS=json.dumps(['--pta-type','ander','--entry-func','main','--dump-call-graph',str(out/'graph.dot'),
                              '--dump-dyn-calls',str(out/'dynamic.txt')]),PTA_LOG='info')
    command=[str(SYSROOT/'bin/cargo'),'check','--frozen','--manifest-path',str(checkout/'Cargo.toml'),
             '-p','uu_chmod','--bin','chmod','--target=x86_64-unknown-linux-gnu','-j','2','-v']
    record={'status':'running','accepted_historical_measurement':False,'argv':command,'cwd':str(checkout),
            'environment':{k:environment[k] for k in ('RUSTC','RUSTDOC','RUSTC_WRAPPER','CARGO_HOME','CARGO_TARGET_DIR','CARGO_ENCODED_RUSTFLAGS','PTA_FLAGS','LD_LIBRARY_PATH','RUSTUP_HOME','RUPTA_PILOT_OUTPUT','RUPTA_PILOT_PTA','PTA_LOG')},
            'cve':'CVE-2026-35338','frozen_mapping':mapping,'mapping_declaration_line':method_line,
            'timeout_seconds':600,'address_space_limit_bytes':16*1024**3,
            'vulnerability_depth':None,'maximum_program_depth':None}
    (out/'launch.json').write_text(json.dumps(record,indent=2))
    start=time.monotonic()
    with (out/'stdout.log').open('w') as stdout,(out/'stderr.log').open('w') as stderr:
        child=subprocess.Popen(command,cwd=checkout,env=environment,stdout=stdout,stderr=stderr,start_new_session=True,preexec_fn=limit)
        try: code=child.wait(timeout=600); status='completed' if code==0 else 'build_or_analysis_failure'
        except subprocess.TimeoutExpired: os.killpg(child.pid,signal.SIGKILL); code=child.wait(); status='timeout'
    record.update(returncode=code,status=status,wall_seconds=time.monotonic()-start)
    changed=[name for name,digest in build['source_manifest_before'].items() if sha(checkout/name)!=digest]
    record['source_tree_changed_files']=changed
    if changed: record['status']='source_integrity_failure'
    if record['status']=='completed':
        assert (out/'analysis-command.json').is_file(), 'no actual analyzer invocation'
        assert json.loads((out/'analysis-exit.json').read_text())['returncode']==0
        raw,graph,_=parse(out,'ander')
        nodes={f['identity']:f for f in graph['functions']}
        entry=nodes[raw['entry']]
        assert entry['name']=='chmod::main', 'wrong entry anchor'
        matches=[f for f in graph['functions'] if f['name'].startswith('uu_chmod::') and f['name'].endswith('::chmod')
                 and (f['source'] or {}).get('file','').endswith(mapping['source_file']) and (f['source'] or {}).get('line')==method_line]
        record['mapped_instances']=matches
        reached=[f for f in matches if f['reachable_from_entry']]
        if reached:
            best=min(reached,key=lambda f:(f['raw_call_depth'],f['identity']))
            record['vulnerability_depth']=best['raw_call_depth']
            record['call_path']=[{'identity':i,'name':nodes[i]['name'],'source':nodes[i]['source']} for i in best['shortest_call_path']['function_identities']]
        else: record['mapping_status']='not_found_or_unreachable_in_completed_graph'
        record['maximum_program_depth']=max(f['raw_call_depth'] for f in graph['functions'] if f['reachable_from_entry'])
        record['coverage']={'nodes':len(raw['functions']),'edges':len(raw['call_edges']),
            'reachable_nodes':sum(f['reachable_from_entry'] for f in graph['functions']),
            'body_unavailable_nodes':sum(not f['body_available'] for f in raw['functions']),
            'special_model_nodes':sum(f['special_model'] for f in raw['functions']),
            'external_boundary_edges':len(raw['external_calls']),
            'recognized_unresolved_callsites':len(raw['unresolved_indirect_callsites']),
            'unresolved_inventory_complete':False}
        record['entry']=entry
        record['depth_scope']='finite shortest paths in the exported instantiated function graph, including library/shim/drop-glue/boundary nodes; provisional, not accepted historical measurements'
        for name,value in (('normalized.json',raw),('graph.json',graph)):
            (out/name).write_text(json.dumps(value,indent=2,sort_keys=True))
    (out/'result.json').write_text(json.dumps(record,indent=2))
    print(record['status'],record['returncode'],'seconds',round(record['wall_seconds'],2),flush=True)
    if record['status']!='completed': print((out/'stderr.log').read_text()[-6000:],flush=True)

if __name__=='__main__': main()
