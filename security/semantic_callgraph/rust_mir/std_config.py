"""One rebuilt-library configuration for controlled MIR extraction.

Reuse Cargo's successful build-std invocation as argv, never as shell input.
The rlib digests are recorded alongside each run for reproducibility.
"""
import hashlib
import json
from pathlib import Path
from probe import BASE


def rebuilt_std_flags(output):
    evidence = BASE / 'built-std-inspection/core-v2/result.json'
    record = json.loads(evidence.read_text())
    argv = record['rustc_argv']
    flags = []
    libraries = {}
    for index, arg in enumerate(argv[:-1]):
        value = argv[index + 1]
        if arg == '--extern' and value.startswith('noprelude:'):
            name, filename = value.split('=', 1)
            path = Path(filename)
            libraries[name.removeprefix('noprelude:')] = {
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'artifact': path.name,
            }
            flags.extend([arg, value])
        elif arg == '-L' and value.startswith('dependency='):
            flags.extend([arg, value])
    assert {'core', 'alloc', 'std'} <= libraries.keys()
    flags.extend(['-Z', 'unstable-options'])
    policy = {'policy': 'uniform_rebuilt_std', 'libraries': libraries,
              'mir_opt_level': 0, 'inline_mir': False, 'always_encode_mir': True,
              'target': 'x86_64-unknown-linux-gnu', 'build_label': 'core-v1', 'panic':'unwind'}
    (output / 'std_configuration.json').write_text(json.dumps(policy, sort_keys=True, indent=2) + '\n')
    return flags
