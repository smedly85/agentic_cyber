#!/usr/bin/env python3
"""Linux utilities preparation and bounded oracle validation.

Static inspection is host-safe. All other operations require the pinned Docker
environment. Candidate execution and formal runs remain disabled until a
separate, per-case execution adapter has been validated.
"""
from __future__ import annotations

import argparse
import base64
import copy
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
SELECTORS = ('c-cp', 'c-mv', 'c-mkdir', 'c-sort')


def read(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=1, ensure_ascii=True) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def environment():
    if platform.system() != 'Linux' or not Path('/.dockerenv').is_file():
        raise RuntimeError('Linux Docker is required; native execution is forbidden')
    if os.geteuid() == 0:
        raise RuntimeError('permission-sensitive validation must run as non-root')
    if subprocess.check_output(['uname', '-s'], text=True).strip() != 'Linux':
        raise RuntimeError('uname does not identify Linux')
    target = os.environ.get('BENCHMARK_ARCH')
    actual = platform.machine()
    if target not in ('aarch64', 'x86_64') or target != actual:
        raise RuntimeError(f'architecture mismatch: target={target!r}, actual={actual}')
    if platform.python_version() != '3.12.8':
        raise RuntimeError('Python 3.12.8 required')
    cc = subprocess.check_output(['gcc', '-dumpfullversion'], text=True).strip()
    if cc != '12.2.0':
        raise RuntimeError('GCC 12.2.0 required, got ' + cc)
    versions = {}
    for utility in ('cp', 'mv', 'mkdir', 'sort'):
        binary = '/opt/gnu/bin/' + utility
        line = subprocess.check_output([binary, '--version'], text=True).splitlines()[0]
        if line != f'{utility} (GNU coreutils) 9.11':
            raise RuntimeError('oracle identity mismatch: ' + line)
        versions[utility] = {'version': line, 'sha256': digest(Path(binary).read_bytes())}
    if os.environ.get('LC_ALL') != 'C' or os.environ.get('TZ') != 'UTC':
        raise RuntimeError('LC_ALL=C and TZ=UTC required')
    os.umask(0o022)
    image = os.environ.get('BENCHMARK_IMAGE_ID', '')
    if not image.startswith('sha256:') or len(image) != 71:
        raise RuntimeError('immutable Docker image ID must be supplied by host launcher')
    return {'os': platform.system(), 'architecture': actual, 'python': platform.python_version(),
            'gcc': cc, 'image_id': image, 'oracles': versions,
            'compiler': subprocess.check_output(['gcc', '--version'], text=True).splitlines()[0]}


def load_suite(selector):
    suite = REPO / 'tests' / (selector + '-test-suite')
    # Each utility uses an independently inherited engine. Avoid cross-suite
    # module caching when validating all four in one invocation.
    for name in ('engine', 'props', 'runner', 'config'):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(suite))
    try:
        engine = importlib.import_module('engine')
        runner = importlib.import_module('runner')
    finally:
        sys.path.pop(0)
    return suite, engine, runner


def frozen(case, engine, utility):
    c = copy.deepcopy(case)
    c.pop('linux_freeze_pending', None)
    result = engine.execute(c, ['/opt/gnu/bin/' + utility])
    if result.timed_out or result.signal_name == 'SKIP_ROOT':
        raise RuntimeError('oracle timeout or permission precondition failed')
    if result.crashed and result.signal_name not in c.get('allow_signals', []):
        raise RuntimeError('unexpected oracle signal')
    if not result.crashed and not c.pop('nondet_exit', False):
        c['exit_code'] = result.exit_code
    if c.get('check', 'golden') == 'golden':
        c['stdout_b64'] = base64.b64encode(result.stdout).decode()
        if utility == 'mkdir':
            c['tree'] = result.tree
        elif utility in ('cp', 'mv'):
            c['expected_tree'] = result.modes
    if c.pop('exact_stderr', False):
        c['stderr_b64'] = base64.b64encode(result.stderr).decode()
    else:
        c['stderr_class'] = 'nonempty' if result.stderr else 'empty'
    if 'output_file' in c:
        c['output_file']['contents_b64'] = base64.b64encode(
            result.outfiles.get(c['output_file']['path'], b'')).decode()
    return c


