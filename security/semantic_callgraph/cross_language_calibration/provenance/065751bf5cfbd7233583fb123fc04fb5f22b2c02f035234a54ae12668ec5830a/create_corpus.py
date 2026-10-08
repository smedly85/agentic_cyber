"""Author source-only calibration fixtures. Never imports or invokes an analyzer.

One-shot authoring utility: refuses to replace a manifest or frozen bundle.
Expected relations below are human source-design declarations, not measured graphs.
"""
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def fn(language,name,role,signature,body):
    annotation='#[inline(never)]\n' if language=='Rust' else ''
    return f'// @function {name} {role}\n{annotation}{signature} {{\n{body}\n}}\n// @end {name}\n'


def target(language,name='target',delta=1):
    return fn(language,name,'callback_target',f'int {name}(int value)' if language=='C' else f'fn {name}(value: i32) -> i32',
              f'    return value + {delta};' if language=='C' else f'    value + {delta}')


def harness(language,result=11,selection=False,boolean=False):
    if language=='C':
        sig='int main(int argc, char **argv)' if selection else 'int main(void)'
        body=('    (void)argv;\n    int choose_b = argc > 1;\n    return entry(choose_b) == (choose_b ? 12 : 11) ? 0 : 1;' if selection else
              '    return entry() ? 0 : 1;' if boolean else f'    return entry() == {result} ? 0 : 1;')
    else:
        sig='fn main()'
        body=('    let choose_b = std::env::args().len() > 1;\n    assert_eq!(entry(choose_b), if choose_b { 12 } else { 11 });' if selection else
              '    assert!(entry());' if boolean else f'    assert_eq!(entry(), {result});')
    return fn(language,'main','runtime_harness_outside_entry_root',sig,body)


def entry(language,body,selection=False,result_type=None):
    sig=('int entry(int choose_b)' if selection else 'int entry(void)') if language=='C' else (
        'fn entry(choose_b: bool) -> i32' if selection else 'fn entry() -> '+(result_type or 'i32'))
    return fn(language,'entry','configured_source_entry',sig,body)


OPS_C='typedef int (*Callback)(int);\nstruct Ops { Callback first; Callback second; };\n'
OPS_R='#[derive(Clone, Copy)]\nstruct Ops { first: fn(i32) -> i32, second: fn(i32) -> i32 }\n'
PAIRS=[]


def add(pair_id,c,r,c_targets=('target',),r_targets=None,c_edges=(),r_edges=None,c_sites=(),r_sites=None,
        expectation='exact_application_structure',constructs=('', ''),notes=(),selection=False,result=11,
        boolean=False,extra=None):
    PAIRS.append(dict(pair_id=pair_id,c=c+harness('C',result,selection,boolean),r=r+harness('Rust',result,selection,boolean),
        c_targets=list(c_targets),r_targets=list(r_targets or c_targets),c_edges=list(c_edges),
        r_edges=list(c_edges if r_edges is None else r_edges),c_sites=list(c_sites),r_sites=list(c_sites if r_sites is None else r_sites),
        expectation=expectation,constructs=constructs,notes=list(notes),selection=selection,extra=extra or {}))


