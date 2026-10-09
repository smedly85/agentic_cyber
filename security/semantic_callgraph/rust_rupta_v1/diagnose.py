"""Inspect adapter coverage without changing analyzer artifacts."""
from pathlib import Path
from security.semantic_callgraph.rust_rupta_v1.adapter import parse,finalize,normalized
from security.semantic_callgraph.rust_rupta_v1.probe import BASE

if __name__=='__main__':
    for p in sorted((BASE/'validation/run-1').rglob('graph.dot')):
        directory=p.parent; mode=p.parent.parent.name
        try:
            raw=parse(directory,mode)
            (directory/'normalized.json').write_text(normalized(raw))
            print(str(directory.relative_to(BASE/'validation/run-1')),len(raw['functions']),len(raw['call_edges']),
                  'unknown',len(raw['unknown_edges']),'unresolved',len(raw['unresolved_indirect_callsites']),
                  'omitted',len(raw['omitted_static_calls']),'drops',len(raw['drop_terminators']),flush=True)
            for e in raw['unknown_edges'][:2]: print(' UNKNOWN',e['caller'],e['callsite'])
        except Exception as e: print('ERROR',directory,e,flush=True)
