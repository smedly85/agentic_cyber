"""Read-only preservation audit and complete change inventory for this continuation."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'docs/benchmarks/cross-language-validation'
initial=json.loads((E/'initial-hashes.json').read_text())
renames=json.loads((E/'renames.json').read_text())
def renamed(name):
    for old,new in renames:
        if name==old or name.startswith(old+'/'): return new+name[len(old):]
    return name
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
protected=('prompts/cp/','prompts/mv/','prompts/python-', 'tests/cp-test-suite/','tests/mv-test-suite/',
           'tests/mkdir-test-suite/','tests/sort-test-suite/','tests/python-',
           'docs/benchmarks/validation-amd64/')
checked={name:digest(ROOT/name)==value for name,value in initial.items() if name.startswith(protected)
         or name in ('experiments/utilities/cp.json','experiments/utilities/mv.json')
         or name.startswith('experiments/utilities/python-')}
assert checked and all(checked.values()), 'protected historical or prior validation data changed'
lines=(E/'final-status-full.txt').read_text(encoding='utf-8-sig').splitlines()
current={line[3:].strip('"') for line in lines if len(line)>3}
tracked=[line[3:].strip('"') for line in lines if line.startswith(' M')]
allowed={'scripts/'+n for n in ('check_heldout_isolation.py','checkpoint_boundary_gate.py','heldout_judge.py',
         'lineage_plan.py','run_experiment.sh','run_lineage_experiment.sh','stage_test_bundle.py')}
assert set(tracked)<=allowed,tracked
assert not (E/'staged-files.txt').read_text(encoding='utf-8-sig').strip()
branch=(E/'branch.txt').read_text(encoding='utf-8-sig').strip()
assert branch=='cleanup/canonical-ordered-diversity'
def purpose(name):
    if '/cross-language-validation/' in name: return 'Validation, preservation or naming/fingerprint evidence'
    if name.startswith('prompts/'): return 'Checkpoint specification; canonical functional requirements'
    if name.startswith('experiments/'): return 'Language-specific manifest and Docker commands'
    if name.startswith('docker/'): return 'Pinned toolchain image/build or execution configuration'
    if name.startswith('docs/'): return 'Methodology, matrix, provenance or delivery report'
    if 'rust-' in name or '/py-' in name: return 'Thin descriptor for the shared canonical suite'
    if name.startswith('tests/test_'): return 'Static or Docker regression coverage'
    if name.startswith('tests/'): return 'Preserved canonical suite; active naming metadata'
    return 'Controller, Docker adapter or bounded validation/documentation tooling'
rows=[]; seen=set()
for name,oldhash in sorted(initial.items()):
    target=renamed(name); path=ROOT/target
    seen.add(target)
    if not path.is_file():
        rows.append((name,'Missing',purpose(name))); continue
    changed=digest(path)!=oldhash
    if target!=name or changed:
        rows.append((target,('Renamed from `'+name+'`'+('; modified' if changed else '')) if target!=name else 'Modified',purpose(target)))
for name in sorted(current-seen):
    if (ROOT/name).is_file(): rows.append((name,'Created',purpose(name)))
assert not any(state=='Missing' for _,state,_ in rows), 'unexpected missing initial file'
(E/'file-inventory.md').write_text('# Changes relative to the initial working tree\n\nUnchanged historical and prior-phase files are omitted; every created/modified/renamed file is listed.\n\n| Path | Change | Purpose |\n|---|---|---|\n'+'\n'.join(f'| `{n}` | {s} | {p} |' for n,s,p in sorted(rows))+'\n')
(E/'preservation.json').write_text(json.dumps({'protected_files_checked':len(checked),'protected_hashes_unchanged':all(checked.values()),
    'checks':checked,'tracked_changes':tracked,'staged_files':[],
    'branch':branch,'no_formal_lineages_started':True,
    'inventory_count':len(rows)},indent=2)+'\n')
print(f'Preserved {len(checked)} protected file hashes; inventoried {len(rows)} changed/created/renamed files')
