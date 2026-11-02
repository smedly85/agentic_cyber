"""Record inventory/preservation from native Git snapshots, without Git writes."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'docs/benchmarks/validation-amd64'
tracked=['scripts/'+s for s in ('check_heldout_isolation.py','checkpoint_boundary_gate.py',
         'heldout_judge.py','lineage_plan.py','run_experiment.sh','run_lineage_experiment.sh','stage_test_bundle.py')]
# Preserve original line endings on unchanged lines, LF on edits. Do not restore
# HEAD contents over the user's initial changes: all current logical lines survive.
for name in tracked:
    old=subprocess.check_output(['git','show','HEAD:'+name]).splitlines(keepends=True)
    current=(ROOT/name).read_bytes().splitlines(keepends=True)
    a=[s.rstrip(b'\r\n') for s in old]; b=[s.rstrip(b'\r\n') for s in current]
    out=[]
    for tag,i,j,k,l in difflib.SequenceMatcher(None,a,b,autojunk=False).get_opcodes():
        out.extend(old[i:j] if tag=='equal' else [line+b'\n' for line in b[k:l]])
    (ROOT/name).write_bytes(b''.join(out))
provenance=json.loads((ROOT/'docs/benchmarks/linux-utilities-input-provenance.json').read_text())
checked={}
for group in provenance.values():
    for name,digest in group.items():
        checked[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
assert all(checked.values()), 'Historical source provenance changed'
initial=json.loads((E/'initial-file-sha256.json').read_text(encoding='utf-8-sig'))
status=(E/'final-status-full.txt').read_text(encoding='utf-8-sig').splitlines()
names={line[3:].strip('"') for line in status if len(line)>3}
names |= set(initial)
def purpose(name):
    if '/validation-amd64/' in name: return 'Infrastructure evidence, audit snapshot or archived prior documentation'
    if '/frozen-revisions/' in name or '/pending-' in name or 'inputs-before' in name: return 'Preserved previous new-namespace artifact'
    if name.startswith('scripts/docker_benchmark'): return 'Mandatory isolated Docker compiler/judge/case transport'
    if name in tracked: return 'Namespaced C integration; historical selector paths preserved'
    if name.startswith('scripts/'): return 'Oracle, isolation, publication or bounded validation support'
    if name.startswith('docker/'): return 'Pinned Docker build/execution configuration and architecture lock'
    if name.startswith('experiments/'): return 'Namespaced C checkpoint manifest'
    if name.startswith('prompts/'): return 'Natural-language C checkpoint specification'
    if '/gen/' in name: return 'Controller-only input definitions/generation entry point'
    if '/heldout/' in name: return 'Controller-only independent frozen held-out corpus'
    if '/suites/' in name or name.endswith('/validation.json'): return 'Linux frozen public corpus, hashes or oracle evidence'
    if name.startswith('tests/'): return 'C suite runtime/configuration or bounded regression test'
    return 'Benchmark methodology, report, contract or provenance'
rows=[]
for name in sorted(names):
    path=ROOT/name
    if not path.is_file(): state='Removed (archived)' if name.endswith('suites/pending.json.gz') else 'Absent'
    elif name not in initial: state='Created' if name not in tracked else 'Modified'
    elif hashlib.sha256(path.read_bytes()).hexdigest()==initial[name]: state='Unchanged initial work'
    else: state='Modified'
    rows.append(f'| `{name}` | {state} | {purpose(name)} |')
(E/'file-inventory.md').write_text('# File inventory relative to initial working tree\n\nIncludes unchanged prior-phase deliverables so the complete new benchmark remains reviewable.\n\n| Path | This continuation | Purpose |\n|---|---|---|\n'+'\n'.join(rows)+'\n')
(E/'preservation.json').write_text(json.dumps({'historical_input_hashes':checked,
    'all_historical_inputs_unchanged':all(checked.values()),
    'tracked_changes_allowlist':tracked,
    'note':'Native Git status and cached diff separately verify tracked changes and an unstaged-only working tree.'},indent=2)+'\n')
print(f'Historical hashes verified: {len(checked)}; inventory paths: {len(rows)}')
