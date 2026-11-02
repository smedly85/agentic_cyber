"""Trusted Docker supervisor. Never placed in an agent's visible bundle.

The judge has no candidate process. The case supervisor admits one input and
executes the binary only after chroot, descriptor closure and UID/GID dropping.
"""
import base64
import contextlib
import dataclasses
import importlib
import io
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys
import tempfile


def wire(value):
    if isinstance(value, bytes):
        return {'$bytes': base64.b64encode(value).decode()}
    if isinstance(value, dict):
        return {k: wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(v) for v in value]
    return value


def unwire(value):
    if isinstance(value, dict):
        if set(value) == {'$bytes'}:
            return base64.b64decode(value['$bytes'])
        return {k: unwire(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unwire(v) for v in value]
    return value


def modules(request):
    root = Path('/tmp/harness')
    root.mkdir()
    for name, text in request['runtime'].items():
        if name not in ('engine.py', 'runner.py', 'props.py', 'config.py'):
            raise ValueError('unexpected runtime member')
        (root / name).write_text(text)
    sys.path.insert(0, str(root))
    return importlib.import_module('engine'), importlib.import_module('runner')


def jailed_executor(engine, utility, binary, language='c'):
    jail = Path(tempfile.mkdtemp(prefix='jail-'))
    # Resolve dependencies of trusted GNU binaries, never run ldd on a candidate.
    libraries = set()
    programs = ['/opt/gnu/bin/' + p for p in ('cp', 'mv', 'mkdir', 'sort')]
    # Rust's standard library also needs libgcc_s; Python extensions are copied
    # from the trusted pinned runtime, never discovered from candidate code.
    import sysconfig
    for path in Path('/lib').glob('*/libgcc_s.so.1'):
        libraries.add(str(path))
    if language == 'py':
        stdlib = Path(sysconfig.get_path('stdlib'))
        shutil.copytree(stdlib, jail / str(stdlib).lstrip('/'),
                        ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests', 'ensurepip'))
        python = Path(sys.executable).resolve()
        target = jail / str(python).lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(python, target); target.chmod(0o555)
        programs += [str(python), *map(str,(stdlib/'lib-dynload').glob('*.so'))]
    for program in programs:
        listing = subprocess.check_output(['ldd', program], text=True)
        for word in listing.split():
            if word.startswith('/') and Path(word).is_file():
                libraries.add(word)
    for library in libraries:
        target = jail / library.lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(library, target)
        target.chmod(0o555)
    (jail / 'candidate').mkdir()
    executable = jail / ('candidate/program.py' if language == 'py' else 'candidate/program')
    executable.write_bytes(binary)
    executable.chmod(0o555)
    (jail / 'tmp').mkdir(mode=0o755)
    jail.chmod(0o755)
    real_popen = subprocess.Popen

    class JailedPopen:
        def __init__(self, argv, **kwargs):
            cwd = Path(kwargs['cwd'])
            self.original = cwd
            self.moved = jail / str(cwd).lstrip('/')
            self.moved.parent.mkdir(parents=True, exist_ok=True)
            # Fixtures must belong to the actual non-root child, not supervisor.
            entries = [cwd, *cwd.rglob('*')]
            for path in entries:
                mode = path.lstat().st_mode & 0o7777
                os.chown(path, 1000, 1000, follow_symlinks=False)
                if not path.is_symlink():
                    path.chmod(mode)
            cwd.rename(self.moved)
            kwargs['cwd'] = str(self.moved)
            original_preexec = kwargs.pop('preexec_fn', None)
            child_env = kwargs.get('env', {})
            # Only deterministic case environment; no controller/Docker secrets.
            kwargs['env'] = {k: v for k, v in child_env.items() if k in
                             ('LC_ALL', 'LANG', 'LANGUAGE', 'TZ', 'TMPDIR', 'POSIXLY_CORRECT', '_POSIX2_VERSION')}
            kwargs['env'].update(HOME=str(cwd), PATH='/nonexistent', TZ='UTC')
            if language == 'py':
                kwargs['env']['LD_LIBRARY_PATH'] = '/usr/local/lib'
            kwargs['executable'] = str(python) if language == 'py' else '/candidate/program'
            kwargs['close_fds'] = True
            kwargs['start_new_session'] = True
            # Regular files bound output via RLIMIT_FSIZE; communicate() cannot
            # allocate unbounded memory in response to a flooding candidate.
            self.captures = {}
            for stream in ('stdout', 'stderr'):
                if kwargs.get(stream) == subprocess.PIPE:
                    self.captures[stream] = tempfile.TemporaryFile()
                    kwargs[stream] = self.captures[stream]
            # Preserve GNU-compatible argv[0] without revealing host paths.
            argv = ([str(python), '-I', '-B', '/candidate/program.py', *argv[1:]]
                    if language == 'py' else [utility, *argv[1:]])

            def enter():
                os.chroot(jail)
                os.chdir(str(cwd))
                os.setgroups([])
                os.setgid(1000)
                os.setuid(1000)
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
                resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))
                resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
                resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
                if original_preexec:
                    original_preexec()

            kwargs['preexec_fn'] = enter
            try:
                if language == 'py':
                    # A missing interpreter/library is infrastructure, never a
                    # candidate failure. Check the jailed runtime independently.
                    probe = real_popen([str(python), '-I', '-B', '-c', 'pass'],
                                       executable=str(python), cwd=kwargs['cwd'],
                                       env=kwargs['env'], preexec_fn=enter,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, close_fds=True)
                    _, diagnostic = probe.communicate(timeout=10)
                    if probe.returncode:
                        raise RuntimeError('jailed Python runtime unavailable: '+diagnostic.decode(errors='replace'))
                self.proc = real_popen(argv, **kwargs)
            except BaseException:
                self.restore()
                raise

        def restore(self):
            if self.moved.exists() and not self.original.exists():
                self.moved.rename(self.original)

        def communicate(self, *args, **kwargs):
            result = self.proc.communicate(*args, **kwargs)
            # Kill any surviving descendants before inspecting filesystem state.
            try:
                os.killpg(self.proc.pid, 9)
            except ProcessLookupError:
                pass
            self.restore()
            output = list(result)
            for index, stream in enumerate(('stdout', 'stderr')):
                if stream in self.captures:
                    self.captures[stream].seek(0)
                    output[index] = self.captures[stream].read(64 * 1024**2)
                    self.captures[stream].close()
            return tuple(output)

        def __getattr__(self, name):
            return getattr(self.proc, name)

    # Permission checks refer to the child UID, not the trusted supervisor.
    engine.EXECUTION_UID = 1000
    engine.EXECUTABLE_PATH = str(executable)
    engine.subprocess.Popen = JailedPopen
    return engine._original_execute


