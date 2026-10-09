"""Collect canonical outputs for the unchanged prior 35-program corpus."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
from security.semantic_callgraph.rust_llvm_svf_v1.validate import (
    controlled_programs, calibration_programs, read, verify_preregistration)
from security.semantic_callgraph.rust_rupta_v1.probe import ROOT,HERE,BASE,SYSROOT,PTA,run

def inventory():
    verify_preregistration()
    old=ROOT/'security/semantic_callgraph/rust_llvm_svf_v1'
    programs=controlled_programs(read(old/'expectations.json'))
    programs += [p for p in calibration_programs(read(ROOT/'security/semantic_callgraph/cross_language_calibration/fixture_manifest.json')) if p['language']=='Rust']
    assert len(programs)==35
    return programs

def main():
    programs=inventory()
    frozen={}
    for p in programs:
        for c in p['crates']:
            frozen[c.source]=hashlib.sha256((ROOT/c.source).read_bytes()).hexdigest()
    frozen['security/semantic_callgraph/rust_rupta_v1/ACCEPTANCE_CRITERIA.md']=hashlib.sha256((HERE/'ACCEPTANCE_CRITERIA.md').read_bytes()).hexdigest()
    (BASE/'validation_inputs.json').write_text(json.dumps({'sources':frozen,'programs':[{**p,'crates':[asdict(c) for c in p['crates']]} for p in programs]},indent=2)+'\n')
    results=[]
    for repeat in (1,2):
        for p in programs:
            folder=BASE/'validation'/f'run-{repeat}'/p['id']
            deps={}
            for c in p['crates'][:-1]:
                out=folder/'dependencies'/c.name
                argv=[SYSROOT/'bin/rustc',ROOT/c.source,'--crate-name',c.name,'--crate-type',c.crate_type,
                      '--edition',c.edition,'--sysroot',SYSROOT,'-Zalways-encode-mir','--out-dir',out]
                result=run(argv,out)
                results.append({'program':p['id'],'repeat':repeat,'dependency':c.name,**result})
                if result['status']!='completed': break
                deps[c.name]=out/f'lib{c.name}.rlib'
            else:
                c=p['crates'][-1]
                entries=['entry'] if p['kind']=='calibration' else ['main']
                if p['id']=='supplement':
                    entries=sorted({case['entry'] for case in p['cases']})
                for mode in ('ander','cs'):
                    for entry in entries:
                        out=folder/mode/entry
                        argv=[PTA,ROOT/c.source,'--pta-type',mode,'--entry-func',entry,
                              '--dump-call-graph',out/'graph.dot','--dump-dyn-calls',out/'dynamic.txt',
                              '--dump-mir',out/'mir.txt','--','--crate-name',c.name,'--crate-type',c.crate_type,
                              '--edition',c.edition,'--sysroot',SYSROOT,'--emit=metadata','--out-dir',out,
                              '-Copt-level=0','-Cpanic=unwind']
                        for cfg in c.cfg: argv += ['--cfg',cfg]
                        for name,path in deps.items(): argv += ['--extern',f'{name}={path}','-L',f'dependency={path.parent}']
                        result=run(argv,out)
                        results.append({'program':p['id'],'repeat':repeat,'mode':mode,'entry':entry,**result})
                        print(repeat,p['id'],mode,entry,result['status'],round(result['wall_seconds'],2),flush=True)
            (BASE/'run_results.json').write_text(json.dumps(results,indent=2)+'\n')
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in frozen.items())

if __name__=='__main__': main()
