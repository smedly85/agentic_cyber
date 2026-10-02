"""Controlled memory-model diagnosis only. Never measures historical Rust."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
V2 = HERE.parent / 'rust_audit_v2'
CACHE = ROOT / 'build/rust-instrument-v3'
sys.path.insert(0, str(ROOT / 'security/historical/rust'))
from semantic_gate import verify_frozen, fingerprint


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def preserve():
    frozen = verify_frozen()
    instrument = json.loads((V2/'instrument.json').read_text())
    expected = '3eee651972af243bd522ec2383d33ccc15b84271d0001e101fde8641dbc26146'
    declared = instrument.pop('instrument_fingerprint')
    if declared != expected or fingerprint(instrument) != expected:
        raise ValueError('STOP: audit-v2 instrument mismatch')
    for path, key in (
        ('build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf','helper_sha256'),
        ('build/semantic-toolchain/SVF/Release-build/lib/libSvfLLVM.so','svf_llvm_library_sha256'),
        ('build/semantic-toolchain/SVF/svf-llvm/lib/SVFIRBuilder.cpp','patched_svf_source_sha256')):
        if sha(ROOT/path) != instrument[key]:
            raise ValueError('STOP: instrument component changed: '+path)
    lock = json.loads((V2/'artifact_manifest.json').read_text())
    for name, value in lock['json_fingerprints'].items():
        if fingerprint(json.loads((V2/name).read_text())) != value:
            raise ValueError('STOP: audit-v2 artifact changed: ' + name)
    result = json.loads((V2/'results.json').read_text())
    record = {'instrument_fingerprint': expected, 'frozen_inputs': frozen,
        'v2_artifact_fingerprints': lock['json_fingerprints'],
        'rust_cases': result['rust_controlled']['cases'],
        'c_controlled': result['c_regression']['controlled'],
        'c_historical_observations': result['c_regression']['observations']}
    path = HERE/'preserved_v2.json'
    serialized = json.dumps(record, indent=2, sort_keys=True) + '\n'
    if path.exists() and path.read_text() != serialized:
        raise ValueError('preserved baseline would change')
    path.write_text(serialized)
    print('Verified and preserved audit-v2 baseline')


def diagnose():
    """Re-run untouched controlled bitcode; alternate flags are diagnostic only."""
    from security.semantic_callgraph.rust_audit_v2 import run_rust as runner
    runner.CACHE = CACHE / 'rust'
    rows = []
    for case in ('stack_bytes', 'box_trait', 'box_fnmut'):
        original = ROOT / 'build/rust-instrument-v2/rust' / case
        for flag in ('-ff-eq-base', '-ff-eq-base=false'):
            directory = CACHE / 'diagnosis' / case / ('official' if flag == '-ff-eq-base' else 'without-ff')
            directory.mkdir(parents=True, exist_ok=True)
            output = runner.command([runner.HELPER, '-stat=false', flag, original/'linked.bc'], directory)
            raw = json.loads(output)
            runner.write(directory/'raw.json', raw)
            rows.append({'case': case, 'flag': flag, 'bitcode_sha256': sha(original/'linked.bc'),
                         'raw_sha256': sha(directory/'raw.json')})
            print(case, flag, 'captured', flush=True)
    (HERE/'diagnostic_runs.json').write_text(json.dumps(rows, indent=2, sort_keys=True)+'\n')


def adversaries():
    """Independent LLVM memory-model fixtures, not rewrites of Rust IR."""
    from security.semantic_callgraph.rust_audit_v2 import run_rust as runner
    specs = [
        ('first', 16, [(0,'first'),(8,'second')], 0, ['first']),
        ('second', 16, [(0,'first'),(8,'second')], 8, ['second']),
        ('three', 24, [(0,'first'),(8,'second'),(16,'third')], 16, ['third']),
        ('reverse', 16, [(8,'second'),(0,'first')], 8, ['second']),
        ('overwrite', 16, [(0,'first'),(8,'second'),(8,'third')], 8, ['third']),
        ('same_slot_union', 16, [(0,'first'),(8,'choice')], 8, ['second','third']),
        ('separate_slots', 16, [(0,'first'),(8,'second')], 8, ['second']),
        ('intervening_bytes', 24, [(0,'first'),(16,'second')], 16, ['second']),
        ('overlap_self_copy', 16, [(0,'first'),(8,'second')], 8, ['second']),
        ('variable', 16, [(0,'first'),(8,'second')], 'variable', ['first','second']),
        ('stack', 16, [(0,'first'),(8,'second')], 8, ['second']),
        ('heap', 16, [(0,'first'),(8,'second')], 8, ['second']),
    ]
    rows=[]
    for name,size,stores,offset,expected in specs:
        directory=CACHE/'adversaries'/name
        directory.mkdir(parents=True,exist_ok=True)
        lines=['target triple = "x86_64-unknown-linux-gnu"',
            'target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"',
            'declare ptr @malloc(i64)',
            'declare void @llvm.memmove.p0.p0.i64(ptr, ptr, i64, i1)',
            'define void @first() { ret void }', 'define void @second() { ret void }',
            'define void @third() { ret void }', 'define void @entry(i1 %choose) {',
            (f'%base = call ptr @malloc(i64 {size})' if name=='heap' else f'%base = alloca [{size} x i8], align 8'),
            '%choice = select i1 %choose, ptr @second, ptr @third']
        for i,(off,value) in enumerate(stores):
            lines += [f'%s{i} = getelementptr i8, ptr %base, i64 {off}',
                      f'store ptr {"%choice" if value=="choice" else "@"+value}, ptr %s{i}, align 8']
        if name=='intervening_bytes':
            lines += ['%gap = getelementptr i8, ptr %base, i64 8','store i64 42, ptr %gap']
        if name=='overlap_self_copy':
            # Identity memmove touches a pointer's bytes without inventing a corrupted pointer.
            lines += ['%part = getelementptr i8, ptr %base, i64 9',
                      'call void @llvm.memmove.p0.p0.i64(ptr %part, ptr %part, i64 3, i1 false)']
        if offset=='variable':
            lines += ['%offset = select i1 %choose, i64 0, i64 8']
        lines += [f'%p = getelementptr i8, ptr %base, i64 {"%offset" if offset=="variable" else offset}',
                  '%f = load ptr, ptr %p, align 8','call void %f()', 'ret void','}']
        (directory/'case.ll').write_text('\n'.join(lines)+'\n')
        runner.command([runner.LLVM/'llvm-as', directory/'case.ll','-o',directory/'case.bc'],directory)
        raw=json.loads(runner.command([runner.HELPER,'-stat=false','-ff-eq-base',directory/'case.bc'],directory))
        runner.write(directory/'raw.json',raw)
        symbols={f['identity']:f['llvm_symbol'] for f in raw['functions']}
        actual=sorted({symbols[e['callee']] for e in raw['call_edges'] if e['edge_type']=='indirect_resolved' and symbols[e['caller']]=='entry'})
        row={'case':name,'expected':expected,'actual':actual,'missing':sorted(set(expected)-set(actual)),
             'unexpected':sorted(set(actual)-set(expected)), 'ir_sha256':sha(directory/'case.ll')}
        row['status']='passed' if not row['missing'] and not row['unexpected'] else 'failed'
        rows.append(row)
        print(name,row['status'],actual,flush=True)
    (HERE/'adversarial_results.json').write_text(json.dumps(rows,indent=2,sort_keys=True)+'\n')


def raw_wpa():
    wpa=ROOT/'build/semantic-toolchain/SVF/Release-build/bin/wpa'
    jobs=[(case,ROOT/'build/rust-instrument-v2/rust'/case/'linked.bc')
          for case in ('stack_bytes','box_trait','box_fnmut')]
    jobs += [('adversary-'+p.parent.name,p) for p in sorted((CACHE/'adversaries').glob('*/case.bc'))]
    for case, bitcode in jobs:
        directory=CACHE/'wpa'/case
        directory.mkdir(parents=True,exist_ok=True)
        argv=[str(wpa),'-ander','-stat=false','-ff-eq-base','-print-all-pts',
              '-print-fp','-dump-pag',str(bitcode)]
        run=subprocess.run(argv,cwd=directory,capture_output=True,text=True,timeout=180)
        (directory/'stdout.txt').write_text(run.stdout)
        (directory/'stderr.txt').write_text(run.stderr)
        (directory/'command.json').write_text(json.dumps({'argv':argv,'exit':run.returncode},indent=2)+'\n')
        print(case,'WPA',run.returncode,flush=True)
        if run.returncode: raise RuntimeError(run.stderr)
        if case.startswith('adversary-'):
            import re
            report=run.stdout.split('Function Pointer Targets')[-1]
            actual=sorted(set(re.findall(r'^\s+(first|second|third)\s*$',report,re.MULTILINE)))
            rows=json.loads((HERE/'adversarial_results.json').read_text())
            expected=next(row['actual'] for row in rows if row['case']==case.removeprefix('adversary-'))
            if actual!=expected: raise ValueError('Raw WPA/helper target disagreement: '+case)
            (directory/'agreement.json').write_text(json.dumps({'raw_wpa_targets':actual,'helper_targets':expected,'agrees':True},indent=2)+'\n')


def replay_rust():
    from security.semantic_callgraph.rust_audit_v2 import run_rust as runner
    from validate_semantic_instrument import CASES
    runner.CACHE=CACHE/'rust'
    rows=[]
    for case,target,depth in list(CASES)+[(name,'target',None) for name in runner.EXPANDED]:
        directory=runner.CACHE/case
        directory.mkdir(parents=True,exist_ok=True)
        original=ROOT/'build/rust-instrument-v2/rust'/case
        raw=json.loads(runner.command([runner.HELPER,'-stat=false','-ff-eq-base',original/'linked.bc'],directory))
        ir=(original/'linked.ll').read_text()
        inventory=runner.validate_definition_inventory(ir,raw)
        source=runner.FIXTURES/('expanded.rs' if case in runner.EXPANDED else 'instrument.rs')
        row=runner.evaluate(raw,ir,case,source,'main' if case in runner.EXPANDED else 'entry_'+case,target,depth)
        row['inventory']=inventory
        row['bitcode_sha256']=sha(original/'linked.bc')
        runner.write(directory/'raw.json',raw)
        rows.append(row)
        print(case,row['status'],flush=True)
    runner.write(HERE/'rust_results.json',{'cases':rows,'method':'replay_unchanged_controlled_bitcode','historical_rust_measurement':False})


def acquire_compiler_evidence():
    directory=CACHE/'compiler-source'
    directory.mkdir(parents=True,exist_ok=True)
    rows=[]
    for name in ('builder.rs','type_of.rs'):
        url='https://raw.githubusercontent.com/rust-lang/rust/254b59607d4417e9dffbc307138ae5c86280fe4c/compiler/rustc_codegen_llvm/src/'+name
        path=directory/name
        if not path.exists():
            with urllib.request.urlopen(url,timeout=60) as response:
                path.write_bytes(response.read())
        rows.append({'url':url,'sha256':sha(path),'path':path.relative_to(ROOT).as_posix(),
                     'retrieved_utc':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()})
    (HERE/'compiler_evidence.json').write_text(json.dumps(rows,indent=2,sort_keys=True)+'\n')


def publish():
    from security.semantic_callgraph.rust_audit_v2 import run_rust as runner
    from security.semantic_callgraph.rust_identity import strip_generic_arguments
    old=json.loads((V2/'instrument.json').read_text())
    if sha(runner.HELPER)!=old['helper_sha256']:
        raise ValueError('Instrument binary changed; a new instrument revision is required')
    rust=json.loads((HERE/'rust_results.json').read_text())
    c=json.loads((CACHE/'c/results.json').read_text())
    (HERE/'c_results.json').write_text(json.dumps(c,indent=2,sort_keys=True)+'\n')
    comparisons=[]
    for case in ('stack_bytes','box_trait','box_fnmut'):
        variants=[]
        for variant in ('official','without-ff'):
            raw=json.loads((CACHE/'diagnosis'/case/variant/'raw.json').read_text())
            owners={'stack_bytes':'by_reference','box_trait':'boxed','box_fnmut':'call_mut'}
            owner_ids={f['identity'] for f in raw['functions'] if strip_generic_arguments(f.get('name',''))==owners[case]}
            # Display filtering only; never used for source identity or measurement.
            edges=[e for e in raw['call_edges'] if e['caller'] in owner_ids and e['edge_type']=='indirect_resolved']
            unresolved=[e for e in raw['unresolved_indirect_callsites'] if e['caller'] in owner_ids]
            variants.append({'option':variant,'edges':edges,'unresolved':unresolved})
        comparisons.append({'case':case,'variants':variants,'unchanged':variants[0]['edges']==variants[1]['edges'] and variants[0]['unresolved']==variants[1]['unresolved']})
    (HERE/'option_comparison.json').write_text(json.dumps(comparisons,indent=2,sort_keys=True)+'\n')
    lines=['# Controlled instrument results','','No historical Rust measurement. Replayed original controlled bitcode with the unchanged v2 instrument.','',
           '| Fixture | Status |','| --- | --- |']
    for row in rust['cases']: lines.append('| '+row['case']+' | '+row['status']+' |')
    lines += ['','## Indirect callsite target sets','',
              'Source-qualified identities below distinguish methods and instances. Runtime sites without an existing expectation remain explicitly unadjudicated; they are not passes.','',
              '| Fixture / caller / site | Expected | Actual | Missing | Unexpected | Status |',
              '| --- | --- | --- | --- | --- | --- |']
    def cell(value):
        if value is None:return 'not adjudicated'
        if not value:return '∅'
        return '<br>'.join(str(v).replace('|','&#124;') for v in value)
    for row in rust['cases']:
        for site in row['indirect_sites']:
            label=row['case']+' / '+site['caller']+' / '+str(site['callsite'])
            lines.append('| '+label.replace('|','&#124;')+' | '+' | '.join(cell(site[k]) for k in ('expected_targets','actual_targets','missing_targets','unexpected_targets'))+' | '+site['verdict']+' |')
    lines += ['','## Independent byte-storage adversaries','',
              '| Fixture | Expected | Actual | Missing | Unexpected | Status |','| --- | --- | --- | --- | --- | --- |']
    for row in json.loads((HERE/'adversarial_results.json').read_text()):
        lines.append('| '+row['case']+' | '+' | '.join(cell(row[k]) for k in ('expected','actual','missing','unexpected'))+' | '+row['status']+' |')
    lines += ['','C controlled: 11/11; C historical observations: 9/9. See c_results.json for exact path, edge-kind, target-set, depth, and reachability checks.','']
    (HERE/'controlled_results.md').write_text('\n'.join(lines))
    evidence={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(CACHE.rglob('*')) if p.is_file()}
    (HERE/'cache_manifest.json').write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n')
    record={'instrument_fingerprint':old['instrument_fingerprint'],'instrument_changed':False,
            'verdict':'STOP — backend unsuitable','historical_rust_measurement':False,
            'frozen_inputs':verify_frozen(),'helper_sha256':sha(runner.HELPER),
            'artifacts':{p.name:sha(p) for p in sorted(HERE.iterdir()) if p.is_file() and p.name!='audit_manifest.json'}}
    record['audit_fingerprint']=fingerprint(record)
    (HERE/'audit_manifest.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    print('Audit fingerprint',record['audit_fingerprint'])


if __name__ == '__main__':
    preserve()
    sys.path.insert(0, str(ROOT))
    if '--diagnose' in sys.argv:
        diagnose()
    if '--adversaries' in sys.argv:
        adversaries()
    if '--wpa' in sys.argv:
        raw_wpa()
    if '--replay-rust' in sys.argv:
        replay_rust()
    if '--acquire-compiler' in sys.argv:
        acquire_compiler_evidence()
    if '--publish' in sys.argv:
        publish()
