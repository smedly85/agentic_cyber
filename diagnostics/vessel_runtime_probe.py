#!/usr/bin/env python3
"""Temporary trusted-only Vessel investigation. Never produces formal evidence."""
import argparse
import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


LIMIT_EXPR = """    address_space = (resource.RLIM_INFINITY if os.environ.get('BENCHMARK_DIAGNOSTIC_ROSETTA') == '1'
                     else 8 * 1024**3 if profile == 'vessel-8g' else 256 * 1024**2)"""


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('worker layout changed; refusing substitution: ' + old[:80])
    return text.replace(old, new, 1)


def worker_source(source, limit, instrument):
    source = replace_once(source, LIMIT_EXPR,
                          '    address_space = ' + ('resource.RLIM_INFINITY' if limit is None else str(limit)))
    if instrument:
        line = '    resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))'
        source = replace_once(source, line,
            "    os.write(2, ('VESSEL before-setrlimit-as requested=%r previous=%r\\n' % "
            "(address_space, resource.getrlimit(resource.RLIMIT_AS))).encode())\n"
            "    try:\n    " + line +
            "\n    except BaseException as error:"
            "\n        os.write(2, ('VESSEL setrlimit-as-error=%r\\n' % (error,)).encode())"
            "\n        raise" +
            "\n    os.write(2, b'VESSEL setrlimit-as-returned\\n')"
            "\n    os.write(2, ('VESSEL observed-as=%r\\n' % (resource.getrlimit(resource.RLIMIT_AS),)).encode())")
        source = replace_once(source, '                os.chroot(jail)',
            "                os.write(2, ('VESSEL pre-jail-exe=' + os.readlink('/proc/self/exe') + "
            "'\\nVESSEL pre-jail-status\\n' + Path('/proc/self/status').read_text() + "
            "'VESSEL pre-jail-maps\\n' + Path('/proc/self/maps').read_text()).encode())\n"
            '                os.chroot(jail)')
        source = replace_once(source, '                set_jail_limits()',
            "                os.write(2, b'VESSEL jailed-uid-dropped\\n')\n"
            '                set_jail_limits()')
        source = replace_once(source, '                    original_preexec()',
            "                    original_preexec()\n"
            "                os.write(2, b'VESSEL preexec-complete\\n')")
        # Popen preexec exceptions otherwise discard its temporary stderr capture.
        source = replace_once(source, '            except BaseException:\n                self.restore()',
            "            except BaseException:\n"
            "                capture = self.captures.get('stderr')\n"
            "                if capture is not None:\n"
            "                    capture.seek(0)\n"
            "                    os.write(2, capture.read(1024 * 1024))\n"
            "                self.restore()")
    ast.parse(source)
    return source


PROBE = r'''
#include <stdio.h>
#include <unistd.h>
#include <sys/resource.h>
int main(void) {
    static const char marker[] = "VESSEL main-entered\n";
    struct rlimit limit;
    if (write(2, marker, sizeof(marker)-1) < 0) return 30;
    if (getrlimit(RLIMIT_AS, &limit)) return 31;
    fprintf(stderr, "VESSEL executable-as=%llu,%llu\n",
            (unsigned long long)limit.rlim_cur, (unsigned long long)limit.rlim_max);
    return 0;
}
'''
CONSTRUCTOR = r'''
__attribute__((constructor)) static void started(void) {
    static const char marker[] = "VESSEL constructor-entered\n";
    if (write(2, marker, sizeof(marker)-1) < 0) _exit(32);
}
'''


def diagnostic_image(vessel, ref):
    """Best-effort metadata; exact-reference execution is the diagnostic gate."""
    evidence = {'pinned_reference': ref, 'metadata_status': 'unverified',
                'formal_provenance_verified': False, 'inspections': []}
    for options in (['--platform', 'linux/amd64'], []):
        command = ['docker', 'image', 'inspect', *options, ref]
        attempt = {'command': command}
        try:
            code, out, err = vessel.run(command, timeout=30)
            attempt.update(returncode=code, stdout=out, stderr=err)
            if code == 0:
                data = json.loads(out)[0]
                attempt['metadata'] = data
                attempt['unavailable_fields'] = [key for key in ('Descriptor', 'Os', 'Architecture')
                                                  if not data.get(key)]
        except Exception as error:
            attempt['error'] = repr(error)
        evidence['inspections'].append(attempt)
    try:
        # Existing bounded probe uses this exact ref, --pull never, linux/amd64,
        # and requires uname -m == x86_64. No image-ID substitution is permitted.
        evidence['execution_architecture'] = vessel.probe_reference(ref)
        evidence['execution_verified'] = evidence['execution_architecture'] == 'x86_64'
    except Exception as error:
        evidence.update(execution_verified=False, execution_error=repr(error))
    return evidence


