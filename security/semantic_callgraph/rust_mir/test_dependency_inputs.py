"""Namespace/input regression tests; no compiler or points-to solver execution."""
import ast,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import dependency_inputs as inputs

class DependencyInputs(unittest.TestCase):
    def test_authenticated_source(self):
        self.assertEqual(inputs.scopeguard(),inputs.DEPENDENCIES/'scopeguard-1.2.0')

    def test_archive_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'scopeguard-1.2.0.crate').write_bytes(b'not the frozen archive')
            with patch.object(inputs,'DEPENDENCIES',root),self.assertRaises(ValueError):inputs.scopeguard()

    def test_source_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            shutil.copy2(inputs.DEPENDENCIES/'scopeguard-1.2.0.crate',root/'scopeguard-1.2.0.crate')
            shutil.copytree(inputs.scopeguard(),root/'scopeguard-1.2.0')
            (root/'scopeguard-1.2.0/src/lib.rs').write_text('// modified source\n')
            with patch.object(inputs,'DEPENDENCIES',root),self.assertRaises(ValueError):inputs.scopeguard()

    def test_controlled_case_identity_and_source_selection(self):
        here=Path(__file__).parent
        cases=[r['case'] for r in json.loads((here/'controlled_results.json').read_text())['cases']]
        frozen=json.loads((inputs.ROOT/'build/rust-mir/lightweight-v1/input_inventory.json').read_text())
        self.assertEqual(cases,[r['name'] for r in frozen if r['group']=='controlled'])
        self.assertEqual(len(set(cases)),31)
        for i,case in enumerate(cases):
            source=inputs.ROOT/'tests/fixtures/rust_semantic'/('instrument.rs' if i<13 else 'expanded.rs')
            self.assertTrue(source.is_file(),case)
        for name in ('controlled_probe.py','cargo_validation.py','continuation_validation.py','transitive_validation.py'):
            text=(here/name).read_text();ast.parse(text)
            self.assertIn('verified_scopeguard()',text)
            self.assertIn('build/rust-mir/dependencies',text)

if __name__=='__main__':unittest.main()
