"""Run existing read-only regression checks, saving logs under build/."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time

root=Path.cwd()
out=root/'build/rupta-v1'/('regression-'+sys.argv[1])
out.mkdir(parents=True,exist_ok=False)
env=dict(os.environ,PYTHONPATH=str(root))
commands=[
 ['python3','-m','security.historical.rust.semantic_gate'],
 ['python3','security/semantic_callgraph/rust_mir_lightweight/verify_results.py','--output',str(out/'verify.json')],
 ['python3','security/semantic_callgraph/rust_mir_lightweight/integrity.py','--output',str(out/'integrity.json')],
 ['python3','-m','pytest','-q','security/semantic_callgraph/cross_language_calibration/test_revision_freeze.py','security/semantic_callgraph/rust_mir/test_dependency_inputs.py'],
 ['python3','-m','pytest','-q','tests'],
]
results=[]
for i,cmd in enumerate(commands):
    start=time.monotonic()
    with (out/f'{i}.log').open('w') as log:
        try:
            result=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=900)
            status={'returncode':result.returncode}
        except subprocess.TimeoutExpired:
            status={'returncode':None,'status':'timeout'}
    results.append({'argv':cmd,'seconds':time.monotonic()-start,**status})
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print(i,status,flush=True)
