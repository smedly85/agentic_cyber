"""Required infrastructure controls recovered from pre-cleanup commit 5c128adb.

These are validation probes, not experimental implementations or lineage seeds.
"""
import ast
import gzip
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
import lineage_plan
import stage_test_bundle
import checkpoint_boundary_gate
import check_heldout_isolation
import linux_benchmark
import linux_utilities_catalog as catalog
import docker_benchmark

class LinuxBenchmarkStaticTests(unittest.TestCase):
    def test_canonical_corpora_match_retained_manifests(self):
        # The cleanup removed duplicate archived oracle corpora. Validate the
        # canonical artifacts against their retained manifests instead of making
        # those obsolete copies live dependencies again.
        from reference_generators import heldout_contract
        for selector in catalog.SELECTORS:
            suite = catalog.suite_root(ROOT, selector)
            manifest = json.loads((suite / 'suites/MANIFEST.json').read_text())
            self.assertEqual(set(manifest['sha256']),
                             {'suites/linux.json.gz', 'heldout/heldout_cases.json.gz'})
            for name, expected in manifest['sha256'].items():
                self.assertEqual(hashlib.sha256((suite / name).read_bytes()).hexdigest(),
                                 expected, (selector, name))
            private = json.loads(gzip.decompress((suite / 'heldout/heldout_cases.json.gz').read_bytes()))
            self.assertEqual(private['corpus_fingerprint'], heldout_contract.fingerprint(private))

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


HISTORICAL_TEXT_EOL = {
    'tests/mkdir-test-suite/README.md': (
        '689e54bac790bf40a39b4b38cf0a97f2a77a4a3e0df6945d3b93a714c41d9d54',
        '68b777a4ee3dab9bc0a565b73ea8eac1b935df13e2073a32ae88aa7db57ddd37'),
    'tests/mkdir-test-suite/engine.py': (
        '2346b6e83ce0073ec2dff0f6a84d87a55680eaccb182f817f5c50783e6ec6467',
        '97d52d862b11ff50a72b826d0abf4e091eb0d17ffaf67e310a862a7e6bf92fc7'),
    'tests/mkdir-test-suite/gen/heldout.py': (
        '278af1861f922c01f0b4807cd9b643353ff3ed0183d49a66e220de3d7525d098',
        '910aab23b44228c2e5b2c48235e20abc2eae2608e99d1e87bc36670ecfb7cb0b'),
    'tests/python-sort-test-suite/suites/MANIFEST.json': (
        'b75ab8bdeda6c9c2920eee8ef781d76b53f0115ff813702f332346062203a864',
        '5ea0310019c7aa13defc8d9dd156355efd9362681bda21164e28876dc45a5828'),
    'tests/sort-test-suite/engine.py': (
        '9a978e1a2495ab63c7ebe5dbe3fe8f2992b82cd812462d2260a7236637d3b88b',
        '4370e7aac7f9043eef281a8a44fed36be65573d371dd4ba701ce6ccac70a5ac0'),
    'tests/sort-test-suite/gen/heldout.py': (
        '29a32e4d4c7617693099b9702634fbe2982b6a2cd6f0dc1c5425ad2ee1cf2246',
        '0c46ce833845036099dab6d06f5a52303468a52028c07ef053b13ce27a1bfe3f'),
    'tests/sort-test-suite/suites/MANIFEST.json': (
        'd5a0098b0283490c1a0f1130b16cdf69b7bb93001e3c1a13f8d03ef0ff034df0',
        '9b3119927b64ddec19ebdb26ddbbc93e60e5ea316e661d68e2f936431f5b787f'),
}


def historical_bytes_match(name, data, expected):
    if name in HISTORICAL_TEXT_EOL:
        captured, lf_digest = HISTORICAL_TEXT_EOL[name]
        return (expected == captured and
                hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest() == lf_digest)
    return hashlib.sha256(data).hexdigest() == expected


