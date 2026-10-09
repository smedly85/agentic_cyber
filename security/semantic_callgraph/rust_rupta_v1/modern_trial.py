"""Bounded build/compatibility check of the existing rust-2026 RUPTA fork."""
from pathlib import Path
import json
import os
import subprocess
import sys
from .probe import ROOT, BASE

OUT=BASE/'drop-trial/compatibility'
SOURCE=OUT/'modern-fork'
PIN='nightly-2026-08-21'
COMMIT='66e29895748bd7a289b448a875d198711f1382dd'
RUSTUP=OUT/'rustup'
SYSROOT=RUSTUP/'toolchains'/f'{PIN}-x86_64-unknown-linux-gnu'
TARGET=OUT/'modern-target'

def env():
    return dict(os.environ,RUSTUP_HOME=str(RUSTUP),CARGO_HOME=str(BASE/'cargo'),
                CARGO_TARGET_DIR=str(TARGET),PATH=str(BASE/'cargo/bin')+':'+os.environ['PATH'],
                LD_LIBRARY_PATH=str(SYSROOT/'lib'))

def execute(name,cmd,timeout=1200,cwd=None):
    cwd=cwd or SOURCE
    record={'argv':list(map(str,cmd)),'cwd':str(cwd),'environment':{k:env()[k] for k in ('RUSTUP_HOME','CARGO_HOME','CARGO_TARGET_DIR','PATH','LD_LIBRARY_PATH')}}
    if (OUT/f'{name}.log').exists():
        index=len(list(OUT.glob(f'{name}-attempt-*.log')))+1
        (OUT/f'{name}-attempt-{index}.log').write_bytes((OUT/f'{name}.log').read_bytes())
    with (OUT/f'{name}.log').open('w') as log:
        try:
            r=subprocess.run(record['argv'],cwd=cwd,env=env(),stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
            record['returncode']=r.returncode
        except subprocess.TimeoutExpired: record.update(returncode=None,status='timeout')
    (OUT/f'{name}.json').write_text(json.dumps(record,indent=2))
    print(name,record.get('returncode'),flush=True)
    print((OUT/f'{name}.log').read_text()[-6000:],flush=True)
    return record.get('returncode')

def install():
    assert subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()==COMMIT
    return execute('modern-install',[BASE/'cargo/bin/rustup','toolchain','install',PIN,'--profile','minimal',
                    '--component','rustc-dev,rust-src,llvm-tools,rustfmt,clippy'])

def build():
    return execute('modern-build',[BASE/'cargo/bin/cargo','+'+PIN,'build','--locked','-j','4'],cwd=OUT/'modern-patched')

def prepare():
    import io
    import tarfile
    dest=OUT/'modern-patched'
    dest.mkdir(exist_ok=False)
    archive=subprocess.check_output(['git','-C',str(SOURCE),'archive',COMMIT])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf: tf.extractall(dest,filter='data')
    original=BASE/'drop-trial/upstream'
    def replace(name,old,new):
        p=dest/name; text=p.read_text()
        assert text.count(old)==1,(name,old)
        p.write_text(text.replace(old,new))
    def adapt(text):
        return text.replace('resolve_drop_in_place','resolve_drop_glue').replace('ty::InstanceDef::DropGlue(_, None)','ty::InstanceKind::Shim(ty::ShimKind::DropGlue(_, None))')
    old=(original/'src/builder/fpag_builder.rs').read_text()
    block=old[old.index('            mir::TerminatorKind::Drop {'):old.index('            mir::TerminatorKind::InlineAsm {')]
    block=adapt(block).replace('Drop { place, .. }','Drop { place, drop, .. }').replace('                let (_, dropped_ty)', '                assert!(drop.is_none(), "unlowered async Drop is unsupported by this trial");\n                let (_, dropped_ty)')
    block=block.replace('self.acx.get_func_id(instance.def.def_id(), instance.args)','self.acx.get_instance_func_id(instance)')
    replace('src/builder/fpag_builder.rs','            mir::TerminatorKind::Drop { place: _, target: _, unwind: _, replace: _, drop: _ } => {}\n',block)
    replace('src/mir/analysis_context.rs','''shim @ (rustc_middle::ty::ShimKind::ConstructCoroutineInClosure { .. }''','''shim @ (rustc_middle::ty::ShimKind::DropGlue(..)
                | rustc_middle::ty::ShimKind::ConstructCoroutineInClosure { .. }''')
    replace('src/mir/analysis_context.rs','''        let generic_types = util::customize_generic_args(self.tcx, gen_args);''','''        if self.tcx.is_lang_item(def_id, rustc_hir::attrs::lang_items::LangItem::DropGlue) {
            let instance = rustc_middle::ty::Instance::resolve_drop_glue(self.tcx, gen_args.types().next().unwrap());
            return self.get_instance_func_id(instance);
        }
        let generic_types = util::customize_generic_args(self.tcx, gen_args);''')
    replace('src/mir/analysis_context.rs','    pub fn get_function_reference(','''    pub fn function_mir(&self, func_id: FuncId) -> Option<&'tcx rustc_middle::mir::Body<'tcx>> {
        let f = self.get_function_reference(func_id);
        (f.shim.is_some() || self.tcx.is_mir_available(f.def_id)).then(|| f.mir_body(self.tcx))
    }

    pub fn get_function_reference(''')
    old=(original/'src/builder/call_graph_builder.rs').read_text()
    block=old[old.index('    // Dynamic Drop'):old.index('    if !util::is_trait_method(tcx, def_id)')]
    block=adapt(block).replace('tcx.lang_items().drop_in_place_fn() == Some(def_id)','tcx.is_lang_item(def_id, rustc_hir::attrs::lang_items::LangItem::DropGlue)')
    replace('src/builder/call_graph_builder.rs','    if !util::is_trait_method(tcx, def_id) {',block+'    if !util::is_trait_method(tcx, def_id) {')
    # Reuse the already-tested sidecar; retain this fork's extra shim identity.
    exporter=(original/'src/util/depth_export.rs').read_text().replace('"promoted":format!("{:?}",fr.promoted),','"promoted":format!("{:?}",fr.promoted), "shim":format!("{:?}",fr.shim),')
    exporter=exporter.replace('lo.file.name.prefer_local().to_string()','lo.file.name.prefer_local_unconditionally().to_string()')
    exporter=exporter.replace('acx.tcx.lang_items().drop_in_place_fn()==Some(fr.def_id)','acx.tcx.is_lang_item(fr.def_id, rustc_hir::attrs::lang_items::LangItem::DropGlue)')
    (dest/'src/util/depth_export.rs').write_text(exporter)
    p=dest/'src/util/mod.rs'; p.write_text(p.read_text()+'\npub mod depth_export;\n')
    replace('src/util/results_dumper.rs','    // dump points-to results','    crate::util::depth_export::dump(acx, call_graph);\n    // dump points-to results')
    old=(original/'src/pta/context_sensitive.rs').read_text()
    block=old[old.index('        if let Some(path) = &self.acx.analysis_options.call_graph_output {'):old.index('        // dump pta statistics')]
    replace('src/pta/context_sensitive.rs','        // dump pta statistics',block+'        // dump pta statistics')
    import difflib
    diff=''
    for p in sorted((dest/'src').rglob('*.rs')):
        name=p.relative_to(dest).as_posix()
        reference=SOURCE/name
        old=reference.read_text() if reference.exists() else ''
        new=p.read_text()
        if old!=new: diff+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+name if old else '/dev/null',tofile='b/'+name))
    (ROOT/'security/semantic_callgraph/rust_rupta_v1/modern_overlay.patch').write_text(diff)