def self_test(source):
    from types import SimpleNamespace
    for limit in (None, 256 * 1024**2, 4 * 1024**3):
        for instrument in (False, True):
            modified = worker_source(source, limit, instrument)
            function = next(n for n in ast.parse(modified).body
                            if isinstance(n, ast.FunctionDef) and n.name == 'set_jail_limits')
            for inherited in ('0', '1'):
                calls = {}
                resource = SimpleNamespace(RLIM_INFINITY=-1, RLIMIT_CORE=0, RLIMIT_CPU=1,
                    RLIMIT_AS=2, RLIMIT_FSIZE=3, RLIMIT_NPROC=4,
                    setrlimit=lambda k, v: calls.update({k: v}), getrlimit=lambda k: calls.get(k, (-1, -1)))
                namespace = dict(resource=resource, os=SimpleNamespace(
                    environ={'BENCHMARK_DIAGNOSTIC_ROSETTA': inherited}, write=lambda *a: None))
                exec(compile(ast.Module(body=[function], type_ignores=[]), '<test>', 'exec'), namespace)
                namespace['set_jail_limits']()
                expected = -1 if limit is None else limit
                assert calls == {0: (0, 0), 1: (10, 10), 2: (expected, expected),
                                 3: (64 * 1024**2,) * 2, 4: (16, 16)}
    try:
        worker_source(source.replace(LIMIT_EXPR, ''), 1, True)
    except ValueError:
        pass
    else:
        raise AssertionError('missing substitution was accepted')
    print('PASS: 12 limit/instrumentation/environment combinations; other rlimits unchanged; drift rejected')
    ref = 'python:3.12.8-bookworm@sha256:' + 'a' * 64
    for inspections in ([(1, '', 'reference cannot be inspected')] * 2,
                        [(0, '[{"Id":"sha256:local"}]', '')] * 2,
                        [(0, 'invalid JSON', '')] * 2):
        fake = SimpleNamespace(run=unittest.mock.Mock(side_effect=inspections),
                               probe_reference=unittest.mock.Mock(return_value='x86_64'))
        evidence = diagnostic_image(fake, ref)
        assert evidence['execution_verified'] and evidence['pinned_reference'] == ref
        assert not evidence['formal_provenance_verified'] and evidence['metadata_status'] == 'unverified'
        assert len(evidence['inspections']) == 2
        fake.probe_reference.assert_called_once_with(ref)
        assert all(call.args[0][-1] == ref for call in fake.run.call_args_list)
        if 'local' in inspections[0][1]:
            assert evidence['inspections'][0]['unavailable_fields'] == ['Descriptor', 'Os', 'Architecture']
        elif inspections[0][0]:
            assert evidence['inspections'][0]['stderr'] == inspections[0][2]
        else:
            assert 'error' in evidence['inspections'][0]
    for result in ('aarch64', RuntimeError('execution failed'), TimeoutError('probe timed out')):
        fake.probe_reference.reset_mock()
        fake.probe_reference.side_effect = result if isinstance(result, Exception) else None
        fake.probe_reference.return_value = result
        fake.run.side_effect = [(1, '', 'unavailable')] * 2
        assert not diagnostic_image(fake, ref)['execution_verified']
    print('PASS: unavailable/incomplete/malformed inspection tolerated; wrong-arch/failed/timed-out execution rejected')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--limits-mib', default='256,512,1024,4096,16384,65536,unlimited')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    repo = args.repo.resolve()
    original = (repo / 'scripts/docker_benchmark_worker.py').read_text()
    if args.self_test:
        self_test(original)
        return
    if not args.lock or not args.output or not args.lock.is_absolute() or not args.output.is_absolute():
        parser.error('--lock and --output must be absolute paths')
    output = args.output.resolve()
    if output == repo or repo in output.parents:
        parser.error('output must be outside repository and agent work directories')
    limits = [None if s == 'unlimited' else int(s) * 1024**2 for s in args.limits_mib.split(',')]
    if any(n is not None and (n < 256 * 1024**2 or n > 1024**4) for n in limits):
        parser.error('finite diagnostic limits must be between 256 MiB and 1 TiB')
    os.environ['LINUX_BENCHMARK_LOCK'] = str(args.lock)
    os.environ.pop('C_BENCHMARK_LOCK', None)
    os.environ['VESSEL_DIAGNOSTIC_ROSETTA'] = '0'
    os.environ['LINUX_BENCHMARK_PROFILE'] = 'standard'
    sys.path[:0] = [str(repo / 'scripts'), str(repo)]
    import docker_benchmark as docker
    import vessel_preflight as vessel
    from tests.test_docker_benchmark_integration import DockerIntegration
    config = docker.settings()
    if config['platform'] != 'linux/amd64':
        parser.error('requires pinned linux/amd64 lock')
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    (output / 'harness.py').write_bytes(Path(__file__).read_bytes())
    (output / 'worker-original.py').write_text(original)
    (output / 'lock.json').write_bytes(args.lock.read_bytes())
    metadata = {'diagnostic_only': True, 'formal_result': False, 'config': config,
                'worker_sha256': hashlib.sha256(original.encode()).hexdigest()}
    metadata['images'] = {key: diagnostic_image(vessel, config[key])
                          for key in ('compiler_image', 'oracle_image')}
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
    if not all(image['execution_verified'] for image in metadata['images'].values()):
        raise RuntimeError('exact pinned image execution check failed; see metadata.json')
    for label, command in [('revision', ['git', '-C', str(repo), 'rev-parse', 'HEAD']),
                           ('status', ['git', '-C', str(repo), 'status', '--short']),
                           ('docker-version', ['docker', 'version']),
                           ('docker-info', ['docker', 'info']),
                           ('context', ['docker', 'context', 'inspect'])]:
        result = subprocess.run(command, capture_output=True, timeout=60)
        metadata[label] = {'returncode': result.returncode, 'stdout': result.stdout.decode(errors='replace'),
                           'stderr': result.stderr.decode(errors='replace')}
    try:
        # Existing trusted read-only metadata probe, using the selected compiler image.
        metadata['emulation'] = vessel.emulation_identity()
    except Exception as error:
        metadata['emulation_error'] = repr(error)
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
    serial = 0
    current = {'limit': 256 * 1024**2, 'instrument': False, 'exact': False}

    def invoke(action, request, timeout=90):
        nonlocal serial
        serial += 1
        stem = output / ('%03d-%s' % (serial, action))
        name = 'vessel-diagnostic-' + __import__('uuid').uuid4().hex
        command = docker.command(action, name, request.get('language', 'c'))
        if command[-2] != original or command[-1] != action:
            raise ValueError('unexpected worker payload location or source')
        if action == 'case' and not current['exact']:
            command[-2] = worker_source(original, current['limit'], current['instrument'])
        stem.with_suffix('.worker.py').write_text(command[-2])
        # Save exact arguments without duplicating the large embedded source.
        recorded = list(command)
        recorded[-2] = '<see corresponding .worker.py>'
        stem.with_suffix('.command.json').write_text(json.dumps(recorded, indent=2))
        try:
            result = subprocess.run(command, input=json.dumps(request).encode() + b'\n',
                                    capture_output=True, timeout=timeout)
            stem.with_suffix('.stdout').write_bytes(result.stdout)
            stem.with_suffix('.stderr').write_bytes(result.stderr)
            stem.with_suffix('.exit').write_text(str(result.returncode))
            if result.returncode:
                raise RuntimeError('worker exit %d; see %s' % (result.returncode, stem))
            value = json.loads(result.stdout)
            if action == 'case':
                for stream in ('stdout', 'stderr'):
                    stem.with_suffix('.child-' + stream).write_bytes(
                        base64.b64decode(value['result'][stream]['$bytes']))
            return value
        except subprocess.TimeoutExpired as error:
            stem.with_suffix('.stdout').write_bytes(error.stdout or b'')
            stem.with_suffix('.stderr').write_bytes(error.stderr or b'')
            stem.with_suffix('.exit').write_text('host-timeout')
            raise
        finally:
            docker.cleanup(name)

    outcomes = []
    with patch.object(docker, 'invoke', invoke):
        for label, source in [('main', PROBE), ('constructor', PROBE + CONSTRUCTOR)]:
            path = output / (label + '.c')
            path.write_text(source)
            if docker.compile_source(path, output / label):
                raise RuntimeError('trusted probe compilation failed')
            metadata[label + '_binary_sha256'] = hashlib.sha256((output / label).read_bytes()).hexdigest()
        (output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
        # Run the existing control verbatim, with its original expected cap and output.
        for mode in ('0', '1'):
            current['exact'] = True
            os.environ['VESSEL_DIAGNOSTIC_ROSETTA'] = mode
            stream = io.StringIO()
            suite = unittest.TestSuite([DockerIntegration('test_nonroot_chroot_and_no_controller_assets')])
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
            (output / ('isolation-' + mode + '.log')).write_text(stream.getvalue())
            outcomes.append({'existing_isolation_mode': mode, 'passed': result.wasSuccessful()})
        os.environ['VESSEL_DIAGNOSTIC_ROSETTA'] = '0'
        current['exact'] = False
        for limit in limits:
            for instrument in (False, True):
                current.update(limit=limit, instrument=instrument)
                for label in ('main', 'constructor'):
                    entry = dict(current, probe=label, call=serial + 1)
                    try:
                        value = docker.execute_case('c-cp', (output / label).read_bytes(),
                                                    {'args': [], 'fixture': [], 'timeout': 10})
                        entry['result'] = value['result']
                    except Exception as error:
                        entry['error'] = repr(error)
                    outcomes.append(entry)
                    (output / 'results.json').write_text(json.dumps(outcomes, indent=2))
                    print(json.dumps({k: v for k, v in entry.items() if k != 'result'}), flush=True)
    print('Diagnostic collection complete; inspect results and child-stderr. No formal approval: ' + str(output))


if __name__ == '__main__':
    main()
