"""Explicit solver selection on the same raw input. Diagnostic output only."""
import argparse, os, pathlib, sys, time
from common import ROOT,HERE,REFERENCE,REFERENCE_SHA,read,sha,write
sys.path[:0]=[str(ROOT),str(ROOT/'security/semantic_callgraph/cross_language_calibration')]
from runtime_provenance import pre_measurement_gate
from security.semantic_callgraph.rust_mir.inclusion import analyze as reference
from security.semantic_callgraph.rust_mir_compact.inclusion import analyze as candidate

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--solver',required=True,choices=['reference','solver-compact'])
    p.add_argument('--input',type=pathlib.Path,required=True)
    p.add_argument('--root',required=True)
    p.add_argument('--output',type=pathlib.Path,required=True)
    a=p.parse_args();assert sha(REFERENCE)==REFERENCE_SHA
    a.output.mkdir(parents=True,exist_ok=False)
    raw=read(a.input);stats={};kwargs={'roots':[a.root]}
    function=reference
    if a.solver!='reference':function=candidate;kwargs['statistics']=stats
    write(a.output/'launch.json',{'solver':a.solver,'reference_sha256':REFERENCE_SHA,
          'candidate_sha256':sha(HERE/'inclusion.py'),'input_path':str(a.input.resolve()),'input_sha256':sha(a.input),
          'root':a.root,'environment':dict(os.environ),'diagnostic_only':True})
    try:
        gate=pre_measurement_gate('Rust',dict(os.environ),[])
        result=function(raw,**kwargs)
    except Exception as error:
        write(a.output/'failure.json',{'error':str(error)});raise
    write(a.output/'gate.json',{'status':'PASS','rows':gate})
    write(a.output/'inclusion.json',result);write(a.output/'operation_counts.json',stats)
    write(a.output/'status.json',{'diagnostic_only':True,'converged':result['converged'],
          'historical_depths_accepted':0,'no_graph_finalization_or_BFS':True})

if __name__=='__main__':main()
