"""Strict adapter for the pinned RUPTA DOT, MIR and resolved-call exports.

No source expectation participates in extracting edges. Unknown edge kinds
remain unknown and block the shared semantic finalizer, rather than becoming
invented direct calls. MIR evidence may add nodes/boundaries, never edges.
"""
import json
import re
from pathlib import Path
from security.semantic_callgraph.backend import finalize_semantic_graph

QUOTED=r'"(?:[^"\\]|\\.)*"'
NODE=re.compile(r'\s*(\d+) \[ label = ('+QUOTED+r') \]')
EDGE=re.compile(r'\s*(\d+) -> (\d+) \[ label = ('+QUOTED+r') \]')
HEADER=re.compile(r'^\[FuncId\((\d+)\) - ('+QUOTED+r')\]$',re.M)

def read_mir(text):
    bodies={}
    matches=list(HEADER.finditer(text))
    for i,m in enumerate(matches):
        name=json.loads(m[2])
        if name in bodies: raise ValueError('colliding MIR function labels: '+name)
        body=text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)]
        # rustc's pretty printer can append a separate MIR FOR CTFE body.
        # DOT locations refer to the first (optimized runtime) body.
        runtime_body=body.split('\n}\n',1)[0]+'\n}\n'
        calls={}; drops=[]; block=None; count=0; pending=''
        for line in runtime_body.splitlines():
            match=re.fullmatch(r'    (bb\d+)(?: \(cleanup\))?: \{',line)
            if match:
                block=match[1]; count=0; pending=''; continue
            if line=='    }': block=None; continue
            if block is None: continue
            pending += line.strip()+' '
            if not line.rstrip().endswith(';'): continue
            statement=pending.strip(); pending=''
            location=f'{block}[{count}]'
            call=re.match(r'_\d+ = (.*?)\(.*\) -> (?:\[|unwind|bb\d+)',statement)
            if call:
                operand=call[1]
                calls[location]={'operand':operand,'statement':statement,
                                 'operand_kind':'pointer' if re.match(r'(?:move |copy )?_\d+$',operand) else 'static'}
            if statement.startswith('drop('): drops.append({'mir_location':location,'statement':statement})
            count += 1
        bodies[name]={'body_available':'Mir is unavailable' not in body,'calls':calls,'drop_terminators':drops,
                      'header':next((s for s in body.splitlines() if s.startswith('fn ')),None)}
    return bodies

def read_dynamic(text):
    sites={}; current=None; category=None
    for line in text.splitlines():
        if line.startswith('#'): category=line[1:].rstrip(':'); current=None
        elif line.startswith('\tcallsite: '):
            m=re.fullmatch(r'\tcallsite: ('+QUOTED+r'), (bb\d+\[\d+\]), callee: *',line)
            if not m: raise ValueError('unparsed dynamic callsite: '+line)
            current=(json.loads(m[1]),m[2])
            if current in sites: raise ValueError('duplicate dynamic callsite')
            sites[current]={'kind':category,'targets':[]}
        elif line.startswith('\t\t'):
            if current is None: raise ValueError('target without callsite')
            sites[current]['targets'].append(json.loads(line.strip()))
        elif line.strip(): raise ValueError('unparsed dynamic output: '+line)
    for site in sites.values(): site['targets']=sorted(set(site['targets']))
    return sites

def parse(directory,mode):
    directory=Path(directory)
    nodes={}; edges=[]
    for line in (directory/'graph.dot').read_text().splitlines():
        if line in ('digraph {','}') or not line.strip(): continue
        m=EDGE.fullmatch(line)
        if m: edges.append((m[1],m[2],json.loads(m[3]))); continue
        m=NODE.fullmatch(line)
        if m:
            if m[1] in nodes: raise ValueError('duplicate DOT node')
            nodes[m[1]]=json.loads(m[2]); continue
        raise ValueError('unparsed DOT line: '+line)
    if len(set(nodes.values()))!=len(nodes): raise ValueError('colliding DOT display identities')
    bodies=read_mir((directory/'mir.txt').read_text())
    dynamic=read_dynamic((directory/'dynamic.txt').read_text())
    functions=[]
    for name in sorted(set(nodes.values())|set(bodies)):
        functions.append({'identity':name,'name':name,'language':'Rust',
                          'identity_basis':'RUPTA printed FunctionReference; not full rustc Instance identity',
                          'body_available':bodies.get(name,{}).get('body_available'),
                          'present_in_dot':name in nodes.values()})
    result_edges=[]; outgoing={}; unknown=[]
    for a,b,loc in edges:
        caller,callee=nodes[a],nodes[b]
        key=(caller,loc)
        info=dynamic.get(key)
        call=bodies.get(caller,{}).get('calls',{}).get(loc)
        if info:
            kind='indirect_resolved'
            if callee not in info['targets']: raise ValueError('DOT target absent from dynamic export')
        elif call and call['operand_kind']=='static': kind='direct'
        else: kind='unknown'
        edge={'caller':caller,'callee':callee,'edge_type':kind,'callsite':{'mir_location':loc},
              'pointer_analysis_backend':'RUPTA','pointer_analysis':mode,
              'indirect_target_set':info['targets'] if info else None,
              'indirect_target_count':len(info['targets']) if info else None}
        result_edges.append(edge)
        outgoing.setdefault(key,set()).add(callee)
        if kind=='unknown': unknown.append(edge)
    for key,info in dynamic.items():
        if outgoing.get(key,set())!=set(info['targets']): raise ValueError('dynamic target set differs from DOT')
    unresolved=[]; omitted=[]; drops=[]
    for name,body in bodies.items():
        for loc,call in body['calls'].items():
            if (name,loc) not in outgoing:
                row={'caller':name,'callsite':{'mir_location':loc},'evidence':call,'origin':'RUPTA MIR dump; not explicit analyzer unresolved ledger'}
                if call['operand_kind']=='pointer': unresolved.append(row)
                else: omitted.append(row)
        drops += [{'caller':name,**d} for d in body['drop_terminators']]
    return {'functions':functions,'call_edges':sorted(result_edges,key=lambda e:(e['caller'],e['callsite']['mir_location'],e['callee'])),
            'unresolved_indirect_callsites':unresolved,'unresolved_inventory_complete':False,
            'omitted_static_calls':omitted,'drop_terminators':drops,'unknown_edges':unknown,
            'body_inventory':bodies,'external_calls':[],
            'projection':'upstream union over call contexts at function-reference granularity',
            'analysis_mode':mode}

def finalize(raw,entry):
    if raw['unknown_edges']: raise ValueError('unknown edge kinds prevent semantic finalization')
    graph=finalize_semantic_graph(raw,entry_point=entry,provenance={'instrument':'canonical RUPTA','projection':raw['projection']})
    graph.update(analysis_backend='rupta_mir',pointer_analysis=raw['analysis_mode'],
                 analysis_status='partial_export',unresolved_inventory_complete=False)
    return graph

def normalized(raw):
    # Deterministic sorting removes exporter HashMap/node-index iteration only.
    return json.dumps(raw,sort_keys=True,indent=2)+'\n'
