"""One-time active namespace migration; recorded research evidence is immutable."""
import hashlib
import json
from pathlib import Path
import shutil
from lineage_plan import resolve_plan

ROOT=Path(__file__).resolve().parents[1]
audit=ROOT/'docs/benchmarks/cross-language-validation'
names=(audit/'initial-files.txt').read_text(encoding='utf-8-sig').splitlines()
names=[n for n in names if n.startswith(('scripts/','prompts/','experiments/utilities/','tests/','docker/','docs/benchmarks/')) and '/__pycache__/' not in n]
hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names if (ROOT/n).is_file()}
assert not (audit/'initial-hashes.json').exists(), 'migration already started'
(audit/'initial-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
(audit/'initial-c-fingerprints.json').write_text(json.dumps({s:resolve_plan(ROOT,s,'','0',None,0,0)['config_fingerprint'] for s in ('c-cp','c-mv','c-mkdir','c-sort')},indent=2)+'\n')
archive=audit/'before-rename'
archive.mkdir()
renames=[]
for relative in ('docker/linux-utilities-v1','prompts/linux-utilities-v1'):
    src=ROOT/relative; dst=ROOT/relative.replace('-v1','')
    assert src.resolve().is_relative_to(ROOT.resolve()) and not dst.exists()
    src.rename(dst); renames.append([relative,str(dst.relative_to(ROOT))])
for src in (ROOT/'docs/benchmarks').glob('linux-utilities-v1*'):
    shutil.copyfile(src,archive/src.name)
    dst=src.with_name(src.name.replace('linux-utilities-v1','linux-utilities'))
    src.rename(dst); renames.append([str(src.relative_to(ROOT)),str(dst.relative_to(ROOT))])
active=list((ROOT/'scripts').glob('*.py'))+list((ROOT/'scripts').glob('*.sh'))
active+=list((ROOT/'docker/linux-utilities').glob('*'))+list((ROOT/'prompts/linux-utilities').rglob('*.md'))
active+=list((ROOT/'docs/benchmarks').glob('linux-utilities*'))
active+=list((ROOT/'experiments/utilities').glob('c-*.json'))+list((ROOT/'tests').glob('test_*benchmark*.py'))
for utility in ('cp','mv','mkdir','sort'):
    suite=ROOT/f'tests/c-{utility}-test-suite'
    active+=list(suite.glob('*.py'))+list(suite.glob('*.sh'))+list(suite.glob('*.md'))+list((suite/'gen').glob('*.py'))
    src=suite/'suites/linux-v1.json.gz'; dst=src.with_name('linux.json.gz')
    src.rename(dst); renames.append([str(src.relative_to(ROOT)),str(dst.relative_to(ROOT))])
    path=suite/'suites/MANIFEST.json'
    shutil.copyfile(path,archive/f'c-{utility}-MANIFEST.json')
    # Preserve the protocol identifier and hash values; only the logical filename changes.
    path.write_bytes(path.read_bytes().replace(b'linux-v1.json.gz',b'linux.json.gz'))
    config=suite/'config.json'; data=json.loads(config.read_text())
    data.update(benchmark='linux-utilities',protocol_version=1)
    config.write_text(json.dumps(data,indent=2)+'\n')
for path in active:
    if path.name == 'prepare_linux_names.py' or not path.is_file(): continue
    raw=path.read_bytes()
    # Content-hash provenance inventory is an immutable mapping of historical inputs.
    if path.name.endswith('input-provenance.json'): continue
    new=raw.replace(b'linux-utilities-v1',b'linux-utilities').replace(b'Linux utilities v1',b'Linux utilities')
    new=new.replace(b'linux-v1.json.gz',b'linux.json.gz').replace(b'agentic-c-linux-v1',b'agentic-linux-utilities')
    if raw!=new: path.write_bytes(new)
(audit/'renames.json').write_text(json.dumps(renames,indent=2)+'\n')
print('Renamed active namespace; preserved initial hashes, fingerprints and original provenance')
