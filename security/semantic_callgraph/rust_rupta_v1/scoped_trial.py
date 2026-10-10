"""Bounded follow-up mechanisms, isolated from all previous analyzers/results."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from .modern_trial import OUT, SYSROOT, TARGET, env
from .probe import ROOT, limit
from .patched_adapter import parse

HERE = Path(__file__).resolve().parent
WORK = OUT/'scope-trial'
SOURCE = WORK/'source'


def run(argv, out, timeout=180, environment=None, cwd=ROOT):
    out.mkdir(parents=True, exist_ok=False)
    command = ['/usr/bin/time', '-v', '-o', str(out/'resources.txt'), *map(str, argv)]
    started = time.monotonic()
    with (out/'stdout.txt').open('w') as stdout, (out/'stderr.txt').open('w') as stderr:
        child = subprocess.Popen(command, cwd=cwd, env=environment or dict(env(), PTA_LOG='info'),
                                 stdout=stdout, stderr=stderr, start_new_session=True, preexec_fn=limit)
        try:
            code = child.wait(timeout=timeout)
            status = 'completed' if code==0 else 'failure'
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL); code=child.wait(); status='timeout'
    record = dict(argv=command, cwd=str(cwd), status=status, returncode=code, wall_seconds=time.monotonic()-started)
    (out/'command.json').write_text(json.dumps(record, indent=2))
    return record


def mechanisms(version):
    pta = TARGET/'debug/pta' if version=='baseline' else WORK/'target/debug/pta'
    records=[]
    for name in ('map_err','lazy_tls','formatting','once'):
        for mode in ('ander','cs'):
            out=WORK/version/name/mode
            fixture=HERE/'fixtures/review'/f'{name}.rs'
            result=run([pta,fixture,'--pta-type',mode,'--entry-func','main',
                        '--dump-call-graph',out/'graph.dot','--dump-dyn-calls',out/'dynamic.txt',
                        '--dump-mir',out/'mir.txt','--','--crate-name','review_'+name,'--crate-type','bin',
                        '--edition','2024','--sysroot',SYSROOT,'--emit=metadata','--out-dir',out,
                        '-Copt-level=0','-Cpanic=unwind'],out)
            result.update(fixture=name,mode=mode,source_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest())
            if result['status']=='completed':
                raw, graph, _=parse(out,mode)
                (out/'normalized.json').write_text(json.dumps(raw,indent=2,sort_keys=True))
                (out/'graph.json').write_text(json.dumps(graph,indent=2,sort_keys=True))
                local=[f for f in graph['functions'] if f['name'].startswith('review_'+name+'::')]
                result['local_functions']=[dict(name=f['name'],depth=f['raw_call_depth']) for f in local]
                lookup={f['identity']:f['name'] for f in graph['functions']}
                result['edges_into_local']=[dict(caller=lookup[e['caller']],callee=lookup[e['callee']],callsite=e['callsite'])
                    for e in raw['call_edges'] if lookup[e['callee']].startswith('review_'+name+'::')]
            records.append(result)
            print(name,mode,result['status'],result.get('local_functions'),flush=True)
    (WORK/f'{version}-mechanisms.json').write_text(json.dumps(records,indent=2))


def prepare():
    import shutil
    SOURCE.mkdir(exist_ok=False)
    for name in ('Cargo.toml','Cargo.lock','rust-toolchain.toml','build.rs'):
        src=OUT/'modern-patched'/name
        if src.exists(): shutil.copy2(src,SOURCE/name)
    for name in ('src',): shutil.copytree(OUT/'modern-patched'/name,SOURCE/name)
    p=SOURCE/'src/builder/special_function_handler.rs'
    s=p.read_text()
    s=s.replace('        return once_callback_summary_required(acx.tcx, def_id);','        return false; // Callback model belongs to the Once function PAG.')
    s=s.replace('        set.insert(KnownNames::StdResultMapErr);','        // map_err uses its available MIR, including the Err callback.')
    old='''        KnownNames::StdResultMapErr => {
            handle_result_map_err(fpb, gen_args, args, destination);
            return true;
        }'''
    assert s.count(old)==1
    s=s.replace(old,'''        KnownNames::StdResultMapErr => { return false; }''')
    old='''            if !once_callback_summary_required(fpb.acx.tcx, *callee_def_id) {
                return false;
            }
            handle_once_callback(fpb, *callee_def_id, *gen_args, args, location);
            return true;'''
    assert s.count(old)==1
    s=s.replace(old,'''            // Traverse the public wrapper; its own PAG adds the callback model.
            return false;''')
    s=s.replace('fn handle_once_callback<','pub(crate) fn handle_once_callback<')
    p.write_text(s)
    p=SOURCE/'src/builder/fpag_builder.rs'; s=p.read_text()
    old='''        self.visit_body();

        // Add extra edges'''
    new='''        self.visit_body();

        // Attribute the existing unavailable-backend callback model to Once,
        // not to the application callsite. Keep ordinary wrapper/backend edges.
        let known = self.acx.get_known_name_for(self.def_id());
        if matches!(known, crate::mir::known_names::KnownNames::StdSyncOnceCallOnce
            | crate::mir::known_names::KnownNames::StdSyncOnceCallOnceForce)
            && special_function_handler::once_callback_summary_required(self.tcx(), self.def_id()) {
            let args = vec![Path::new_parameter(self.func_id, 1), Path::new_parameter(self.func_id, 2)];
            let location = mir::Location { block: mir::START_BLOCK,
                statement_index: self.mir.basic_blocks[mir::START_BLOCK].statements.len() };
            let gen_args = self.substs_specializer.specialize_generic_args(
                ty::GenericArgs::identity_for_item(self.tcx(), self.def_id()));
            special_function_handler::handle_once_callback(self, self.def_id(),
                gen_args, &args, location);
        }

        // Add extra edges'''
    assert s.count(old)==1
    p.write_text(s.replace(old,new))
    # Explicitly identify synthetic summary sites, which have no MIR statement.
    p=SOURCE/'src/util/depth_export.rs'; s=p.read_text()
    s=s.replace('"def_id":format!("{:?}",fr.def_id),', '''"def_id":format!("{:?}",fr.def_id),
                "crate":acx.tcx.crate_name(fr.def_id.krate).as_str(),
                "def_kind":format!("{:?}",acx.tcx.def_kind(fr.def_id)),''')
    old='''"source":span.map(|s|source(acx,s)),"targets":targets}));'''
    new='''"source":span.map(|s|source(acx,s)),"targets":targets,
                "summary_site":acx.function_mir(id).map(|b|
                    base.location.statement_index > b.basic_blocks[base.location.block].statements.len()).unwrap_or(false)}));'''
    assert s.count(old)==1
    p.write_text(s.replace(old,new))


def build():
    environment=dict(env(), CARGO_TARGET_DIR=str(WORK/'target'))
    command=[OUT.parents[1]/'cargo/bin/cargo','+nightly-2026-08-21','build','--locked','--offline','-j','4']
    # Build from the isolated source, with the existing pinned dependency cache.
    if (WORK/'build.log').exists():
        index=len(list(WORK.glob('build-attempt-*.log')))+1
        (WORK/f'build-attempt-{index}.log').write_bytes((WORK/'build.log').read_bytes())
    with (WORK/'build.log').open('w') as log:
        result=subprocess.run(list(map(str,command)),cwd=SOURCE,env=environment,stdout=log,stderr=subprocess.STDOUT,timeout=600)
    (WORK/'build-command.json').write_text(json.dumps(dict(argv=list(map(str,command)),cwd=str(SOURCE),returncode=result.returncode),indent=2))
    print((WORK/'build.log').read_text()[-3000:],flush=True)
    return result.returncode


def regression():
    from .validate import inventory
    from .patched_adapter import adjudicate
    programs={p['id']:p for p in inventory()}
    records=[]
    prior=json.loads((OUT/'modern-validation-results.json').read_text())
    for row in [r for r in prior if r['repeat']==1]:
        old=OUT/'modern-validation/run-1'/row['program']/row['mode']/row['entry']
        out=WORK/'regression'/row['program']/row['mode']/row['entry']
        command=[str(WORK/'target/debug/pta')]+[v.replace(str(old),str(out)) for v in row['argv'][5:]]
        # Sidecar validation does not use the optional enormous MIR text dump.
        if '--dump-mir' in command:
            i=command.index('--dump-mir'); del command[i:i+2]
        result=run(command,out)
        result.update(program=row['program'],mode=row['mode'],entry=row['entry'])
        if result['status']=='completed':
            result['evaluation']=adjudicate(programs[row['program']],out,row['mode'],row['entry'])
        records.append(result)
        (WORK/'regression-results.json').write_text(json.dumps(records,indent=2))
        passed=result.get('evaluation',{}).get('required_expectations_passed',False)
        print(row['program'],row['mode'],row['entry'],passed,flush=True)
        if not passed: return 1
    return 0


def pilot():
    baseline=OUT/'historical-pilot'
    old=json.loads((baseline/'result.json').read_text())
    source=Path(old['cwd'])/old['frozen_mapping']['source_file']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==old['frozen_mapping']['source_sha256']
    records=json.loads((WORK/'regression-results.json').read_text())
    assert len(records)==76 and all(r['evaluation']['required_expectations_passed'] for r in records)
    out=WORK/'pilot'
    invocation=json.loads((baseline/'analysis-command.json').read_text())
    command=[str(WORK/'target/debug/pta'),*invocation['argv'][5:]]
    command[command.index('--out-dir')+1]=str(out)
    # New replays must also isolate rustc's incremental cache. The first saved
    # diagnostic replay inherited the prior pilot cache; its command records this.
    command=[('incremental='+str(out/'incremental')) if v.startswith('incremental=') else v for v in command]
    environment=dict(env(),PTA_LOG='info',PTA_FLAGS=json.dumps(['--pta-type','ander','--entry-func','main',
        '--dump-call-graph',str(out/'graph.dot'),'--dump-dyn-calls',str(out/'dynamic.txt')]))
    result=run(command,out,600,environment,Path(invocation['cwd']))
    result.update(accepted_historical_measurement=False,purpose='diagnostic scoped recomputation; new mechanism gates remain failed',
                  frozen_mapping=old['frozen_mapping'],environment={k:environment[k] for k in ('PTA_FLAGS','LD_LIBRARY_PATH','RUSTUP_HOME')})
    if result['status']=='completed':
        raw,graph,_=parse(out,'ander')
        (out/'normalized.json').write_text(json.dumps(raw,indent=2,sort_keys=True))
        (out/'graph.json').write_text(json.dumps(graph,indent=2,sort_keys=True))
    assert hashlib.sha256(source.read_bytes()).hexdigest()==old['frozen_mapping']['source_sha256']
    (out/'result.json').write_text(json.dumps(result,indent=2))
    print(result['status'],result['wall_seconds'],flush=True)


def assess():
    results=[]
    expected={'map_err':['callback_target','returned_target'],
              'lazy_tls':['lazy_init','lazy_target','tls_init','tls_target'],
              'formatting':['display_target'], 'once':['target_a','target_b']}
    for version in ('baseline','patched'):
        for row in json.loads((WORK/f'{version}-mechanisms.json').read_text()):
            name=row['fixture']; mode=row['mode']; out=WORK/version/name/mode
            raw=json.loads((out/'normalized.json').read_text())
            names={f['identity']:f['name'] for f in raw['functions']}
            required=['review_'+name+'::'+s for s in expected[name]]
            missing=sorted(set(required)-set(names.values()))
            checks={'required_functions_reachable':not missing}
            detail={}
            if name=='map_err':
                targets={names[e['callee']] for e in raw['call_edges'] if names[e['caller']]=='review_map_err::driver' and e['edge_type']=='indirect_resolved'}
                checks['returned_pointer_exact']=targets=={'review_map_err::returned_target'}
                detail['returned_pointer_targets']=sorted(targets)
            if name=='once':
                for suffix in ('a','b'):
                    closures={k for k,n in names.items() if n.startswith('review_once::driver_'+suffix+'::{closure#0}')}
                    incoming=[e for e in raw['call_edges'] if e['callee'] in closures]
                    checks['callback_'+suffix+'_attributed_to_Once']=bool(incoming) and all(names[e['caller']].startswith('std::sync::once::') for e in incoming)
                    # Distinct generic Once instances must not exchange the callbacks.
                    checks['callback_'+suffix+'_correct_instance']=bool(incoming) and all('review_once' in names[e['caller']] and 'driver_'+suffix in names[e['caller']] for e in incoming)
                    detail['callback_'+suffix+'_callers']=sorted({names[e['caller']] for e in incoming})
            results.append(dict(version=version,fixture=name,mode=mode,checks=checks,missing=missing,details=detail,passed=all(checks.values())))
    (HERE/'scoped_mechanism_results.json').write_text(json.dumps(results,indent=2)+'\n')
    for r in results: print(r['version'],r['fixture'],r['mode'],r['passed'],r['missing'],r['checks'],flush=True)


def evidence():
    import difflib
    diff=''
    for p in sorted((SOURCE/'src').rglob('*.rs')):
        relative=p.relative_to(SOURCE).as_posix()
        old=(OUT/'modern-patched'/relative).read_text(); new=p.read_text()
        if old!=new:
            diff+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+relative,tofile='b/'+relative))
    patch=HERE/'scoped_callback_overlay.patch'; patch.write_text(diff)
    files=[patch,WORK/'target/debug/pta',SYSROOT/'bin/rustc',SOURCE/'Cargo.lock']
    record={'base_fork_commit':'66e29895748bd7a289b448a875d198711f1382dd',
            'base_overlay':'modern_overlay.patch','additional_overlay':patch.name,'compiler':'nightly-2026-08-21',
            'sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            'lock_unchanged':(SOURCE/'Cargo.lock').read_bytes()==(OUT/'modern-patched/Cargo.lock').read_bytes()}
    (HERE/'scoped_provenance.json').write_text(json.dumps(record,indent=2)+'\n')


def inspect_mir():
    fixture=HERE/'fixtures/review/lazy_tls.rs'; out=WORK/'initializer-mir'
    result=run([SYSROOT/'bin/rustc',fixture,'--crate-name','review_lazy_tls','--edition','2024',
                '--emit=mir','--out-dir',out,'-Copt-level=0'],out)
    print(result,flush=True)


def repeat():
    comparisons=[]
    for row in json.loads((WORK/'patched-mechanisms.json').read_text()):
        old=WORK/'patched'/row['fixture']/row['mode']; out=WORK/'repeat'/row['fixture']/row['mode']
        command=[v.replace(str(old),str(out)) for v in row['argv'][4:]]
        i=command.index('--dump-mir'); del command[i:i+2]
        record=run(command,out)
        if record['status']=='completed':
            raw,graph,_=parse(out,row['mode'])
            for name,value in (('normalized.json',raw),('graph.json',graph)):
                (out/name).write_text(json.dumps(value,indent=2,sort_keys=True))
            record['identical']=all((old/n).read_bytes()==(out/n).read_bytes() for n in ('normalized.json','graph.json'))
        record.update(fixture=row['fixture'],mode=row['mode'])
        comparisons.append(record)
        print(row['fixture'],row['mode'],record.get('identical'),flush=True)
    (WORK/'repeat-results.json').write_text(json.dumps(comparisons,indent=2))


if __name__=='__main__':
    if sys.argv[1]=='mechanisms': mechanisms(sys.argv[2])
    elif sys.argv[1]=='prepare': prepare()
    elif sys.argv[1]=='build': sys.exit(build())
    elif sys.argv[1]=='regression': sys.exit(regression())
    elif sys.argv[1]=='pilot': pilot()
    elif sys.argv[1]=='assess': assess()
    elif sys.argv[1]=='evidence': evidence()
    elif sys.argv[1]=='inspect-mir': inspect_mir()
    elif sys.argv[1]=='repeat': repeat()