def designs():
    add('direct_chain',target('C')+fn('C','helper','application_helper','int helper(int value)','    return target(value);')+entry('C','    return helper(10);'),
        target('Rust')+fn('Rust','helper','application_helper','fn helper(value: i32) -> i32','    target(value)')+entry('Rust','    helper(10)'),
        c_edges=[('entry','helper'),('helper','target')],constructs=('direct calls','direct calls'))
    add('recursion',target('C')+fn('C','recursive','recursive_helper','int recursive(unsigned remaining)',
        '    if (remaining == 0) return target(10);\n    return recursive(remaining - 1);')+entry('C','    return recursive(2);'),
        target('Rust')+fn('Rust','recursive','recursive_helper','fn recursive(remaining: u32) -> i32',
        '    if remaining == 0 { return target(10); }\n    recursive(remaining - 1)')+entry('Rust','    recursive(2)'),
        c_edges=[('entry','recursive'),('recursive','recursive'),('recursive','target')],constructs=('recursive function','recursive function'),
        notes=['The recursive self-edge is required. Runtime recursion count is not the metric.'])
    add('single_pointer',target('C')+entry('C','    int (*callback)(int) = target;\n    // @site entry.callback\n    return callback(10);'),
        target('Rust')+entry('Rust','    let callback: fn(i32) -> i32 = target;\n    // @site entry.callback\n    callback(10)'),
        c_sites=[('entry.callback','entry',['target'],None)],expectation='equivalent_indirect_target_set',constructs=('function pointer','fn value'))
    add('multi_pointer',target('C','target_a')+target('C','target_b',2)+entry('C',
        '    int (*callback)(int) = choose_b ? target_b : target_a;\n    // @site entry.callback\n    return callback(10);',True),
        target('Rust','target_a')+target('Rust','target_b',2)+entry('Rust',
        '    let callback: fn(i32) -> i32 = if choose_b { target_b } else { target_a };\n    // @site entry.callback\n    callback(10)',True),
        c_targets=['target_a','target_b'],c_sites=[('entry.callback','entry',['target_a','target_b'],None)],selection=True,
        expectation='equivalent_indirect_target_set',constructs=('runtime-selected pointer','runtime-selected fn value'),
        notes=['Selection is a runtime entry parameter, supplied by command-line argument presence. Both branches have prescribed executions.'])
    for pair,field,initializer in [('first_field','first','target, other'),('non_first_field','second','other, target'),('stack_copy','second','other, target')]:
        first,second=initializer.split(', ')
        c=OPS_C+target('C')+target('C','other',2)
        r=OPS_R+target('Rust')+target('Rust','other',2)
        cb=f'    struct Ops original = {{ {initializer} }};\n'
        rb=f'    let original = Ops {{ first: {first}, second: {second} }};\n'
        object_name='copied' if pair=='stack_copy' else 'original'
        if pair=='stack_copy':cb+='    struct Ops copied = original;\n';rb+='    let copied = original;\n'
        cb+=f'    // @site entry.callback\n    return {object_name}.{field}(10);'
        rb+=f'    // @site entry.callback\n    ({object_name}.{field})(10)'
        add(pair,c+entry('C',cb),r+entry('Rust',rb),c_sites=[('entry.callback','entry',['target'],{'name':field,'index':0 if field=='first' else 1})],
            expectation='equivalent_indirect_target_set',constructs=('stack struct'+(' assignment copy' if pair=='stack_copy' else ''),'Copy struct'+(' assignment copy' if pair=='stack_copy' else '')),
            notes=['The other callback field contains other; it must not enter the called field target set.'])
    add('heap_struct','#include <stdlib.h>\n'+OPS_C+target('C')+target('C','other',2)+entry('C',
        '    struct Ops *object = malloc(sizeof *object);\n    if (object == NULL) return -1;\n    object->first = other;\n    object->second = target;\n    // @site entry.callback\n    int result = object->second(10);\n    free(object);\n    return result;'),
        OPS_R+target('Rust')+target('Rust','other',2)+entry('Rust',
        '    let object = Box::new(Ops { first: other, second: target });\n    // @site entry.callback\n    (object.second)(10)'),
        c_sites=[('entry.callback','entry',['target'],{'name':'second','index':1})],
        expectation='equivalent_application_transition_with_runtime_nodes',constructs=('malloc/initialize/free','Box<Ops>'),
        notes=['Allocator/library/drop internals are not expected to be structurally identical.',
               'Runtime configurations assume successful allocation. C reports failure; Rust allocation failure diverges. Neither failure path is a callback path.'],
        extra={'external_boundaries':{'C':['malloc','free'],'Rust':[]},'runtime_structure':['Rust Box allocation and drop bodies; C allocator external boundaries']})
    add('generic_specialization',fn('C','target','source_target','long long target(long long value)','    return value + 1;')+
        fn('C','helper_i32','hand_specialized_helper','long long helper_i32(int value)','    return target((long long)value);')+
        fn('C','entry','configured_source_entry','long long entry(void)','    return helper_i32(10);'),
        fn('Rust','target','source_target','fn target(value: i64) -> i64','    value + 1')+
        fn('Rust','helper','generic_source_function','fn helper<T: Into<i64>>(value: T) -> i64','    target(value.into())')+
        entry('Rust','    helper::<i32>(10)',result_type='i64'),
        c_edges=[('entry','helper_i32'),('helper_i32','target')],r_edges=[('entry','helper'),('helper','target')],
        expectation='equivalent_application_transition_with_runtime_nodes',constructs=('hand-specialized i32-to-i64 helper','helper::<i32> with Into<i64>'),
        extra={'generic_policy':{'source_function':'helper','concrete_type_arguments':['i32'],'expected_concrete_instance_count':1,
                               'source_observation_count':1,'target_source_function':'target','policy':'Retain concrete Instances; group only by source identity, never duplicate source observations.'}},
        notes=['Latest corpus instruction requests one concrete instantiation. Into<i64> may add core conversion nodes; C uses a cast.'])
    add('static_dispatch',target('C')+fn('C','operation','concrete_operation','int operation(int value)','    return target(value);')+entry('C','    return operation(10);'),
        'trait Action { fn operation(&self, value: i32) -> i32; }\nstruct First;\n'+target('Rust')+'impl Action for First {\n'+
        fn('Rust','First::operation','concrete_operation','fn operation(&self, value: i32) -> i32','    target(value)')+'}\n'+entry('Rust','    First.operation(10)'),
        c_edges=[('entry','operation'),('operation','target')],r_edges=[('entry','First::operation'),('First::operation','target')],
        constructs=('ordinary direct function','known concrete trait method'),notes=['No C vtable or function pointer; Rust dispatch is static.'])
    c='struct First { int value; };\nstruct Second { int value; };\nstruct Object { const void *context; int (*operation)(const void *); };\n'
    c+=fn('C','first_operation','target_a','int first_operation(const void *context)','    const struct First *object = context;\n    return object->value + 1;')
    c+=fn('C','second_operation','target_b','int second_operation(const void *context)','    const struct Second *object = context;\n    return object->value + 2;')
    c+=entry('C','    struct First first = { 10 };\n    struct Second second = { 10 };\n    struct Object a = { &first, first_operation };\n    struct Object b = { &second, second_operation };\n    const struct Object *receiver = choose_b ? &b : &a;\n    // @site entry.dispatch\n    return receiver->operation(receiver->context);',True)
    r='trait Action { fn operation(&self) -> i32; }\nstruct First { value: i32 }\nstruct Second { value: i32 }\n'
    for name,delta,role in [('First',1,'target_a'),('Second',2,'target_b')]:
        r+=f'impl Action for {name} {{\n'+fn('Rust',name+'::operation',role,'fn operation(&self) -> i32',f'    self.value + {delta}')+'}\n'
    r+=entry('Rust','    let first = First { value: 10 };\n    let second = Second { value: 10 };\n    let receiver: &dyn Action = if choose_b { &second } else { &first };\n    // @site entry.dispatch\n    receiver.operation()',True)
    add('dyn_vtable',c,r,c_targets=['first_operation','second_operation'],r_targets=['First::operation','Second::operation'],
        c_sites=[('entry.dispatch','entry',['first_operation','second_operation'],{'name':'operation','index':1})],
        r_sites=[('entry.dispatch','entry',['First::operation','Second::operation'],None)],selection=True,
        expectation='equivalent_application_transition_with_runtime_nodes',constructs=('explicit context + method pointer','&dyn Action'),
        extra={'possible_receiver_types':{'C':['struct First','struct Second'],'Rust':['First','Second']},
               'target_correspondence':[['first_operation','First::operation'],['second_operation','Second::operation']]},
        notes=['Exactly two receivers are possible. References/context pointers remain valid throughout entry. Raw vtable/shim node identity is not required.'])
    c='struct Environment { int offset; };\n'+target('C')+fn('C','callback','environment_callback','int callback(const struct Environment *environment, int value)',
        '    return target(value + environment->offset);')+entry('C','    struct Environment environment = { 3 };\n    int (*function)(const struct Environment *, int) = callback;\n    // @site entry.callback\n    return function(&environment, 7);')
    r=target('Rust')+entry('Rust','    let offset = 3;\n    // @function entry::closure capturing_closure\n    let callback = |value: i32| { target(value + offset) };\n    // @end entry::closure\n    // @site entry.callback\n    callback(7)')
    add('closure_context',c,r,c_edges=[('callback','target')],r_edges=[('entry','entry::closure'),('entry::closure','target')],
        c_sites=[('entry.callback','entry',['callback'],None)],r_sites=[],
        expectation='equivalent_application_transition_with_runtime_nodes',constructs=('callback + explicit Environment','capturing closure'),
        extra={'callback_correspondence':[['callback','entry::closure']],'runtime_callbacks':{'C':['callback'],'Rust':['entry::closure']}},
        notes=['The Rust closure call is statically known, not forced into a fn pointer. Preserve actual compiler Fn/shim transitions. C passes the environment explicitly.'])
    c='#include <stdlib.h>\n'+fn('C','target','library_comparator','int target(const void *left, const void *right)',
        '    int a = *(const int *)left;\n    int b = *(const int *)right;\n    return (a > b) - (a < b);')+entry('C',
        '    int values[3] = { 3, 1, 2 };\n    // @site entry.library_callback\n    qsort(values, 3, sizeof values[0], target);\n    return values[0] == 1 && values[1] == 2 && values[2] == 3;')
    r=fn('Rust','target','library_comparator','fn target(left: &i32, right: &i32) -> std::cmp::Ordering','    left.cmp(right)')+entry('Rust',
        '    let mut values = [3, 1, 2];\n    // @site entry.library_callback\n    values.sort_by(target);\n    values[0] == 1 && values[1] == 2 && values[2] == 3',result_type='bool')
    add('library_callback',c,r,expectation='expected_library_boundary_difference',constructs=('libc qsort','slice sort_by'),boolean=True,
        extra={'external_boundaries':{'C':['qsort'],'Rust':[]},'runtime_callbacks':{'C':['target'],'Rust':['target']},
               'library_callback_binding':{'C':{'callee':'qsort','argument_index_zero_based':3,'targets':['target']},
                                           'Rust':{'callee':'[i32]::sort_by','argument_index_excluding_receiver':0,'targets':['target']}},
               'application_semantic_obligation':'entry delegates to the sorting library, which invokes target; no direct entry-to-target raw edge is asserted',
               'boundary_policy':'Record libc external versus compiled generic std bodies. Do not invent libc callback edges or contract Rust paths. Dynamic boundary coverage must be explicitly adjudicated in the later calibration.'},
        notes=['No equal raw path or depth is preregistered. Library callback bindings are not application indirect callsites.',
               'Expected dynamic callback set is {target}; callback invocation count is not specified. Comparator results and sorted values agree.'])
    for pair,heap in [('mixed_stack_static',False),('mixed_stack_heap',True)]:
        c=('#include <stdlib.h>\n' if heap else '')+OPS_C+target('C','target_a')+target('C','target_b',2)+target('C','unrelated',3)
        r=OPS_R+target('Rust','target_a')+target('Rust','target_b',2)+target('Rust','unrelated',3)
        if not heap:
            c+='static const struct Ops STATIC_OPS = { unrelated, target_b };\n'
            r+='static STATIC_OPS: Ops = Ops { first: unrelated, second: target_b };\n'
        c+=fn('C','invoke','shared_indirect_caller','int invoke(const struct Ops *object)','    // @site invoke.callback\n    return object->second(10);')
        r+=fn('Rust','invoke','shared_indirect_caller','fn invoke(object: &Ops) -> i32','    // @site invoke.callback\n    (object.second)(10)')
        cb='    struct Ops stack = { unrelated, target_a };\n'
        rb='    let stack = Ops { first: unrelated, second: target_a };\n'
        if heap:
            cb+='    struct Ops *heap = malloc(sizeof *heap);\n    if (heap == NULL) return -1;\n    heap->first = unrelated;\n    heap->second = target_b;\n'
            rb+='    let heap = Box::new(Ops { first: unrelated, second: target_b });\n'
        cb+='    int a = invoke(&stack);\n    int b = invoke('+('heap' if heap else '&STATIC_OPS')+');\n'+('    free(heap);\n' if heap else '')+'    return a + b;'
        rb+='    let a = invoke(&stack);\n    let b = invoke('+('&heap' if heap else '&STATIC_OPS')+');\n    a + b'
        add(pair,c+entry('C',cb),r+entry('Rust',rb),c_targets=['target_a','target_b'],c_edges=[('entry','invoke')],
            c_sites=[('invoke.callback','invoke',['target_a','target_b'],{'name':'second','index':1})],result=23,
            expectation='equivalent_application_transition_with_runtime_nodes' if heap else 'equivalent_indirect_target_set',
            constructs=('stack + '+('malloc' if heap else 'static')+' objects','stack + '+('Box' if heap else 'static')+' objects'),
            extra={'external_boundaries':{'C':['malloc','free'] if heap else [],'Rust':[]}},
            notes=['Both objects reach the same invoke callback site in one execution, in explicit statement order.',
                   'Expected site targets are exactly target_a and target_b; unrelated is confined to the other field.',
                   'Allocator/drop internals may differ; normal runtime assumes allocation succeeds.' if heap else 'This is the preregistered mixed stack/static category.'])


