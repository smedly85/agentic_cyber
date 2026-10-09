"""Isolated, bounded Drop integration trial; never overwrites baseline outputs."""
from pathlib import Path
import hashlib
import difflib
import io
import json
import os
import subprocess
import sys
import tarfile

from .probe import ROOT, BASE, SYSROOT, environment, run

TRIAL = BASE / 'drop-trial'
SOURCE = TRIAL / 'upstream'
SHA = 'b19f187e9cbe37b5afb1103d88b663253e1f0a03'

def setup():
    TRIAL.mkdir(exist_ok=False)
    paths = subprocess.check_output(['git', 'ls-files', 'security', 'tests'], text=True).splitlines()
    paths += [str(p.relative_to(ROOT)) for p in (ROOT/'security/semantic_callgraph/rust_rupta_v1').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name != 'patched_trial.py']
    snapshot = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths if (ROOT/p).is_file()}
    (TRIAL/'preservation-before.json').write_text(json.dumps(snapshot, indent=2))
    archive = subprocess.check_output(['git', '-C', str(BASE/'upstream'), 'archive', SHA])
    SOURCE.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(SOURCE, filter='data')
    # Record whether baseline checkout differences are only CRLF conversion.
    diff = subprocess.check_output(['git', '-C', str(BASE/'upstream'), 'diff', '--ignore-space-at-eol', SHA])
    (TRIAL/'baseline-non-eol.diff').write_bytes(diff)

def build():
    env = environment()
    env['CARGO_TARGET_DIR'] = str(TRIAL/'target')
    cmd = [str(BASE/'cargo/bin/cargo'), '+nightly-2024-02-03', 'build', '--locked', '--offline', '-j', '4']
    (TRIAL/'build-command.json').write_text(json.dumps({'argv':cmd,'cwd':str(SOURCE),'environment':{k:env[k] for k in ('CARGO_TARGET_DIR','RUSTUP_HOME','CARGO_HOME')}}, indent=2))
    if (TRIAL/'build.log').exists():
        index=len(list(TRIAL.glob('build-attempt-*.log')))+1
        (TRIAL/f'build-attempt-{index}.log').write_bytes((TRIAL/'build.log').read_bytes())
    with (TRIAL/'build.log').open('w') as f:
        result = subprocess.run(cmd, cwd=SOURCE, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=1200)
    print('build exit', result.returncode, flush=True)
    print((TRIAL/'build.log').read_text()[-7000:])
    return result.returncode

