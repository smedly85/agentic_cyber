"""Freeze the passing controlled science before any semantic implementation edit."""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(path):
    return json.loads(path.read_text())


def digest(value):
    return hashlib.sha256((json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()).hexdigest()


def main():
    if '--compare' in sys.argv:
        label=sys.argv[sys.argv.index('--compare')+1]
        assert label.replace('-','').isalnum()
        directory=ROOT/'build/rust-mir/continuation'/label
        report=read(directory/'complete_validation.json')
        baseline=read(HERE/'cast_gate_baseline.json')
        rows=[]
        for frozen in baseline['frozen_passing_fixtures']:
            name=frozen['fixture'];path=directory/'run-1'/name
            case=next(c for c in report['cases'] if c['case']==name)
            scientific={'graph':read(path/'scientific_graph.json'),'flow':read(path/'inclusion.json'),'complete_validation':case}
            rows.append({'fixture':name,'identical':digest(scientific)==frozen['normalized_sha256'],
                         'components':{k:digest(v)==frozen['components'][k] for k,v in scientific.items()}})
        result={'fixtures':rows,'unchanged':sum(r['identical'] for r in rows),'total':27}
        (directory/'frozen_comparison.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
        print('Frozen scientific outputs unchanged:',result['unchanged'],'/27')
        if result['unchanged']!=27:raise SystemExit(1)
        return
    if '--enrich' in sys.argv:
        from inclusion import analyze
        records = []
        baseline = read(HERE/'cast_gate_baseline.json')
        for name in sorted({c['fixture'] for c in baseline['original_casts']}):
            directory = ROOT/'build/rust-mir/continuation/cast-audit-v1/run-1'/name
            raw = read(directory/'api.json')
            roots = [r['root'] for r in read(directory.parent/'results.json') if r['case']==name]
            audit = []
            analyze(raw, roots=roots, cast_audit=audit)
            for item in audit:
                evidence = item.pop('cast_evidence')
                pointer = evidence['source_type'].startswith('*const')
                assert evidence['cast_kind']=='Transmute' and evidence['destination_type']=='usize'
                records.append({'fixture': name, **item, **evidence,
                    'classification': 'C' if pointer else 'A',
                    'contract': 'pointer_address_bits' if pointer else 'pointer_free_transparent_scalar',
                    'expected_semantic_effect': (
                        'Extract address bits without exposing provenance. Retain a non-dereferenceable address token; no callable target, heap or field mutation. Integer-to-pointer conversion must remain unsupported.' if pointer else
                        'Extract integer from compiler-typed transparent pointer-free wrapper; no callable, receiver, heap or field payload.'),
                    'effects': {k: False for k in ('callable_values','object_identity','receiver_type','heap_identity','field_identity')},
                    'no_graph_relevant_mutation': True})
        assert len(records)==8
        target=HERE/'cast_gate_ledger.json'
        assert not target.exists()
        target.write_text(json.dumps(records,sort_keys=True,indent=2)+'\n')
        print('Eight casts enriched with normalized rustc types and fixed-point abstract values.')
        return
    baseline = ROOT/'build/rust-mir/continuation/body-v5'
    report = read(baseline/'complete_validation.json')
    frozen = []
    casts = []
    for case in report['cases']:
        name = case['case']
        directory = baseline/'run-1'/name
        flow = read(directory/'inclusion.json')
        raw = read(directory/'api.json')
        if case['complete_semantic_pass']:
            scientific = {'graph': read(directory/'scientific_graph.json'),
                          'flow': flow, 'complete_validation': case}
            frozen.append({'fixture': name, 'normalized_sha256': digest(scientific),
                           'components': {k: digest(v) for k, v in scientific.items()}})
        active = set(flow['active_instances'])
        for row in raw['instances']:
            if row['instance_identity'] not in active:
                continue
            for constraint in row['constraints']:
                if constraint['kind'] != 'unsupported_cast':
                    continue
                local = constraint['source']['place'][0]
                destination = constraint['destination'][0]
                casts.append({'fixture': name, 'calling_instance': row['instance_identity'],
                              'source_span': constraint['source_span'],
                              'mir_rvalue': constraint['operation_detail'],
                              'source_type_key': row['local_types'][local],
                              'destination_type_key': row['local_types'][destination],
                              'source_operand': constraint['source'],
                              'cast_kind': 'Transmute',
                              'current_abstract_value': 'unsupported; no transfer applied',
                              'classification': 'E pending compiler-type audit',
                              'expected_semantic_effect': 'Pending normalized compiler type evidence; never implicitly identity',
                              'effects': None})
    assert len(frozen) == 27 and len(casts) == 8
    target = HERE/'cast_gate_baseline.json'
    assert not target.exists(), 'Baseline must never be overwritten'
    target.write_text(json.dumps({'baseline': str(baseline.relative_to(ROOT)),
                                 'frozen_passing_fixtures': frozen, 'original_casts': casts},
                                sort_keys=True, indent=2)+'\n')
    print('Frozen 27 normalized scientific outputs; recorded eight original casts.')


if __name__ == '__main__':
    main()
