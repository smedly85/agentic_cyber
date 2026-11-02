#!/usr/bin/env python3
"""Host-side Docker transport only: never compiles or executes native candidates."""
import argparse
import base64
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid
from linux_utilities_catalog import SELECTORS, suite_root, utility_name, language_name

ROOT = Path(__file__).resolve().parents[1]


class InfrastructureError(RuntimeError):
    pass


def settings():
    path = Path(os.environ.get('LINUX_BENCHMARK_LOCK', os.environ.get('C_BENCHMARK_LOCK', ROOT / 'docker/linux-utilities/lock-amd64.json')))
    config = json.loads(path.read_text())
    for key in ('oracle_image', 'compiler_image', 'rust_compiler_image'):
        if key == 'rust_compiler_image' and key not in config:
            continue
        if not re.fullmatch(r'(sha256:[a-f0-9]{64}|[^\s]+@sha256:[a-f0-9]{64})', config[key]):
            raise InfrastructureError('immutable image reference required')
    if config['platform'] not in ('linux/amd64', 'linux/arm64'):
        raise InfrastructureError('unsupported target platform')
    return config


def command(action, name, language='c'):
    config = settings()
    arch = 'x86_64' if config['platform'] == 'linux/amd64' else 'aarch64'
    args = ['docker', 'run', '--rm', '--name', name, '--platform', config['platform'],
            '--network', 'none', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--cpus', '1', '--memory', '768m',
            '--pids-limit', '64', '--ulimit', 'nofile=256:256',
            '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=512m',
            '-e', 'LC_ALL=C', '-e', 'TZ=UTC', '-e', 'BENCHMARK_ARCH=' + arch]
    if action == 'case':
        args += ['--user', '0:0']
        for cap in ('SYS_CHROOT', 'SETUID', 'SETGID', 'CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'FSETID', 'KILL'):
            args += ['--cap-add', cap]
    else:
        args += ['--user', '1000:1000']
    image_key = ('rust_compiler_image' if language == 'rust' else 'compiler_image') if action in ('compile','toolchain') else 'oracle_image'
    if image_key not in config:
        raise InfrastructureError('missing pinned image: ' + image_key)
    args += ['-i', config[image_key],
             'python3', '-I', '-c', (ROOT / 'scripts/docker_benchmark_worker.py').read_text(), action]
    return args


def cleanup(name):
    try:
        subprocess.run(['docker', 'rm', '-fv', name], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        # Keep the original classified infrastructure error; cleanup must not
        # turn a missing daemon into an unhandled host exception or fallback.
        pass


def invoke(action, request, timeout=90):
    name = 'c-benchmark-' + uuid.uuid4().hex
    try:
        result = subprocess.run(command(action, name, request.get('language', 'c')), input=json.dumps(request).encode() + b'\n',
                                capture_output=True, timeout=timeout)
        if result.returncode != 0:
            raise InfrastructureError('Docker worker failed: ' + result.stderr.decode(errors='replace')[-1500:])
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise InfrastructureError(str(error)) from error
    finally:
        cleanup(name)


def compile_source(source, executable):
    language = {'.c':'c','.rs':'rust','.py':'py'}.get(source.suffix)
    if language is None:
        raise InfrastructureError('unsupported source extension')
    result = invoke('compile', {'source': base64.b64encode(source.read_bytes()).decode(),
                               'language':language,
                               'python_validator': (ROOT/'scripts/python_candidate.py').read_text() if language == 'py' else None})
    if result['stderr']:
        print(result['stderr'], file=sys.stderr)
    if result['status'] != 0:
        if executable.is_file():
            executable.unlink()
        return 1
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(base64.b64decode(result['binary']))
    executable.chmod(0o755)
    return 0


def runtime(selector):
    suite = suite_root(ROOT, selector)
    return {name: (suite / name).read_text() for name in ('engine.py', 'runner.py', 'props.py', 'config.py')}


def input_case(case):
    # Expectations, private corpus metadata and unrelated cases never enter the
    # candidate container. Only execution inputs required by the fixture engine.
    allowed = {'args', 'fixture', 'stdin_b64', 'files_b64', 'umask', 'faults', 'timeout',
               'env', 'abs_targets', 'mode_paths', 'needs_non_root', 'output_file'}
    result = {k: v for k, v in case.items() if k in allowed}
    if 'output_file' in result:
        result['output_file'] = {'path': result['output_file']['path']}
    return result


def execute_case(selector, binary, case, mode='pipe', *, executable_kind=None):
    return invoke('case', {'runtime': runtime(selector), 'utility': utility_name(selector),
                          'language': executable_kind or language_name(selector),
                          'binary': base64.b64encode(binary).decode(),
                          'case': input_case(case), 'mode': mode},
                  timeout=max(60, int(case.get('timeout', 10)) + 45))


def boundary_probe(executable, selector, option, flag):
    utility = utility_name(selector)
    case = {'args': [option], 'fixture': [], 'stdin_b64': 'YgphCg=='}
    if option == '@existing-file-operand':
        case['args'] = ['input']
        case['fixture'] = []
        case['files_b64'] = {'input': 'YgphCg=='}
    elif utility == 'mkdir':
        case['args'] += ['755', 'made'] if flag == '-m' else ['made']
    elif utility in ('cp', 'mv'):
        case['args'] += ['input', 'output']
        case['fixture'] = [{'path': 'input', 'type': 'file', 'contents_b64': 'cGF5bG9hZAo=', 'mode': '0644'}]
        case['stdin_b64'] = 'eQo='
    result = execute_case(selector, executable.read_bytes(), case)['result']
    stdout = base64.b64decode(result['stdout']['$bytes'])
    stderr = base64.b64decode(result['stderr']['$bytes'])
    expected = 2 if utility == 'sort' else 1
    passed = (result['exit_code'] == expected and not stdout and bool(stderr)
              and not result.get('timed_out') and not result.get('signal_name'))
    return {'option': option, 'flag': flag, 'argv': case['args'],
            'exit_status': result['exit_code'], 'stdout_bytes': len(stdout),
            'stderr_bytes': len(stderr), 'rejected': passed,
            'violation': None if passed else 'did not reject future option with required status and diagnostic',
            'docker_provenance': settings()}


def judge(selector, candidate, flags, hidden=False, report_path=None, cases_override=None, *, calibration_native=False):
    suite = suite_root(ROOT, selector)
    config = json.loads((suite / 'config.json').read_text())
    config['implemented'] = flags
    manifest = json.loads((ROOT / 'experiments/utilities' / (selector + '.json')).read_text())
    frozen_manifest = json.loads((suite / 'suites/MANIFEST.json').read_text())
    architecture = 'x86_64' if settings()['platform'] == 'linux/amd64' else 'aarch64'
    if frozen_manifest['environment']['architecture'] != architecture:
        raise InfrastructureError('corpus architecture has not been validated for this Docker target')
    if not any(c['implemented_flags'] == flags for c in manifest['checkpoints']):
        raise InfrastructureError('flags do not identify a canonical checkpoint')
    if cases_override is None:
        corpus = suite / ('heldout/heldout_cases.json.gz' if hidden else 'suites/linux.json.gz')
        cases = json.loads(gzip.decompress(corpus.read_bytes()))['cases']
    else:
        cases = cases_override
    name = 'c-benchmark-judge-' + uuid.uuid4().hex
    binary = candidate.read_bytes()
    proc = None
    watchdog = None
    try:
        proc = subprocess.Popen(command('judge', name), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        watchdog = threading.Timer(1800, cleanup, args=(name,))
        watchdog.daemon = True
        watchdog.start()
        proc.stdin.write(json.dumps({'runtime': runtime(selector), 'cases': cases, 'config': config}) + '\n')
        proc.stdin.flush()
        final = None
        for line in proc.stdout:
            if line.startswith('@CASE '):
                request = json.loads(line[6:])
                answer = execute_case(selector, binary, request['case'], request['mode'],
                                      executable_kind='c' if calibration_native else None)
                proc.stdin.write(json.dumps(answer) + '\n')
                proc.stdin.flush()
            elif line.startswith('@REPORT '):
                final = json.loads(line[8:])
            elif not hidden:
                print(line, end='')
        proc.wait(timeout=30)
        if proc.returncode != 0 or final is None:
            raise InfrastructureError('trusted judge did not produce a verdict: ' + proc.stderr.read()[-1000:])
        final['report']['docker_provenance'] = settings()
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(final['report'], indent=2) + '\n')
        if hidden:
            print('Held-out evaluation complete; counts=' + json.dumps(final['report']['counts']))
        return final
    finally:
        if watchdog:
            watchdog.cancel()
        cleanup(name)
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                stream.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'judge', 'check-commands', 'preflight'))
    parser.add_argument('--utility', choices=SELECTORS, required=True)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--hidden', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--build-command')
    parser.add_argument('--feature-command')
    parser.add_argument('--extra-command')
    parser.add_argument('--base-command', default='')
    parser.add_argument('flags', nargs='*')
    args = parser.parse_args(argv)
    manifest = json.loads((ROOT / 'experiments/utilities' / (args.utility + '.json')).read_text())
    candidate = args.candidate or Path(manifest['executable_path'])
    if args.action == 'preflight':
        print(json.dumps(invoke('toolchain', {'language':language_name(args.utility)}), sort_keys=True))
        return 0
    if args.action == 'check-commands':
        features = [' '.join([manifest['judge'], manifest['executable_path'], *c['implemented_flags']])
                    for c in manifest['checkpoints']]
        if (args.build_command != manifest['build_command'] or args.feature_command not in features
                or args.extra_command != manifest['extra_test_command'] or args.base_command):
            raise InfrastructureError('Linux benchmark commands must exactly match the Docker-backed manifest')
        settings()
        return 0
    if args.action == 'build':
        return compile_source(Path(manifest['source_path']), candidate)
    report = args.report or (Path(os.environ['VALIDATION_JSON_REPORT']) if os.environ.get('VALIDATION_JSON_REPORT') else None)
    return judge(args.utility, candidate, args.flags, args.hidden, report)['status']


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (InfrastructureError, OSError, ValueError) as error:
        print('INFRASTRUCTURE ERROR: ' + str(error), file=sys.stderr)
        raise SystemExit(2)
