"""Additional std-mediated callbacks, retaining every semantic adapter node."""
import argparse
from collections import deque
import hashlib
import json
import os
from prepare import ROOT,HERE,require_c
from probe import BASE,SYSROOT,command
from std_config import rebuilt_std_flags
from inclusion import analyze


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--label',required=True);args=parser.parse_args()
    if not args.label.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c();out=BASE/'adapter-validation'/args.label;out.mkdir(parents=True,exist_ok=False)
    env=os.environ.copy();env.update(RUSTC_BOOTSTRAP='1',MIR_PROBE_TRANSITIVE='1',LD_LIBRARY_PATH=str(SYSROOT/'lib')+':'+str(SYSROOT/'lib/rustlib/x86_64-unknown-linux-gnu/lib'))
    driver=out/'driver';rustc=SYSROOT/'bin/rustc'
    command([rustc,HERE/'driver.rs','--edition=2021','-C','prefer-dynamic','-L',SYSROOT/'lib','-o',driver],out,env)
    flags=['--sysroot',SYSROOT,'--edition=2021','--target=x86_64-unknown-linux-gnu','-C','opt-level=0','-C','panic=unwind',
           '-Z','mir-opt-level=0','-Z','inline-mir=no','-Z','always-encode-mir','--remap-path-prefix',str(ROOT)+'=.',*rebuilt_std_flags(out)]
    runs=[]
    for run in ('run-1','run-2'):
        directory=out/run;directory.mkdir()
        raw=json.loads(command([driver,ROOT/'tests/fixtures/rust_mir/std_callbacks.rs',*flags,'--out-dir',directory],directory,env))
        root=next(r['instance_identity'] for r in raw['instances'] if r['instance_identity'].endswith('::crate::main'))
        graph=analyze(raw,roots=[root]);edges={}
        for site in graph['sites']:edges.setdefault(site['owner'],set()).update(site['targets'])
        previous={root:None};queue=deque([root])
        while queue:
            for target in sorted(edges.get(queue.popleft(),())):
                if target not in previous:previous[target]=True;queue.append(target)
        checks=[]
        for target,adapter in [('crate::sort_target','sort_by'),('crate::boxed_target','Map<')]:
            targets=[i for i in previous if i.endswith('::'+target)]
            adapters=[i for i in previous if adapter in i]
            # Require an actual path from an adapter to its designated callback.
            reached=set(adapters);pending=list(adapters)
            while pending:
                for child in edges.get(pending.pop(),()):
                    if child not in reached:reached.add(child);pending.append(child)
            checks.append({'target':target,'adapter_selector':adapter,'adapter_nodes':sorted(adapters),
                           'actual_targets':targets,'passed':bool(targets) and set(targets)<=reached})
        payload=json.dumps({'api':raw,'inclusion':graph},sort_keys=True,indent=2)+'\n';(directory/'graph.json').write_text(payload)
        runs.append({'checks':checks,'sha256':hashlib.sha256(payload.encode()).hexdigest(),
                     'unsupported_operations':graph['unsupported_operations'],
                     'unresolved_sites':[s for s in graph['sites'] if not s['targets']]})
    result={'runs':runs,'deterministic':runs[0]['sha256']==runs[1]['sha256'],'accepted_backend':False}
    (out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print([c['passed'] for c in runs[0]['checks']],flush=True)


if __name__=='__main__':main()