def compiler_api():
    from .compatibility_followup import fetch
    for file,subdir in (('instance.rs','ty'),('sty.rs','ty'),('syntax.rs','mir')):
        response=fetch('https://raw.githubusercontent.com/rust-lang/rust/8925ea358/compiler/rustc_middle/src/'+subdir+'/'+file)
        (OUT/('rustc-'+file+'.json')).write_text(json.dumps(response,indent=2))
        if 'text' in response:
            (OUT/('rustc-'+file)).write_text(response['text'])
            print(file,'saved',flush=True)
        else: print(response,flush=True)
    response=fetch('https://raw.githubusercontent.com/rust-lang/rust/8925ea358/compiler/rustc_span/src/lib.rs')
    (OUT/'rustc-span.rs').write_text(response['text'])

def provenance():
    import difflib
    import hashlib
    patched=OUT/'modern-patched'
    diff=''
    for p in sorted((patched/'src').rglob('*.rs')):
        name=p.relative_to(patched).as_posix()
        old=(SOURCE/name).read_text() if (SOURCE/name).exists() else ''
        new=p.read_text()
        if old!=new: diff+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+name if old else '/dev/null',tofile='b/'+name))
    patch=ROOT/'security/semantic_callgraph/rust_rupta_v1/modern_overlay.patch'
    patch.write_text(diff)
    record={'fork':'https://github.com/wenyaoc/rupta-fork','branch':'rust-2026','commit':COMMIT,'toolchain':PIN}
    for name,command in (('rustc',[SYSROOT/'bin/rustc','-vV']),('cargo',[SYSROOT/'bin/cargo','-V']),('pta_help',[TARGET/'debug/pta','--help'])):
        result=subprocess.run(list(map(str,command)),cwd=ROOT,env=env(),capture_output=True,text=True)
        record[name]={'argv':list(map(str,command)),'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    files=[patch,TARGET/'debug/pta',SYSROOT/'bin/rustc',patched/'Cargo.lock']
    record['sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    record['fork_lock_unchanged']=(SOURCE/'Cargo.lock').read_bytes().replace(b'\r\n',b'\n')==(patched/'Cargo.lock').read_bytes()
    (OUT/'modern-provenance.json').write_text(json.dumps(record,indent=2))
    print(record['rustc']['stdout'],record['cargo']['stdout'],flush=True)

def validate():
    import signal
    import time
    from .probe import limit
    from .validate import inventory
    from .patched_adapter import adjudicate
    programs=inventory()
    programs.sort(key=lambda p:(0 if p['id']=='expanded/crates_io' else 1 if p['id']=='supplement' else 2 if p['id']=='expanded/box_trait' else 3,p['id']))
    results=[]
    def run(argv,out):
        out.mkdir(parents=True,exist_ok=False)
        command=['/usr/bin/time','-v','-o',str(out/'resources.txt'),*map(str,argv)]
        started=time.monotonic()
        with (out/'stdout.txt').open('w') as stdout,(out/'stderr.txt').open('w') as stderr:
            child=subprocess.Popen(command,cwd=ROOT,env=dict(env(),PTA_LOG='info'),stdout=stdout,stderr=stderr,start_new_session=True,preexec_fn=limit)
            try: code=child.wait(timeout=180); status='completed' if code==0 else 'build_or_analysis_failure'
            except subprocess.TimeoutExpired: os.killpg(child.pid,signal.SIGKILL); code=child.wait(); status='timeout'
        record={'argv':command,'cwd':str(ROOT),'status':status,'returncode':code,'wall_seconds':time.monotonic()-started,
                'timeout_seconds':180,'address_space_limit_bytes':16*1024**3,
                'environment':{k:env()[k] for k in ('RUSTUP_HOME','CARGO_HOME','CARGO_TARGET_DIR','PATH','LD_LIBRARY_PATH')}}
        (out/'command.json').write_text(json.dumps(record,indent=2))
        return record
    for repeat in (1,2):
        for p in programs:
            deps={}; failed=False
            for c in p['crates'][:-1]:
                folder=OUT/'modern-validation/dependencies'/p['id']/c.name
                if repeat==1:
                    result=run([SYSROOT/'bin/rustc',ROOT/c.source,'--crate-name',c.name,'--crate-type',c.crate_type,'--edition',c.edition,
                                '-Zalways-encode-mir','--out-dir',folder],folder)
                    if result['status']!='completed': print('dependency failure',p['id'],c.name,flush=True); return 1
                deps[c.name]=folder/f'lib{c.name}.rlib'
            c=p['crates'][-1]
            entries=['entry'] if p['kind']=='calibration' else ['main']
            if p['id']=='supplement': entries=sorted({case['entry'] for case in p['cases']})
            for mode in ('ander','cs'):
                for entry in entries:
                    out=OUT/'modern-validation'/f'run-{repeat}'/p['id']/mode/entry
                    argv=[TARGET/'debug/pta',ROOT/c.source,'--pta-type',mode,'--entry-func',entry,
                          '--dump-call-graph',out/'graph.dot','--dump-dyn-calls',out/'dynamic.txt','--dump-mir',out/'mir.txt',
                          '--','--crate-name',c.name,'--crate-type',c.crate_type,'--edition',c.edition,
                          '--sysroot',SYSROOT,'--emit=metadata','--out-dir',out,'-Copt-level=0','-Cpanic=unwind']
                    for cfg in c.cfg: argv+=['--cfg',cfg]
                    for name,path in deps.items(): argv+=['--extern',f'{name}={path}','-L',f'dependency={path.parent}']
                    record={'program':p['id'],'mode':mode,'repeat':repeat,'entry':entry,**run(argv,out)}
                    if record['status']=='completed':
                        try:
                            record['evaluation']=adjudicate(p,out,mode,entry)
                            failed |= not record['evaluation']['required_expectations_passed']
                        except Exception as exc: record['adapter_failure']=repr(exc); failed=True
                    else: failed=True
                    if repeat==2 and not failed:
                        first=OUT/'modern-validation/run-1'/p['id']/mode/entry
                        record['deterministic']=all((first/name).read_bytes()==(out/name).read_bytes() for name in ('normalized.json','context.graph.json'))
                        failed |= not record['deterministic']
                    results.append(record)
                    (OUT/'modern-validation-results.json').write_text(json.dumps(results,indent=2))
                    print(repeat,p['id'],mode,entry,record.get('adapter_failure') or record.get('evaluation',{}).get('failures') or record['status'],flush=True)
            if failed: print('STOP: modern compiler validation gate failed',p['id'],flush=True); return 1
    return 0

if __name__=='__main__':
    if sys.argv[1]=='install': sys.exit(install())
    elif sys.argv[1]=='build': sys.exit(build())
    elif sys.argv[1]=='compiler-api': compiler_api()
    elif sys.argv[1]=='prepare': prepare()
    elif sys.argv[1]=='validate': sys.exit(validate())
    elif sys.argv[1]=='provenance': provenance()
