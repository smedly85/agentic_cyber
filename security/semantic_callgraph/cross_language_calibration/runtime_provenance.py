"""Read-only loader inspection and mandatory pre-measurement runtime gate.

Never executes SVF, the MIR driver, graph code, or a calibration fixture.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
try:
    from .validate_corpus import ROOT, HERE, read, require, validate
except ImportError:
    from validate_corpus import ROOT, HERE, read, require, validate

def normalized(value):return str(value).replace(str(ROOT),'$REPO')
def expand(value):return str(value).replace('$REPO',str(ROOT))
def digest_file(path):
    with open(path,'rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def run(argv,env):
    return subprocess.check_output(argv,env=env,cwd=ROOT,text=True,stderr=subprocess.PIPE)
def identity(path):
    p=Path(path).resolve(strict=True)
    return {'path':normalized(p),'sha256':digest_file(p)}
def elf(path,env):
    text=run(['/usr/bin/readelf','-d',str(path)],env)
    return {key:re.findall(r'\('+key+r'\).*?\[(.*?)\]',text) for key in ('SONAME','RPATH','RUNPATH','NEEDED')}
def closure(executable,env):
    text=run(['/usr/bin/ldd',str(executable)],env)
    require('not found' not in text,'Unresolved dynamic library')
    libraries={}
    for line in text.splitlines():
        match=re.match(r'\s*(\S+) => (.*?) \(0x',line)
        if match:name,path=match.groups()
        else:
            match=re.match(r'\s*(/.*?) \(0x',line)
            if not match:continue
            path=match[1];name='ELF_INTERPRETER'
        libraries[name]={**identity(path),'elf':elf(Path(path),env)}
    require(bool(libraries),'No dynamic dependency closure')
    return libraries

def enforce_environment(policy,env,options):
    for key in policy['unset']:
        require(key not in env,'Forbidden environment override: '+key)
    for key,value in policy['required'].items():
        require(env.get(key)==expand(value),'Required runtime environment differs: '+key)
    require(list(options)==policy['helper_options'],'Unfrozen helper options or extapi override')
    require(not Path('/etc/ld.so.preload').exists() or not Path('/etc/ld.so.preload').read_text().strip(),'System runtime preloading is not accepted')

def resolve_extapi(core,env):
    base=ROOT/'build/semantic-toolchain/SVF'
    header=base/'Release-build/include/Util/config.h'
    source=base/'svf/lib/Util/ExtAPI.cpp'
    build_dir=re.search(r'^#define SVF_BUILD_DIR "(.*)"$',header.read_text(),re.M)[1]
    candidates=[str(Path(build_dir+'/lib/extapi.bc'))]
    # Exact read-only fallback command used by ExtAPI.cpp. No analysis is run.
    probe=subprocess.run(['/bin/sh','-c','command -v npm >/dev/null 2>&1 && npm root'],cwd=ROOT,env=env,capture_output=True,text=True)
    npm_root=probe.stdout.replace('\r','').replace('\n','') if probe.returncode==0 else ''
    if npm_root:candidates.append(npm_root.rstrip('/')+'/SVF/lib/extapi.bc')
    candidates.append(str(Path(expand(core['path'])).parent/'extapi.bc'))
    selected=next((p for p in candidates if Path(p).exists()),None)
    require(selected is not None,'No extapi model resolved')
    npm=shutil.which('npm',path=env.get('PATH',''))
    return {**identity(selected),'selection_mechanism':'ExtAPI::getExtBcPath: no setter in helper, empty default -extapi, compiled SVF_BUILD_DIR candidate, SVF_DIR unset, npm root candidate, then loaded libSvfCore directory. First existing candidate wins.',
        'candidates':[{'path':normalized(p),'exists':Path(p).exists()} for p in candidates],
        'working_directory':'$REPO','npm_root':normalized(npm_root),'npm_executable':identity(npm) if npm else None,
        'shell':identity('/bin/sh'),'selection_source':identity(source),'compiled_configuration':identity(header),
        'options_source':identity(base/'svf/lib/Util/Options.cpp')}

def inspect(language,config,env):
    executable=expand(config['executable']['path'])
    result={'executable':{**identity(executable),'elf':elf(executable,env)},'libraries':closure(executable,env)}
    if language=='C':
        compiler=shutil.which('clang',path=env.get('PATH',''))
        require(compiler is not None,'Clang absent from actual PATH')
        result['compiler']={**identity(compiler),'version':run([compiler,'--version'],env),'default_target':run([compiler,'-dumpmachine'],env).strip()}
        result['compiler_libraries']=closure(compiler,env)
        core=next(v for k,v in result['libraries'].items() if k.startswith('libSvfCore'))
        result['external_model']=resolve_extapi(core,env)
    else:
        compiler=expand(config['compiler']['path'])
        result['compiler']={**identity(compiler),'version':run([compiler,'-vV'],env)}
        result['compiler_libraries']=closure(compiler,env)
        result['rebuilt_std']={name:identity(expand(row['path'])) for name,row in config['rebuilt_std'].items()}
    return result

class RuntimeMismatch(ValueError):
    def __init__(self,rows):
        self.rows=rows
        super().__init__('Runtime provenance mismatch: '+', '.join(r['component'] for r in rows if r['status']!='PASS'))

def compare(expected,actual):
    rows=[]
    def walk(a,b,name):
        if isinstance(a,dict) and 'path' in a and 'sha256' in a:
            rows.append({'component':name,'expected_path':a['path'],'resolved_path':b.get('path') if isinstance(b,dict) else None,
                'expected_sha256':a['sha256'],'actual_sha256':b.get('sha256') if isinstance(b,dict) else None,
                'status':'PASS' if isinstance(b,dict) and a['path']==b.get('path') and a['sha256']==b.get('sha256') else 'FAIL'})
        if isinstance(a,dict) and isinstance(b,dict):
            if set(a)!=set(b):rows.append({'component':name+'.keys','status':'FAIL','expected':sorted(a),'actual':sorted(b)})
            for key in a:walk(a[key],b.get(key),name+'.'+key)
        elif a!=b:rows.append({'component':name,'status':'FAIL','expected':a,'actual':b})
    walk(expected,actual,'runtime')
    if any(r['status']!='PASS' for r in rows):raise RuntimeMismatch(rows)
    return rows

def verify_runtime(language,*,env=None,options=None,manifest=None,inspector=inspect):
    manifest=read(HERE/'fixture_manifest.json') if manifest is None else manifest
    runtime=manifest['semantic_extraction_configuration'][language]['dynamic_runtime']
    env=dict(os.environ if env is None else env)
    options=runtime['resolution_policy']['helper_options'] if options is None else options
    enforce_environment(runtime['resolution_policy'],env,options)
    actual=inspector(language,runtime['identities'],env)
    return compare(runtime['identities'],actual)

def verify_all_runtimes():
    # C inherits the actual environment: never sanitize a prohibited override.
    manifest=read(HERE/'fixture_manifest.json')
    c=verify_runtime('C',manifest=manifest)
    # Rust has an explicit separate child environment, already frozen by R5.
    rust_env=dict(os.environ)
    rust_env.update({k:expand(v) for k,v in manifest['semantic_extraction_configuration']['Rust']['dynamic_runtime']['resolution_policy']['required'].items()})
    r=verify_runtime('Rust',env=rust_env,manifest=manifest)
    return {'C':c,'Rust':r,'status':'PASS','rust_environment_scope':'Explicit Rust child environment; C environment checked first without normalization.'}

def pre_measurement_gate(language,env,options=()):
    """Required immediately before any future authorized analyzer launch.

    The caller must pass the exact launch environment/options and launch only
    after success, without subsequent substitution. This function never launches.
    """
    validate()
    require(Path.cwd().resolve()==ROOT.resolve(),'Calibration launch cwd must be the frozen repository root')
    return verify_runtime(language,env=env,options=options)

if __name__=='__main__':
    validate()
    print(json.dumps(verify_all_runtimes(),indent=2))
