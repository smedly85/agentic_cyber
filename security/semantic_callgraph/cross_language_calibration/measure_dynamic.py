"""Independent native entry tracing; static edges never influence instrumentation."""
import argparse
import bisect
import json
import os
import re
import struct
import subprocess
from pathlib import Path
from measure_approved import OUT,BUNDLE,write,command,normalized
from validate_corpus import ROOT,HERE,read,validate,require
from runtime_provenance import expand

def source_mapping(pair,language,raw):
    prefix='c' if language=='C' else 'rust';functions=pair[prefix+'_functions']
    mapping={};names={};by_symbol={};origins={}
    for row in raw['functions' if language=='C' else 'instances']:
        identity=row['identity' if language=='C' else 'instance_identity']
        symbol=row.get('llvm_symbol' if language=='C' else 'symbol')
        if symbol:by_symbol[symbol]=identity
        origins[identity]=row
        if language=='C':
            line=row.get('definition',{}).get('line');file=row.get('source_file','');hint=row.get('name')
        else:
            src=row.get('source','');match=re.search(r':(\d+):\d+:',src)
            line=int(match[1]) if match else None;file=src;hint=row.get('def_path','')
            if row.get('compiler_generated') and row.get('instance_kind')!='item':continue
        if not line or pair[prefix+'_source'] not in file:continue
        matches=[(v['source_span']['end_line']-v['source_span']['start_line'],k) for k,v in functions.items()
                 if v['source_span']['start_line']<=line<=v['source_span']['end_line']]
        if not matches:continue
        name=min(matches)[1]
        if language=='C' and name!=hint:continue
        mapping.setdefault(name,[]).append(identity);names[identity]=name
    return mapping,names,by_symbol,origins

