"""Approved calibration orchestration; never mutates frozen inputs/backends."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from validate_corpus import ROOT,HERE,read,sha,validate,require
from runtime_provenance import pre_measurement_gate,expand
from corpus_integrity import verify_instruments
sys.path.insert(0,str(ROOT))
from security.semantic_callgraph.backend import finalize_semantic_graph
from security.semantic_callgraph.rust_mir.inclusion import analyze
from security.semantic_callgraph.rust_mir.graph import export_partial

BUNDLE='ed7ea699999445b3db2da1113637b4e19a00c7e07a77277bef48e984d6ca3024'
OUT=ROOT/'build/cross-language-calibration-measured/approved-v1'
def write(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
def normalized(value,directory):
    return json.loads(json.dumps(value).replace(str(directory),'$OUTPUT').replace(str(ROOT),'$REPO'))
def command(argv,env,directory,label):
    result=subprocess.run(list(map(str,argv)),env=env,cwd=ROOT,capture_output=True,text=True,timeout=600)
    (directory/(label+'.stdout')).write_text(result.stdout)
    (directory/(label+'.stderr')).write_text(result.stderr)
    write(directory/(label+'.command.json'),{'argv':list(map(str,argv)),'environment':env,'cwd':str(ROOT),'returncode':result.returncode})
    require(result.returncode==0,label+' failed: '+result.stderr[-1000:])
    return result.stdout

def guarded(language,argv,env,options,directory):
    # No command or environment mutation between live gate and subprocess launch.
    write(directory/'analyzer_launch.json',{'argv':argv,'environment':env,'options':options,'cwd':str(ROOT)})
    started=time.time()
    try:
        gate=pre_measurement_gate(language,env,options)
    except Exception as error:
        write(directory/'gate.json',{'status':'FAIL','error':str(error),'details':getattr(error,'rows',None)})
        raise
    result=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=600)
    write(directory/'gate.json',{'status':'PASS','components':gate,'immediately_before_invocation':True,'gate_and_launch_elapsed_seconds':time.time()-started})
    (directory/'analyzer.stdout').write_text(result.stdout)
    (directory/'analyzer.stderr').write_text(result.stderr)
    write(directory/'analyzer_exit.json',{'returncode':result.returncode})
    require(result.returncode==0,'Analyzer failed: '+result.stderr[-1500:])
    return json.loads(result.stdout)

def static(pair,language,directory,manifest):
    directory.mkdir(parents=True,exist_ok=False)
    config=manifest['semantic_extraction_configuration'][language]
    env=dict(os.environ)
    if language=='Rust':env.update({k:expand(v) for k,v in config['driver']['environment'].items()})
    prefix='c' if language=='C' else 'rust'
    source=str(ROOT/pair[prefix+'_source'])
    if language=='C':
        bitcode=directory/'fixture.bc'
        compiler=expand(config['dynamic_runtime']['identities']['compiler']['path'])
        command([compiler,*[expand(f) for f in config['flags']],source,'-o',bitcode],env,directory,'compile')
        options=config['helper_options']
        argv=[expand(config['dynamic_runtime']['identities']['executable']['path']),*options,str(bitcode)]
        raw=guarded(language,argv,env,options,directory)
        write(directory/'raw.json',raw)
        graph=finalize_semantic_graph(raw,entry_point='entry')
        write(directory/'graph.json',graph)
    else:
        argv=[expand(config['driver']['path']),source,*[expand(f) for f in config['flags']],
              '--crate-name','calibration_'+pair['pair_id'],'--out-dir',str(directory)]
        raw=guarded(language,argv,env,[],directory)
        write(directory/'raw.json',raw)
        roots=[r['instance_identity'] for r in raw['instances'] if r.get('def_path','').split('::')[-1]=='entry' and pair['rust_source'] in r.get('source','')]
        require(len(roots)==1,'Configured Rust entry must resolve uniquely: '+str(roots))
        flow=analyze(raw,roots=roots)
        write(directory/'inclusion.json',flow)
        active=set(flow['active_instances'])
        exported=export_partial({'instances':[r for r in raw['instances'] if r['instance_identity'] in active]},flow)
        write(directory/'exported.json',exported)
        # Same deterministic BFS implementation as the C finalization pipeline;
        # retain controlled MIR export diagnostics and do not grant acceptance here.
        graph=finalize_semantic_graph(exported,entry_point=roots[0],provenance={'backend':'accepted_controlled_MIR_CORE','acceptance_evaluated_separately':True})
        write(directory/'graph.json',graph)
    write(directory/'normalized_graph.json',normalized(graph,directory))
    return {'pair_id':pair['pair_id'],'language':language,'static_status':'measured','graph_sha256':sha(directory/'normalized_graph.json')}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True,choices=['run-1','run-2']);args=parser.parse_args()
    frozen=validate();require(frozen['calibration_fixture_bundle_sha256']==BUNDLE,'STOP: frozen bundle differs')
    OUT.mkdir(parents=True,exist_ok=True)
    manifest=read(HERE/'fixture_manifest.json')
    directory=OUT/args.run;directory.mkdir(exist_ok=False)
    write(directory/'integrity_before.json',verify_instruments())
    results=[]
    for pair in manifest['pairs']:
        for language in ('C','Rust'):
            folder=directory/pair['pair_id']/language
            try:row=static(pair,language,folder,manifest)
            except Exception as error:
                row={'pair_id':pair['pair_id'],'language':language,'static_status':'FAIL','error':str(error),'traceback':traceback.format_exc()}
                write(folder/'failure.json',row)
                if (folder/'gate.json').exists() and read(folder/'gate.json')['status']=='FAIL':
                    write(directory/'results.json',results+[row]);raise
            results.append(row);write(directory/'results.json',results)
            print(args.run,pair['pair_id'],language,row['static_status'],row.get('error',''),flush=True)
    write(directory/'integrity_after_static.json',verify_instruments());validate()

if __name__=='__main__':main()