def freeze(selector, provenance):
    suite, engine, runner = load_suite(selector)
    inputs = read(suite / 'gen/inputs.json.gz')
    sys.path.insert(0, str(REPO / 'tests'))
    from reference_generators import heldout_contract
    public = [frozen(c, engine, selector[2:]) for c in inputs['public']]
    hidden = [frozen(c, engine, selector[2:]) for c in inputs['heldout']]
    metadata = {'benchmark': 'linux-utilities', 'environment': provenance,
                'input_sha256': digest((suite / 'gen/inputs.json.gz').read_bytes())}
    payload = {'suites/linux.json.gz': gzip.compress(encode({'cases': public}), mtime=0),
               'heldout/heldout_cases.json.gz': gzip.compress(encode(
                   heldout_contract.build(selector, metadata, hidden)), mtime=0)}
    metadata['sha256'] = {name: digest(data) for name, data in payload.items()}
    payload['suites/MANIFEST.json'] = encode(metadata)
    return payload


def write_new(root, payload):
    if root.exists():
        raise RuntimeError('refusing to overwrite an existing output directory: ' + str(root))
    root.mkdir(parents=True)
    for name, data in payload.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def verify_frozen_bundles(selector, payload):
    """Apply the existing bundle/isolation machinery to newly frozen bytes."""
    import stage_test_bundle
    sys.path.insert(0, str(REPO / 'tests'))
    from reference_generators import heldout_contract
    manifest = read(REPO / 'experiments/utilities' / (selector + '.json'))
    source = REPO / manifest['test_dir']
    private = json.loads(gzip.decompress(payload['heldout/heldout_cases.json.gz']))
    aliases = manifest['flag_aliases']
    options = frozenset(aliases) | frozenset(a for values in aliases.values() for a in values)
    from linux_benchmark_isolation import identifying_values
    needles = [v.encode('utf-8', 'surrogateescape') for c in private['cases']
               for v in identifying_values(selector, c, heldout_contract.scannable_values(c, public_options=options))]
    with tempfile.TemporaryDirectory(prefix='frozen-bundle-') as temp:
        root = Path(temp)
        suite = root / manifest['test_dir']
        suite.mkdir(parents=True)
        for name in (*stage_test_bundle.ALLOWED_FILES, 'config.json'):
            if (source / name).is_file():
                (suite / name).write_bytes((source / name).read_bytes())
        for name, data in payload.items():
            target = suite / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for checkpoint in manifest['checkpoints']:
            bundle = stage_test_bundle.build_payload(root, manifest['test_dir'], checkpoint, selector)
            for name, data in bundle['files'].items():
                if any(needle in data for needle in needles):
                    matches = [n for n in needles if n in data]
                    raise RuntimeError('frozen held-out value overlap in ' + selector + ': ' + name + ': ' + repr(matches[:1]))
                if name.startswith('suites/'):
                    for case in json.loads(data)['cases']:
                        if not set(case.get('flags', [])) <= set(checkpoint['implemented_flags']):
                            raise RuntimeError('future-checkpoint input leaked into bundle')


def static_report(selectors):
    import lineage_plan
    import stage_test_bundle
    import checkpoint_boundary_gate
    report = {'status': 'Static plans plus recorded Docker oracle evidence; no new functional execution', 'utilities': {}}
    for selector in selectors:
        plan = lineage_plan.resolve_plan(REPO, selector, '', '0', None, 0, 0)
        inputs = read(REPO / plan['test_dir'] / 'gen/inputs.json.gz')
        evidence_path = REPO / plan['test_dir'] / 'validation.json'
        evidence = read(evidence_path) if evidence_path.exists() else None
        rows = []
        for checkpoint in plan['checkpoints']:
            bundle = stage_test_bundle.build_payload(REPO, plan['test_dir'], checkpoint, selector)
            implemented = set(checkpoint['implemented_flags'])
            rows.append({'checkpoint': checkpoint['id'],
                         'public_inputs': bundle['manifest']['cases_included'],
                         'heldout_inputs': sum(set(c.get('flags', [])) <= implemented for c in inputs['heldout']),
                         'oracle_cases_executed': 0, 'functional_pass': None, 'functional_fail': None,
                         'bundle_fingerprint': bundle['manifest']['bundle_fingerprint']})
            if evidence:
                row = next(r for r in evidence['checkpoints'] if r['checkpoint'] == checkpoint['id'])
                passed = row['public'].get('PASS', 0) + row['heldout'].get('PASS', 0)
                rows[-1].update(oracle_cases_executed=passed, functional_pass=passed, functional_fail=0,
                                oracle_public_counts=row['public'], oracle_heldout_counts=row['heldout'],
                                recorded_environment=evidence['environment'])
            assert all(not f.startswith(('heldout/', 'gen/')) for f in bundle['files'])
            assert (REPO / checkpoint['prompt']).is_file()
        assert selector in checkpoint_boundary_gate.PROBES
        report['utilities'][selector] = rows
    return report


