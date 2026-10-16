"""Freeze and self-check Python suites through the existing filesystem engine.

Only offline tooling imports this module. Goldens always come from independently
installed GNU Coreutils 9.11; no candidate implementation is supplied.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from reference_generators import heldout_contract, python_cases
from reference_generators.transfer_oracle import frozen, load_engine, oracle, render


def artifacts(suite, utility, binary, version):
    engine = load_engine(suite)
    public = python_cases.definitions(utility)
    private = python_cases.heldout(utility, public)
    for case in public + private:
        with tempfile.TemporaryDirectory() as temp:
            engine.validate_case(case, Path(temp).resolve())
    public = [frozen(c, engine, binary) for c in public]
    private = [frozen(c, engine, binary) for c in private]
    provenance = dict(project='GNU Coreutils', version='9.11', version_line=version,
                      role='functional_behavioral_oracle')
    private_payload = heldout_contract.build('python-' + utility, provenance, private)
    files = {'suites/cases.json.gz': gzip.compress(render(dict(schema_version=1, cases=public)), mtime=0),
             'heldout/heldout_cases.json.gz': gzip.compress(render(private_payload), mtime=0)}
    manifest = dict(schema_version=1, functional_oracle=provenance,
                    platform_contract=('Linux' if utility == 'mkdir' else 'POSIX Linux/Darwin') + '; non-root permission tests; C locale; pipe output',
                    counts=dict(public=len(public), heldout=len(private)),
                    sha256={k:hashlib.sha256(v).hexdigest() for k,v in files.items()})
    files['suites/MANIFEST.json'] = render(manifest)
    return files


def audit(suite, utility):
    repo = suite.parents[1]
    name = 'python-' + utility
    manifest = json.loads((suite/'suites/MANIFEST.json').read_text())
    for path, digest in manifest['sha256'].items():
        if hashlib.sha256((suite/path).read_bytes()).hexdigest() != digest:
            raise ValueError('corpus hash mismatch: ' + path)
    ladder = json.loads((repo/f'experiments/utilities/{name}.json').read_text())
    public = json.loads(gzip.decompress((suite/'suites/cases.json.gz').read_bytes()))['cases']
    private = heldout_contract.load(suite)
    errors = heldout_contract.corpus_invariants(private, [c['implemented_flags'] for c in ladder['checkpoints']])
    if errors:
        raise ValueError('; '.join(errors))
    public_names = {c['name'] for c in public}
    if len(public_names) != len(public) or any(c['dual_of'] not in public_names for c in private['cases']):
        raise ValueError('duplicate names or missing public dual')
    sys.path.insert(0, str(repo/'scripts'))
    import stage_test_bundle
    import check_heldout_isolation
    all_flags = set(ladder['checkpoints'][-1]['implemented_flags'])
    for checkpoint in ladder['checkpoints']:
        payload = stage_test_bundle.build_payload(repo, ladder['test_dir'], checkpoint, name)
        content = b'\n'.join(payload['files'].values()) + render(payload['manifest'])
        for flag in all_flags - set(checkpoint['implemented_flags']):
            for spelling in [flag, *ladder['flag_aliases'].get(flag, [])]:
                if re.search(rb'(?<![\w-])'+re.escape(spelling.encode())+rb'(?![\w-])', content):
                    raise ValueError('future option in bundle: ' + spelling)
    leaks, _, _ = check_heldout_isolation.scan_utility(repo, name)
    if leaks:
        raise ValueError('; '.join(leaks))
    print(name + ': hashes, cumulative flags and held-out isolation passed')


def selfcheck(suite, utility, binary):
    """Exercise the actual staged judge and isolated held-out wrapper at every rung."""
    repo = suite.parents[1]
    sys.path.insert(0, str(repo/'scripts'))
    import stage_test_bundle
    ladder = json.loads((repo/f'experiments/utilities/python-{utility}.json').read_text())
    for checkpoint in ladder['checkpoints']:
        with tempfile.TemporaryDirectory(prefix='python-suite-check-') as temp:
            work = Path(temp)
            target = work/ladder['test_dir']
            payload = stage_test_bundle.build_payload(repo, ladder['test_dir'], checkpoint, ladder['utility'])
            stage_test_bundle.write_bundle(payload, target)
            report_path = work/'public.json'
            hidden_report = work/'heldout.json'
            env = dict(os.environ, PYTHON_BIN=sys.executable, PYTHONDONTWRITEBYTECODE='1',
                       VALIDATION_JSON_REPORT=str(report_path))
            subprocess.run(['bash', str(target/'judge_candidate.sh'), binary, *checkpoint['implemented_flags']],
                           cwd=work, env=env, check=True)
            subprocess.run([sys.executable, '-B', str(repo/'scripts/heldout_judge.py'),
                            '--utility', ladder['utility'], '--test-dir', ladder['test_dir'],
                            '--candidate', binary, '--workdir', str(work), '--json-report', str(hidden_report)], cwd=work, env=env, check=True)
            report = json.loads(report_path.read_text())
            if report['counts'].get('SKIP') or report['counts'].get('FAIL'):
                raise ValueError('self-check must execute every selected public case')
            hidden = json.loads(hidden_report.read_text())
            expected = sum(set(c['flags']) <= set(checkpoint['implemented_flags'])
                           for c in heldout_contract.load(suite)['cases'])
            if hidden['counts'].get('PASS') != expected or hidden['counts'].get('FAIL'):
                raise ValueError('self-check must pass every selected held-out case')
            print(f"{ladder['utility']} {checkpoint['id']}: public and held-out GNU self-pass")


def main(suite, utility):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    try:
        if args.audit:
            audit(suite, utility)
            return 0
        if os.name != 'posix' or os.geteuid() == 0:
            raise ValueError('GNU freeze/self-check requires a non-root POSIX host')
        required = json.loads((suite/'config.json').read_text()).get('required_platform')
        if required and required != platform.system():
            raise ValueError(f'platform incompatible: requires {required}')
        binary, version = oracle(utility)
        first = artifacts(suite, utility, binary, version)
        if first != artifacts(suite, utility, binary, version):
            raise ValueError('nondeterministic GNU outcomes')
        for name, data in first.items():
            path = suite/name
            if args.check:
                if not path.is_file() or path.read_bytes() != data:
                    raise ValueError('stale artifact: ' + name)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        audit(suite, utility)
        if args.check:
            selfcheck(suite, utility, binary)
        print('GNU 9.11 deterministic generation verified: python-' + utility)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2
