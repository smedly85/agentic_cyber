"""One candidate: stop all validation immediately on a failed equality check."""
import os,signal,subprocess,sys,time
from common import HERE,OUT,ROOT,read,write,sha
assert (OUT/'preservation_before.json').exists()
subprocess.run([sys.executable,str(HERE/'integrity.py')],cwd=ROOT,check=True)
workers={name:subprocess.Popen([sys.executable,str(HERE/name)],cwd=ROOT,start_new_session=True)
         for name in ('unit_mirror.py','compare_suite.py')}
failure=None
while any(p.poll() is None for p in workers.values()):
    failure=next(((name,p.returncode) for name,p in workers.items() if p.poll() not in (None,0)),None)
    if failure:break
    time.sleep(1)
failure=failure or next(((name,p.returncode) for name,p in workers.items() if p.poll() not in (None,0)),None)
if failure:
    for p in workers.values():
        try:os.killpg(p.pid,signal.SIGTERM)
        except ProcessLookupError:pass
    write(OUT/'validation_stop.json',{'status':'STOP','failure':failure,'candidate_sha256':sha(HERE/'inclusion.py')})
    raise SystemExit('STOP: equality validation failed; no historical runs permitted')
assert all(p.returncode==0 for p in workers.values())
write(OUT/'validation_complete.json',{'status':'PASS','candidate_sha256':sha(HERE/'inclusion.py'),
    'equality':read(OUT/'equality_summary.json'),'unit_mirror':read(OUT/'unit_mirror_summary.json')})
print('ALL VALIDATION PASS',flush=True)