def patch():
    def replace(file, old, new):
        p = SOURCE/file
        text = p.read_text()
        assert text.count(old) == 1, (file, old)
        p.write_text(text.replace(old, new))
    replace('src/mir/analysis_context.rs', '    pub fn get_function_reference(', '''    /// Select compiler-generated drop glue instead of the generic intrinsic body.
    pub fn function_mir(&self, func_id: FuncId) -> Option<&'tcx rustc_middle::mir::Body<'tcx>> {
        let f = self.get_function_reference(func_id);
        if self.tcx.lang_items().drop_in_place_fn() == Some(f.def_id) {
            let dropped_ty = match f.generic_args.first() {
                Some(GenericArgE::Type(t)) => *t,
                _ => panic!("drop_in_place without type argument"),
            };
            let instance = rustc_middle::ty::Instance::resolve_drop_in_place(self.tcx, dropped_ty);
            return Some(self.tcx.instance_mir(instance.def));
        }
        self.tcx.is_mir_available(f.def_id).then(|| self.tcx.optimized_mir(f.def_id))
    }

    pub fn get_function_reference(''')
    replace('src/graph/pag.rs', '''        if !acx.tcx.is_mir_available(def_id) {
            warn!("Unavailable mir for def_id: {:?}", def_id);
            return false;
        }''', '''        let Some(mir) = acx.function_mir(func_id) else {
            warn!("Unavailable mir for def_id: {:?}", def_id);
            return false;
        };''')
    replace('src/graph/pag.rs', '''        if let Some(promoted_funcs) = self.promote_constants(acx, def_id, gen_args) {
            self.promoted_funcs_map.insert(func_id, promoted_funcs);
        }''', '''        if acx.tcx.lang_items().drop_in_place_fn() != Some(def_id) {
            if let Some(promoted_funcs) = self.promote_constants(acx, def_id, gen_args) {
                self.promoted_funcs_map.insert(func_id, promoted_funcs);
            }
        }''')
    replace('src/graph/pag.rs', '        let mir = acx.tcx.optimized_mir(def_id);\n', '')
    replace('src/util/type_util.rs', '''    let def_id = acx.get_function_reference(func_id).def_id;
    let mir = acx.tcx.optimized_mir(def_id);''', '''    let mir = acx.function_mir(func_id).expect("local declaration without MIR");''')
    replace('src/builder/fpag_builder.rs', '            mir::TerminatorKind::InlineAsm {', '''            mir::TerminatorKind::Drop { place, .. } => {
                let (_, dropped_ty) = self.get_path_and_type_for_place(place);
                let instance = ty::Instance::resolve_drop_in_place(self.tcx(), dropped_ty);
                // Empty glue has no destructor/callback to traverse.
                if !matches!(instance.def, ty::InstanceDef::DropGlue(_, None)) {
                    let callee = self.acx.get_func_id(instance.def.def_id(), instance.args);
                    let pointer = self.create_aux_local(Ty::new_mut_ptr(self.tcx(), dropped_ty));
                    self.visit_ref_or_address_of(pointer.clone(), place);
                    let destination = self.create_aux_local(self.tcx().types.unit);
                    let site = self.new_callsite(self.func_id, location, vec![pointer], destination);
                    self.fpag.add_static_dispatch_callsite(site, callee);
                }
            }
            mir::TerminatorKind::InlineAsm {''')
    # Keep generated glue MIR visible as diagnostics even before structured export.
    replace('src/util/results_dumper.rs', '''        if !acx.tcx.is_mir_available(def_id) {
            mir_writer.write_all''', '''        if acx.tcx.lang_items().drop_in_place_fn() == Some(def_id) {
            writeln!(mir_writer, "Generated drop glue: {:#?}", acx.function_mir(func_id).unwrap()).unwrap();
        } else if !acx.tcx.is_mir_available(def_id) {
            mir_writer.write_all''')

def scopeguard():
    for mode in ('ander', 'cs'):
        original = BASE/'validation/run-1/expanded/crates_io'/mode/'main/command.json'
        command = json.loads(original.read_text())['argv'][4:]
        old = str(original.parent)
        out = TRIAL/'scopeguard'/mode
        command = [str(TRIAL/'target/debug/pta') if i == 0 else x.replace(old, str(out)) for i,x in enumerate(command)]
        result = run(command, out)
        print(mode, result['status'], flush=True)

