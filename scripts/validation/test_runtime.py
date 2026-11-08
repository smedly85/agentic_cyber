"""Required infrastructure controls recovered from pre-cleanup commit 5c128adb.

These are validation probes, not experimental implementations or lineage seeds.
"""
import base64
import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
import docker_benchmark as docker
import checkpoint_boundary_gate as gate

class CompilerFailureClassification(unittest.TestCase):
    """Mocked transport/worker checks; these tests do not start Docker."""

    def test_adapter_abnormal_status_is_infrastructure(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'probe.c'
            source.write_text('int main(void) { return 0; }\n')
            for status in (-9, -11, 2, 101, 137):
                with self.subTest(status=status), patch.object(docker, 'invoke',
                        return_value={'status': status, 'stderr': '', 'binary': None}):
                    with self.assertRaises(docker.InfrastructureError):
                        docker.compile_source(source, Path(temp) / 'probe')
            with patch.object(docker, 'invoke', return_value={'status': 1, 'stderr': '', 'binary': None}):
                self.assertEqual(docker.compile_source(source, Path(temp) / 'probe'), 1)

    @unittest.skipUnless(os.name == 'posix', 'worker imports Linux resource module')
    def test_worker_separates_toolchain_failures_from_source_diagnostics(self):
        import docker_benchmark_worker as worker
        failures = [(-9, b''), (101, b'compiler panicked'),
                    (1, b'gcc: internal compiler error: Killed (program cc1)'),
                    (1, b'gcc: fatal error: cannot execute cc1'),
                    (1, b'No space left on device'), (1, b'Cannot allocate memory'),
                    (1, b'error while loading shared libraries: lib.so')]
        for status, stderr in failures:
            with self.subTest(status=status, stderr=stderr), self.assertRaises(RuntimeError):
                worker.check_compiler_result(SimpleNamespace(returncode=status, stderr=stderr))
        for status, stderr in ((0, b''), (1, b'error: expected expression'),
                               (1, b'error[E0308]: mismatched types')):
            worker.check_compiler_result(SimpleNamespace(returncode=status, stderr=stderr))


class DockerIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def compile(self, text):
        source, binary = self.root / 'smoke.c', self.root / 'smoke'
        source.write_text(text)
        self.assertEqual(docker.compile_source(source, binary), 0)
        return binary

    def test_nonroot_chroot_and_no_controller_assets(self):
        binary = self.compile(r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/resource.h>
#include <sys/utsname.h>
#include <sys/socket.h>
#include <arpa/inet.h>
int main(void) {
  struct utsname host;
  if (uname(&host) || strcmp(host.sysname, "Linux") || strcmp(host.machine, "EXPECTED_ARCH")) return 20;
  const int resources[] = {RLIMIT_CORE, RLIMIT_CPU, RLIMIT_AS, RLIMIT_FSIZE, RLIMIT_NPROC};
  const rlim_t limits[] = {0, 10, EXPECTED_AS, 64UL*1024*1024, 16};
  for (unsigned i=0; i<sizeof(resources)/sizeof(resources[0]); ++i) {
    struct rlimit limit;
    if (getrlimit(resources[i], &limit) || limit.rlim_cur != limits[i] || limit.rlim_max != limits[i]) return 21;
  }
  if (EXPECT_AS_LIMIT) {
    void *too_large = malloc((size_t)EXPECTED_AS + 4096UL);
    if (too_large) { free(too_large); return 22; }
  }
  const char *paths[] = {"/opt/gnu/bin/cp", "/bin/cp", "/work", "/proc/1/environ",
    "/var/run/docker.sock", "/tmp/harness/runner.py", "/output", "/etc/shadow"};
  if (getuid() != 1000 || getgid() != 1000) return 10;
  for (unsigned i=0; i<sizeof(paths)/sizeof(paths[0]); ++i)
    if (access(paths[i], F_OK)==0) return 11;
  if (chroot("/")==0) return 12;
  int fd=socket(AF_INET, SOCK_STREAM, 0);
  struct sockaddr_in peer={0}; peer.sin_family=AF_INET; peer.sin_port=htons(80);
  if (inet_pton(AF_INET,"1.1.1.1",&peer.sin_addr)!=1) return 13;
  alarm(2);
  if (fd>=0 && connect(fd,(struct sockaddr *)&peer,sizeof(peer))==0) return 14;
  if (fd>=0) close(fd);
  puts("isolated uid=1000"); return 0;
}
'''.replace('if (chroot("/")==0) return 12;', 'if (setuid(0)==0) return 12;')
           .replace('EXPECTED_AS', 'RLIM_INFINITY' if docker.execution_profile().get('diagnostic_only')
                    else str(docker.execution_profile()['rlimit_as_bytes']) + 'ULL')
           .replace('EXPECT_AS_LIMIT', '0' if docker.execution_profile().get('diagnostic_only') else '1')
           .replace('EXPECTED_ARCH', 'x86_64' if docker.settings()['platform'] == 'linux/amd64' else 'aarch64'))
        result = docker.execute_case('c-cp', binary.read_bytes(), {'args': [], 'fixture': []})['result']
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(base64.b64decode(result['stdout']['$bytes']), b'isolated uid=1000\n')

    def test_timeout_is_candidate_outcome(self):
        binary = self.compile('int main(void) { for (;;) {} }\n')
        result = docker.execute_case('c-cp', binary.read_bytes(), {'args': [], 'timeout': 1})['result']
        self.assertTrue(result['timed_out'])

    def test_compile_error_is_not_infrastructure_error(self):
        source = self.root / 'invalid.c'
        source.write_text('this is deliberately invalid C\n')
        self.assertEqual(docker.compile_source(source, self.root / 'invalid'), 1)

    def test_missing_docker_never_falls_back(self):
        with patch.object(docker.subprocess, 'run', side_effect=FileNotFoundError('docker missing')):
            with self.assertRaises((docker.InfrastructureError, FileNotFoundError)):
                docker.invoke('case', {})

    def test_checkpoint_boundaries(self):
        for selector in (s for s in docker.SELECTORS if s.startswith('c-')):
            status = 2 if selector == 'c-sort' else 1
            binary = self.compile('#include <stdio.h>\nint main(void) { fputs("unknown option\\n",stderr); return '+str(status)+'; }\n')
            manifest = gate.load_manifest(ROOT, selector)
            for checkpoint in manifest['checkpoints']:
                report = gate.evaluate(ROOT, selector, checkpoint['id'], binary)
                self.assertTrue(report['passed'], (selector, checkpoint['id']))
        binary = self.compile('int main(void) { return 0; }\n')
        self.assertFalse(gate.evaluate(ROOT, 'c-cp', '000', binary)['passed'])

    def test_public_and_hidden_negative_control(self):
        binary = self.compile('int main(void) { return 0; }\n')
        for hidden in (False, True):
            result = docker.judge('c-cp', binary, [], hidden=hidden)
            self.assertEqual(result['status'], 1)
            self.assertGreater(result['report']['counts'].get('FAIL', 0), 0)


class CrossLanguageDocker(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def build(self,language,text):
        source=self.root/('probe.'+{'rust':'rs','py':'py'}[language])
        source.write_text(text); binary=self.root/('probe-'+language)
        self.assertEqual(docker.compile_source(source,binary),0)
        return binary

    def test_real_rust_and_python_runtime_isolation_and_io(self):
        programs={
          'rust':r'''use std::{fs,io::{self,Read,Write}};
fn main(){
 for p in ["/opt/gnu/bin/cp","/bin/cp","/work","/proc/1/environ","/var/run/docker.sock","/tmp/harness/runner.py","/output","/etc/shadow"] { assert!(!std::path::Path::new(p).exists()); }
 assert!(fs::write("locked",b"bad").is_err());
 let mut data=Vec::new();io::stdin().read_to_end(&mut data).unwrap();
 fs::write("out",&data).unwrap(); std::os::unix::fs::symlink("out","link").unwrap();
 io::stdout().write_all(&data).unwrap();
}''',
          'py':'''import os,sys,socket,hashlib,shutil,pathlib,stat
assert os.getuid()==1000 and os.getgid()==1000
for p in ['/opt/gnu/bin/cp','/bin/cp','/work','/proc/1/environ','/var/run/docker.sock','/tmp/harness/runner.py','/output','/etc/shadow']:
    assert not os.path.exists(p)
try: open('locked','wb'); raise AssertionError('permissions bypassed')
except PermissionError: pass
try: os.setuid(0); raise AssertionError('root gained')
except PermissionError: pass
s=socket.socket(); s.settimeout(1)
try: s.connect(('1.1.1.1',80)); raise AssertionError('network accessible')
except OSError: pass
finally: s.close()
data=sys.stdin.buffer.read(); pathlib.Path('out').write_bytes(data); os.symlink('out','link'); sys.stdout.buffer.write(data)
'''}
        data=b'case transport\x00\xff\n'
        for language,text in programs.items():
            binary=self.build(language,text)
            result=docker.execute_case(language+'-cp',binary.read_bytes(),{
                'args':[],'stdin_b64':base64.b64encode(data).decode(),
                'fixture':[{'path':'locked','type':'file','contents_b64':'b2s=','mode':'0444'}]})['result']
            self.assertEqual(result['exit_code'],0,result)
            self.assertEqual(base64.b64decode(result['stdout']['$bytes']),data)
            self.assertEqual(result['modes']['out']['sha256'],hashlib.sha256(data).hexdigest())
            self.assertEqual(result['modes']['locked']['sha256'],hashlib.sha256(b'ok').hexdigest())
            self.assertEqual(result['modes']['link']['type'],'symlink')

    def test_syntax_failures_and_empty_python_are_candidate_failures(self):
        for suffix,text in [('rs','invalid Rust'),('py','def broken(:'),('py','')]:
            source=self.root/('invalid.'+suffix); source.write_text(text)
            self.assertEqual(docker.compile_source(source,self.root/'invalid'),1)

    def test_python_and_rust_timeouts(self):
        for language,text in [('py','while True: pass\n'),('rust','fn main(){loop {std::hint::spin_loop();}}')]:
            binary=self.build(language,text)
            result=docker.execute_case(language+'-cp',binary.read_bytes(),{'args':[],'timeout':1})['result']
            self.assertTrue(result['timed_out'])

    def test_all_thirty_language_checkpoint_boundaries(self):
        for language in ('rust','py'):
            for utility in ('cp','mv','mkdir','sort'):
                status=2 if utility=='sort' else 1
                text=('fn main(){eprintln!("unknown option");std::process::exit('+str(status)+');}' if language=='rust'
                      else 'import sys\nsys.stderr.write("unknown option\\n")\nsys.exit('+str(status)+')\n')
                binary=self.build(language,text); selector=language+'-'+utility
                for checkpoint in gate.load_manifest(ROOT,selector)['checkpoints']:
                    self.assertTrue(gate.evaluate(ROOT,selector,checkpoint['id'],binary)['passed'],(selector,checkpoint['id']))

    def test_sixty_runtime_mutation_controls(self):
        for language in ('rust','py'):
            binary=self.build(language,'fn main(){}' if language=='rust' else 'pass\n')
            for utility in ('cp','mv','mkdir','sort'):
                selector=language+'-'+utility
                suite=docker.suite_root(ROOT,selector)
                manifest=gate.load_manifest(ROOT,selector)
                for hidden in (False,True):
                    corpus=json.loads(gzip.decompress((suite/('heldout/heldout_cases.json.gz' if hidden else 'suites/linux.json.gz')).read_bytes()))['cases']
                    for checkpoint in manifest['checkpoints']:
                        case=dict(next(c for c in corpus if not c.get('flags') and c.get('check','golden')=='golden'))
                        case['exit_code']=73
                        with contextlib.redirect_stdout(io.StringIO()):
                            verdict=docker.judge(selector,binary,checkpoint['implemented_flags'],hidden=hidden,cases_override=[case])
                        self.assertEqual(verdict['status'],1,(selector,checkpoint['id'],hidden))
                        self.assertEqual(verdict['report']['counts'].get('FAIL'),1)

    def test_permissive_boundaries_and_missing_docker_fail_closed(self):
        for language in ('rust','py'):
            binary=self.build(language,'fn main(){}' if language=='rust' else 'pass\n')
            self.assertFalse(gate.evaluate(ROOT,language+'-cp','000',binary)['passed'])
            with patch.object(docker.subprocess,'run',side_effect=FileNotFoundError('Docker unavailable')) as run:
                with self.assertRaises(docker.InfrastructureError):
                    docker.invoke('compile',{'language':language,'source':''})
                self.assertTrue(all(call.args[0][0]=='docker' for call in run.call_args_list))

