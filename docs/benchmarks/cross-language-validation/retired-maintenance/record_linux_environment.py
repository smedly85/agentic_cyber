"""Record Docker provenance and static plans; never execute a candidate."""
import json
import subprocess
from docker_benchmark import ROOT, settings
from linux_benchmark import static_report, SELECTORS

directory=ROOT/'docs/benchmarks/validation-amd64'
config=settings()
commands={
    'docker-version.json':['docker','version','--format','{{json .}}'],
    'docker-info.json':['docker','info','--format','{{json .}}'],
    'packages.txt':['docker','run','--rm','--network','none','--platform',config['platform'],config['oracle_image'],'cat','/provenance/packages.txt'],
    'compiler-image-inspect.json':['docker','image','inspect',config['compiler_image']],
}
for name,command in commands.items():
    result=subprocess.run(command,capture_output=True,check=True,timeout=60)
    (directory/name).write_bytes(result.stdout)
(ROOT/'docs/benchmarks/linux-utilities-static-report.json').write_text(
    json.dumps(static_report(SELECTORS),indent=2)+'\n')
print('Recorded Docker engine, compiler image, package inventory and final plan fingerprints')
