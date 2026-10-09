"""Post-hoc main-root sensitivity for mixed storage and trait decoys."""
import json
from security.semantic_callgraph.rust_rupta_v1.probe import ROOT,BASE,PTA,SYSROOT,run
from security.semantic_callgraph.rust_rupta_v1.validate import inventory
from security.semantic_callgraph.rust_rupta_v1.adapter import parse,normalized
from security.semantic_callgraph.rust_rupta_v1.evaluate import evaluate

if __name__=='__main__':
    results=[]
    for p in inventory():
        if p['id'] not in ('calibration/dyn_vtable/Rust','calibration/mixed_stack_static/Rust','calibration/mixed_stack_heap/Rust'): continue
        for mode in ('ander','cs'):
            norms=[]
            for repeat in (1,2):
                out=BASE/'main-root-sensitivity'/p['id']/mode/str(repeat)
                c=p['crates'][-1]
                r=run([PTA,ROOT/c.source,'--pta-type',mode,'--entry-func','main','--dump-call-graph',out/'graph.dot',
                       '--dump-mir',out/'mir.txt','--dump-dyn-calls',out/'dynamic.txt','--','--crate-name',c.name,
                       '--edition=2021','--sysroot',SYSROOT,'--emit=metadata','--out-dir',out,'-Copt-level=0'],out)
                row={'program':p['id'],'mode':mode,'repeat':repeat,'command':r}
                if r['status']=='completed':
                    raw=parse(out,mode); norms.append(normalized(raw))
                    e,_=evaluate(p,raw); row['evaluation']=e
                results.append(row)
                print(p['id'],mode,repeat,r['status'],flush=True)
            results[-1]['normalized_deterministic']=len(norms)==2 and norms[0]==norms[1]
    (BASE/'root_sensitivity.json').write_text(json.dumps(results,sort_keys=True,indent=2)+'\n')
