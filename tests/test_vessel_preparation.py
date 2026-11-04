"""Vessel preparation regressions: metadata mocks and print-only/failing shell paths."""
import contextlib
import ast
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
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

    @contextlib.contextmanager
    def rebuilt_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config = dict(self.config)
            images = copy.deepcopy(self.images)
            for index, key in enumerate(v.IMAGE_KEYS):
                data = images.pop(self.config[key])
                data['Id'] = 'sha256:' + str(index + 1) * 64
                if key != 'compiler_image':
                    config[key] = data['Id']
                    data['Descriptor']['digest'] = 'sha256:' + str(index + 4) * 64
                images[config[key]] = data
            del images[config['oracle_image']]['Descriptor']['platform']
            environment = {'revision': 'a' * 40, 'dockerfiles': {'Dockerfile': 'digest'}, 'docker': {'ID': 'vessel'}}
            bases = [config['compiler_image'], config['rust_base_image']]
            build = {'revision': 'b' * 40, 'dockerfiles': environment['dockerfiles'], 'pinned_bases': bases,
                     'oracle_build_command': 'recorded oracle command', 'rust_build_command': 'recorded rust command',
                     'builder_description': 'operator build record'}
            provenance = {'schema_version': 1, 'mode': 'vessel-built',
                          'baseline_lock_sha256': v.canonical_sha(self.config), 'lock_sha256': v.canonical_sha(config),
                          'environment': environment, 'build_record': build, 'pinned_bases': bases,
                          'windows_byte_identity_claimed': False,
                          'images': {k: {'execution_ref': config[k], 'identity': v.rebuilt_identity(images[config[k]]),
                                         'inspect': images[config[k]], 'history': 'captured history'} for k in v.IMAGE_KEYS}}
            provenance['images']['oracle_image']['build_metadata'] = {
                'base-image.txt': config['compiler_image'], 'build-architecture.txt': 'amd64',
                'packages.txt': 'recorded packages', 'compiler.txt': 'gcc'}
            lock = directory / 'lock.json'
            args = SimpleNamespace(vessel_provenance=directory / 'provenance.json',
                                   vessel_validation=directory / 'validation' / 'validation.json',
                                   vessel_approval=directory / 'approval.json')
            v.write_new_json(lock, config)
            v.write_new_json(args.vessel_provenance, provenance)
            with patch.dict(os.environ, LINUX_BENCHMARK_LOCK=str(lock)), \
                    patch.object(v, 'vessel_environment', return_value=environment), \
                    patch.object(v, 'git_dockerfile_hashes', return_value=environment['dockerfiles']), \
                    patch.object(v, 'check_jailed_execution'), \
                    patch.object(v, 'inspect_image', side_effect=lambda ref, platform: images[ref]):
                binding = v.vessel_binding(config, lock, args.vessel_provenance)
                args.vessel_validation.parent.mkdir()
                for name in v.required_validation_files(args.vessel_validation.parent, config):
                    path = args.vessel_validation.parent / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('fixture report')
                (args.vessel_validation.parent / 'step.log').write_text('complete fixture output')
                commands = v.validation_commands(args.vessel_validation.parent, config)
                report = {'schema_version': 1, 'passed': True, 'binding': binding,
                          'generation_invoked': False, 'infrastructure_failure': False,
                          'completed_at': v.time.time(), 'commands': commands, 'returncodes': [0] * len(commands),
                          'checks': [{'check': c, 'status': 'PASS'} for c in v.required_validation_checks()],
                          'files': v.validation_files(args.vessel_validation.parent)}
                v.write_new_json(args.vessel_validation, report)
                v.write_new_json(args.vessel_approval, {'schema_version': 1, 'validation_sha256': v.file_sha(args.vessel_validation),
                                                       'binding_sha256': v.canonical_sha(binding), 'scope': 'diagnostic-only'})
                yield config, lock, args, images, report

    def test_rebuilt_missing_descriptor_platform_is_separate_from_original_auth(self):
        with self.rebuilt_fixture() as (config, lock, args, images, report):
            self.assertTrue(v.check_vessel_built(config, lock, args))
            with self.assertRaises(ValueError):
                v.image_identity(images[config['oracle_image']])
            self.assertFalse(v.check_images(config, lock, self.evidence))
            for field, value in [('Architecture', 'arm64'), ('Config', {'Env': ['different']}),
                                 ('Id', 'sha256:' + 'f' * 64), ('RootFS', {'Layers': ['sha256:' + 'e' * 64]})]:
                data = images[config['oracle_image']]
                original = data[field]
                data[field] = value
                self.assertFalse(v.check_vessel_built(config, lock, args), field)
                data[field] = original
            images[config['oracle_image']]['Descriptor']['platform'] = {'os': 'linux', 'architecture': 'arm64'}
            self.assertFalse(v.check_vessel_built(config, lock, args))

    def test_capture_uses_repository_digests_when_bare_ids_do_not_resolve(self):
        with self.rebuilt_fixture() as (config, lock, args, images, report):
            original = v.DEFAULT_LOCK.read_bytes()
            record_path = lock.parent / 'build-record.json'
            record_path.write_text(json.dumps(json.loads(args.vessel_provenance.read_text())['build_record']))
            aliases = {'agentic-linux-utilities:latest': config['oracle_image'],
                       'agentic-linux-utilities-rust:latest': config['rust_compiler_image']}
            expected = dict(config)
            for tag, image_id in list(aliases.items()):
                digest_ref = tag.rsplit(':', 1)[0] + '@' + image_id
                images[image_id]['RepoDigests'] = [digest_ref]
                aliases[digest_ref] = image_id
                key = 'oracle_image' if tag == 'agentic-linux-utilities:latest' else 'rust_compiler_image'
                expected[key] = digest_ref
            def inspect(ref, platform):
                self.assertEqual(platform, 'linux/amd64')
                if ref.startswith('sha256:'):
                    raise ValueError('bare image ID cannot be resolved')
                return images[aliases.get(ref, ref)]
            def probe(ref, command=None):
                self.assertIn(ref, expected.values())
                if command is None:
                    self.assertNotIn('latest', ref)
                    return 'x86_64'
                return {'base-image.txt': config['compiler_image'], 'build-architecture.txt': 'amd64',
                        'packages.txt': 'packages', 'compiler.txt': 'gcc'}[Path(command[1]).name]
            target = lock.parent / 'capture'
            with patch.object(v, 'check_docker', return_value=True), patch.object(v, 'required_run', return_value='history'), \
                    patch.object(v, 'probe_reference', side_effect=probe) as probes, \
                    patch.object(v, 'inspect_image', side_effect=inspect):
                v.prepare_vessel_lock(target, record_path)
                with self.assertRaises(FileExistsError):
                    v.prepare_vessel_lock(target, record_path)
                failed = lock.parent / 'failed-capture'
                with patch.object(v, 'probe_reference', side_effect=ValueError('execution failed')):
                    with self.assertRaisesRegex(ValueError, 'execution failed'):
                        v.prepare_vessel_lock(failed, record_path)
                self.assertFalse((failed / 'lock.json').exists())
                self.assertFalse((failed / 'provenance.json').exists())
            self.assertEqual(json.loads((target / 'lock.json').read_text()), expected)
            for key in v.IMAGE_KEYS:
                self.assertIn(unittest.mock.call(expected[key]), probes.call_args_list)
            self.assertEqual(v.DEFAULT_LOCK.read_bytes(), original)
            self.assertFalse((target / 'validation.json').exists())
            self.assertFalse(json.loads((target / 'provenance.json').read_text())['windows_byte_identity_claimed'])

    def test_repository_digest_selection_rejects_missing_and_mismatched_images(self):
        with self.rebuilt_fixture() as (config, lock, args, images, report):
            data = images[config['oracle_image']]
            identity = v.rebuilt_identity(data)
            ref = 'agentic-linux-utilities:latest'
            data['RepoDigests'] = ['mutable:latest', 'example@sha256:' + 'c' * 64]
            with patch.object(v, 'inspect_image', side_effect=ValueError('missing')):
                with self.assertRaisesRegex(ValueError, 'no locally resolvable'):
                    v.repository_execution_ref(ref, data, identity)
            changed = copy.deepcopy(data)
            changed['Config'] = {'Env': ['changed']}
            with patch.object(v, 'inspect_image', return_value=changed):
                with self.assertRaisesRegex(ValueError, 'no locally resolvable'):
                    v.repository_execution_ref(ref, data, identity)
            # A matching repository-qualified manifest also works when Docker
            # omits RepoDigests; it must still be inspected, never assumed.
            data['RepoDigests'] = []
            with patch.object(v, 'inspect_image', return_value=data) as inspect:
                selected = v.repository_execution_ref(ref, data, identity)
                self.assertEqual(selected, 'agentic-linux-utilities@' + identity['manifest_digest'])
                inspect.assert_called_once_with(selected, 'linux/amd64')

    def test_rebuilt_validation_rejects_stale_missing_incomplete_and_modified_reports(self):
        with self.rebuilt_fixture() as (config, lock, args, images, report):
            original = args.vessel_validation.read_text()
            for field, value in [('passed', False), ('completed_at', 0), ('completed_at', v.time.time() + 100),
                                 ('binding', {}), ('commands', []), ('returncodes', [0]), ('files', {}), ('checks', [])]:
                changed = dict(report, **{field: value})
                args.vessel_validation.write_text(json.dumps(changed))
                self.assertFalse(v.check_vessel_built(config, lock, args, require_approval=False), field)
            args.vessel_validation.write_text(original)
            (args.vessel_validation.parent / 'step.log').write_text('changed')
            self.assertFalse(v.check_vessel_built(config, lock, args))
            args.vessel_validation.unlink()
            self.assertFalse(v.check_vessel_built(config, lock, args))

    def test_rebuilt_approval_provenance_environment_and_active_adapter_required(self):
        with self.rebuilt_fixture() as (config, lock, args, images, report):
            args.vessel_approval.unlink()
            self.assertFalse(v.check_vessel_built(config, lock, args))
            self.assertTrue(v.check_vessel_built(config, lock, args, require_approval=False))
            with patch.object(v, 'vessel_environment', return_value={'revision': 'changed'}):
                self.assertFalse(v.check_vessel_built(config, lock, args))
            with patch.dict(os.environ, LINUX_BENCHMARK_LOCK=str(v.DEFAULT_LOCK)):
                self.assertFalse(v.check_vessel_built(config, lock, args, require_approval=False))
            changed = dict(config, gcc='different')
            with self.assertRaises(ValueError):
                v.vessel_binding(changed, lock, args.vessel_provenance)
            args.vessel_provenance.write_text('{}')
            self.assertFalse(v.check_vessel_built(config, lock, args, require_approval=False))

    def test_validation_stops_at_first_failed_command_and_never_approves(self):
        with self.rebuilt_fixture() as (config, lock, args, images, report), contextlib.ExitStack() as stack:
            for name in ('check_python_and_bash', 'check_timeout', 'check_architecture_probe', 'check_toolchains', 'check_checkpoints'):
                stack.enter_context(patch.object(v, name))
            invocation = stack.enter_context(patch.object(v.subprocess, 'run', return_value=SimpleNamespace(returncode=1)))
            directory = lock.parent / 'failed-validation'
            with self.assertRaisesRegex(ValueError, 'infrastructure/environment failure'):
                v.validate_vessel(directory, config, lock, args.vessel_provenance, args)
            self.assertEqual(invocation.call_count, 1)
            self.assertFalse(json.loads((directory / 'validation.json').read_text())['passed'])
            self.assertIsNone(v.VALIDATION_LOG)

    def test_vessel_capture_requires_opt_in_and_never_checks_models(self):
        with patch.object(v, 'prepare_vessel_lock') as prepare, patch.object(v, 'check_aider') as aider, patch.object(v, 'check_ollama') as ollama:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                v.main(['--prepare-vessel-lock', '/tmp/new'])
            prepare.assert_not_called()
            self.assertEqual(v.main(['--image-mode', 'vessel-built', '--prepare-vessel-lock', '/tmp/new']), 0)
            aider.assert_not_called()
            ollama.assert_not_called()

    def test_immutable_probe_failure_and_cleanup(self):
        with patch.object(v, 'run', side_effect=[(1, '', 'cannot execute digest'), (0, '', '')]) as invoke:
            with self.assertRaisesRegex(ValueError, 'cannot execute digest'):
                v.probe_reference('sha256:' + '1' * 64)
            self.assertIn('--pull', invoke.call_args_list[0].args[0])
            self.assertEqual(invoke.call_args_list[1].args[0][:3], ['docker', 'rm', '-fv'])

    def test_changed_python_files_parse(self):
        for name in ('scripts/vessel_preflight.py', 'tests/test_vessel_preparation.py',
                     'tests/test_docker_benchmark_integration.py'):
            ast.parse((ROOT / name).read_text(), filename=name)

    def test_diagnostic_profile_invalidates_standard_validation_approval(self):
        for validated, changed in (('0', '1'), ('1', '0')):
            with patch.dict(os.environ, VESSEL_DIAGNOSTIC_ROSETTA=validated), self.rebuilt_fixture() as (config, lock, args, images, report):
                self.assertTrue(v.check_vessel_built(config, lock, args))
                with patch.dict(os.environ, VESSEL_DIAGNOSTIC_ROSETTA=changed), patch.object(v, 'check_jailed_execution') as jail:
                    self.assertFalse(v.check_vessel_built(config, lock, args))
                    jail.assert_not_called()

    def test_diagnostic_preflight_requires_explicit_vessel_built_opt_in(self):
        with patch.dict(os.environ, VESSEL_DIAGNOSTIC_ROSETTA='1'), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                v.main(['--image-mode', 'vessel-built', '--verify-vessel-built'])
        with patch.dict(os.environ, VESSEL_DIAGNOSTIC_ROSETTA='0'), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                v.main(['--diagnostic-rosetta'])
            with patch.object(v, 'prepare_vessel_lock') as prepare:
                self.assertEqual(v.main(['--diagnostic-rosetta', '--image-mode', 'vessel-built',
                                         '--prepare-vessel-lock', '/tmp/not-created']), 0)
                prepare.assert_called_once()
                self.assertEqual(os.environ['VESSEL_DIAGNOSTIC_ROSETTA'], '1')

    def test_git_build_revision_hashes_raw_blobs_and_rejects_mismatch(self):
        import hashlib
        blobs = [b'FROM pinned\n', b'FROM rust\n\n']
        with patch.object(v, 'required_run') as commit, patch.object(v.subprocess, 'run',
                side_effect=[SimpleNamespace(returncode=0, stdout=b) for b in blobs]) as show:
            hashes = v.git_dockerfile_hashes('a' * 40)
        self.assertEqual(hashes, {p: hashlib.sha256(b).hexdigest() for p, b in zip(v.DOCKERFILES, blobs)})
        commit.assert_called_once_with(['git', 'cat-file', '-e', 'a' * 40 + '^{commit}'])
        self.assertEqual(show.call_args_list[0].args[0], ['git', 'show', 'a' * 40 + ':' + v.DOCKERFILES[0]])
        with self.rebuilt_fixture() as (config, lock, args, images, report):
            with patch.object(v, 'git_dockerfile_hashes', return_value={'different': 'hash'}):
                self.assertFalse(v.check_vessel_built(config, lock, args))
        with patch.object(v, 'required_run', side_effect=ValueError('unknown revision')):
            with self.assertRaisesRegex(ValueError, 'unknown revision'):
                v.git_dockerfile_hashes('0' * 40)
        with patch.object(v, 'required_run'), patch.object(v.subprocess, 'run',
                return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(ValueError, 'cannot read'):
                v.git_dockerfile_hashes('a' * 40)

    def test_emulation_identity_records_vm_registration_and_interpreter(self):
        registration = {'boot_id': 'boot-one', 'registrations': {
            'status': 'enabled\n', 'qemu-x86_64': 'enabled\ninterpreter /usr/bin/qemu-x86_64\nflags: F\n'}}
        with patch.object(v, 'probe_reference', side_effect=[json.dumps(registration), 'a' * 64]) as probe:
            identity = v.emulation_identity()
        self.assertEqual(identity['interpreter_sha256'], {'/usr/bin/qemu-x86_64': 'a' * 64})
        self.assertIn('type=bind,src=/proc/sys/fs/binfmt_misc,dst=/binfmt,readonly', probe.call_args_list[0].args[2])
        self.assertIn('type=bind,src=/usr/bin/qemu-x86_64,dst=/emulator,readonly', probe.call_args_list[1].args[2])
        with patch.object(v, 'probe_reference', side_effect=ValueError('unreadable emulator')):
            with self.assertRaisesRegex(ValueError, 'unreadable'):
                v.emulation_identity()

    def test_emulation_change_and_failed_fresh_jail_invalidate_approval(self):
        with self.rebuilt_fixture() as (config, lock, args, images, report):
            environment = report['binding']['environment']
            for emulation in ({'boot_id': 'new'}, {'registrations': 'flags changed'},
                              {'interpreter_sha256': 'changed'}):
                with patch.object(v, 'vessel_environment', return_value=dict(environment, emulation=emulation)):
                    self.assertFalse(v.check_vessel_built(config, lock, args))
            with patch.object(v, 'check_jailed_execution', side_effect=ValueError('jail failed')):
                self.assertFalse(v.check_vessel_built(config, lock, args))
            with patch.object(v, 'check_jailed_execution') as jail:
                self.assertTrue(v.check_vessel_built(config, lock, args))
                jail.assert_called_once_with()
            with patch.object(v, 'check_jailed_execution') as jail:
                self.assertTrue(v.check_vessel_built(config, lock, args, require_approval=False))
                jail.assert_not_called()
            binding = report['binding']
            with patch.object(v, 'vessel_binding', side_effect=[binding, dict(binding, environment={})]):
                self.assertFalse(v.check_vessel_built(config, lock, args))

    def test_fresh_jail_uses_real_docker_controls_and_fails_closed(self):
        for code in (1, 124, 127):
            with patch.object(v, 'run', return_value=(code, '', 'failed')) as run:
                with self.assertRaisesRegex(ValueError, 'infrastructure failure'):
                    v.check_jailed_execution()
                command = run.call_args.args[0]
                self.assertIn('tests.test_docker_benchmark_integration.DockerIntegration.test_nonroot_chroot_and_no_controller_assets', command)
                self.assertIn('tests.test_cross_language_docker.CrossLanguageDocker.test_real_rust_and_python_runtime_isolation_and_io', command)


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

    def test_bash_syntax_and_three_checkpoint_zero_print_commands(self):
        import shlex
        import lineage_plan
        for script in ('scripts/vessel_smoke_stage.sh', 'docker/linux-utilities/build.sh', 'docker/linux-utilities/run.sh'):
            subprocess.run(['/bin/bash', '-n', str(ROOT / script)], check=True)
        with tempfile.TemporaryDirectory() as temp:
            for selector in v.DEFAULT_SELECTORS:
                command = self.command('--image-mode', 'vessel-built', '--output-dir', str(Path(temp) / selector))
                command[command.index('--selector') + 1] = selector
                result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, TMPDIR=temp), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((Path(temp) / selector).exists())
                line = next(row.strip() for row in result.stdout.splitlines() if row.startswith('  bash scripts/run_experiment.sh'))
                words = shlex.split(line)
                plan = lineage_plan.resolve_plan(ROOT, selector, '', '1', None, 1, 1)
                for option, field in (('--build-cmd', 'build_command'), ('--extra-test-cmd', 'extra_test_command'), ('--source', 'source_path')):
                    self.assertEqual(words[words.index(option) + 1], plan[field])
                self.assertEqual(words[words.index('--feature-test-cmd') + 1], plan['checkpoints'][0]['feature_test_command'])

    def test_failed_preflight_cannot_reach_runner_and_retains_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shim = root / 'python-shim'
            shim.write_text('#!' + sys.executable + '\nimport os,sys,json\n'
                            'from pathlib import Path\n'
                            'if sys.argv[1].endswith("vessel_preflight.py"):\n'
                            ' if "--verify-vessel-built" in sys.argv: print(json.dumps(sys.argv)); sys.exit(1)\n'
                            ' ok=os.environ.get("TEST_INITIAL_PASS")=="yes"\n'
                            ' p=Path(sys.argv[sys.argv.index("--json-report")+1]); p.write_text(json.dumps({"preflight_passed":ok,"models":{"architect":{},"editor":{}}})); sys.exit(0 if ok else 1)\n'
                            'os.execv(sys.executable,[sys.executable]+sys.argv[1:])\n')
            shim.chmod(0o755)
            sentinel = root / 'runner-called'
            bash = root / 'bash'
            bash.write_text('#!/bin/sh\nprintf forbidden >"' + str(sentinel) + '"\nexit 99\n')
            bash.chmod(0o755)
            for mode, initial_pass, rosetta in (('original', False, False), ('vessel-built', False, False),
                                                ('vessel-built', True, False), ('vessel-built', True, True)):
                output = root / ('diagnostic-%s-%s-%s' % (mode, initial_pass, rosetta))
                extra = ['--diagnostic-rosetta'] if rosetta else []
                result = subprocess.run(self.command('--image-mode', mode, '--generate', '--output-dir', str(output), *extra), cwd=ROOT,
                                        env=dict(os.environ, PYTHON_BIN=str(shim), TMPDIR=temp,
                                                 TEST_INITIAL_PASS='yes' if initial_pass else 'no',
                                                 PATH=temp + os.pathsep + os.environ['PATH']), capture_output=True, text=True)
                self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
                self.assertFalse(sentinel.exists())
                self.assertEqual(json.loads((output / 'preflight.json').read_text())['preflight_passed'], initial_pass)
                if initial_pass:
                    self.assertTrue((output / 'image-recheck.log').exists())
                    if rosetta:
                        self.assertIn('--diagnostic-rosetta', (output / 'image-recheck.log').read_text())
                else:
                    self.assertFalse((output / '000').exists())


