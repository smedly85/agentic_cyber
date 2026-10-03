"""Inspect the controlled app against freshly encoded std, using Cargo's argv."""
import argparse
from collections import Counter
import json
import os
import shlex
from prepare import ROOT,HERE,require_c
from probe import BASE,SYSROOT,command
from inclusion import analyze


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--build-label',required=True)
    parser.add_argument('--label',required=True)
    args=parser.parse_args()
    for value in vars(args).values():
        if not value.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c()
    build=BASE/'build-std-probe'/args.build_label
    assert json.loads((build/'result.json').read_text())['status']=='compiled'
    lines=[line for line in (build/'build.log').read_text().splitlines()
           if 'Running `' in line and '--crate-name controlled_std_probe ' in line]
    assert len(lines)==1
    # Parse the recorded command into argv; never evaluate it in a shell.
    recorded=lines[0].split('Running `',1)[1].rsplit('`',1)[0]
    compiler=str(SYSROOT/'bin/rustc')
    assert recorded.count(compiler)==1
    # Cargo renders the executable path without quoting spaces, but quotes args.
    argv=shlex.split(recorded.split(compiler,1)[1])
    out=BASE/'built-std-inspection'/args.label
    out.mkdir(parents=True,exist_ok=False)
    env=os.environ.copy()
    env.update(RUSTC_BOOTSTRAP='1',MIR_PROBE_TRANSITIVE='1',MIR_PROBE_OUTPUT=str(out/'api.json'),
               LD_LIBRARY_PATH=str(SYSROOT/'lib')+':'+str(SYSROOT/'lib/rustlib/x86_64-unknown-linux-gnu/lib'))
    driver=out/'driver'
    command([SYSROOT/'bin/rustc',HERE/'driver.rs','--edition=2021','-C','prefer-dynamic','-L',SYSROOT/'lib','-o',driver],out,env)
    argv[argv.index('--out-dir')+1]=str(out)
    # Cargo's relative primary source is relative to its manifest directory.
    argv=[str(build/'application'/a) if a=='src/main.rs' else a for a in argv]
    command([driver,*argv],out,env)
    raw=json.loads((out/'api.json').read_text())
    roots=[r['instance_identity'] for r in raw['instances'] if r['instance_identity'].endswith('::crate::main')]
    assert len(roots)==1
    result=analyze(raw,roots=roots)
    (out/'inclusion.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    relevant=[r for r in raw['instances'] if r['instance_identity'] in result['active_instances']]
    inventory=[{k:r[k] for k in ('instance_identity','body_classification','phase','inlined_scopes') if k in r} for r in relevant]
    summary={'accepted_backend':False,'body_inventory':inventory,
             'body_counts':dict(Counter(r.get('body_classification','unclassified') for r in relevant)),
             'inlined_instances':[r['instance_identity'] for r in relevant if r.get('inlined_scopes',0)],
             'missing_required_bodies':[r['instance_identity'] for r in relevant if r.get('body_classification')=='missing_required_body'],
             'target_reachable':any(i.endswith('::crate::target') for i in result['active_instances']),
             'rustc_argv':argv}
    (out/'result.json').write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
    print(summary['body_counts'],'target',summary['target_reachable'],'inlined',len(summary['inlined_instances']),flush=True)


if __name__=='__main__':main()
