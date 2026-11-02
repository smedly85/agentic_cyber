"""Independent observable-contract spot checks. Run only in the oracle Docker."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
from linux_benchmark import environment


def verify():
    environment()
    checks = {}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for utility in ('cp', 'mv'):
            (root / 'src').write_bytes(b'new')
            (root / 'dst').write_bytes(b'old')
            result = subprocess.run(['/opt/gnu/bin/' + utility, '-i', 'src', 'dst'],
                                    cwd=root, input=b'n\n', capture_output=True)
            checks[utility + '_decline_status'] = result.returncode
            assert result.returncode == 1 and (root / 'dst').read_bytes() == b'old'
        for mode, expected in (('+t', 0o1755), ('a+t', 0o1755), ('a=rwx,+t', 0o1777), ('1777', 0o1777)):
            target = root / ('mode-' + str(len(checks)))
            subprocess.run(['/opt/gnu/bin/mkdir', '-m', mode, str(target)], check=True, umask=0o022)
            actual = target.stat().st_mode & 0o7777
            checks['mkdir_' + mode] = oct(actual)
            assert actual == expected, (mode, oct(actual), oct(expected))
        for flags, expected in ((['-c', '-f'], 1), (['-c', '-f', '-u'], 1)):
            result = subprocess.run(['/opt/gnu/bin/sort', *flags], input=b'a\nA\n', capture_output=True)
            checks['sort_' + ''.join(flags)] = result.returncode
            assert result.returncode == expected and not result.stdout and result.stderr
    return checks


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
