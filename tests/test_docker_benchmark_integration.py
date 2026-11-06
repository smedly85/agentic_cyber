"""Bounded infrastructure smoke tests, never lineage seeds or research results.

Host Python only transports data. All C compilation/execution and judging take
place in Docker. Temporary source/executable files are removed on completion.
"""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
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


if __name__ == '__main__':
    unittest.main()