def source_metadata(text,language,source):
    functions={};sites={};starts={};lines=text.splitlines()
    for n,line in enumerate(lines,1):
        start=re.search(r'// @function (\S+) (\S+)',line)
        end=re.search(r'// @end (\S+)',line)
        site=re.search(r'// @site (\S+)',line)
        if start:starts[start[1]]=(n+1,start[2])
        if end:
            first,role=starts.pop(end[1]);last=n-1
            functions[end[1]]={'language':language,'source_file':source,'function_name':end[1],
                'source_span':{'start_line':first,'start_column':1,'end_line':last,'end_column':len(lines[last-1])+1},
                'semantic_role':role,'identity_policy':'Match source file + definition span + qualified function/impl/closure identity, not a bare symbol name.'}
            if '::operation' in end[1]:functions[end[1]]['qualified_name']='<'+end[1].split('::')[0]+' as Action>::operation'
            if end[1]=='entry::closure':functions[end[1]]['qualified_name']='entry::{closure#0}'
        if site:sites[site[1]]={'source_file':source,'line':n+1,'column':1,'source_text':lines[n].strip()}
    assert not starts
    return functions,sites


def main():
    import hashlib
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def read(path):return json.loads(path.read_text())
    def write(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
    assert not (HERE/'fixture_manifest.json').exists() and not (HERE/'CORPUS_FROZEN.json').exists()
    designs()
    old=read(HERE/'preregistered_expectations.json')['pairs']
    assert [p['pair_id'] for p in PAIRS]==[p['pair'] for p in old]
    freeze=read(HERE/'instrument_fingerprints.json')
    build_record=read(ROOT/'build/rust-mir/built-std-inspection/core-v2/result.json')
    rust_std=[]
    for index,arg in enumerate(build_record['rustc_argv'][:-1]):
        value=build_record['rustc_argv'][index+1]
        if (arg=='--extern' and value.startswith('noprelude:')) or (arg=='-L' and value.startswith('dependency=')):
            rust_std.extend([arg,value.replace(str(ROOT),'$REPO')])
    config={'C':{'compiler':'/usr/lib/llvm-21/bin/clang','compiler_identity':'Clang/LLVM 21.1.8',
                     'compiler_sha256':freeze['C']['compiler_sha256'],'target':'x86_64-pc-linux-gnu',
                     'flags':['-std=c11','-g','-O0','-fno-inline','-fno-builtin','-fno-discard-value-names','--target=x86_64-pc-linux-gnu'],
                     'link_libraries':[],'smoke_output':'native executable; no LLVM bitcode or semantic extraction'},
            'Rust':{'compiler':'$REPO/build/rust-mir/toolchain/bin/rustc','compiler_identity':'rustc 1.93.0 / LLVM 21.1.8',
                    'compiler_sha256':freeze['Rust']['compiler_sha256'],'target':'x86_64-unknown-linux-gnu','edition':'2021',
                    'flags':['--sysroot','$REPO/build/rust-mir/toolchain','--edition=2021','--target=x86_64-unknown-linux-gnu',
                             '-C','opt-level=0','-C','codegen-units=1','-C','panic=unwind','-Z','mir-opt-level=0',
                             '-Z','inline-mir=no','-Z','always-encode-mir','--remap-path-prefix','$REPO=.',
                             *rust_std,'-Z','unstable-options'],
                    'environment':{'RUSTC_BOOTSTRAP':'1'},'std_policy':freeze['Rust']['std_configuration'],
                    'smoke_output':'native executable using rustc directly, never the MIR analyzer driver'},
            'future_dynamic_tracing':'Instrumentation and runtime-edge collection are deferred until independent audit; ordinary smoke tests do not measure calls.'}
    pairs=[];review=[]
    for design,registered in zip(PAIRS,old):
        pid=design['pair_id'];folder=HERE/'fixtures'/pid;folder.mkdir(parents=True,exist_ok=False)
        record={'pair_id':pid,'category':registered['category'],'registered_relationship':registered['verbatim_expectation'],
                'cross_language_expectation':design['expectation'],'build_configuration':config,'notes':design['notes'],
                'constructs':{'C':design['constructs'][0],'Rust':design['constructs'][1]},'special_semantics':design['extra']}
        for language,prefix,extension in [('C','c','c'),('Rust','rust','rs')]:
            text='// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.\n'+design['c' if language=='C' else 'r']
            path=folder/('fixture.'+extension);path.write_text(text)
            source=path.relative_to(ROOT).as_posix();functions,sites=source_metadata(text,language,source)
            record[prefix+'_source']=source;record[prefix+'_source_sha256']=sha(path)
            record[prefix+'_functions']=functions;record[prefix+'_callsites']=sites
            record[prefix+'_entry_identity']=functions['entry']
            targets=design['c_targets' if language=='C' else 'r_targets']
            record[prefix+'_target_identity']=[functions[t] for t in targets]
            edges=design['c_edges' if language=='C' else 'r_edges']
            record['expected_'+prefix+'_edges']=[{'caller':a,'callee':b,'relation':'closure_application_transition' if b=='entry::closure' else 'direct_application_call'} for a,b in edges]
            tuples=design['c_sites' if language=='C' else 'r_sites']
            record['expected_'+prefix+'_indirect_targets']=[{'callsite_id':sid,'owner':owner,'source_identity':sites[sid],
                        'expected_targets':targets,'exactness':'exact','field_identity':field} for sid,owner,targets,field in tuples]
            record[prefix+'_external_boundaries']=design['extra'].get('external_boundaries',{}).get(language,[])
            callbacks=design['extra'].get('runtime_callbacks',{}).get(language,[t for _,_,targets,_ in tuples for t in targets])
            record[prefix+'_runtime_callback_union']=sorted(set(callbacks))
        record['runtime_inputs']=[]
        renamed={'generic_specialization':{'helper_i32':'helper'},'static_dispatch':{'operation':'First::operation'},
                 'dyn_vtable':{'first_operation':'First::operation','second_operation':'Second::operation'},
                 'closure_context':{'callback':'entry::closure'}}.get(pid,{})
        record['application_correspondence']=[{'C':name,'Rust':renamed.get(name,name),'inside_entry_scope':name!='main'} for name in record['c_functions']]
        assert all(row['Rust'] in record['rust_functions'] for row in record['application_correspondence'])
        for index,args in enumerate([[],['choose_b']] if design['selection'] else [[]]):
            observed={language:([design['c_targets' if language=='C' else 'r_targets'][index]] if design['selection'] else record[prefix+'_runtime_callback_union']) for language,prefix in [('C','c'),('Rust','rust')]}
            reached={language:([design['c_targets' if language=='C' else 'r_targets'][index]] if design['selection'] else design['c_targets' if language=='C' else 'r_targets']) for language in ('C','Rust')}
            record['runtime_inputs'].append({'id':'choose_b' if index else 'default','arguments':args,'stdin':'',
                 'expected_termination':'normal','expected_exit_code':0,'expected_stdout':'','expected_stderr':'',
                 'expected_observed_callbacks':observed,'expected_reached_source_targets':reached,
                 'callback_count_policy':'Only the set is specified; not invocation counts. These are source expectations, not measured traces.',
                 'environment_assumptions':['successful allocation','ordinary single-threaded execution']})
        pairs.append(record)
        review.append({'pair_id':pid,'review_basis':'Hand-authored source semantics before analyzer execution',
                       'application_helper_layers':'Explicit functions listed in the manifest; main is a harness outside entry.',
                       'branches':'Same runtime selection parameter and both executions' if design['selection'] else 'No target-selection branch; any recursion/allocation checks are explicitly described.',
                       'callback_location_and_targets':'Reviewed against declared callsites and function fields; no output-derived targets',
                       'lifetimes':'All borrowed/context pointers live through the call; heap objects are freed/dropped afterward.',
                       'storage':'Stack/static/heap placements follow the registered category.',
                       'legitimate_differences':design['notes'],'analyzer_outputs_consulted':False})
    manifest={'schema_version':1,'purpose':'Pre-measurement source/expectation freeze only','pair_count':15,
        'instrument_fingerprint_reference':'instrument_fingerprints.json','instrument_fingerprint_file_sha256':sha(HERE/'instrument_fingerprints.json'),
        'rust_calibration_start_sha256':freeze['Rust']['calibration_start_sha256'],'c_helper_sha256':freeze['C']['helper_sha256'],
        'source_identity_policy':'Configured entry and source targets use language, source file, definition span and qualified identity. Compiler Instance identities must be resolved later without feeding comments to analyzers.',
        'runtime_harness_policy':'main validates return values; source-level entry is the sole measurement root. Harness/runtime-to-entry edges are outside that root.',
        'measurement_policy':'No analyzer-produced values or depths. Preserve all actual library, shim and drop nodes in future raw measurements.',
        'expectation_policy':'Direct relations and exact application indirect sites are declared separately. Library argument bindings do not assert a nonexistent libc body or direct callback edge.',
        'pairs':pairs}
    write(HERE/'fixture_manifest.json',manifest);write(HERE/'source_review.json',{'pairs':review,'independent_audit':'pending'})
    lines=['# Calibration corpus preregistration','',
           'Source-only design, frozen before semantic measurement. Exactly the original 15 categories; no analyzer output informed these programs. Independent preregistration audit is pending.',
           '', 'The source-level root is `entry`. `main` is a runtime harness. Edge lists describe intended application relations, not contracted raw graphs. No numeric depth is preregistered.',
           '', '| Pair | Concept | C construct | Rust construct | Expected application relationship | Expected special difference |',
           '|---|---|---|---|---|---|']
    for p in pairs:
        relation='; '.join(e['caller']+' → '+e['callee'] for e in p['expected_c_edges'])
        relation+='; '.join(('; ' if relation else '')+s['owner']+' → {'+', '.join(s['expected_targets'])+'}' for s in p['expected_c_indirect_targets'])
        if p['pair_id']=='library_callback':relation='entry → sorting library → target comparator (boundary-mediated)'
        lines.append('| '+' | '.join([p['pair_id'],p['category'],p['constructs']['C'],p['constructs']['Rust'],relation,' '.join(p['notes']) or 'No application-structure difference intended.'])+' |')
    lines+=['','## Frozen interpretation rules','',
      '- Exact indirect sets concern the declared application callsites. A callback argument binding to qsort/sort_by is recorded separately; it is not an invented source-level indirect site.',
      '- The library pair requires explicit later adjudication of runtime edges crossing unmodeled libc. A known boundary must never silently turn missing dynamic coverage into a pass.',
      '- Raw std/core, Fn/closure/vtable shim, allocator and drop transitions remain visible. There is no depth correction factor or equal-raw-path requirement.',
      '- Generic helper has exactly one requested concrete instantiation, helper::<i32>, and one source observation. This follows the latest corpus instruction while retaining the registered Instance/source distinction.',
      '- Multi-pointer and dyn pairs execute with no arguments and with choose_b. Other pairs use one default run; mixed-object pairs invoke both targets in separate statements.',
      '- Smoke runs check exit status and output only. Expected callbacks are hand-written predictions; no callback tracing or semantic graph measurement occurs in this pass.',
      '- OOM behavior is not structurally equalized: C checks malloc, Rust Box may diverge on failure. The runtime configurations assume successful allocation.',
      '- Source spans, all source functions (including harness and closure), exact targets, field indices, receiver types and build flags are in fixture_manifest.json.',
      '- Semantic labels in comments support human review and source-integrity validation only. The scientific backends must not consume them as graph facts.',
      '', '## Manual source review','',
      'All pairs were reviewed for helper count, selection branches, callback placement, possible targets, object lifetimes and stack/static/heap storage. No wrappers were inserted to equalize raw depth. Legitimate differences and source review declarations are recorded in source_review.json.',
      '', '## Freeze and audit boundary','',
      'fixture_hashes.json binds the complete manifest, every C/Rust source, schema, this document and source review. Any source, expectation, mapping, runtime input or build-policy change invalidates the bundle. Existing preflight null measurements remain unchanged. The first semantic run is prohibited until independent audit approves this frozen bundle.','']
    (HERE/'CALIBRATION_PREREGISTRATION.md').write_text('\n'.join(lines))
    print('Authored exactly 15 source pairs and source-declared expectations; no analyzer run.')


if __name__=='__main__':main()
