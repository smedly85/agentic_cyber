"""One-shot audit R1-R5 correction. Source/configuration records only; no analyzers."""
import copy
import json
import shutil
from pathlib import Path
from create_corpus import source_metadata, fn
from validate_corpus import HERE, ROOT, read, sha, validate

OLD='065751bf5cfbd7233583fb123fc04fb5f22b2c02f035234a54ae12668ec5830a'

def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')

def main():
    archive=HERE/'provenance'/OLD
    if not archive.exists():
        assert validate()['calibration_fixture_bundle_sha256']==OLD
        archive.mkdir(parents=True, exist_ok=False)
        for p in HERE.iterdir():
            if p.is_file(): shutil.copy2(p,archive/p.name)
        shutil.copytree(HERE/'fixtures',archive/'fixtures')
    assert read(HERE/'fixture_hashes.json')['calibration_fixture_bundle_sha256']==OLD
    manifest=read(HERE/'fixture_manifest.json')
    prior=copy.deepcopy(manifest)
    for pair in manifest['pairs']:
        pid=pair['pair_id']
        if pid not in ('dyn_vtable','multi_pointer','static_dispatch'): continue
        for language,prefix in [('C','c'),('Rust','rust')]:
            path=ROOT/pair[prefix+'_source'];text=(archive/path.relative_to(HERE)).read_text()
            if pid=='multi_pointer':
                name='unrelated'
                extra=fn(language,name,'harness_only_decoy','int unrelated(int value)' if language=='C' else 'fn unrelated(value: i32) -> i32', '    return value + 3;' if language=='C' else '    value + 3')
                harness=('    int (*decoy)(int) = unrelated;\n    if (decoy(10) != 13) return 1;\n' if language=='C' else '    let decoy: fn(i32) -> i32 = unrelated;\n    assert_eq!(decoy(10), 13);\n')
            elif pid=='static_dispatch':
                name='second_operation' if language=='C' else 'Second::operation'
                extra=fn(language,name,'harness_only_decoy','int second_operation(int value)' if language=='C' else 'fn operation(&self, value: i32) -> i32','    return value + 3;' if language=='C' else '    value + 3')
                if language=='Rust': extra='struct Second;\nimpl Action for Second {\n'+extra+'}\n'
                harness='    if (second_operation(10) != 13) return 1;\n' if language=='C' else '    assert_eq!(Second.operation(10), 13);\n'
            else:
                name='third_operation' if language=='C' else 'Third::operation'
                if language=='C':
                    extra='struct Third { int value; };\n'+fn(language,name,'harness_only_decoy','int third_operation(const void *context)','    const struct Third *object = context;\n    return object->value + 3;')
                    harness='    struct Third third = { 10 };\n    struct Object decoy = { &third, third_operation };\n    if (decoy.operation(decoy.context) != 13) return 1;\n'
                else:
                    extra='struct Third { value: i32 }\nimpl Action for Third {\n'+fn(language,name,'harness_only_decoy','fn operation(&self) -> i32','    self.value + 3')+'}\n'
                    harness='    let third = Third { value: 10 };\n    let decoy: &dyn Action = &third;\n    assert_eq!(decoy.operation(), 13);\n'
            text=text.replace('// @function entry configured_source_entry',extra+'// @function entry configured_source_entry',1)
            pos=text.index('{',text.index('// @function main '))+2
            text=text[:pos]+harness+text[pos:]
            path.write_text(text)
            functions,sites=source_metadata(text,language,pair[prefix+'_source'])
            pair[prefix+'_source_sha256']=sha(path)
            pair[prefix+'_functions']=functions;pair[prefix+'_callsites']=sites
            pair[prefix+'_entry_identity']=functions['entry']
            pair[prefix+'_target_identity']=[functions[t['function_name']] for t in pair[prefix+'_target_identity']]
            for site in pair['expected_'+prefix+'_indirect_targets']:site['source_identity']=sites[site['callsite_id']]
        names={'dyn_vtable':('third_operation','Third::operation'),'multi_pointer':('unrelated','unrelated'),'static_dispatch':('second_operation','Second::operation')}[pid]
        pair['application_correspondence'].append({'C':names[0],'Rust':names[1],'inside_entry_scope':False})
        pair['special_semantics']['decoy']={'C':names[0],'Rust':names[1],
            'materialization':'main constructs and invokes the decoy and checks result 13 in every prescribed run; dyn uses a live trait object / context-method object, multi uses a live function pointer, static uses only direct calls.',
            'non_flow_proof':'The decoy is local to main, never passed to entry, and writes no shared state. entry only receives its original boolean selector (or no argument for static); its original assignments/direct call are unchanged. No entry-reachable function refers to the decoy.',
            'expected_harness_result':13,'tested_entry_path_unchanged':True}
        pair['notes'].append('Audit decoy '+names[0]+' / '+names[1]+' is used only by main outside the entry root; no shared state or parameter can carry it to the tested site.')
    generic=next(p for p in manifest['pairs'] if p['pair_id']=='generic_specialization')
    wording='Exactly one concrete Rust monomorphized Instance, helper::<i32>, corresponds to the one hand-specialized C helper_i32. Source-level aggregation treats that Instance as the concrete realization of one generic source function helper; no multiple concrete instances are claimed.'
    generic['registered_relationship']=wording
    provenance={'prior_calibration_fixture_bundle_sha256':OLD,'status':'superseded_before_measurement',
        'reason':'independent preregistration audit corrections R1-R5','semantic_analyzer_output_ever_existed':False,
        'archive':archive.relative_to(HERE).as_posix(),
        'R4':{'kind':'expectation_only','superseded_preregistration_wording':next(p for p in prior['pairs'] if p['pair_id']=='generic_specialization')['registered_relationship'],'replacement':wording},
        'archive_files_sha256':{p.relative_to(archive).as_posix():sha(p) for p in sorted(archive.rglob('*')) if p.is_file()}}
    write(HERE/'revision_provenance.json',provenance)
    manifest['revision_provenance']={'path':'revision_provenance.json','sha256':sha(HERE/'revision_provenance.json'),'prior_bundle_status':'superseded_before_measurement'}
    manifest['exact_application_structure_definition']='Equivalence of preregistered APPLICATION-LEVEL semantic nodes/relationships inside the entry root. Equality is not required for compiler-generated Rust shims, std/core nodes, allocator internals, or runtime/startup implementation nodes. All actual raw nodes remain uncontracted in any later authorized measurement.'
    manifest['external_boundary_definition']='c_external_boundaries, rust_external_boundaries and special_semantics.external_boundaries list external body-unavailable calls directly originating from application source inside the entry root (including entry-reachable application helpers), not every external function reachable transitively. Calls to compiled Rust std/core generic bodies are not external boundaries; harness calls and transitive allocator/runtime calls are excluded.'

    # Read only argv from the accepted instrument command log; never inspect stdout/graph data.
    log=ROOT/'build/rust-mir/continuation/cast-final-v2/run-1/trait_one/commands.jsonl'
    argv_records=[json.loads(line)['argv'] for line in log.read_text().splitlines()]
    accepted=next(a for a in argv_records if a[0].endswith('/cast-final-v2/driver'))
    normalized=[a.replace(str(ROOT),'$REPO') for a in accepted]
    # The shared flags precede fixture-specific crate and dependency arguments.
    end=next(i for i,a in enumerate(normalized) if a.startswith('--crate-name='))
    flags=normalized[2:end]+['-C','panic=unwind','-A','dead_code','--emit=link']
    freeze=read(HERE/'instrument_fingerprints.json')
    def reference(path):return {'path':path,'sha256':sha(ROOT/path)}
    canonical_record={'accepted_command_argv':normalized,'source_log':reference(log.relative_to(ROOT).as_posix()),
        'selection':'First accepted driver invocation; only argv read. Fixture-specific source, crate identity, dependency and output paths are not calibration flags.',
        'std_configuration':read(ROOT/'build/rust-mir/continuation/cast-final-v2/std_configuration.json')}
    write(HERE/'semantic_extraction_canonical.json',canonical_record)
    rust={'compiler_identity':freeze['Rust']['compiler_version'],'compiler_sha256':freeze['Rust']['compiler_sha256'],
        'canonical_configuration':{'path':'semantic_extraction_canonical.json','sha256':sha(HERE/'semantic_extraction_canonical.json')},
        'flags':flags,'target':'x86_64-unknown-linux-gnu','edition':'2021','opt_level':0,'mir_opt_level':0,'inline_mir':False,'always_encode_mir':True,'panic':'unwind','codegen_units':1,
        'std_policy':canonical_record['std_configuration'],
        'std_flag_provider':reference('security/semantic_callgraph/rust_mir/std_config.py'),
        'rebuilt_std_build_record':reference('build/rust-mir/built-std-inspection/core-v2/result.json'),
        'driver':{'path':freeze['Rust']['driver_binary_path'],'sha256':freeze['Rust']['driver_binary_sha256'],
            'source':reference('security/semantic_callgraph/rust_mir/driver.rs'),
            'build_argv':next([a.replace(str(ROOT),'$REPO') for a in json.loads(line)['argv']] for line in (log.parents[2]/'commands.jsonl').read_text().splitlines() if any(a.endswith('/driver.rs') for a in json.loads(line)['argv'])),
            'entry_point':'rustc_driver::run_compiler with Probe callbacks; after_analysis; Compilation::Stop',
            'environment':{'RUSTC_BOOTSTRAP':'1','MIR_PROBE_TRANSITIVE':'1','LD_LIBRARY_PATH':'$REPO/build/rust-mir/toolchain/lib:$REPO/build/rust-mir/toolchain/lib/rustlib/x86_64-unknown-linux-gnu/lib'},
            'unset_environment':['MIR_PROBE_CONTINUE','MIR_PROBE_OUTPUT','RUSTFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER']},
        'invocation_policy':'driver SOURCE followed by frozen flags, --crate-name calibration_PAIR and --out-dir OUTPUT; no fixture cfg or extra dependency; output locations do not change semantics.'}
    import ast
    tree=ast.parse((ROOT/'security/semantic_callgraph/backend.py').read_text())
    cflags=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFAULT_CFLAGS' for t in n.targets))
    c={'canonical_provider':reference('security/semantic_callgraph/backend.py'),'compiler':'/usr/lib/llvm-21/bin/clang','compiler_sha256':freeze['C']['compiler_sha256'],
        'flags':list(cflags)+['-fdebug-compilation-dir=.','-fdebug-prefix-map=$REPO=.','-emit-llvm','-c'],
        'extra_compile_flags':[],'target_policy':'Intentional host-default target; no --target override in accepted extraction backend. Pinned compiler reports x86_64-pc-linux-gnu. Smoke build explicitly pins that same triple.',
        'recorded_host_target':'x86_64-pc-linux-gnu','analysis':freeze['C']['analysis'],'helper_options':freeze['C']['helper_options'],
        'helper_sha256':freeze['C']['helper_sha256'],'link_policy':'llvm-link input bitcode modules using accepted backend; one translation unit per fixture'}
    manifest['semantic_extraction_configuration']={'C':c,'Rust':rust}
    write(HERE/'fixture_manifest.json',manifest)
    print('Applied R1-R5 source/manifest corrections; preserved prior freeze. Documentation and refreeze still required.')

if __name__=='__main__': main()
