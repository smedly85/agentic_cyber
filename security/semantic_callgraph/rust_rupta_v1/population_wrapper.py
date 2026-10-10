#!/usr/bin/env python3
"""Capture authenticated Cargo invocations; never alter compiler arguments."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

args = sys.argv[1:]
def value(flag):
    return args[args.index(flag) + 1] if flag in args else None

out = Path(os.environ['RUPTA_CAPTURE'])
record = {'argv': args, 'cwd': os.getcwd(), 'crate': value('--crate-name'),
          'crate_type': value('--crate-type'), 'edition': value('--edition'),
          'package': os.environ.get('CARGO_PKG_NAME'),
          'package_version': os.environ.get('CARGO_PKG_VERSION'),
          'manifest_dir': os.environ.get('CARGO_MANIFEST_DIR')}
path = out / ('invocation-' + uuid.uuid4().hex + '.json')
code = subprocess.call(args)
record['returncode'] = code
path.write_text(json.dumps(record, indent=2))
if value('--crate-name') == os.environ['RUPTA_EXECUTABLE'] and value('--crate-type') == 'bin':
    (out / 'binary-command.json').write_text(json.dumps(record, indent=2))
sys.exit(code)
