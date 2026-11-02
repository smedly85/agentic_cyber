"""Publish verified Linux results into only the new C namespace.

Input-only placeholders are archived under gen/ first. Existing frozen results
are never overwritten; an identical re-publication is a no-op.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def publish(source, revise=False, platform='linux/amd64'):
    for selector in ('c-cp', 'c-mv', 'c-mkdir', 'c-sort'):
        incoming = source / selector
        validation = json.loads((incoming / 'validation.json').read_text())
        assert validation['deterministic_freeze'] and validation['frozen_bundle_isolation']
        assert validation['environment']['architecture'] == ('x86_64' if platform == 'linux/amd64' else 'aarch64')
        for row in validation['checkpoints']:
            for kind in ('public', 'heldout'):
                assert row[kind].get('PASS', 0) > 0
                assert not any(row[kind].get(k, 0) for k in ('FAIL','TIMEOUT','CRASH','XFAIL','SANITIZER'))
                assert row[kind + '_mutation_detected']
        manifest = json.loads((incoming / 'suites/MANIFEST.json').read_text())
        for name, digest in manifest['sha256'].items():
            assert hashlib.sha256((incoming / name).read_bytes()).hexdigest() == digest
    for selector in ('c-cp', 'c-mv', 'c-mkdir', 'c-sort'):
        incoming = source / selector
        suite = ROOT / 'tests' / (selector + '-test-suite')
        for name, backup in [('suites/pending.json.gz', 'gen/pending-public-original.json.gz'),
                             ('heldout/heldout_cases.json.gz', 'gen/pending-heldout-original.json.gz')]:
            path = suite / name
            if path.exists():
                cases = json.loads(gzip.decompress(path.read_bytes()))['cases']
                if all(c.get('linux_freeze_pending') for c in cases):
                    target = suite / backup
                    if target.exists() and target.read_bytes() != path.read_bytes():
                        raise ValueError('refusing to overwrite archived inputs')
                    if not target.exists():
                        shutil.copyfile(path, target)
                    path.unlink()
        for name in ('suites/linux.json.gz', 'suites/MANIFEST.json', 'heldout/heldout_cases.json.gz', 'validation.json'):
            target = suite / name
            data = (incoming / name).read_bytes()
            if target.exists() and target.read_bytes() != data:
                if not revise:
                    raise ValueError('refusing to overwrite existing frozen artifact: ' + str(target))
                archive = suite / 'gen/frozen-revisions' / hashlib.sha256(target.read_bytes()).hexdigest() / name
                archive.parent.mkdir(parents=True, exist_ok=True)
                if not archive.exists():
                    shutil.copyfile(target, archive)
                target.write_bytes(data)
            if not target.exists():
                target.write_bytes(data)
        print(selector + ': published independently verified ' + platform + ' corpus')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--revise-new-namespace', action='store_true')
    parser.add_argument('--platform', choices=('linux/amd64','linux/arm64'), default='linux/amd64')
    args = parser.parse_args()
    publish(args.source, args.revise_new_namespace, args.platform)
