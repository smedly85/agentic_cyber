"""Repeat frozen historical retained-call graphs into a fresh evidence directory."""
import argparse,pathlib,subprocess,sys
from common import ROOT,HERE,OUT,RESULTS,read,write,sha
from study import verify

def main(output):
    fingerprint=verify();output=output.resolve()
    assert output.is_relative_to(ROOT) and not output.exists()
    output.mkdir(parents=True)
    contexts={(c['release'],c['utility']):c for c in read(RESULTS/'semantic_results.json')['program_contexts']}
    results=[]
    for source in read(OUT/'historical_input_inventory.json'):
        if not source['available']:continue
        key=(source['release'],source['utility']);expected=contexts[key]
        for ref in source['files'].values():assert sha(ROOT/ref['path'])==ref['sha256']
        folder=output/key[0]/key[1];folder.mkdir(parents=True)
        environment=read(ROOT/source['files']['launch.json']['path'])['environment']
        command=[sys.executable,str(HERE/'study.py'),'--graph-input',str(ROOT/source['files']['raw.json']['path']),
                 '--root',expected['entry'],'--output',str(folder)]
        write(folder/'launch.json',{'argv':command,'environment':environment,'method_fingerprint':fingerprint})
        with (folder/'stdout').open('w') as stdout,(folder/'stderr').open('w') as stderr:
            subprocess.run(command,cwd=ROOT,env=environment,stdout=stdout,stderr=stderr,timeout=900,check=True)
        actual=sha(folder/'graph.json')
        assert actual==expected['graph_sha256']==sha(ROOT/expected['graph_artifact']),key
        assert read(folder/'gate.json')['status']=='PASS'
        results.append({'release':key[0],'utility':key[1],'status':'PASS','graph_sha256':actual})
        write(output/'progress.json',results);print(*key,'canonical graph byte equality PASS',flush=True)
    assert len(results)==28
    write(output/'result.json',{'status':'PASS','contexts':28,'method_fingerprint':fingerprint,'results':results,
          'replication':'Fresh processes and output directories; equality to both previously identical canonical graph runs',
          'points_to_solver_used':False})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True)
    main(p.parse_args().output)
