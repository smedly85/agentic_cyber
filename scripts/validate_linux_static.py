"""Run trusted contract/static checks inside Docker; no Docker socket is mounted."""
from pathlib import Path
import json
import subprocess
import argparse
import uuid
import re
from docker_benchmark import ROOT, settings

config = settings()
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
output=parser.parse_args().output
output.mkdir(parents=True, exist_ok=False)
image_id = config['oracle_image']
if '@' in image_id:
    image_id = subprocess.check_output(['docker', 'image', 'inspect', '--platform', config['platform'],
                                        '--format', '{{.Id}}', image_id], text=True, timeout=30).strip()
if not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id):
    raise ValueError('invalid local oracle image ID')
volume = 'linux-static-' + uuid.uuid4().hex
loader = volume + '-loader'
common = ['docker','run','--rm','--pull','never','--platform',config['platform'],'--network','none',
          '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
          '--mount',f'type=volume,source={volume},target=/work,readonly',
          '--tmpfs','/tmp:rw,exec,nosuid,nodev,size=512m',
          '-e','BENCHMARK_ARCH='+('x86_64' if config['platform']=='linux/amd64' else 'aarch64'),'-e','BENCHMARK_IMAGE_ID='+image_id,
          config['oracle_image']]
checks = {
    'syntax': ['python3','-c', '''import ast, pathlib, subprocess
paths=list(pathlib.Path('scripts').glob('*.py'))+list(pathlib.Path('scripts/validation').glob('*.py'))
for path in paths: ast.parse(path.read_text(), filename=str(path))
shells=[pathlib.Path('scripts/run_experiment.sh'),pathlib.Path('scripts/run_lineage_experiment.sh')]+list(pathlib.Path('docker/linux-utilities').glob('*.sh'))+list(pathlib.Path('tests').glob('c-*-test-suite/*.sh'))+list(pathlib.Path('tests').glob('rust-*-test-suite/*.sh'))+list(pathlib.Path('tests').glob('py-*-test-suite/*.sh'))
for path in shells: subprocess.run(['bash','-n',str(path)],check=True)
print(f'{len(paths)} Python files parsed; {len(shells)} shell syntax checks passed')'''],
    'contract': ['python3','scripts/check_linux_contract.py'],
    'static': ['python3','-B','scripts/run_vessel_validation_tests.py','--suite','integrity'],
    'isolation': ['python3','scripts/check_heldout_isolation.py',
                  '--utility','c-cp','--utility','c-mv','--utility','c-mkdir','--utility','c-sort'],
}
results={}
try:
    subprocess.run(['docker', 'volume', 'create', volume], check=True, capture_output=True, timeout=30)
    # Copy only validation inputs through the API into a never-started loader.
    subprocess.run(['docker', 'create', '--pull', 'never', '--name', loader,
                    '--platform', config['platform'], '--network', 'none', '--read-only',
                    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--mount', f'type=volume,source={volume},target=/work',
                    config['oracle_image'], 'true'], check=True, capture_output=True, timeout=30)
    for directory in ('scripts', 'tests', 'experiments', 'prompts', 'docs', 'docker'):
        subprocess.run(['docker', 'cp', str(ROOT / directory), loader + ':/work/'],
                       check=True, capture_output=True, timeout=180)
    for name, command in checks.items():
        result = subprocess.run(common+command,capture_output=True,text=True,timeout=180)
        (output/(name+'.log')).write_text(result.stdout+result.stderr)
        results[name] = result.returncode
        print(name, result.returncode, result.stdout[-1000:], result.stderr[-1000:])
finally:
    try:
        subprocess.run(['docker', 'rm', '-fv', loader], check=True, capture_output=True, timeout=30)
    finally:
        subprocess.run(['docker', 'volume', 'rm', volume], check=True, capture_output=True, timeout=30)
(output/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
raise SystemExit(1 if any(results.values()) else 0)
