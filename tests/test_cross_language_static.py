"""Static contract parity, historical preservation and bundle isolation in Docker."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import lineage_plan
import stage_test_bundle
import check_heldout_isolation
import linux_utilities_catalog as catalog
import docker_benchmark


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
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name); checked+=1
        self.assertGreater(checked,50)

    @unittest.skipUnless(docker_benchmark.settings()['platform']=='linux/amd64',
                         'AMD64 naming audit; ARM64 needs its own oracle validation')
    def test_corpus_bytes_unchanged_by_rename(self):
        initial=json.loads((ROOT/'docs/benchmarks/cross-language-validation/initial-hashes.json').read_text())
        for utility in catalog.UTILITIES:
            for path in ('suites/linux-v1.json.gz','heldout/heldout_cases.json.gz'):
                old=f'tests/c-{utility}-test-suite/{path}'
                current=old.replace('linux-v1.json.gz','linux.json.gz')
                self.assertEqual(hashlib.sha256((ROOT/current).read_bytes()).hexdigest(),initial[old])

    @unittest.skipUnless(docker_benchmark.settings()['platform']=='linux/amd64',
                         'AMD64 naming audit; ARM64 needs its own oracle validation')
    def test_regenerated_oracle_bytes_match_canonical_corpora(self):
        from reference_generators import heldout_contract
        for utility in catalog.UTILITIES:
            for path in ('suites/linux.json.gz','heldout/heldout_cases.json.gz'):
                canonical=ROOT/f'tests/c-{utility}-test-suite'/path
                regenerated=ROOT/f'docs/benchmarks/cross-language-validation/rename-oracle/validated/c-{utility}'/path
                if path.startswith('suites/'):
                    self.assertEqual(canonical.read_bytes(),regenerated.read_bytes())
                else:
                    old=json.loads(gzip.decompress(canonical.read_bytes()))
                    new=json.loads(gzip.decompress(regenerated.read_bytes()))
                    self.assertEqual(old['corpus_fingerprint'],heldout_contract.fingerprint(old))
                    self.assertEqual(new['corpus_fingerprint'],heldout_contract.fingerprint(new))
                    # The sole allowed content change is the requested active
                    # provenance label, plus its correctly recomputed digest.
                    old['provenance']['benchmark']='linux-utilities'
                    old['corpus_fingerprint']=heldout_contract.fingerprint(old)
                    self.assertEqual(old,new)


if __name__=='__main__': unittest.main()
