"""Host-safe checks: parse files and inspect data only; never execute candidates."""
import ast
import gzip
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import lineage_plan
import stage_test_bundle
import checkpoint_boundary_gate
import check_heldout_isolation
import linux_benchmark


class LinuxBenchmarkStaticTests(unittest.TestCase):
    def test_fifteen_plans_have_cumulative_filtered_bundles(self):
        total = 0
        for selector in linux_benchmark.SELECTORS:
            plan = lineage_plan.resolve_plan(ROOT, selector, '', '0', None, 0, 0)
            self.assertEqual(plan['required_platform'], 'Linux')
            self.assertTrue(plan['execution_environment']['formal_execution_enabled'])
            import docker_benchmark
            self.assertEqual(plan['execution_environment']['docker']['platform'], docker_benchmark.settings()['platform'])
            previous = set()
            for stage in plan['checkpoints']:
                total += 1
                flags = set(stage['implemented_flags'])
                self.assertLessEqual(previous, flags)
                previous = flags
                self.assertTrue((ROOT / stage['prompt']).is_file())
                payload = stage_test_bundle.build_payload(ROOT, plan['test_dir'], stage, selector)
                for name, data in payload['files'].items():
                    self.assertFalse(name.startswith(('heldout/', 'gen/', 'model/', 'corpus/')))
                    if name.startswith('suites/'):
                        for case in json.loads(data)['cases']:
                            self.assertLessEqual(set(case.get('flags', [])), flags)
                            self.assertFalse(case.get('linux_freeze_pending'))
                            self.assertTrue('exit_code' in case or case.get('allow_signals'))
                            if case.get('check', 'golden') == 'golden':
                                self.assertIn('stdout_b64', case)
            self.assertFalse((ROOT / plan['source_path']).exists())
        self.assertEqual(total, 15)

    def test_heldout_inputs_do_not_reach_bundles(self):
        for selector in linux_benchmark.SELECTORS:
            leaks, checkpoints, values = check_heldout_isolation.scan_utility(ROOT, selector)
            self.assertFalse(leaks)
            self.assertGreater(checkpoints, 0)
            self.assertGreater(values, 0)

    def test_new_mv_sequence_and_historical_rust_identity(self):
        new = linux_benchmark.read(ROOT / 'experiments/utilities/c-mv.json')
        self.assertEqual([s['implemented_flags'] for s in new['checkpoints']],
                         [[], ['-f'], ['-f', '-i']])
        for utility in ('cp', 'mv'):
            old = linux_benchmark.read(ROOT / 'experiments/utilities' / (utility + '.json'))
            self.assertTrue(old['source_path'].endswith('.rs'))

    def test_boundary_contracts_resolve_but_cannot_execute(self):
        with patch('checkpoint_boundary_gate.subprocess.run') as invoke:
            for selector in linux_benchmark.SELECTORS:
                manifest = checkpoint_boundary_gate.load_manifest(ROOT, selector)
                self.assertEqual(len(checkpoint_boundary_gate.availability(manifest)),
                                 len(manifest['checkpoints']))
                with self.assertRaises(checkpoint_boundary_gate.GateError):
                    checkpoint_boundary_gate.evaluate(ROOT, selector, '000', Path('absent'))
            invoke.assert_not_called()

    def test_functional_entrypoints_fail_closed_on_host(self):
        with patch('linux_benchmark.platform.system', return_value='Windows'), \
             patch('linux_benchmark.subprocess.check_output') as invoke:
            with self.assertRaises(RuntimeError):
                linux_benchmark.environment()
            with self.assertRaises(RuntimeError):
                linux_benchmark.main(['build', '--utility', 'c-cp'])
            invoke.assert_not_called()

    def test_python_syntax_without_importing_execution_engines(self):
        paths = [ROOT / 'scripts/linux_benchmark.py']
        for selector in linux_benchmark.SELECTORS:
            paths.extend((ROOT / 'tests' / (selector + '-test-suite')).rglob('*.py'))
        for path in paths:
            ast.parse(path.read_text(), filename=str(path))

    def test_shared_diagnostic_exception_does_not_hide_case_leaks(self):
        import linux_benchmark_isolation
        from reference_generators import heldout_contract
        root = ROOT / 'tests/c-sort-test-suite'
        private = heldout_contract.load(root)['cases']
        full = next(c for c in private if c.get('faults', {}).get('stdout') == '/dev/full')
        values = heldout_contract.scannable_values(full)
        retained = linux_benchmark_isolation.identifying_values('c-sort', full, values)
        self.assertIn(full['name'], retained)
        self.assertIn(full['stdin_b64'], retained)
        self.assertLess(len(retained), len(values))
        original = stage_test_bundle.build_payload
        def leak(*args, **kwargs):
            payload = original(*args, **kwargs)
            payload['files']['injected.txt'] = full['name'].encode()
            return payload
        with patch.object(stage_test_bundle, 'build_payload', side_effect=leak):
            leaks, _, _ = check_heldout_isolation.scan_utility(ROOT, 'c-sort')
            self.assertTrue(leaks)

    def test_noncanonical_controller_commands_are_refused(self):
        import docker_benchmark
        with self.assertRaises(docker_benchmark.InfrastructureError):
            docker_benchmark.main(['check-commands', '--utility', 'c-cp',
                                  '--build-command', 'gcc candidate.c # docker_benchmark.py',
                                  '--feature-command', 'echo judge_candidate.sh',
                                  '--extra-command', ''])


if __name__ == '__main__':
    unittest.main()
