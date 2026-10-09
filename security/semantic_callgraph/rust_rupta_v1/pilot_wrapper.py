#!/usr/bin/env python3
"""Select exactly the chmod binary for PTA; preserve Cargo's other rustc calls."""
import json
import os
from pathlib import Path
import subprocess
import sys

args=sys.argv[1:]
def value(flag):
    return args[args.index(flag)+1] if flag in args else None

if value('--crate-name')=='chmod' and value('--crate-type')=='bin':
    out=Path(os.environ['RUPTA_PILOT_OUTPUT'])
    command=['/usr/bin/time','-v','-o',str(out/'analysis.resources.txt'),os.environ['RUPTA_PILOT_PTA'],*args[1:]]
    with (out/'analysis-command.json').open('x') as f:
        json.dump({'argv':command,'cwd':os.getcwd(),'PTA_FLAGS':json.loads(os.environ['PTA_FLAGS'])},f,indent=2)
    result=subprocess.run(command)
    (out/'analysis-exit.json').write_text(json.dumps({'returncode':result.returncode}))
    sys.exit(result.returncode)
os.execv(args[0],args)