class RosettaDiagnosticTests(unittest.TestCase):
    def test_docker_isolation_is_identical_except_explicit_worker_profile(self):
        import docker_benchmark as docker
        for action, language in (('case', 'c'), ('compile', 'c'), ('compile', 'rust'), ('compile', 'py')):
            with patch.dict(os.environ, VESSEL_DIAGNOSTIC_ROSETTA='0'):
                standard = docker.command(action, 'probe', language)
                self.assertEqual(docker.execution_profile()['rlimit_as_bytes'], 256 * 1024**2)
            with patch.dict(os.environ, VESSEL_DIAGNOSTIC_ROSETTA='1'):
                diagnostic = docker.command(action, 'probe', language)
                self.assertIs(docker.execution_profile()['formal_result'], False)
                self.assertIsNone(docker.execution_profile()['rlimit_as_bytes'])
            index = diagnostic.index('BENCHMARK_DIAGNOSTIC_ROSETTA=1')
            self.assertEqual(diagnostic[index - 1], '-e')
            del diagnostic[index - 1:index + 1]
            self.assertEqual(diagnostic, standard)
        with patch.dict(os.environ, VESSEL_DIAGNOSTIC_ROSETTA='unexpected'):
            with self.assertRaises(docker.InfrastructureError):
                docker.command('case', 'probe')
        config = dict(docker.settings(), platform='linux/arm64')
        with patch.dict(os.environ, VESSEL_DIAGNOSTIC_ROSETTA='1'), patch.object(docker, 'settings', return_value=config):
            with self.assertRaises(docker.InfrastructureError):
                docker.command('case', 'probe')

    @unittest.skipUnless(os.name == 'posix', 'Linux resource module')
    def test_only_address_space_rlimit_changes(self):
        import docker_benchmark_worker as worker
        import resource
        observed = []
        for mode in ('0', '1'):
            with patch.dict(os.environ, BENCHMARK_DIAGNOSTIC_ROSETTA=mode), patch.object(worker.resource, 'setrlimit') as limit:
                worker.set_jail_limits()
                observed.append({call.args[0]: call.args[1] for call in limit.call_args_list})
        self.assertEqual(observed[0].pop(resource.RLIMIT_AS), (256 * 1024**2,) * 2)
        self.assertEqual(observed[1].pop(resource.RLIMIT_AS), (resource.RLIM_INFINITY,) * 2)
        self.assertEqual(observed[0], observed[1])
        self.assertEqual(observed[0], {resource.RLIMIT_CORE: (0, 0), resource.RLIMIT_CPU: (10, 10),
                                      resource.RLIMIT_FSIZE: (64 * 1024**2,) * 2, resource.RLIMIT_NPROC: (16, 16)})

    @unittest.skipUnless(os.name == 'posix', 'Bash entrypoints')
    def test_formal_and_direct_generation_reject_diagnostic_environment(self):
        for script in ('run_lineage_experiment.sh', 'run_experiment.sh'):
            result = subprocess.run(['/bin/bash', str(ROOT / 'scripts' / script), '--help'],
                                    env=dict(os.environ, VESSEL_DIAGNOSTIC_ROSETTA='1',
                                             VESSEL_DIAGNOSTIC_GENERATION_APPROVED='0'), capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('Rosetta diagnostics', result.stderr)
        result = subprocess.run(['/bin/bash', str(ROOT / 'scripts/run_lineage_experiment.sh'), '--help'],
                                env=dict(os.environ, VESSEL_DIAGNOSTIC_ROSETTA='1',
                                         VESSEL_DIAGNOSTIC_GENERATION_APPROVED='1'), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    @unittest.skipUnless(os.name == 'posix', 'Bash metadata writer')
    def test_diagnostic_attempt_metadata_cannot_claim_formal_results(self):
        import shlex
        script = (ROOT / 'scripts/run_experiment.sh').read_text()
        writer = 'write_metadata() {' + script.split('write_metadata() {', 1)[1].split('\n}\n', 1)[0] + '\n}\n'
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'metadata.json'
            for mode in ('0', '1'):
                result = subprocess.run(['/bin/bash'], input=writer + '\nwrite_metadata ' + shlex.quote(str(target)) + ' formal_result true\n',
                                        env=dict(os.environ, PYTHON_BIN=sys.executable, VESSEL_DIAGNOSTIC_ROSETTA=mode),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(target.read_text())
                self.assertEqual(data['formal_result'], mode == '0')
                if mode == '1':
                    self.assertIs(data['diagnostic_only'], True)
                    self.assertEqual(data['execution_profile'], 'vessel-rosetta-diagnostic')
                    self.assertIsNone(data['rlimit_as_bytes'])
                else:
                    self.assertNotIn('execution_profile', data)


@unittest.skipUnless(os.name == 'posix', 'Bash regression tests run under WSL/macOS')
class OracleLauncherTests(unittest.TestCase):
    """Real shell execution with Docker and staging copies stubbed; no workloads."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.log = self.root / 'docker.jsonl'
        self.image_id = 'sha256:' + 'b' * 64
        docker = self.root / 'docker'
        docker.write_text('#!' + sys.executable + '\n'
            'import json,os,sys\n'
            'with open(os.environ["DOCKER_LOG"],"a") as out: out.write(json.dumps(sys.argv[1:])+"\\n")\n'
            'if sys.argv[1:3]==["image","inspect"] and "--platform" in sys.argv:\n'
            ' print(os.environ["INSPECT_ID"]); sys.exit(int(os.environ.get("INSPECT_EXIT","0")))\n'
            'if sys.argv[1]=="cp":\n'
            ' from pathlib import Path\n'
            ' outgoing=":/output/." in sys.argv[2]\n'
            ' if os.environ.get("COPY_FAIL")==("out" if outgoing else "in"): sys.exit(1)\n'
            ' if outgoing:\n'
            '  p=Path(sys.argv[3])/"validated/c-cp/validation.json"; p.parent.mkdir(parents=True); p.write_text("{}")\n'
            'if sys.argv[1]=="run": sys.exit(int(os.environ.get("STATIC_EXIT","0")))\n'
            'if "{{.State.ExitCode}}" in sys.argv: print(os.environ.get("ORACLE_EXIT","0"))\n'
            'elif "{{.State.Status}}" in sys.argv: print("exited")\n'
            'else: print("{}")\n')
        docker.chmod(0o755)
        copy = self.root / 'cp'
        copy.write_text('#!/bin/sh\nexit 0\n')
        copy.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                        TMPDIR=str(self.root), DOCKER_LOG=str(self.log), INSPECT_ID=self.image_id)

    def invoke(self, ref, number=0, **env):
        output = self.root / ('output-' + str(number))
        result = subprocess.run(['/bin/bash', str(ROOT / 'docker/linux-utilities/run.sh'),
                                 ref, str(output), 'linux/amd64'],
                                env=dict(self.env, **env), capture_output=True, text=True)
        return result, output

    def test_immutable_refs_keep_execution_platform_isolation_and_provenance(self):
        digest = 'sha256:' + 'a' * 64
        refs = [digest, 'agentic-linux-utilities@' + digest,
                'agentic-linux-utilities-rust@' + digest,
                'localhost:5000/team/image@' + digest,
                'registry.example/team/image:release@' + digest]
        for i, ref in enumerate(refs):
            with self.subTest(ref=ref):
                result, output = self.invoke(ref, i)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = [json.loads(line) for line in self.log.read_text().splitlines()]
                create = next(call for call in calls if call[0] == 'create' and 'bash' in call)
                self.assertEqual(create[create.index('--pull') + 1], 'never')
                self.assertEqual(create[create.index('--platform') + 1], 'linux/amd64')
                self.assertEqual(create[create.index('--network') + 1], 'none')
                self.assertIn('--read-only', create)
                self.assertEqual(create[create.index('--cap-drop') + 1], 'ALL')
                self.assertIn('no-new-privileges', create)
                for option, value in (('--cpus', '2'), ('--memory', '2g'), ('--pids-limit', '128')):
                    self.assertEqual(create[create.index(option) + 1], value)
                self.assertEqual(create[create.index('bash') - 1], ref)
                self.assertIn('BENCHMARK_ARCH=x86_64', create)
                self.assertIn('BENCHMARK_IMAGE_ID=' + (self.image_id if '@' in ref else ref), create)
                self.assertTrue((output / 'validation.log').is_file())
                self.assertTrue((output / 'validated/c-cp/validation.json').is_file())
                self.assertFalse(any('type=bind' in arg for call in calls for arg in call))
                self.assertTrue(any(arg.startswith('type=volume,') and arg.endswith('target=/work,readonly') for arg in create))
                self.assertTrue(any(call[0] == 'cp' and call[2].endswith(':/work') for call in calls))
                self.assertEqual(calls[-1][:2], ['volume', 'rm'])
                self.log.unlink()

    def test_mutable_and_malformed_refs_stop_before_docker_or_output(self):
        digest = 'sha256:' + 'a' * 64
        refs = ['image', 'image:latest', '@' + digest, 'image@@' + digest,
                'image@sha256:abc', 'image@sha256:' + 'A' * 64,
                'image@sha512:' + 'a' * 64, 'image@' + digest + 'extra',
                'bad image@' + digest, 'team//image@' + digest, '-image@' + digest,
                'image/@' + digest, 'https://registry/image@' + digest]
        for ref in refs:
            with self.subTest(ref=ref):
                result, output = self.invoke(ref)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(output.exists())
                self.assertFalse(self.log.exists())

    def test_failed_resolution_and_oracle_failure_remain_fail_closed(self):
        ref = 'image@sha256:' + 'a' * 64
        for env in ({'INSPECT_EXIT': '1'}, {'INSPECT_ID': 'malformed'}):
            result, output = self.invoke(ref, **env)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
            self.assertFalse(any(json.loads(line)[0] == 'create' for line in self.log.read_text().splitlines()))
            self.log.unlink()
        result, output = self.invoke(ref, ORACLE_EXIT='7')
        self.assertEqual(result.returncode, 7)
        self.assertTrue((output / 'container-inspect.json').exists())
        self.assertTrue((output / 'validated/c-cp/validation.json').exists())

    def test_oracle_copy_failures_stop_validation_and_cleanup_volumes(self):
        ref = 'image@sha256:' + 'a' * 64
        for i, direction in enumerate(('in', 'out')):
            result, output = self.invoke(ref, i, COPY_FAIL=direction)
            self.assertNotEqual(result.returncode, 0)
            calls = [json.loads(line) for line in self.log.read_text().splitlines()]
            self.assertEqual(calls[-1][:2], ['volume', 'rm'])
            self.assertEqual(calls[-2][:2], ['rm', '-fv'])
            if direction == 'in':
                self.assertFalse(any(call[0] == 'start' for call in calls))
            else:
                self.assertEqual(result.returncode, 2)
                self.assertTrue((output / 'container-inspect.json').is_file())
            self.log.unlink()

    def test_static_validator_copies_inputs_and_preserves_all_checks(self):
        lock = self.root / 'lock.json'
        config = json.loads(v.DEFAULT_LOCK.read_text())
        config['oracle_image'] = 'image@sha256:' + 'a' * 64
        lock.write_text(json.dumps(config))
        for i, extra in enumerate(({}, {'STATIC_EXIT': '7'}, {'COPY_FAIL': 'in'})):
            output = self.root / ('static-' + str(i))
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/validate_linux_static.py'),
                                     '--output', str(output)], capture_output=True, text=True,
                                    env=dict(self.env, LINUX_BENCHMARK_LOCK=str(lock), **extra))
            self.assertEqual(result.returncode == 0, not extra, result.stderr)
            calls = [json.loads(line) for line in self.log.read_text().splitlines()]
            self.assertFalse(any('type=bind' in arg for call in calls for arg in call))
            runs = [call for call in calls if call[0] == 'run']
            self.assertEqual(len(runs), 0 if 'COPY_FAIL' in extra else 4)
            for call in runs:
                self.assertIn('--read-only', call)
                self.assertEqual(call[call.index('--pull') + 1], 'never')
                self.assertIn('BENCHMARK_IMAGE_ID=' + self.image_id, call)
                self.assertTrue(any(arg.endswith('target=/work,readonly') for arg in call))
            self.assertEqual(calls[-2][:2], ['rm', '-fv'])
            self.assertEqual(calls[-1][:2], ['volume', 'rm'])
            if runs:
                summary = json.loads((output / 'summary.json').read_text())
                self.assertEqual(set(summary), {'syntax', 'contract', 'static', 'isolation'})
            self.log.unlink()


if __name__ == '__main__':
    unittest.main()