def evidence():
    files = ['src/mir/analysis_context.rs','src/graph/pag.rs','src/util/type_util.rs',
             'src/builder/fpag_builder.rs','src/util/results_dumper.rs',
             'src/util/mod.rs','src/pta/context_sensitive.rs','src/util/depth_export.rs',
             'src/builder/call_graph_builder.rs']
    diff = ''
    for name in files:
        if name == 'src/util/depth_export.rs': old = ''
        else: old = subprocess.check_output(['git','-C',str(BASE/'upstream'),'show',SHA+':'+name],text=True)
        new = (SOURCE/name).read_text()
        diff += ''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+name if old else '/dev/null',tofile='b/'+name))
    dest = ROOT/'security/semantic_callgraph/rust_rupta_v1/drop_trial.patch'
    dest.write_text(diff)
    files = [dest, TRIAL/'target/debug/pta', SYSROOT/'bin/rustc', SOURCE/'Cargo.lock']
    (TRIAL/'hashes.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()},indent=2))

def reporting():
    (SOURCE/'src/util/depth_export.rs').write_text((ROOT/'security/semantic_callgraph/rust_rupta_v1/depth_export.rs').read_text())
    p = SOURCE/'src/util/mod.rs'
    p.write_text(p.read_text()+'\npub mod depth_export;\n')
    p = SOURCE/'src/util/results_dumper.rs'
    s = p.read_text()
    s = s.replace('    // dump points-to results','    crate::util::depth_export::dump(acx, call_graph);\n    // dump points-to results',1)
    p.write_text(s)
    p = SOURCE/'src/pta/context_sensitive.rs'
    s = p.read_text()
    needle = '        // dump pta statistics'
    assert s.count(needle)==1
    s = s.replace(needle, '''        if let Some(path) = &self.acx.analysis_options.call_graph_output {
            let mut contexts = std::collections::BTreeMap::new();
            for f in self.call_graph.reach_funcs_iter() {
                contexts.insert(format!("{:?}",f.cid),
                    format!("{:?}",self.ctx_strategy.get_context_by_id(f.cid)));
            }
            std::fs::write(format!("{}.contexts.json",path),
                serde_json::to_vec_pretty(&contexts).unwrap()).unwrap();
        }
''' + needle)
    p.write_text(s)

def validate():
    from .validate import inventory
    from .patched_adapter import adjudicate
    programs=inventory()
    programs.sort(key=lambda p:(0 if p['id']=='expanded/crates_io' else 1 if p['id']=='supplement' else 2 if p['id']=='expanded/box_trait' else 3,p['id']))
    results=[]
    for repeat in (1,2):
        for p in programs:
            failed=False
            entries=sorted((BASE/'validation/run-1'/p['id']/'ander').glob('*/command.json'))
            for mode in ('ander','cs'):
                for entry_cmd in entries:
                    entry=entry_cmd.parent.name
                    original=BASE/'validation/run-1'/p['id']/mode/entry/'command.json'
                    command=json.loads(original.read_text())['argv'][4:]
                    out=TRIAL/'validation-v2'/f'run-{repeat}'/p['id']/mode/entry
                    command=[str(TRIAL/'target/debug/pta') if i==0 else x.replace(str(original.parent),str(out)) for i,x in enumerate(command)]
                    run_result=run(command,out)
                    record={'program':p['id'],'mode':mode,'entry':entry,'repeat':repeat,**run_result}
                    if run_result['status']=='completed':
                        try:
                            result=adjudicate(p,out,mode,entry)
                            record['evaluation']=result
                            failed |= not result['required_expectations_passed']
                        except Exception as exc:
                            record['adapter_failure']=repr(exc); failed=True
                    else: failed=True
                    if repeat==2 and not failed:
                        first=TRIAL/'validation-v2/run-1'/p['id']/mode/entry
                        record['deterministic']=all((first/n).read_bytes()==(out/n).read_bytes() for n in ('normalized.json','context.graph.json'))
                        failed |= not record['deterministic']
                    results.append(record)
                    print(repeat,p['id'],mode,entry,record.get('adapter_failure') or record.get('evaluation',{}).get('failures') or run_result['status'],flush=True)
                    (TRIAL/'validation-v2-results.json').write_text(json.dumps(results,indent=2))
            if failed:
                print('STOP at failed required gate:',p['id'],flush=True)
                return 1
    return 0

def dynamic_drop():
    evidence()
    (TRIAL/'initial-static-drop.patch').write_bytes((ROOT/'security/semantic_callgraph/rust_rupta_v1/drop_trial.patch').read_bytes())
    (TRIAL/'initial-static-drop-hashes.json').write_bytes((TRIAL/'hashes.json').read_bytes())
    p=SOURCE/'src/builder/fpag_builder.rs'
    s=p.read_text()
    old='''                    let site = self.new_callsite(self.func_id, location, vec![pointer], destination);
                    self.fpag.add_static_dispatch_callsite(site, callee);'''
    new='''                    let site = self.new_callsite(self.func_id, location, vec![pointer.clone()], destination);
                    if matches!(dropped_ty.kind(), TyKind::Dynamic(..)) {
                        // The concrete pointee selects the vtable's drop glue.
                        // Reuse existing dynamic-receiver propagation, not a
                        // recursive static edge to drop_in_place<dyn Trait>.
                        self.acx.add_dyn_callsite(site.clone().into(), instance.def.def_id(), instance.args);
                        self.fpag.add_dynamic_dispatch_callsite(pointer, site);
                    } else {
                        self.fpag.add_static_dispatch_callsite(site, callee);
                    }'''
    assert s.count(old)==1
    p.write_text(s.replace(old,new))

    p=SOURCE/'src/builder/call_graph_builder.rs'
    s=p.read_text()
    old='''    if !util::is_trait_method(tcx, def_id) {
        return None;
    }'''
    new='''    // Dynamic Drop is selected by the pointee's concrete type, using the
    // compiler's drop-glue resolver. The existing propagator substitutes Self.
    if tcx.lang_items().drop_in_place_fn() == Some(def_id) {
        let dropped_ty = gen_args.types().next()?;
        if matches!(dropped_ty.kind(), TyKind::Dynamic(..)) { return None; }
        let instance = rustc_middle::ty::Instance::resolve_drop_in_place(tcx, dropped_ty);
        return Some((instance.def.def_id(), instance.args));
    }
    if !util::is_trait_method(tcx, def_id) {
        return None;
    }'''
    assert s.count(old)==1
    p.write_text(s.replace(old,new))

def preservation():
    from concurrent.futures import ThreadPoolExecutor
    before=json.loads((TRIAL/'preservation-before.json').read_text())
    def changed(item):
        path,digest=item
        p=ROOT/path
        return path if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest else None
    with ThreadPoolExecutor(max_workers=16) as pool:
        changes=[p for p in pool.map(changed,before.items()) if p]
    result={'files_checked':len(before),'changed_or_missing':changes,'passed':not changes}
    (TRIAL/'preservation-after.json').write_text(json.dumps(result,indent=2))
    print(result,flush=True)

def summarize():
    import re
    records=json.loads((TRIAL/'validation-v2-results.json').read_text())
    summary={}
    for mode in ('ander','cs'):
        first=[r for r in records if r['mode']==mode and r['repeat']==1]
        second=[r for r in records if r['mode']==mode and r['repeat']==2]
        programs={r['program'] for r in first}
        passed={p for p in programs if all(r['status']=='completed' and r.get('evaluation',{}).get('required_expectations_passed') for r in first if r['program']==p)}
        sites=[s for r in first for s in r.get('evaluation',{}).get('sites',[]) if s['expected']]
        summary[mode]={'programs_passed':len(passed),'programs_total':len(programs),
            'resolved_designated_sites':len(sites),'exact_designated_sites':sum(s['passed'] for s in sites),
            'repeat_analyses':len(second),'deterministic':len(first)==len(second) and all(r.get('deterministic') for r in second)}
        assert len(programs)==35 and len(passed)==35 and len(sites)==23 and all(s['passed'] for s in sites)
        assert summary[mode]['deterministic']
    for r in records:
        out=TRIAL/'validation-v2'/f"run-{r['repeat']}"/r['program']/r['mode']/r['entry']
        rss=re.search(r'Maximum resident set size \(kbytes\): (\d+)',(out/'resources.txt').read_text())
        r['peak_rss_kib']=int(rss[1]) if rss else None
        g=json.loads((out/'context.graph.json').read_text())
        r['context_maximum_finite_shortest_path_depth']=max(f['raw_call_depth'] for f in g['functions'] if f['reachable_from_entry'])
        r['artifact_directory']=str(out.relative_to(ROOT))
    evidence()
    result={'upstream_commit':SHA,'toolchain':'nightly-2024-02-03','instrument':'separate Drop/export patch, revision 2',
            'validation_gate':'passed','historical_measurement_gate':'blocked_pending_compiler_compatibility',
            'summary':summary,'records':records,'hashes':json.loads((TRIAL/'hashes.json').read_text()),
            'preservation':json.loads((TRIAL/'preservation-after.json').read_text()),
            'superseded_trial':'validation/ is rejected: static dyn-Drop self-loop; repeat interrupted; use validation-v2/ only'}
    (ROOT/'security/semantic_callgraph/rust_rupta_v1/patched_validation_results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__ == '__main__':
    if sys.argv[1] == 'setup': setup()
    elif sys.argv[1] == 'patch': patch()
    elif sys.argv[1] == 'build': sys.exit(build())
    elif sys.argv[1] == 'scopeguard': scopeguard()
    elif sys.argv[1] == 'evidence': evidence()
    elif sys.argv[1] == 'reporting': reporting()
    elif sys.argv[1] == 'validate': sys.exit(validate())
    elif sys.argv[1] == 'dynamic-drop': dynamic_drop()
    elif sys.argv[1] == 'preservation': preservation()
    elif sys.argv[1] == 'summarize': summarize()
