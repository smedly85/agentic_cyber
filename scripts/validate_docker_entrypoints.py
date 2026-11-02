"""Exercise controller commands without an LLM or a retained candidate seed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import argparse
from docker_benchmark import ROOT
from stage_test_bundle import build_payload, resolve_checkpoint, write_bundle

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--utility',default='c-cp')
args=parser.parse_args()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
manifest = json.loads((ROOT/f'experiments/utilities/{args.utility}.json').read_text())
results = {}
with tempfile.TemporaryDirectory() as directory:
    work = Path(directory)
    source = work / manifest['source_path']
    source.parent.mkdir(parents=True)
    source.write_text({'.c':'int main(void) { return 0; }\n','.rs':'fn main() {}\n','.py':'pass\n'}[source.suffix])
    test_dir, checkpoint = resolve_checkpoint(ROOT, args.utility, '000')
    write_bundle(build_payload(ROOT, test_dir, checkpoint, args.utility), work/test_dir)
    env = dict(os.environ, HELDOUT_ROOT=str(ROOT),
               VALIDATION_JSON_REPORT=str(output/'public.json'),
               HELDOUT_JSON_REPORT=str(output/'heldout.json'))
    commands = {'build': manifest['build_command'],
                'public': 'bash '+manifest['judge']+' '+manifest['executable_path'],
                'heldout': manifest['extra_test_command']}
    for name, command in commands.items():
        result = subprocess.run(['bash','-c',command],cwd=work,env=env,
                                capture_output=True,text=True,timeout=600)
        # Hidden details are never copied to a public repair log.
        (output/(name+'.log')).write_text(result.stdout+result.stderr)
        results[name] = result.returncode
        assert result.returncode == (0 if name=='build' else 1), (name,result.stderr)
    for name in ('public','heldout'):
        report=json.loads((output/(name+'.json')).read_text())
        assert report['counts'].get('FAIL',0)>0
        results[name+'_counts']=report['counts']
(output/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results))