def dynamic(pair,language,directory,manifest,support):
    raw=read(directory/'raw.json');mapping,names,by_symbol,origins=source_mapping(pair,language,raw)
    env=dict(os.environ);config=pair['build_configuration'][language]
    if language=='Rust':env.update({k:expand(v) for k,v in manifest['semantic_extraction_configuration']['Rust']['driver']['environment'].items()})
    flags=[expand(f) for f in config['flags']]
    compiler=expand(config['compiler']);prefix='c' if language=='C' else 'rust'
    target=directory/'trace';target.mkdir(exist_ok=False);executable=target/'execute'
    if language=='C':
        argv=[compiler,str(ROOT/pair['c_source']),*flags,'-pg','-fno-omit-frame-pointer','-fno-pie','-no-pie',str(support/'mcount.o'),str(support/'recorder.o'),'-o',str(executable)]
    else:
        argv=[compiler,str(ROOT/pair['rust_source']),*flags,'--crate-name','calibration_'+pair['pair_id'],
              '-Z','instrument-mcount','-C','force-frame-pointers=yes','-C','relocation-model=static','-C','debuginfo=2',
              '-C','link-arg='+str(support/'mcount.o'),'-C','link-arg='+str(support/'recorder.o'),'-C','link-arg=-no-pie','-o',str(executable)]
    command(argv,env,target,'trace_compile')
    nm=command(['nm','-n','-S','--defined-only',executable],env,target,'symbols')
    symbols=[]
    for line in nm.splitlines():
        parts=line.split()
        if len(parts)==4 and parts[2] in ('t','T','w','W'):symbols.append((int(parts[0],16),int(parts[1],16),parts[3]))
    symbols.sort();starts=[s[0] for s in symbols]
    def resolve(pc):
        i=bisect.bisect_right(starts,pc-1)-1
        if i<0:return None
        start,size,name=symbols[i]
        return name if start<=pc-1<start+size else None
    executions=[];all_observed=set();all_unmapped=set();all_boundaries=set()
    source_functions=pair[prefix+'_functions']
    user={identity for identity,name in names.items() if name!='main' and source_functions[name]['semantic_role']!='harness_only_decoy'}
    root=set(mapping['entry'])
    for runtime in pair['runtime_inputs']:
        trace=target/(runtime['id']+'.bin')
        with trace.open('wb') as stream:
            require(stream.fileno()==3,'Native trace FD 3 unavailable')
            result=subprocess.run([str(executable),*runtime['arguments']],input=runtime['stdin'],cwd=ROOT,env=env,
                pass_fds=(3,),capture_output=True,text=True,timeout=30)
        data=trace.read_bytes();require(data and len(data)%16==0,'Missing/truncated native trace')
        events=list(struct.iter_unpack('<QQ',data));pcs=sorted({pc for e in events for pc in e})
        lines=subprocess.check_output(['addr2line','-afi','-e',str(executable),*[hex(pc-1) for pc in pcs]],text=True).splitlines()
        dwarf={};current=None;frames=[]
        for line in [*lines,'0x0']:
            if line.startswith('0x'):
                if current is not None:dwarf[current]=[f for f in frames[::2] if f!='??'] or [resolve(current)]
                current=int(line,16)+1;frames=[]
            else:frames.append(line)
        observed=set();unmapped=set();boundaries=set();chains=[]
        for callee_pc,caller_pc in events:
            chain=list(reversed(dwarf[caller_pc]))+list(reversed(dwarf[callee_pc]))
            if not any(by_symbol.get(symbol) in user for symbol in chain):continue
            chains.append(chain)
            for caller,callee in zip(chain,chain[1:]):
                owner=by_symbol.get(caller);dest=by_symbol.get(callee)
                if dest in root and owner not in user:boundaries.add((caller or '<unknown>',dest));continue
                if owner and dest:observed.add((owner,dest))
                else:unmapped.add((caller or '<unknown>',callee or '<unknown>'))
        all_observed|=observed;all_unmapped|=unmapped;all_boundaries|=boundaries
        executions.append({'configuration':runtime['id'],'arguments':runtime['arguments'],'exit_code':result.returncode,
            'stdout':result.stdout,'stderr':result.stderr,'runtime_passed':result.returncode==runtime['expected_exit_code'] and result.stdout==runtime['expected_stdout'] and result.stderr==runtime['expected_stderr'],
            'observed_edges':sorted(observed),'unmapped_edges':sorted(unmapped),'entry_boundaries':sorted(boundaries),'records':len(events),'inline_chains':chains})
    graph=read(directory/'graph.json')
    edges={(e['caller'],e['callee']) for e in graph['call_edges']}
    if language=='Rust':
        flow=read(directory/'inclusion.json');edges={(s['owner'],t) for s in flow['sites'] for t in s['targets']}
    missing=all_observed-edges
    report={'mechanism':'Native mcount entry recorder; compiler symbols and DWARF only for identity mapping; no graph-derived instrumentation',
        'scope':'Declared entry/application functions; harness and inbound entry transitions excluded; unmapped application boundary edges retained as coverage limitations.',
        'observed_dynamic_edges':sorted(all_observed),'static_edges':sorted(edges),'missing_dynamic_edges':sorted(missing),
        'unmapped_edges':sorted(all_unmapped),'entry_boundaries':sorted(all_boundaries),'executions':executions,
        'mapped_subset_passed':not missing,'complete_soundness_passed':bool(all_observed) and not missing and not all_unmapped and all(e['runtime_passed'] for e in executions)}
    write(directory/'dynamic.json',report)
    return report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True,choices=['run-1','run-2']);args=parser.parse_args()
    require(validate()['calibration_fixture_bundle_sha256']==BUNDLE,'STOP bundle mismatch')
    manifest=read(HERE/'fixture_manifest.json');support=OUT/args.run/'trace_support';support.mkdir(exist_ok=False)
    env=dict(os.environ)
    for name,source in [('mcount','runtime_mcount.S'),('recorder','runtime_trace.c')]:
        command(['/usr/lib/llvm-21/bin/clang','-c','-O0',ROOT/'security/semantic_callgraph/rust_mir'/source,'-o',support/(name+'.o')],env,support,name)
    results=[]
    for pair in manifest['pairs']:
        for language in ('C','Rust'):
            directory=OUT/args.run/pair['pair_id']/language
            try:
                report=dynamic(pair,language,directory,manifest,support)
                row={'pair_id':pair['pair_id'],'language':language,'passed':report['complete_soundness_passed'],
                    'missing':len(report['missing_dynamic_edges']),'unmapped':len(report['unmapped_edges'])}
            except Exception as error:
                row={'pair_id':pair['pair_id'],'language':language,'passed':False,'error':str(error)}
                write(directory/'dynamic.json',row)
            results.append(row);write(OUT/args.run/'dynamic_results.json',results)
            print(args.run,'dynamic',row,flush=True)
    validate()

if __name__=='__main__':main()
