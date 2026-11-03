"""Vessel preparation regressions: metadata mocks and print-only/failing shell paths."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import vessel_preflight as v


class PreflightTests(unittest.TestCase):
    def setUp(self):
        v.RESULTS.clear()
        v.MODEL_IDENTITIES.clear()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.config = json.loads(v.DEFAULT_LOCK.read_text())
        self.images = {}
        for key in v.IMAGE_KEYS:
            self.images[self.config[key]] = {
                'Os': 'linux', 'Architecture': 'amd64', 'Config': {'Env': ['PATH=/usr/bin']},
                'RootFS': {'Layers': ['sha256:' + 'a' * 64]},
                'Descriptor': {'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                               'digest': v.AMD64_MANIFESTS[key],
                               'platform': {'os': 'linux', 'architecture': 'amd64'}}}
        self.evidence = {'schema_version': 1, 'baseline_lock_sha256': v.canonical_sha(self.config),
                         'images': {k: {'original_ref': self.config[k],
                                        'identity': v.image_identity(self.images[self.config[k]])}
                                    for k in v.IMAGE_KEYS}}

    def verify(self, config=None, evidence=None):
        def inspect(ref, platform):
            key = next(k for k in v.IMAGE_KEYS if ref in (self.config[k], v.AMD64_MANIFESTS[k]))
            return self.images[self.config[key]]
        roots = {self.config[k]: self.evidence['images'][k]['identity']['rootfs_sha256'] for k in v.IMAGE_KEYS}
        with patch.object(v, 'inspect_image', side_effect=inspect), patch.object(v, 'AMD64_ROOTFS', roots):
            return v.check_images(config or self.config, Path('/tmp/alternate.json'), evidence)

    def test_original_and_manifest_refs_require_complete_evidence(self):
        self.assertFalse(self.verify())
        self.assertTrue(self.verify(evidence=self.evidence))
        alternate = dict(self.config, **v.AMD64_MANIFESTS)
        self.assertTrue(self.verify(alternate, self.evidence))
        self.assertEqual(v.IMAGE_IDENTITIES['oracle_image']['execution_ref'], alternate['oracle_image'])

    def test_unrelated_alternate_ref_and_lock_changes_fail(self):
        self.assertFalse(self.verify(dict(self.config, oracle_image='sha256:' + 'f' * 64), self.evidence))
        self.assertFalse(self.verify(dict(self.config, gcc='different'), self.evidence))

    def test_configuration_layers_platform_and_manifest_are_all_checked(self):
        original = copy.deepcopy(self.images)
        for field, value in [('Config', {'Entrypoint': ['/bin/sh']}),
                             ('RootFS', {'Layers': ['sha256:' + 'b' * 64]}),
                             ('Architecture', 'arm64'),
                             ('Descriptor', {'digest': 'sha256:' + 'c' * 64}),
                             ('Config', {})]:
            with self.subTest(field=field):
                self.images = copy.deepcopy(original)
                self.images[self.config['oracle_image']][field] = value
                self.assertFalse(self.verify(evidence=self.evidence))

    def test_classic_config_id_and_failed_platform_inspection_fail_closed(self):
        for result in [(0, '[{"Id":"sha256:' + 'a' * 64 + '"}]', ''), (1, '', 'unsupported platform')]:
            with patch.object(v, 'run', return_value=result), self.assertRaises(ValueError):
                v.inspect_image(self.config['oracle_image'], 'linux/amd64')

    def test_git_status_timeout_is_not_clean_even_with_allow_dirty(self):
        for failure in (1, 124):
            calls = [(0, 'head', ''), (0, 'branch', ''), (0, 'upstream', ''),
                     (failure, '', 'unavailable'), (0, '', '')]
            with patch.object(v, 'run', side_effect=calls):
                v.check_git(True)
            self.assertEqual(v.RESULTS[-1]['status'], 'FAIL')

    def test_docker_endpoint_precedence_and_remote_rejection(self):
        def run(argv, **kwargs):
            if argv[1:3] == ['context', 'show']:
                return 0, 'default', ''
            if argv[1:3] == ['context', 'inspect']:
                return 0, 'unix:///tmp/docker.sock' if argv[3] == 'local' else 'ssh://remote', ''
            if argv[1] == 'info':
                return 0, json.dumps({'OSType': 'linux'}), ''
            raise AssertionError(argv)
        for env, expected in [({'DOCKER_CONTEXT': 'local', 'DOCKER_HOST': 'tcp://remote:2375'}, True),
                              ({'DOCKER_CONTEXT': 'remote', 'DOCKER_HOST': 'unix:///tmp/docker.sock'}, False),
                              ({'DOCKER_HOST': 'tcp://remote:2375'}, False),
                              ({'DOCKER_HOST': 'unix:///tmp/docker.sock'}, True), ({}, False)]:
            with patch.dict(os.environ, env, clear=True), patch.object(v.shutil, 'which', side_effect=lambda x: x if x == 'docker' else None), patch.object(v, 'run', side_effect=run) as invoke:
                self.assertEqual(v.check_docker('linux/amd64'), expected)
                if not expected:
                    self.assertFalse(any(c.args[0][1] == 'info' for c in invoke.call_args_list))

    def test_model_requires_identity_metadata_and_retains_observation(self):
        entry = {'name': 'model:tag', 'digest': 'a' * 64, 'size': 42,
                 'details': {'parameter_size': '1B', 'quantization_level': 'Q4'}}
        for missing in (None, 'digest', 'size', 'details', 'context'):
            v.MODEL_IDENTITIES.clear()
            model = copy.deepcopy(entry)
            if missing in model:
                del model[missing]
            show = {} if missing == 'context' else {'model_info': {'test.context_length': 65536}}
            with patch.object(v, 'http_json', side_effect=[{'version': 'test'}, {'models': [model]}, show]):
                v.check_ollama('http://127.0.0.1:11434', [('architect', 'ollama_chat/model:tag')], '65536')
            self.assertEqual(v.RESULTS[-1]['status'], 'PASS' if missing is None else 'FAIL')
            self.assertEqual(bool(v.MODEL_IDENTITIES), missing is None)

    def test_architecture_cleanup_runs_on_success_failure_and_timeout(self):
        for result in [(0, 'x86_64', ''), (1, '', 'failed'), (124, '', 'timed out')]:
            with patch.object(v, 'run', side_effect=[result, (0, '', '')]) as invoke:
                v.check_architecture_probe(self.config)
            start, cleanup = [c.args[0] for c in invoke.call_args_list]
            self.assertEqual(cleanup, ['docker', 'rm', '-fv', start[start.index('--name') + 1]])
            self.assertIn('--read-only', start)

    def test_immediate_timeout_status_does_not_pass(self):
        with patch.object(v.shutil, 'which', return_value='/mock/timeout'), patch.object(v, 'run', return_value=(124, '', '')), patch.object(v.time, 'time', side_effect=[0, 0]):
            v.check_timeout()
        self.assertEqual(v.RESULTS[-1]['status'], 'FAIL')

    def test_preflight_report_and_temporary_paths_cannot_enter_repository(self):
        with self.assertRaises(ValueError):
            v.external_path(ROOT / 'build' / 'report.json')
        with patch.dict(os.environ, {'TMPDIR': str(ROOT / 'build')}), patch.object(v, 'check_git') as git:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                v.main([])
            self.assertEqual(error.exception.code, 2)
            git.assert_not_called()


@unittest.skipUnless(os.name == 'posix', 'Bash paths exercised under WSL/macOS')
class SmokeTests(unittest.TestCase):
    def command(self, *extra):
        return ['/bin/bash', str(ROOT / 'scripts/vessel_smoke_stage.sh'), '--selector', 'c-cp',
                '--timeout', '1', '--temperature', '1', '--architect-think', 'low',
                '--sampling-seed', '42', '--num-ctx', '65536', *extra]

    def test_tmpdir_and_symlink_output_inside_repo_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            link = Path(temp) / 'link'
            link.symlink_to(ROOT, target_is_directory=True)
            for extra, tmp in [([], str(ROOT / 'build')), (['--output-dir', str(link / 'forbidden-output')], temp)]:
                result = subprocess.run(self.command(*extra), cwd=ROOT, env=dict(os.environ, TMPDIR=tmp), capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_failed_preflight_cannot_reach_runner_and_retains_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shim = root / 'python-shim'
            shim.write_text('#!' + sys.executable + '\nimport os,sys,json\n'
                            'from pathlib import Path\n'
                            'if sys.argv[1].endswith("vessel_preflight.py"):\n'
                            ' p=Path(sys.argv[sys.argv.index("--json-report")+1]); p.write_text(json.dumps({"preflight_passed":False})); sys.exit(1)\n'
                            'os.execv(sys.executable,[sys.executable]+sys.argv[1:])\n')
            shim.chmod(0o755)
            sentinel = root / 'runner-called'
            bash = root / 'bash'
            bash.write_text('#!/bin/sh\nprintf forbidden >"' + str(sentinel) + '"\nexit 99\n')
            bash.chmod(0o755)
            output = root / 'diagnostic'
            result = subprocess.run(self.command('--generate', '--output-dir', str(output)), cwd=ROOT,
                                    env=dict(os.environ, PYTHON_BIN=str(shim), TMPDIR=temp,
                                             PATH=temp + os.pathsep + os.environ['PATH']), capture_output=True, text=True)
            self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
            self.assertFalse(sentinel.exists())
            self.assertFalse(json.loads((output / 'preflight.json').read_text())['preflight_passed'])
            self.assertFalse((output / '000').exists())


if __name__ == '__main__':
    unittest.main()