def main():
    if (platform.system() != 'Linux' or os.uname().sysname != 'Linux'
            or not Path('/.dockerenv').is_file()):
        raise RuntimeError('Docker Linux required')
    if platform.machine() != os.environ['BENCHMARK_ARCH']:
        raise RuntimeError('wrong container architecture')
    if platform.python_version() != '3.12.8':
        raise RuntimeError('trusted Python runtime version mismatch')
    request = json.loads(sys.stdin.readline())
    action = sys.argv[1]
    if action == 'toolchain':
        language=request['language']
        version = (subprocess.check_output(['rustc','--version'],text=True).strip() if language=='rust'
                   else subprocess.check_output(['gcc','-dumpfullversion'],text=True).strip() if language=='c'
                   else platform.python_version())
        expected={'rust':'rustc 1.85.1 ', 'c':'12.2.0','py':'3.12.8'}[language]
        if not version.startswith(expected): raise RuntimeError('toolchain version mismatch')
        print(json.dumps({'os':platform.system(),'uname':os.uname().sysname,'architecture':platform.machine(),
                          'language':language,'version':version,'uid':os.geteuid(),'python':platform.python_version()}))
        return
    if action == 'compile':
        if os.geteuid() == 0:
            raise RuntimeError('compiler must be non-root')
        language = request.get('language','c')
        if platform.python_version() != '3.12.8':
            raise RuntimeError('compiler/runtime version mismatch')
        if language == 'c' and subprocess.check_output(['gcc','-dumpfullversion'],text=True).strip() != '12.2.0':
            raise RuntimeError('C compiler version mismatch')
        if language == 'rust' and not subprocess.check_output(['rustc','--version'],text=True).startswith('rustc 1.85.1 '):
            raise RuntimeError('Rust compiler version mismatch')
        with tempfile.TemporaryDirectory() as temp:
            source, binary = Path(temp) / ('program.'+{'c':'c','rust':'rs','py':'py'}[language]), Path(temp) / 'program'
            source.write_bytes(base64.b64decode(request['source']))
            if language == 'py':
                # Reuse the historical nonempty/in-memory compile check in Docker.
                # Its temporary launcher is discarded; the case adapter pins the
                # interpreter directly, so no host-interpreter path can escape.
                validator={ '__name__':'python_candidate_validator' }
                exec(compile(request['python_validator'],'python_candidate.py','exec'),validator)
                try:
                    validator['prepare'](source,binary)
                except (SyntaxError,ValueError) as error:
                    print(json.dumps({'status':1,'stderr':str(error),'binary':None})); return
                print(json.dumps({'status':0,'stderr':'','binary':base64.b64encode(source.read_bytes()).decode()})); return
            build = (['rustc','--edition=2021','-C','opt-level=2','-D','warnings',str(source),'-o',str(binary)]
                     if language == 'rust' else ['gcc', '-std=c11', '-D_POSIX_C_SOURCE=200809L',
                                     '-Wall', '-Wextra', '-Werror', '-pedantic', '-O2',
                                     str(source), '-o', str(binary)])
            result = subprocess.run(build, capture_output=True, timeout=60)
            print(json.dumps({'status': result.returncode, 'stderr': result.stderr.decode(errors='replace'),
                              'binary': base64.b64encode(binary.read_bytes()).decode() if result.returncode == 0 else None}))
        return
    engine, runner = modules(request)
    if action == 'case':
        execute = jailed_executor(engine, request['utility'], base64.b64decode(request['binary']), request.get('language','c'))
        kwargs = {'stdin_mode': request['mode']} if request['utility'] == 'sort' else {}
        result = execute(request['case'], [engine.EXECUTABLE_PATH], **kwargs)
        print(json.dumps({'result': wire(dataclasses.asdict(result))}))
        return
    if action == 'judge':
        # Current-case request/response protocol. No candidate runs here.
        def remote(case, cmd, **kwargs):
            print('@CASE ' + json.dumps({'case': case, 'mode': kwargs.get('stdin_mode', 'pipe')}), flush=True)
            response = json.loads(sys.stdin.readline())
            if 'infrastructure_error' in response:
                raise RuntimeError(response['infrastructure_error'])
            return engine.Result(**unwire(response['result']))
        engine.execute = remote
        Path('/tmp/corpus.json').write_text(json.dumps({'cases': request['cases']}))
        Path('/tmp/config.json').write_text(json.dumps(request['config']))
        sys.argv = ['runner.py', '/tmp/corpus.json', '--config', '/tmp/config.json',
                    '--jobs', '1', '--json-report', '/tmp/report.json', '--', '/candidate/program']
        try:
            runner.main()
        except SystemExit as finished:
            status = finished.code or 0
        report = json.loads(Path('/tmp/report.json').read_text())
        print('@REPORT ' + json.dumps({'status': status, 'report': report}), flush=True)
        return
    raise ValueError('unknown worker action')


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print('@INFRA ' + str(error), file=sys.stderr, flush=True)
        raise SystemExit(2)
