"""Calibrate the isolated adapter with GNU reference executables, not lineages.

Every invocation runs inside Docker. Host temporary binaries are data only.
The final checkpoint covers all cumulative inputs; oracle self-checks separately
exercise all fifteen checkpoint filters.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import docker_benchmark as docker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--utility', choices=docker.SELECTORS, action='append')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {}
    with tempfile.TemporaryDirectory() as directory:
        for selector in args.utility or docker.SELECTORS:
            if docker.utility_name(selector) == 'grep':
                # GNU grep needs the contract adapter (-a -F plus deterministic
                # recursion), so raw-binary calibration would test the wrong
                # program. Canonical oracle self-passes cover functional
                # semantics; runtime/boundary tests cover each language jail.
                validation = json.loads((docker.ROOT / 'tests/c-grep-test-suite/validation.json').read_text())
                result[selector] = {}
                for hidden in (False, True):
                    label = 'heldout' if hidden else 'public'
                    record = {
                        'status': 0,
                        'scope': 'canonical GNU grep adapter self-pass; raw-binary calibration not applicable',
                        'checkpoints': [
                            {'checkpoint': row['checkpoint'], 'counts': row[label]}
                            for row in validation['checkpoints']
                        ],
                    }
                    result[selector][label] = record
                    (args.output / (selector + '-' + label + '.json')).write_text(
                        json.dumps(record, indent=2) + '\n')
                (args.output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
                continue
            config = docker.settings()
            binary = Path(directory) / selector
            # Transfer bytes only; no native execution and no source seed.
            data = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none',
                                            '--platform', config['platform'], config['oracle_image'],
                                            'cat', '/opt/gnu/bin/' + docker.utility_name(selector)], timeout=30)
            binary.write_bytes(data)
            binary.chmod(0o755)
            manifest = json.loads((docker.ROOT / 'experiments/utilities' / (selector + '.json')).read_text())
            flags = manifest['checkpoints'][-1]['implemented_flags']
            result[selector] = {}
            for hidden in (False, True):
                label = 'heldout' if hidden else 'public'
                print(selector + ' ' + label + ': Docker calibration starting', flush=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    verdict = docker.judge(selector, binary, flags, hidden=hidden,
                                           report_path=args.output / (selector + '-' + label + '.json'),
                                           calibration_native=True)
                result[selector][label] = {'status': verdict['status'], 'counts': verdict['report']['counts']}
                (args.output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
                print(selector + ' ' + label + ': ' + json.dumps(result[selector][label]), flush=True)
                if verdict['status']:
                    raise SystemExit(1)


if __name__ == '__main__':
    main()
