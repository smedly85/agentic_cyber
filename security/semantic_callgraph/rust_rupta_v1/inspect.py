"""Read-only inventory and preservation snapshot; run from repository root."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tomllib

ROOT = Path.cwd()
OUT = ROOT / 'build/rupta-v1'
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, sort_keys=True)+'\n')

if sys.argv[1] == 'before':
    paths = subprocess.check_output(['git','ls-files','security','tests/fixtures'], text=True).splitlines()
    paths = [p for p in paths if not p.startswith('security/semantic_callgraph/rust_rupta_v1/')]
    write('protected_before.json', {p:sha(ROOT/p) for p in paths if (ROOT/p).is_file()})
    sources = {}
    for release in ('0.0.3','0.2.2'):
        base=ROOT/'build/historical-rust-measurement/method-v1'/release
        provenance=json.loads((base/'source_provenance.json').read_text())
        checkout=ROOT/provenance['checkout']
        manifests=[]
        for p in sorted(checkout.rglob('Cargo.toml')):
            if 'target' in p.parts or '.git' in p.parts: continue
            data=tomllib.loads(p.read_text())
            package=data.get('package',{})
            manifests.append({'path':str(p.relative_to(checkout)), 'sha256':sha(p),
                              'name':package.get('name'),'edition':package.get('edition'),
                              'rust_version':package.get('rust-version'),
                              'workspace_package':data.get('workspace',{}).get('package')})
        lock=checkout/'Cargo.lock'
        sources[release]={'provenance':provenance, 'manifest_inventory':manifests,
                          'lock_sha256':sha(lock),'lock_version':tomllib.loads(lock.read_text()).get('version'),
                          'lock_matches_frozen':sha(lock)==provenance['cargo_lock_sha256']}
    write('historical_inspection.json',sources)
else:
    before=json.loads((OUT/'protected_before.json').read_text())
    changes=[p for p,h in before.items() if not (ROOT/p).is_file() or sha(ROOT/p)!=h]
    write('protected_after.json',{'files_checked':len(before),'changed_or_missing':changes,'passed':not changes})
    print('Protected artifacts:',len(before),'changed:',changes)
