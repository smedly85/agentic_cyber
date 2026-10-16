"""SORT integration/regression tests; no models, candidates or lineage runs.

Set SORT_ORACLE_BIN to GNU 9.11 to enable live oracle comparisons. On Linux these
are diagnostic comparisons only: no Darwin goldens are generated or published.
"""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
SUITE = REPO/'tests/python-sort-test-suite'
sys.path[:0] = [str(REPO/'scripts'), str(REPO/'tests')]
import check_heldout_isolation
import checkpoint_boundary_gate
import lineage_plan
import prompt_render
import stage_test_bundle
from reference_generators import heldout_contract, python_sort_oracle
from reference_generators.python_sort_cases import public_cases
from reference_generators.python_sort_heldout import heldout_cases
from reference_generators.transfer_oracle import load_engine, oracle


class PythonSortInfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = load_engine(SUITE)
        spec = importlib.util.spec_from_file_location('python_sort_runner', SUITE/'runner.py')
        cls.runner = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, engine=cls.engine, props=types.SimpleNamespace(CHECKS={})):
            spec.loader.exec_module(cls.runner)
        cls.binary = None
        if os.environ.get('SORT_ORACLE_BIN'):
            # A supplied wrong version is an error, never a silent test skip.
            cls.binary, _ = oracle('sort')

    def require_oracle(self):
        if not self.binary or os.name != 'posix':
            self.skipTest('set SORT_ORACLE_BIN to executable GNU 9.11 on POSIX')

    def test_discovery_contains_real_test_cases(self):
        self.assertTrue((REPO/'tests/test_python_infrastructure.py').is_file())
        self.assertGreaterEqual(unittest.defaultTestLoader.loadTestsFromTestCase(type(self)).countTestCases(), 14)

    def test_public_and_private_c_value_are_scope_assertions(self):
        for cases, name in [(public_cases(), 'c-value'), (heldout_cases(), 'heldout-c-value')]:
            selected = next(c for c in cases if c['name'] == name)
            self.assertTrue(selected['scope_error'])
            self.assertEqual(selected['flags'], ['-c'])
            self.assertTrue(selected['args'][0].startswith('--check='))
            self.assertEqual(len(cases), 75)
            self.assertEqual(sum(bool(c.get('scope_error')) for c in cases), 5)

    def test_bounded_invalid_value_freezes_exact_status_two(self):
        engine = Mock()
        for cases in (public_cases(), heldout_cases()):
            selected = next(c for c in cases if c['name'].endswith('c-value'))
            result = python_sort_oracle.freeze_case(selected, engine, '/not-called')
            self.assertEqual(result['exit_code'], 2)
            self.assertEqual(result['stdout_b64'], '')
            self.assertEqual(result['stderr_class'], 'nonempty')
            self.assertEqual(result['expected_tree'], {})
        engine.execute.assert_not_called()

    def test_gnu_statuses_are_not_reclassified(self):
        case = next(c for c in public_cases() if c['name'] == 'check-late-disorder')
        for status in (0, 1, 2):
            engine = Mock()
            engine.execute.return_value = self.engine.Result(status, b'', b'diagnostic' if status else b'')
            result = python_sort_oracle.freeze_case(case, engine, '/oracle')
            self.assertEqual(result['exit_code'], status)

    def test_runner_rejects_one_when_contract_requires_two(self):
        case = next(c for c in public_cases() if c['name'] == 'c-value')
        frozen = python_sort_oracle.freeze_case(case, None, None)
        for status, verdict in [(1, 'FAIL'), (2, 'PASS')]:
            with patch.object(self.engine, 'execute', return_value=self.engine.Result(status, b'', b'invalid argument')):
                observed, detail = self.runner.run_one(frozen, ['/unused'], False, False)
            self.assertEqual(observed, verdict)
            if status == 1:
                self.assertIn('exit: got 1, want 2', detail)

    def test_runner_still_checks_stdout_and_stderr(self):
        case = python_sort_oracle.freeze_case(next(c for c in public_cases() if c['name'] == 'c-value'), None, None)
        for out, err in [(b'unwanted output', b'diagnostic'), (b'', b'')]:
            with patch.object(self.engine, 'execute', return_value=self.engine.Result(2, out, err)):
                verdict, _ = self.runner.run_one(case, ['/unused'], False, False)
            self.assertEqual(verdict, 'FAIL')

    def test_direct_gnu_invalid_check_value_is_not_disorder(self):
        self.require_oracle()
        # XARGMATCH exits 1 before examining input, even on ordered/empty input.
        for data in (b'', b'a\nb\n', b'b\na\n'):
            result = subprocess.run([self.binary, '--check=invalid'], input=data,
                                    capture_output=True, env=dict(os.environ, LC_ALL='C'))
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b'')
            self.assertIn(b'invalid argument', result.stderr)
            self.assertNotIn(b'disorder:', result.stderr)
        print('Direct GNU 9.11 --check=invalid: status 1, invalid-argument diagnostic (3 inputs)')

    def test_generated_adapter_rejects_values_and_preserves_check_statuses(self):
        self.require_oracle()
        with tempfile.TemporaryDirectory() as temp:
            adapter = python_sort_oracle.write_oracle_adapter(temp, self.binary)
            for args, data, expected in [(['--check=invalid'], b'b\na\n', 2),
                                         (['--check'], b'a\nb\n', 0),
                                         (['--check'], b'b\na\n', 1),
                                         (['--check','--invalid-option'], b'a\nb\n', 2)]:
                result = subprocess.run([str(adapter), *args], input=data, capture_output=True,
                                        env=dict(os.environ, LC_ALL='C'))
                self.assertEqual(result.returncode, expected)
                self.assertEqual(result.stdout, b'')
                self.assertEqual(bool(result.stderr), expected != 0)

    def test_live_oracle_adapter_matches_all_scenarios_without_publishing_goldens(self):
        self.require_oracle()
        with tempfile.TemporaryDirectory() as temp:
            adapter = python_sort_oracle.write_oracle_adapter(temp, self.binary)
            for label, cases in [('public', public_cases()), ('heldout', heldout_cases())]:
                passed = 0
                for case in cases:
                    with self.subTest(case=case['name']):
                        expected = python_sort_oracle.freeze_case(case, self.engine, self.binary)
                        verdict, detail = self.runner.run_one(expected, [str(adapter)], False, False)
                        self.assertEqual(verdict, 'PASS', detail)
                        passed += 1
                print(f'Host-local oracle/adapter diagnostic: {label} {passed}/{len(cases)}; no corpus written')

    def test_pending_recipes_are_deterministic_and_remain_unknown(self):
        first = python_sort_oracle.artifacts(SUITE)
        self.assertEqual(first, python_sort_oracle.artifacts(SUITE))
        cases = json.loads(gzip.decompress(first['suites/cases.json.gz']))['cases']
        self.assertTrue(all(c['oracle_pending'] and c['exit_code'] is None for c in cases))

    def test_committed_corpus_hashes_counts_and_scope_are_synchronized(self):
        manifest = json.loads((SUITE/'suites/MANIFEST.json').read_text())
        for name, digest in manifest['sha256'].items():
            self.assertEqual(hashlib.sha256((SUITE/name).read_bytes()).hexdigest(), digest)
            cases = json.loads(gzip.decompress((SUITE/name).read_bytes()))['cases']
            self.assertEqual(len(cases), 75)
            c_value = next(c for c in cases if c['name'].endswith('c-value'))
            self.assertTrue(c_value['scope_error'])
            if manifest['status'] == 'validated':
                self.assertEqual(c_value['exit_code'], 2)
                self.assertNotIn('oracle_pending', c_value)
            else:
                self.assertIsNone(c_value['exit_code'])

    def test_darwin_generation_guard_is_preserved(self):
        with patch.object(python_sort_oracle.platform, 'system', return_value='Linux'):
            with self.assertRaisesRegex(ValueError, 'Darwin'):
                python_sort_oracle.artifacts(SUITE, '/must-not-run', 'sort (GNU coreutils) 9.11')

    def test_five_checkpoints_render_and_filter_c_value(self):
        plan = lineage_plan.resolve_plan(REPO, 'python-sort', 'test-model', '0', None, 1, 30)
        self.assertEqual([c['source_mode'] for c in plan['checkpoints']], ['new']+['existing']*4)
        for checkpoint, count in zip(plan['checkpoints'], [17,22,31,46,75]):
            rendered = prompt_render.render_file(REPO, REPO/checkpoint['prompt'])
            self.assertIn('`sort_lines`', rendered)
            self.assertIn('Invalid arguments require status 2', rendered)
            payload = stage_test_bundle.build_payload(REPO, plan['test_dir'], checkpoint, 'python-sort')
            self.assertEqual(payload['manifest']['cases_included'], count)
            cases = json.loads(payload['files']['suites/cases.json.gz'])['cases']
            self.assertEqual(any(c['name'] == 'c-value' for c in cases), checkpoint['id'] == '004')

    def test_heldout_isolation(self):
        leaks, checkpoints, _ = check_heldout_isolation.scan_utility(REPO, 'python-sort')
        self.assertEqual(leaks, [])
        self.assertEqual(checkpoints, 5)
        private = heldout_contract.load(SUITE)
        self.assertEqual(private['total_cases'], 75)

    def test_future_check_requires_argument_rejection_status(self):
        self.assertEqual(checkpoint_boundary_gate.PROBES['python-sort']['required_exit_status'], 2)
        self.assertNotIn('required_exit_status', checkpoint_boundary_gate.PROBES['sort'])


if __name__ == '__main__':
    unittest.main()
