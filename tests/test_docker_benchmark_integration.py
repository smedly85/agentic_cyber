"""Bounded infrastructure smoke tests, never lineage seeds or research results.

Host Python only transports data. All C compilation/execution and judging take
place in Docker. Temporary source/executable files are removed on completion.
"""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import docker_benchmark as docker
import checkpoint_boundary_gate as gate


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
#include <unistd.h>
#include <sys/socket.h>
#include <arpa/inet.h>
int main(void) {
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
'''.replace('if (chroot("/")==0) return 12;', 'if (setuid(0)==0) return 12;'))
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
