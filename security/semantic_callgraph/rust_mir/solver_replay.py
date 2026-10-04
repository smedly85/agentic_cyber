"""Verify the cell-index optimization preserves every existing scientific result."""
import argparse
import hashlib
import json
from prepare import HERE,require_c
from probe import BASE
from inclusion import analyze


def main():
    p=argparse.ArgumentParser();p.add_argument('--label',required=True);args=p.parse_args()
    if not args.label.replace('-','').isalnum():raise ValueError('Invalid label')
    require_c();out=BASE/'solver-replay'/args.label;out.mkdir(parents=True,exist_ok=False)
    inputs=[]
    for case in json.loads((BASE/'continuation/body-v5/run-1/results.json').read_text()):
        directory=BASE/'continuation/body-v5/run-1'/case['case']
        inputs.append(('controlled-'+case['case'],json.loads((directory/'api.json').read_text()),json.loads((directory/'inclusion.json').read_text()),[case['root']]))
    for group,base in [('focused',BASE/'core-validation/bodies-v3'),('memory',BASE/'memory-validation/bodies-v1')]:
        for path in sorted(base.glob('*/run-1/graph.json')):
            data=json.loads(path.read_text());raw=data['api'];roots=[r['instance_identity'] for r in raw['instances'] if r['instance_identity'].endswith('::crate::main')]
            inputs.append((group+'-'+path.parent.parent.name,raw,data['inclusion'],roots))
    runs=[]
    for run in ('run-1','run-2'):
        directory=out/run;directory.mkdir();rows=[]
        for name,raw,expected,roots in inputs:
            actual=analyze(raw,roots=roots)
            content=json.dumps(actual,sort_keys=True,indent=2)+'\n';(directory/(name+'.json')).write_text(content)
            reference=json.dumps(expected,sort_keys=True,indent=2)+'\n'
            rows.append({'case':name,'identical_to_reference':content==reference,'sha256':hashlib.sha256(content.encode()).hexdigest()})
        runs.append(rows)
    result={'cases':runs[0],'total':len(inputs),'identical_to_reference':all(r['identical_to_reference'] for r in runs[0]),
            'fresh_solver_reruns_identical':runs[0]==runs[1],'inclusion_sha256':hashlib.sha256((HERE/'inclusion.py').read_bytes()).hexdigest()}
    (out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(result['total'],result['identical_to_reference'],result['fresh_solver_reruns_identical'],flush=True)


if __name__=='__main__':main()
