#!/usr/bin/env python3
"""Cargo rustc wrapper, controlled fixture only; never silently skips a crate."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    rustc, *args = sys.argv[1:]
    if '--crate-name' not in args or '--print' in args or any(a.startswith('--print=') for a in args):
        return subprocess.call([rustc, *args])
    directory = Path(os.environ['MIR_CARGO_EVIDENCE'])
    crate = args[args.index('--crate-name') + 1]
    metadata = next((a for a in args if a.startswith('metadata=')), 'none')
    key = crate + '-' + hashlib.sha256(metadata.encode()).hexdigest()[:12]
    output = directory / (key + '.api.json')
    env = os.environ.copy()
    env.update(MIR_PROBE_OUTPUT=str(output), MIR_PROBE_CONTINUE='1', MIR_PROBE_TRANSITIVE='1')
    result = subprocess.run([env['MIR_CARGO_DRIVER'], *args], env=env)
    evidence = {'crate': crate, 'rustc': rustc, 'rustc_invocation': [rustc, *args],
                'driver_invocation': [env['MIR_CARGO_DRIVER'], *args], 'exit_code': result.returncode,
                'package': os.environ.get('CARGO_PKG_NAME'), 'package_version': os.environ.get('CARGO_PKG_VERSION'),
                'features': [args[i + 1] for i, a in enumerate(args[:-1]) if a == '--cfg' and args[i + 1].startswith('feature=')],
                'edition': next((a.split('=', 1)[1] for a in args if a.startswith('--edition=')), '2015'),
                'target': args[args.index('--target') + 1] if '--target' in args else 'host',
                'profile': 'dev', 'panic_strategy': 'unwind', 'encoded_mir_requested': 'always-encode-mir' in args,
                'mir_extracted': output.exists()}
    (directory / (key + '.invocation.json')).write_text(json.dumps(evidence, sort_keys=True, indent=2) + '\n')
    if result.returncode == 0 and not output.exists():
        raise RuntimeError('Compilation completed without MIR evidence for ' + crate)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
