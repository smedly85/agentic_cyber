"""Required infrastructure controls recovered from pre-cleanup commit 5c128adb.

These are validation probes, not experimental implementations or lineage seeds.
"""
import contextlib
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
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
            environment = {'revision': 'a' * 40, 'dockerfiles': {'Dockerfile': 'digest'}, 'docker': {'ID': 'vessel'},
                           'emulation': {'boot_id': 'boot-one', 'registrations': {'handler': 'enabled'},
                                         'interpreter_sha256': {'/emulator': 'a' * 64}}}
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
                                                       'binding_sha256': v.canonical_sha(v.stable_binding(binding)), 'scope': 'diagnostic-only'})
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


    def test_all_twelve_selectors_require_independent_entrypoint_evidence(self):
        import linux_utilities_catalog as catalog
        self.assertEqual(v.DEFAULT_SELECTORS, catalog.SELECTORS)
        self.assertEqual(len(v.DEFAULT_SELECTORS), 12)
        with self.rebuilt_fixture() as (config, lock, args, images, report):
            commands = v.validation_commands(args.vessel_validation.parent, config)
            self.assertEqual(len(commands), 16)  # oracle, integration, calibration, 12 entrypoints, static
            entries = [cmd for cmd in commands if '--utility' in cmd]
            self.assertEqual([cmd[cmd.index('--utility') + 1] for cmd in entries], list(catalog.SELECTORS))
            original = args.vessel_validation.read_text()
            for selector in catalog.SELECTORS:
                for kind in ('summary', 'public', 'heldout'):
                    relative = 'entry-%s/%s.json' % (selector, kind)
                    path = args.vessel_validation.parent / relative
                    saved = path.read_bytes()
                    path.unlink()
                    # Even rehashing a directory with a missing report must fail.
                    changed = dict(report, files=v.validation_files(path.parent.parent))
                    args.vessel_validation.write_text(json.dumps(changed))
                    self.assertFalse(v.check_vessel_built(config, lock, args, require_approval=False), relative)
                    path.write_bytes(saved)
                changed = dict(report, checks=[r for r in report['checks']
                                              if r['check'] != 'checkpoint 000 ' + selector])
                args.vessel_validation.write_text(json.dumps(changed))
                self.assertFalse(v.check_vessel_built(config, lock, args, require_approval=False), selector)
            args.vessel_validation.write_text(original)
            self.assertTrue(v.check_vessel_built(config, lock, args))
            # The old cp-only command list cannot authorize any selector now.
            old = [cmd for cmd in commands if '--utility' not in cmd or cmd[cmd.index('--utility') + 1].endswith('-cp')]
            self.assertEqual(len(old), 7)
            args.vessel_validation.write_text(json.dumps(dict(report, commands=old, returncodes=[0] * len(old))))
            self.assertFalse(v.check_vessel_built(config, lock, args, require_approval=False))


    def test_invalid_preflight_selector_rejected_before_checks(self):
        with patch.object(v, 'check_git') as git, contextlib.redirect_stderr(io.StringIO()):
            for selector in ('cp', 'python-cp', 'c-ls', 'c-cp/../sort'):
                with self.assertRaises(SystemExit) as error:
                    v.main(['--selector', selector])
                self.assertEqual(error.exception.code, 2)
            git.assert_not_called()


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
            rebooted = dict(environment, emulation=dict(environment['emulation'], boot_id='boot-two'))
            with patch.object(v, 'vessel_environment', return_value=rebooted), patch.object(v, 'check_jailed_execution') as jail:
                self.assertTrue(v.check_vessel_built(config, lock, args))
                jail.assert_called_once_with()
            for emulation in ({'registrations': 'flags changed'},
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
            with patch.object(v, 'vessel_binding', side_effect=[binding, dict(binding, environment=rebooted)]):
                self.assertFalse(v.check_vessel_built(config, lock, args))


    def test_formal_scope_requires_new_finite_profile_approval(self):
        with patch.dict(os.environ, LINUX_BENCHMARK_PROFILE='vessel-8g', VESSEL_DIAGNOSTIC_ROSETTA='0'), \
                self.rebuilt_fixture() as (config, lock, args, images, report):
            args.approval_scope = 'formal-vessel-8g'
            self.assertFalse(v.check_vessel_built(config, lock, args))
            approval = json.loads(args.vessel_approval.read_text())
            approval['scope'] = args.approval_scope
            args.vessel_approval.write_text(json.dumps(approval))
            self.assertTrue(v.check_vessel_built(config, lock, args))
            with patch.dict(os.environ, LINUX_BENCHMARK_PROFILE='standard'):
                self.assertFalse(v.check_vessel_built(config, lock, args))
        for profile in ({'mode': 'standard', 'rlimit_as_bytes': 256 * 1024**2},
                        {'mode': 'vessel-rosetta-diagnostic', 'rlimit_as_bytes': None}):
            with self.assertRaisesRegex(ValueError, 'fixed vessel-8g'):
                v.approval_scope(SimpleNamespace(approval_scope='formal-vessel-8g'), {'execution_profile': profile})


    def test_emulator_probe_uses_selected_lock(self):
        import docker_benchmark as docker
        ref = 'example@sha256:' + 'b' * 64
        with patch.object(docker, 'settings', return_value={'compiler_image': ref}), \
                patch.object(v, 'probe_reference', return_value=json.dumps({'boot_id': 'one', 'registrations': {}})) as probe:
            v.emulation_identity()
            self.assertEqual(probe.call_args.args[0], ref)

    def test_new_commit_requires_new_capture_validation_and_approval(self):
        with self.rebuilt_fixture() as (config, lock, args, images, report):
            changed = copy.deepcopy(report['binding']['environment'])
            changed['revision'] = 'c' * 40  # Everything except HEAD stays identical.
            with patch.object(v, 'vessel_environment', return_value=changed):
                self.assertFalse(v.check_vessel_built(config, lock, args))
                # Even a fresh capture cannot make the old validation current.
                provenance = json.loads(args.vessel_provenance.read_text())
                provenance['environment'] = changed
                args.vessel_provenance.write_text(json.dumps(provenance))
                binding = v.vessel_binding(config, lock, args.vessel_provenance)
                with self.assertRaisesRegex(ValueError, 'stale or mismatched'):
                    v.checked_validation(args.vessel_validation, binding, config)
                # A newly successful report still needs a separate new approval.
                report['binding'] = binding
                args.vessel_validation.write_text(json.dumps(report))
                self.assertTrue(v.check_vessel_built(config, lock, args, require_approval=False))
                self.assertFalse(v.check_vessel_built(config, lock, args))

    def test_dirty_checkout_stops_before_environment_probes(self):
        with patch.object(v, 'required_run', return_value=' M scripts/vessel_preflight.py') as run:
            with self.assertRaisesRegex(ValueError, 'clean tracked checkout'):
                v.vessel_environment()
            run.assert_called_once_with(['git', 'status', '--porcelain', '--untracked-files=no'])


class ValidationDispatchTests(unittest.TestCase):
    def test_all_required_suites_resolve_without_executing_docker(self):
        import run_vessel_validation_tests as dispatch
        for name, tests in dispatch.SUITES.items():
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromNames(tests)
            self.assertFalse(loader.errors, name)
            self.assertGreater(suite.countTestCases(), 0, name)
        self.assertEqual(unittest.TestLoader().loadTestsFromNames(dispatch.SUITES['jailed']).countTestCases(), 2)

    def test_runner_rejects_missing_empty_skipped_expected_failure_and_failure(self):
        import run_vessel_validation_tests as dispatch
        class Probe(unittest.TestCase):
            def passed(self): pass
            def failed(self): self.fail('fixture failure')
            @unittest.skip('mandatory check unavailable')
            def skipped(self): pass
            @unittest.expectedFailure
            def expected_failure(self): self.fail('mandatory check failed')
        for method, expected in [('passed', 0), ('failed', 1), ('skipped', 1), ('expected_failure', 1)]:
            with patch.object(unittest.TestLoader, 'loadTestsFromNames',
                              return_value=unittest.TestSuite([Probe(method)])):
                self.assertEqual(dispatch.run_suites(['jailed'], stream=io.StringIO()), expected)
        with patch.object(unittest.TestLoader, 'loadTestsFromNames', return_value=unittest.TestSuite()):
            with self.assertRaisesRegex(ValueError, 'empty'):
                dispatch.run_suites(['jailed'])
        with patch.dict(dispatch.SUITES, missing=('scripts.validation.nonexistent',)):
            with self.assertRaisesRegex(ValueError, 'missing'):
                dispatch.run_suites(['missing'])
        with patch.dict(os.environ, PYTHONOPTIMIZE='1'):
            with self.assertRaisesRegex(ValueError, 'assertion checks'):
                dispatch.run_suites(['jailed'])

    def test_fresh_jail_dispatch_and_failures(self):
        for code in (0, 1, 124, 127):
            with patch.object(v, 'run', return_value=(code, '', 'fixture')) as run:
                if code:
                    with self.assertRaisesRegex(ValueError, 'infrastructure failure'):
                        v.check_jailed_execution()
                else:
                    v.check_jailed_execution()
                command = run.call_args.args[0]
                self.assertEqual(command[-3:], [str(ROOT / 'scripts/run_vessel_validation_tests.py'),
                                               '--suite', 'jailed'])
                self.assertEqual(run.call_args.kwargs['timeout'], 600)

    def test_static_wrapper_preserves_isolation_and_failure_status(self):
        import runpy
        import docker_benchmark as docker
        for failed in (False, True):
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / 'static'
                calls = []
                def invoke(command, **kwargs):
                    calls.append(command)
                    status = int(failed and '--suite' in command)
                    return SimpleNamespace(returncode=status, stdout='fixture', stderr='')
                with patch.object(subprocess, 'run', side_effect=invoke), \
                     patch.object(subprocess, 'check_output', return_value='sha256:' + 'a' * 64), \
                     patch.object(sys, 'argv', ['validate_linux_static.py', '--output', str(output)]):
                    with self.assertRaises(SystemExit) as error:
                        runpy.run_path(str(ROOT / 'scripts/validate_linux_static.py'), run_name='__main__')
                self.assertEqual(error.exception.code, int(failed))
                summary = json.loads((output / 'summary.json').read_text())
                self.assertEqual(set(summary), {'syntax', 'contract', 'static', 'isolation'})
                self.assertEqual(summary['static'], int(failed))
                checks = [cmd for cmd in calls if cmd[:2] == ['docker', 'run']]
                self.assertEqual(len(checks), 4)
                for command in checks:
                    for flag, expected in [('--platform', docker.settings()['platform']),
                                           ('--network', 'none'), ('--cap-drop', 'ALL'),
                                           ('--security-opt', 'no-new-privileges')]:
                        self.assertEqual(command[command.index(flag) + 1], expected)
                    self.assertIn('--read-only', command)
                    self.assertTrue(command[command.index('--mount') + 1].endswith('target=/work,readonly'))
                    self.assertNotIn('docker.sock', ' '.join(command))
                self.assertEqual(calls[-2][:3], ['docker', 'rm', '-fv'])
                self.assertEqual(calls[-1][:3], ['docker', 'volume', 'rm'])


