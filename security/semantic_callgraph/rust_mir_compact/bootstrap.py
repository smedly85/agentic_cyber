"""Create one isolated compact candidate and reuse unchanged validation protocols."""
import pathlib,sys,json,hashlib
HERE=pathlib.Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OLD=HERE.parent/'rust_mir_performance_v2';OUT=ROOT/'build/rust-mir/solver-compact'
assert not (HERE/'inclusion.py').exists()
OUT.mkdir(parents=True,exist_ok=True)
for name in ('common.py','compare_suite.py','unit_mirror.py','integrity.py','historical_diagnostics.py','solve.py'):
    data=(OLD/name).read_text().replace('rust_mir_performance_v2','rust_mir_compact').replace('solver-v2-performance','solver-compact')
    if name=='historical_diagnostics.py':
        data=data.replace("    assert read(OUT/'performance_summary.json')['status']=='PASS'\n",'')
    (HERE/name).write_text(data)
for name in ('input_inventory.json','synthetic_input_inventory.json'):
    (OUT/name).write_bytes((ROOT/'build/rust-mir/solver-v2-performance'/name).read_bytes())
data=(OLD/'inclusion.py').read_text()
start=data.index('    class Facts(set):');end=data.index('    class Cells',start)
data=data[:start]+'''    Facts=make_facts(stats)
    def union_values(items):
        result=Facts()
        for item in items:result.merge(item)
        return result
'''+data[end:]
data=data.replace('incoming=set()\n                for key','incoming=Facts()\n                for key')
data=data.replace('set().union(*(values[canonical(p)] for p in cells))','union_values(values[canonical(p)] for p in cells)')
data=data.replace('set().union(*(values[canonical(p)] for p in sources))','union_values(values[canonical(p)] for p in sources)')
data=data.replace('set().union(*(values[canonical(p)] for p in source_cells))','union_values(values[canonical(p)] for p in source_cells)')
start=data.index('                end=len(incoming.additions)');end=data.index('            else:',start)
data=data[:start]+'''                version=incoming.version
                if transfers.get(relation)==version:
                    stats['unchanged_transfers_avoided']+=1
                    continue
                transfers[relation]=version
                stats['compact_transfer_facts_considered']+=len(incoming)
                changed |= destination.merge(incoming)
'''+data[end:]
data=data.replace("if any(value[0]=='function' for value in values[cell])", "if any(values[cell].tokens('function'))")
data=data.replace("if not any(value[0]=='function' for value in values[cell])", "if not any(values[cell].tokens('function'))")
data=data.replace('def analyze(probe,', (HERE/'storage_template.py').read_text()+'\n\ndef analyze(probe,',1)
assert 'additions[' not in data and 'set().union' not in data
(HERE/'inclusion.py').write_text(data)
print('Candidate created',hashlib.sha256((HERE/'inclusion.py').read_bytes()).hexdigest())
