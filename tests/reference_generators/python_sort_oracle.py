"""Darwin-only GNU 9.11 SORT freezing; pending recipes are never judgeable.

The four stdin-interface rejection cases are specification assertions, explicitly
not GNU goldens. Full GNU accepts operands/-- whereas this bounded ladder does
not. The offline selfcheck adapter enforces only that interface and delegates all
supported behavior to the verified GNU binary. It is never a candidate or seed.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import sys
import tempfile

from reference_generators import heldout_contract, python_oracle
from reference_generators.python_sort_cases import public_cases
from reference_generators.python_sort_heldout import heldout_cases
from reference_generators.transfer_oracle import frozen, load_engine, oracle, render


def artifacts(suite, binary=None, version=None):
    ready = binary is not None
    if ready and platform.system() != 'Darwin':
        raise ValueError('platform incompatible: requires Darwin GNU 9.11 generation')
    engine = load_engine(suite)
    groups = [public_cases(), heldout_cases()]
    for cases in groups:
        for index, case in enumerate(cases):
            with tempfile.TemporaryDirectory() as temp:
                engine.validate_case(case, Path(temp).resolve())
            if not ready:
                # Null is an explicit unknown, never an expected GNU result.
                cases[index] = dict(case, exit_code=None, oracle_pending=True)
            elif case.get('scope_error'):
                cases[index] = dict(case, exit_code=2, stdout_b64='',
                                    stderr_class='nonempty', expected_tree={})
            else:
                cases[index] = frozen(case, engine, binary)
    provenance = dict(project='GNU Coreutils', version='9.11',
                      role='functional_behavioral_oracle',
                      status='validated' if ready else 'pending-darwin-generation')
    if ready:
        provenance['version_line'] = version
    files = {
        'suites/cases.json.gz': gzip.compress(render(dict(schema_version=1, cases=groups[0])), mtime=0),
        'heldout/heldout_cases.json.gz': gzip.compress(render(
            heldout_contract.build('python-sort', provenance, groups[1])), mtime=0),
    }
    ladder = [[], ['-r'], ['-r','-f'], ['-r','-f','-u'], ['-r','-f','-u','-c']]
    manifest = dict(schema_version=1, functional_oracle=provenance,
                    status=provenance['status'],
                    platform_contract='Darwin; GNU Coreutils 9.11; LC_ALL=C; binary pipe I/O; stdin only',
                    scope_exceptions='scope_error cases assert bounded argument rejection, not GNU behavior',
                    counts=dict(public=len(groups[0]), heldout=len(groups[1])),
                    cumulative_counts=[dict(checkpoint=f'{i:03}', public=sum(set(c['flags']) <= set(flags) for c in groups[0]),
                                            heldout=sum(set(c['flags']) <= set(flags) for c in groups[1])) for i,flags in enumerate(ladder)],
                    sha256={k:hashlib.sha256(v).hexdigest() for k,v in files.items()})
    files['suites/MANIFEST.json'] = render(manifest)
    return files


def selfcheck(suite, binary):
    # This temporary controller-only adapter handles the narrower argv contract,
    # never sorting data itself. All supported calls reach the pinned GNU oracle.
    with tempfile.TemporaryDirectory(prefix='sort-oracle-interface-') as temp:
        adapter = Path(temp)/'oracle-interface'
        source = Path(temp)/'interface.py'
        source.write_text('''import os, sys
args = sys.argv[1:]
aliases = {'--reverse', '--ignore-case', '--unique', '--check'}
if any(a not in aliases and not (a.startswith('-') and not a.startswith('--') and len(a) > 1 and set(a[1:]) <= set('rfuc')) for a in args):
    print('invalid argument for bounded stdin interface', file=sys.stderr)
    sys.exit(2)
os.execv('''+repr(binary)+''', ['''+repr(binary)+''', *args])
''')
        adapter.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' -B '+shlex.quote(str(source))+' "$@"\n')
        adapter.chmod(0o755)
        python_oracle.selfcheck(suite, 'sort', str(adapter))


def main(suite, utility='sort'):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--write-pending', action='store_true', help='write deterministic, unjudgeable recipes without claiming oracle validation')
    args = parser.parse_args()
    try:
        if args.audit:
            python_oracle.audit(suite, utility)
            manifest = json.loads((suite/'suites/MANIFEST.json').read_text())
            print('Corpus status: '+manifest['status'])
            return 0
        if args.write_pending:
            if args.check:
                raise ValueError('--write-pending cannot be combined with --check')
            first = artifacts(suite)
            second = artifacts(suite)
        else:
            if platform.system() != 'Darwin':
                raise ValueError('platform incompatible: requires Darwin; finalize on vessel')
            if os.geteuid() == 0:
                raise ValueError('GNU freeze/selfcheck requires a non-root user')
            binary, version = oracle('sort')
            first = artifacts(suite, binary, version)
            second = artifacts(suite, binary, version)
        if first != second:
            raise ValueError('nondeterministic corpus generation')
        for name, data in first.items():
            path = suite/name
            if args.check:
                if not path.is_file() or path.read_bytes() != data:
                    raise ValueError('stale artifact: '+name)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        python_oracle.audit(suite, utility)
        if args.check:
            selfcheck(suite, binary)
        print('Pending recipes only; NOT ready for experiments' if args.write_pending else 'Darwin GNU 9.11 deterministic generation verified')
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