class CrossLanguageStatic(unittest.TestCase):
    def test_all_forty_five_checkpoints_and_shared_scenarios(self):
        total=0; expected={}; plans={}
        for selector in catalog.SELECTORS:
            manifest=json.loads((ROOT/f'experiments/utilities/{selector}.json').read_text())
            plan=lineage_plan.resolve_plan(ROOT,selector,'','0',None,0,0)
            plans[selector]=plan['config_fingerprint']
            self.assertEqual(plan['config_fingerprint'],lineage_plan.fingerprint(plan))
            self.assertFalse((ROOT/manifest['source_path']).exists())
            self.assertEqual(plan['required_platform'],'Linux')
            cumulative=set()
            for checkpoint in plan['checkpoints']:
                total+=1
                self.assertLessEqual(cumulative,set(checkpoint['implemented_flags']))
                cumulative=set(checkpoint['implemented_flags'])
                prompt=(ROOT/checkpoint['prompt']).read_text()
                self.assertIn('Do not compile or execute natively on the host.',prompt)
                body=prompt.split('\n\n',4)[4].split('## Implementation and validation')[0]
                bundle=stage_test_bundle.build_payload(ROOT,plan['test_dir'],checkpoint,selector)
                public={n:hashlib.sha256(b).hexdigest() for n,b in bundle['files'].items() if n.startswith('suites/')}
                key=(catalog.utility_name(selector),checkpoint['id'])
                if key in expected: self.assertEqual(expected[key],(body,public))
                else: expected[key]=(body,public)
                for path in bundle['files']:
                    self.assertFalse(path.startswith(('gen/','heldout/','model/')))
            leaks,_,_=check_heldout_isolation.scan_utility(ROOT,selector)
            self.assertFalse(leaks,selector)
        self.assertEqual(total,45)
        self.assertEqual(len(set(plans.values())),12)


    def test_historical_language_experiments_preserved(self):
        initial=json.loads((ROOT/'docs/benchmarks/cross-language-validation/initial-hashes.json').read_text())
        prefixes=('prompts/cp/','prompts/mv/','prompts/python-','tests/cp-test-suite/',
                  'tests/mv-test-suite/','tests/mkdir-test-suite/','tests/sort-test-suite/','tests/python-')
        checked=0
        for name,digest in initial.items():
            if name.startswith(prefixes) or name in ('experiments/utilities/cp.json','experiments/utilities/mv.json') or name.startswith('experiments/utilities/python-'):
                self.assertTrue(historical_bytes_match(name, (ROOT/name).read_bytes(), digest), name); checked+=1
        self.assertGreater(checked,50)


    def test_historical_eol_allowance_rejects_content_and_reference_changes(self):
        initial=json.loads((ROOT/'docs/benchmarks/cross-language-validation/initial-hashes.json').read_text())
        for name in HISTORICAL_TEXT_EOL:
            data=(ROOT/name).read_bytes().replace(b'\r\n', b'\n')
            with self.subTest(name=name):
                for variant in (data, data.replace(b'\n', b'\r\n'), data.replace(b'\n', b'\r\n', 1)):
                    self.assertTrue(historical_bytes_match(name, variant, initial[name]))
                for changed in (data + b' ', data + b'\n', b'X' + data[1:], data.replace(b'\n', b'\r', 1)):
                    self.assertFalse(historical_bytes_match(name, changed, initial[name]))
                self.assertFalse(historical_bytes_match(name, data, '0' * 64))


    def test_unlisted_text_and_binary_still_require_exact_bytes(self):
        data=b'unchanged\r\nbytes\x00\xff'
        digest=hashlib.sha256(data).hexdigest()
        for name in ('tests/cp-test-suite/engine.py', 'tests/c-cp-test-suite/suites/linux.json.gz'):
            self.assertTrue(historical_bytes_match(name, data, digest))
            self.assertFalse(historical_bytes_match(name, data.replace(b'\r\n', b'\n'), digest))


    @unittest.skipUnless(docker_benchmark.settings()['platform']=='linux/amd64',
                         'AMD64 naming audit; ARM64 needs its own oracle validation')
    def test_corpus_bytes_unchanged_by_rename(self):
        initial=json.loads((ROOT/'docs/benchmarks/cross-language-validation/initial-hashes.json').read_text())
        for utility in catalog.UTILITIES:
            for path in ('suites/linux-v1.json.gz','heldout/heldout_cases.json.gz'):
                old=f'tests/c-{utility}-test-suite/{path}'
                current=old.replace('linux-v1.json.gz','linux.json.gz')
                self.assertEqual(hashlib.sha256((ROOT/current).read_bytes()).hexdigest(),initial[old])



