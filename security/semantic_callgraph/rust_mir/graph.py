"""Export incomplete probe relations without turning them into depth results."""
from security.semantic_callgraph.backend import finalize_semantic_graph
from pathlib import Path
import json


def export_partial(probe,inclusion):
    by_id={r['instance_identity']:r for r in probe['instances']}
    functions=[{'identity':identity,'name':identity,'instance_identity':identity,
                'source_identity':row['source_identity'],'definition':{'source_span':row['source']},
                'mir_phase':row['phase']} for identity,row in sorted(by_id.items())]
    targets={(s['owner'],s['block']):s['targets'] for s in inclusion['sites']}
    edges=[]; calls=[]; unresolved=[]; external=[]
    for owner,row in sorted(by_id.items()):
        for site in row['calls']:
            possible=targets.get((owner,site['block']),[])
            location={'source_span':site.get('source',row['source']),'mir_block':site['block']}
            indirect=site['status'].startswith('unresolved')
            record={'caller':owner,'callsite':location,'targets':possible,'mir_kind':site['status']}
            calls.append(record)
            if not possible:unresolved.append(record)
            for target in possible:
                if target not in by_id:
                    external.append({**record,'callee':target});continue
                edges.append({'caller':owner,'callee':target,'callsite':location,
                              'edge_type':'indirect_resolved' if indirect else 'direct',
                              'mir_kind':site['status'],
                              'indirect_target_set':possible if indirect else None,
                              'indirect_target_count':len(possible) if indirect else None})
    return {'schema_version':1,'analysis_status':'incomplete','accepted_backend':False,
            'functions':functions,'call_edges':edges,'callsites':calls,
            'unresolved_indirect_callsites':unresolved,'external_calls':external,
            'precision_losses':inclusion['unsupported_operations'],
            'provenance':{'backend':'rustc_mir_probe','scientific_use_permitted':False}}


def finalize_accepted(raw,entry_point):
    instrument_path=Path(__file__).with_name('instrument.json')
    instrument=json.loads(instrument_path.read_text()) if instrument_path.exists() else {}
    if instrument.get('status')!='MIR-GO':
        raise ValueError('MIR-STOP: instrument acceptance gates have not passed')
    if not raw.get('accepted_backend') or raw.get('analysis_status')!='success':
        raise ValueError('MIR-STOP: incomplete graph may not produce scientific depths')
    return finalize_semantic_graph(raw,entry_point=entry_point)
