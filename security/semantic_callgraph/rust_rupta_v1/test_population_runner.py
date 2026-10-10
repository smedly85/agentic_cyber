import tempfile
from pathlib import Path
import unittest
from security.semantic_callgraph.rust_rupta_v1.population_runner import resolve_source, sha, observe, compiler_method_matches

class PopulationMappingTests(unittest.TestCase):
    def test_compiler_definition_ignores_display_generic_spelling(self):
        m=dict(def_kind='Fn',def_id='DefId(61:30 ~ uu_test[afc8]::uumain::uumain)',name='uu_test::uumain::uumain<T>')
        self.assertTrue(compiler_method_matches(m,'uumain'))
        self.assertFalse(compiler_method_matches(dict(m,def_kind='Closure'),'uumain'))
    def resolve(self, text, function):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); p=root/'source.rs';p.write_text(text)
            return resolve_source(dict(source_file='source.rs',source_sha256=sha(p),function=function),root)

    def test_generic_owner_unique_definition(self):
        r=self.resolve('impl<T> Reader<T> {\n fn read(&self) {}\n}\n','Reader<T>::read')
        self.assertEqual(r['status'],'authenticated_unique_declaration')
        self.assertEqual(r['line'],2)

    def test_duplicate_definition_fails_closed(self):
        r=self.resolve('fn read() {}\nfn read() {}\n','read')
        self.assertEqual(r['status'],'ambiguous_source_declaration')

    def test_owner_mismatch_not_repaired_by_name(self):
        r=self.resolve('impl Other {\n fn read(&self) {}\n}\n','Reader::read')
        self.assertEqual(r['status'],'owner_confirmation_needed')

    def test_named_impl_disambiguates_without_graph_depth(self):
        r=self.resolve('impl From<u8> for Other {\n    fn from(x:u8) {}\n}\nimpl From<u8> for Options {\n    fn from(x:u8) {}\n}\n','Options::from')
        self.assertEqual(r['status'],'authenticated_unique_declaration')
        self.assertEqual(r['line'],5)

    def test_platform_does_not_borrow_linux_measurement(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'f.rs';p.write_text('fn target() {}')
            r=observe(dict(frozen_mapping=dict(source_file='f.rs',source_sha256=sha(p),function='target'),platform='windows'),
                      dict(build_status='completed',analysis_status='completed'),Path(d))
        self.assertIsNone(r['depth'])
        self.assertIsNone(r['maximum_depth'])
        self.assertEqual(r['analysis_status'],'not_run')
        self.assertEqual(r['measurement_validity'],'unsupported_platform')

if __name__=='__main__':unittest.main()