def validate(selector, provenance, output):
    first = freeze(selector, provenance)
    second = freeze(selector, provenance)
    if first != second:
        raise RuntimeError('repeat freeze differs; no corpus published')
    verify_frozen_bundles(selector, first)
    suite, engine, runner = load_suite(selector)
    manifest = read(REPO / 'experiments/utilities' / (selector + '.json'))
    rows = []
    with tempfile.TemporaryDirectory(prefix='linux-benchmark-') as temp:
        work = Path(temp)
        for checkpoint in manifest['checkpoints']:
            config = read(suite / 'config.json')
            config['implemented'] = checkpoint['implemented_flags']
            config_file = work / 'config.json'
            config_file.write_bytes(encode(config))
            row = {'checkpoint': checkpoint['id']}
            for kind, name in [('public', 'suites/linux.json.gz'),
                               ('heldout', 'heldout/heldout_cases.json.gz')]:
                corpus = work / (kind + '.json.gz')
                corpus.write_bytes(first[name])
                report_path = work / (kind + '-report.json')
                command = [sys.executable, str(suite / 'runner.py'), str(corpus),
                           '--config', str(config_file), '--jobs', '1', '--json-report', str(report_path),
                           '--', '/opt/gnu/bin/' + selector[2:]]
                result = subprocess.run(command, capture_output=True, timeout=600)
                if result.returncode != 0 or not report_path.is_file():
                    if kind == 'public':
                        print(result.stdout.decode(errors='replace')[-12000:], file=sys.stderr)
                        print(result.stderr.decode(errors='replace')[-3000:], file=sys.stderr)
                    # Keep hidden concrete failures controller-only.
                    raise RuntimeError(f'{selector} {checkpoint["id"]} {kind} oracle self-pass failed')
                row[kind] = read(report_path)['counts']
                if not row[kind].get('PASS') or any(row[kind].get(k, 0) for k in
                                                  ('XFAIL', 'FAIL', 'TIMEOUT', 'SANITIZER', 'CRASH')):
                    raise RuntimeError('oracle self-pass did not produce an unqualified scored pass')
                # Controlled mutation of assertions, not a supplied candidate
                # implementation: every selected normal exit expectation is wrong.
                payload = json.loads(gzip.decompress(first[name]))
                mutated = 0
                for case in payload['cases']:
                    if set(case.get('flags', [])) <= set(config['implemented']) and 'exit_code' in case:
                        case['exit_code'] = 73
                        mutated += 1
                if not mutated:
                    raise RuntimeError('no mutation-sensitive cases selected')
                corpus.write_bytes(gzip.compress(encode(payload), mtime=0))
                result = subprocess.run(command, capture_output=True, timeout=600)
                if result.returncode != 1:
                    raise RuntimeError('controlled assertion mutation not detected as candidate failure')
                row[kind + '_mutation_detected'] = True
            rows.append(row)
    first['validation.json'] = encode({'environment': provenance, 'checkpoints': rows,
                                      'deterministic_freeze': True,
                                      'frozen_bundle_isolation': True,
                                      'candidate_isolation': 'Oracle-only job; see separate Docker adapter validation'})
    write_new(output, first)
    return {'utility': selector, 'output': str(output), 'checkpoints': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('static', 'verify', 'freeze', 'validate', 'build'))
    parser.add_argument('--utility', choices=SELECTORS, action='append')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    selectors = args.utility or list(SELECTORS)
    if args.action == 'static':
        report = static_report(selectors)
    elif args.action == 'build':
        raise RuntimeError('Formal candidate compilation disabled pending Docker adapter validation')
    else:
        provenance = environment()
        if args.action == 'verify':
            # Compiler probe is an object-only translation unit, never a utility
            # implementation, seed, executable or lineage artifact.
            with tempfile.TemporaryDirectory() as temp:
                subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                                '-x', 'c', '-c', '-o', str(Path(temp) / 'probe.o'), '-'],
                               input=b'int benchmark_compiler_probe;\n', check=True, timeout=30)
            report = provenance
        else:
            if args.output is None:
                raise RuntimeError('--output must name a new directory')
            if args.output.exists():
                raise RuntimeError('output already exists; use a fresh directory')
            reports = []
            for selector in selectors:
                target = args.output / selector
                if args.action == 'freeze':
                    write_new(target, freeze(selector, provenance))
                    reports.append({'utility': selector, 'status': 'frozen but not self-checked'})
                else:
                    reports.append(validate(selector, provenance, target))
            report = reports
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print('INFRASTRUCTURE ERROR: ' + str(error), file=sys.stderr)
        raise SystemExit(2)
