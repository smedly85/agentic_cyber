"""Bounded checks: host orchestration only; candidates always run via Docker."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import docker_benchmark as docker

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--only',choices=('static','integration','c-integration'))
args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=False)
config=docker.settings()
base=['docker','run','--rm','--platform',config['platform'],'--network','none','--read-only',
      '--cap-drop','ALL','--security-opt','no-new-privileges','--cpus','2','--memory','2g','--pids-limit','128',
      '--mount',f'type=bind,source={docker.ROOT},target=/work,readonly','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=512m',
      '-e','BENCHMARK_ARCH='+('x86_64' if config['platform']=='linux/amd64' else 'aarch64'),
      '-e','BENCHMARK_IMAGE_ID='+config['oracle_image'],config['oracle_image']]
commands={
 'static':base+['python3','tests/test_cross_language_static.py'],
 'integration':[sys.executable,str(docker.ROOT/'tests/test_cross_language_docker.py')],
 'c-integration':[sys.executable,str(docker.ROOT/'tests/test_docker_benchmark_integration.py')],
}
results={}
for name,command in commands.items():
    if args.only and args.only!=name: continue
    print(name+': starting',flush=True)
    result=subprocess.run(command,capture_output=True,text=True,timeout=1800)
    (args.output/(name+'.log')).write_text(result.stdout+result.stderr)
    results[name]=result.returncode
    (args.output/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
    print(name+': '+str(result.returncode)+'\n'+result.stderr[-1800:],flush=True)
raise SystemExit(1 if any(results.values()) else 0)
