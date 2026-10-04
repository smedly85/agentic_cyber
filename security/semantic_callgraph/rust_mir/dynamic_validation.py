"""Independent native entry tracing of controlled executable fixtures.

Instrument code generation, not MIR or static edges. Static compiler symbols
are used only to map recorded machine addresses back to Instance identities.
"""
import argparse
import bisect
import json
import os
from pathlib import Path
import struct
import subprocess
from prepare import ROOT, HERE, require_c
from probe import BASE, SYSROOT, command
from std_config import rebuilt_std_flags
from trace_compare import compare


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--static-label',required=True)
    parser.add_argument('--label',required=True)
    args=parser.parse_args()
    for label in vars(args).values():
        if not label.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c()
    out=BASE/'dynamic-validation'/args.label
    out.mkdir(parents=True,exist_ok=False)
    static=BASE/'continuation'/args.static_label
    env=os.environ.copy()
    env.update(RUSTC_BOOTSTRAP='1',LD_LIBRARY_PATH=str(SYSROOT/'lib')+':'+str(SYSROOT/'lib/rustlib/x86_64-unknown-linux-gnu/lib'))
    rustc=SYSROOT/'bin/rustc'
    trace_flags=['-Z','instrument-mcount','-C','force-frame-pointers=yes','-C','relocation-model=static','-C','debuginfo=2']
    asm=out/'mcount.o';recorder=out/'recorder.o'
    command(['cc','-c',HERE/'runtime_mcount.S','-o',asm],out,env)
    command(['cc','-c','-O0',HERE/'runtime_trace.c','-o',recorder],out,env)
    link_flags=['-C','link-arg='+str(asm),'-C','link-arg='+str(recorder),'-C','link-arg=-no-pie']
    common=['--sysroot',SYSROOT,'--edition=2021','--target=x86_64-unknown-linux-gnu','-C','opt-level=0','-C','panic=unwind',
            '-Z','mir-opt-level=0','-Z','inline-mir=no','-Z','always-encode-mir',
            '--remap-path-prefix',str(ROOT)+'=.',*rebuilt_std_flags(out)]
    results=[]
    for run in ('run-1','run-2'):
        directory=out/run;directory.mkdir()
        # Replay both dependency builds with instrumentation, retaining crate identity.
        dependency_commands=[json.loads(line)['argv'] for line in (static/run/'commands.jsonl').read_text().splitlines()]
        for original in dependency_commands:
            argv=[str(directory) if a==str(static/run) else a for a in original]
            command([*argv,*trace_flags],directory,env)
        cases=[]
        for original_result in json.loads((static/run/'results.json').read_text()):
            case=original_result['case'];case_dir=directory/case;case_dir.mkdir()
            raw=json.loads((static/run/case/'api.json').read_text())
            graph=json.loads((static/run/case/'inclusion.json').read_text())
            original=json.loads((static/run/case/'commands.jsonl').read_text().splitlines()[0])['argv']
            argv=[str(rustc),*[a.replace(str(static/run),str(directory)) for a in original[1:]]]
            argv[argv.index('--out-dir')+1]=str(case_dir)
            library='--crate-type=rlib' in argv
            executable=case_dir/'execute'
            try:
                command([*argv,*trace_flags,*([] if library else [*link_flags,'-o',executable])],case_dir,env)
                if library:
                    # The original no_std library exports a C `main` for an older
                    # harness. Rename only that unused export in this trace copy.
                    command(['objcopy','--redefine-sym','main=controlled_fixture_main',
                             case_dir/'libsemantic_instrument.rlib'],case_dir,env)
                    harness=case_dir/'harness.rs'
                    harness.write_text('fn main(){for x in [0u64,1,3]{std::hint::black_box(semantic_instrument::entry_'+case+'(x));}}\n')
                    command([rustc,harness,*common,'--extern',
                             'semantic_instrument='+str(case_dir/'libsemantic_instrument.rlib'),
                             '-L','dependency='+str(directory),*link_flags,'-o',executable],case_dir,env)
                nm=command(['nm','-n','-S','--defined-only',executable],case_dir,env)
                symbols=[]
                for line in nm.splitlines():
                    parts=line.split()
                    if len(parts)==4 and parts[2] in ('t','T','w','W'):
                        symbols.append((int(parts[0],16),int(parts[1],16),parts[3]))
                symbols.sort();starts=[s[0] for s in symbols]
                by_symbol={r['symbol']:r['instance_identity'] for r in raw['instances'] if 'symbol' in r}
                if len(by_symbol)!=sum('symbol' in r for r in raw['instances']):
                    raise RuntimeError('Ambiguous compiler symbol-to-Instance mapping')
                def resolve(pc):
                    index=bisect.bisect_right(starts,pc-1)-1
                    if index<0:return None
                    start,size,name=symbols[index]
                    return name if start<=pc-1<start+size else None
                trace=case_dir/'native_edges.bin'
                with trace.open('wb') as stream:
                    if stream.fileno()!=3:raise RuntimeError('Trace FD 3 unavailable')
                    execution=subprocess.run([str(executable)],cwd=ROOT,env=env,pass_fds=(3,),capture_output=True,timeout=30)
                if execution.returncode:raise RuntimeError('Trace executable exit '+str(execution.returncode)+': '+execution.stderr.decode(errors='replace'))
                data=trace.read_bytes()
                if not data or len(data)%16:raise RuntimeError('Missing or truncated native trace')
                observed=set();unmapped=set();boundaries=set()
                dwarf={}
                pcs=sorted({pc for pair in struct.iter_unpack('<QQ',data) for pc in pair})
                lines=subprocess.check_output(['addr2line','-afi','-e',str(executable),*[hex(pc-1) for pc in pcs]],text=True).splitlines()
                current=None;frame_lines=[]
                for line in [*lines,'0x0']:
                    if line.startswith('0x'):
                        if current is not None:
                            dwarf[current]=[f for f in frame_lines[::2] if f!='??'] or [resolve(current)]
                        current=int(line,16)+1;frame_lines=[]
                    else:frame_lines.append(line)
                inline_evidence=set()
                user={r['instance_identity'] for r in raw['instances'] if r.get('defining_crate') not in ('core','alloc','std','panic_unwind','compiler_builtins','libc','unwind','rustc_std_workspace_core')}
                for callee_pc,caller_pc in struct.iter_unpack('<QQ',data):
                    # DWARF supplies semantic inline frames independently of the MIR graph.
                    caller_frames=list(reversed(dwarf[caller_pc]));callee_frames=list(reversed(dwarf[callee_pc]))
                    chain=caller_frames+callee_frames
                    if not any(by_symbol.get(symbol) in user for symbol in chain):continue
                    if len(chain)>2:inline_evidence.add(tuple(chain))
                    for caller,callee in zip(chain,chain[1:]):
                        target=by_symbol.get(callee);owner=by_symbol.get(caller)
                        if target==original_result['root'] and owner not in graph['active_instances']:
                            boundaries.add(('controlled_harness' if library else 'runtime_entry',target))
                        elif owner and target:observed.add((owner,target))
                        else:unmapped.add((caller or '<unknown>',callee or '<unknown>'))
                edges={(s['owner'],t) for s in graph['sites'] for t in s['targets']}
                row={'case':case,'dynamic_user_application_edges':sorted(observed),
                     'static_edges':sorted(edges),**compare(observed,edges),'unmapped_edges':sorted(unmapped),
                     'entry_boundaries':sorted(boundaries),
                     'dwarf_inline_chains':sorted(inline_evidence),
                     'unresolved_static_sites':[s for s in graph['sites'] if not s['targets']],
                     'trace_records':len(data)//16,
                     'passed':bool(observed) and not (observed-edges) and not unmapped}
            except Exception as error:
                row={'case':case,'passed':False,'error':str(error)}
            cases.append(row)
            print(run,case,row['passed'],row.get('error','').split('\n')[0],flush=True)
            write(case_dir/'comparison.json',row)
            write(directory/'results.json',cases)
        results.append(cases)
    write(out/'result.json',{'cases':results[0],'passed':sum(r['passed'] for r in results[0]),
          'total':len(results[0]),'deterministic':results[0]==results[1],
          'mechanism':'rustc instrument-mcount + native entry recorder; no graph-derived instrumentation',
          'accepted_backend':False})
    require_c()


if __name__=='__main__':main()
