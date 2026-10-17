"""Bounded longitudinal analysis; run in the recorded WSL compiler environment.

python3 docs/checkpoint_diversity_trajectories.py [--measure-only | --summarize-only]
Reinvocation resumes saved observations; completed failures are never retried.
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter
from fractions import Fraction
from importlib.metadata import version
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import ordered_diversity_threshold_study as study
from scripts.analysis.ordered_thresholds import analyze_population
from final_checkpoint_diversity_sample import verify_hash

STATE = ROOT / 'docs/checkpoint_diversity_measurements.json'
BUILD = ROOT / 'build/checkpoint-diversity-trajectories'
SPECS = {'mkdir': [7, 7, 7], 'grep': [10]*5, 'chmod': [7, 6, 6, 6, 6], 'sort': [8, 8, 8, 7, 7]}
TOTAL_SECONDS = 3600
POPULATION_SECONDS = 900
HISTORY_PATHS = ['docs/ordered_diversity_threshold_pairwise.json',
                 'docs/final_checkpoint_diversity_new_pairwise.json',
                 'docs/final_checkpoint_diversity_sample.json']


def read(path):
    return json.loads(path.read_bytes())


def committed(path):
    relative = str(path.relative_to(ROOT))
    blob = subprocess.check_output(['git', 'show', 'HEAD:' + relative], cwd=ROOT)
    assert blob.replace(b'\r\n', b'\n') == path.read_bytes().replace(b'\r\n', b'\n'), relative
    return study.sha(blob)


def provenance():
    manifest_path = ROOT / 'security/generated_candidate_population.json'
    manifest = read(manifest_path)
    evidence = [read(ROOT / p) for p in HISTORY_PATHS]
    old, new, sample = evidence
    checked = {'manifest_committed_blob_sha256': committed(manifest_path), 'historical_evidence': {},
               'source_verification': {}, 'feature_records': {}}
    clang = shutil.which('clang')
    assert clang and study.sha(Path(clang).resolve().read_bytes()) == old['compiler_binary_sha256']
    current_algorithms = {}
    for path, data in zip(HISTORY_PATHS[:2], evidence[:2]):
        assert data['completed'] and data['profile'] == study.PROFILE
        assert data['profile_verification_error'] is None
        assert data['compiler_binary_sha256'] == old['compiler_binary_sha256']
        assert data['comparison_limits'] == vars(study.ExactLimits())
        assert data['packages'] == {name: version(name) for name in ('numpy', 'scipy')}
        assert data['scope'] == old['scope']
        assert data['scope'] == {'exclude_regex': study.DEFAULT_EXCLUDE, 'forced_includes': [], 'main_always_included': True}
        checked['historical_evidence'][path] = {
            'sha256': study.sha((ROOT / path).read_bytes()),
            'manifest': verify_hash(manifest_path, data['manifest_sha256']),
            'phase27': verify_hash(ROOT / 'docs/ordered_diversity_phase27_feasibility.json', data['phase27_evidence_sha256']),
            'algorithms': {p: verify_hash(ROOT / p, h) for p, h in data['algorithm_sha256'].items()}}
        current_algorithms.update({p: study.sha((ROOT / p).read_bytes()) for p in data['algorithm_sha256']})
    assert sample['profile'] == study.PROFILE
    for key, path in [('reuse_evidence', HISTORY_PATHS[0]), ('new_evidence', HISTORY_PATHS[1])]:
        verify_hash(ROOT / path, sample[key]['sha256'])
    verify_hash(ROOT / 'docs/final_checkpoint_diversity_sample.py', sample['runner_sha256'])
    checked['historical_evidence'][HISTORY_PATHS[2]] = {'sha256': study.sha((ROOT / HISTORY_PATHS[2]).read_bytes())}
    members = {c['candidate_id']: c for c in manifest['candidates']}
    assert len(members) == len(manifest['candidates']) == 140
    populations = []
    for utility, counts in SPECS.items():
        run = next(r for r in manifest['formal_runs'] if r['utility'] == utility)
        lineage_path = ROOT / run['lineage_root'] / 'lineages.json'
        committed(lineage_path)
        lineage = read(lineage_path)
        assert lineage['repository_commit'] == run['generation_repository_commit']
        checked['feature_records'][utility] = {'path': str(lineage_path.relative_to(ROOT)), 'sha256': study.sha(lineage_path.read_bytes())}
        for t, count in enumerate(counts):
            checkpoint = f'{t:03}'
            selected = sorted([c for c in members.values() if c['utility'] == utility and c['checkpoint_id'] == checkpoint], key=lambda c: c['candidate_id'])
            assert len(selected) == count and len({c['lineage_id'] for c in selected}) == count
            assert all(c['formal_run_id'] == run['formal_run_id'] and c['functional_population_status'] == 'public_checkpoint_stage_success' for c in selected)
            feature = next(c for c in lineage['checkpoints'] if c['id'] == checkpoint)
            assert all(c['checkpoint_name'] == feature['name'] for c in selected)
            populations.append({'utility': utility, 'checkpoint': checkpoint, 'formal_run_id': run['formal_run_id'],
                                'feature_requirements': feature, 'candidate_ids': [c['candidate_id'] for c in selected]})
    for member in members.values():
        source = ROOT / member['candidate_source']
        assert member['candidate_id'] == '/'.join([member['formal_run_id'], member['lineage_id'], member['checkpoint_id']])
        checked['source_verification'][member['candidate_id']] = {
            **verify_hash(source, member['candidate_source_sha256']), 'committed_blob_sha256': committed(source)}
    header_hashes = {}
    final_groups = old['populations'] + new['populations']
    for group in final_groups:
        corresponding = next(g for g in populations if (g['utility'], g['checkpoint']) == (group['utility'], group['checkpoint']))
        assert set(corresponding['candidate_ids']) == {c['candidate_id'] for c in group['candidates']}
        assert group['formal_run_id'] == corresponding['formal_run_id']
        saved = next(g for g in sample['populations'] if g['utility'] == group['utility'])
        assert saved['pairs'] == group['pairs']
        assert len(group['pairs']) == len(list(itertools.combinations(group['candidates'], 2)))
        assert {tuple(sorted((p['left'], p['right']))) for p in group['pairs']} == set(itertools.combinations(corresponding['candidate_ids'], 2))
        for row in group['candidates']:
            member = members[row['candidate_id']]
            assert all(row[k] == v for k, v in member.items())
            assert row['source_unchanged']
            verify_hash(ROOT / row['candidate_source'], row['source_sha256'])
            verify_hash(ROOT / row['experiment']['path'], row['experiment']['sha256'])
            assert row['experiment']['analysis_flags'] == study.recorded_flags(read(ROOT / row['experiment']['path'])) + study.ADDITIONS
            for item in row['preprocessing']['input_files']:
                if not item['path'].endswith('.c'):
                    if item['path'] in header_hashes:
                        assert header_hashes[item['path']] == item['sha256']
                    header_hashes[item['path']] = item['sha256']
    for path, expected in header_hashes.items():
        assert study.sha(Path(path).read_bytes()) == expected, path
    checked['verified_header_sha256'] = header_hashes
    env = dict(os.environ)
    removed = {key: env.pop(key, None) for key in study.ENV_REMOVE}
    env['LC_ALL'] = 'C'
    metadata = {'manifest_sha256': study.sha(manifest_path.read_bytes()), 'profile': study.PROFILE,
                'algorithm_sha256': current_algorithms, 'compiler_binary_sha256': old['compiler_binary_sha256'],
                'compiler': study.execute([clang, '--version'], env), 'scope': old['scope'],
                'comparison_limits': vars(study.ExactLimits()), 'pair_hard_timeout_seconds': study.PAIR_HARD_TIMEOUT,
                'total_new_comparison_budget_seconds': TOTAL_SECONDS, 'per_population_budget_seconds': POPULATION_SECONDS,
                'extraction_limits': '110 new candidates maximum; one AST and two preprocessing calls per candidate; existing 120-second call timeouts',
                'packages': {name: version(name) for name in ('numpy', 'scipy')}, 'python': sys.version,
                'removed_environment': removed, 'LC_ALL': 'C', 'verification': checked,
                'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    return members, populations, final_groups, metadata, clang, env


def pair_key(left, right):
    return '|'.join(sorted((left, right)))


def save_state(state):
    # Windows readers can briefly hold the destination open across WSL rename.
    # Retry only journal persistence, never extraction or comparison work.
    for attempt in range(20):
        try:
            study.save(STATE, state)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.1)


def initialize(members, populations, groups, metadata):
    if STATE.exists():
        state = read(STATE)
        for key in ('manifest_sha256', 'algorithm_sha256', 'profile', 'compiler_binary_sha256', 'scope', 'comparison_limits', 'packages',
                    'total_new_comparison_budget_seconds', 'per_population_budget_seconds'):
            assert state['provenance'][key] == metadata[key], 'resume_provenance_changed:' + key
        assert state['populations'] == populations
        for row in state['candidates'].values():
            assert all(row[k] == v for k, v in members[row['candidate_id']].items())
            if row.get('source_sha256'):
                assert study.sha((ROOT / row['candidate_source']).read_bytes()) == row['source_sha256'], 'resume_source_bytes_changed'
            for item in row.get('preprocessing', {}).get('input_files', []):
                if not item['path'].endswith('.c'):
                    assert study.sha(Path(item['path']).read_bytes()) == item['sha256']
        return state
    state = {'schema_version': 1, 'provenance': metadata, 'populations': populations, 'candidates': {}, 'pairs': {},
             'completed': False, 'new_comparison_seconds': 0., 'population_comparison_seconds': {}}
    for group in groups:
        for candidate in group['candidates']:
            state['candidates'][candidate['candidate_id']] = {**copy.deepcopy(candidate), 'measurement_origin': 'verified_final_cache'}
        for pair in group['pairs']:
            state['pairs'][pair_key(pair['left'], pair['right'])] = {**copy.deepcopy(pair), 'measurement_origin': 'verified_final_cache'}
    assert len(state['candidates']) == 30 and len(state['pairs']) == 102
    save_state(state)
    return state


def measure(state, members, clang, env):
    BUILD.mkdir(parents=True, exist_ok=True)
    # A journal entry precedes each expensive operation. An interrupted extraction
    # is not repeated. A completed pair worker file is recovered before marking loss.
    for group in state['populations']:
        for cid in group['candidate_ids']:
            row = state['candidates'].get(cid)
            if row is not None and row.get('journal_status') != 'running':
                continue
            if row is not None:
                row.update(journal_status='completed', comparison_eligible=False, extraction_status='unavailable',
                           failure_reason='interrupted_extraction_not_retried')
            else:
                state['candidates'][cid] = {**members[cid], 'journal_status': 'running'}
                save_state(state)
                row = study.extract_member(members[cid], clang, env, BUILD, None)
                row.update(journal_status='completed', measurement_origin='new_extraction')
                state['candidates'][cid] = row
            save_state(state)
            print('EXTRACT', cid, row['extraction_status'], row.get('failure_reason'), flush=True)
    for group in state['populations']:
        population = group['utility'] + '/' + group['checkpoint']
        for left, right in itertools.combinations(group['candidate_ids'], 2):
            key = pair_key(left, right)
            previous = state['pairs'].get(key)
            if previous is not None and previous.get('journal_status') != 'running':
                continue
            output = BUILD / (study.sha(key.encode()) + '.comparison.json')
            start = time.monotonic()
            if previous is not None:
                value = read(output) if output.exists() else study.unavailable('interrupted_comparison_not_retried')
                elapsed = study.PAIR_HARD_TIMEOUT  # conservative charge for interrupted work
            else:
                remaining = min(TOTAL_SECONDS - state['new_comparison_seconds'],
                                POPULATION_SECONDS - state['population_comparison_seconds'].get(population, 0.))
                state['pairs'][key] = {'left': left, 'right': right, 'journal_status': 'running'}
                save_state(state)
                a, b = state['candidates'][left], state['candidates'][right]
                if not a['comparison_eligible'] or not b['comparison_eligible']:
                    value = study.unavailable('candidate_extraction_or_provenance_unavailable')
                elif remaining <= 0:
                    value = study.unavailable('study_comparison_budget_exhausted')
                else:
                    paths = [ROOT / c['representation_artifact'] for c in (a, b)]
                    valid = all(p.exists() and study.sha(p.read_bytes()) == c['representation_sha256'] for p, c in zip(paths, (a, b)))
                    if not valid:
                        value = study.unavailable('cached_representation_missing_or_hash_mismatch')
                    else:
                        try:
                            result = subprocess.run([sys.executable, '-m', 'scripts.ordered_diversity_threshold_study', '--worker',
                                                     *map(str, paths), str(output)], cwd=ROOT, env=env, capture_output=True,
                                                    text=True, timeout=min(study.PAIR_HARD_TIMEOUT, remaining))
                            value = read(output) if result.returncode == 0 and output.exists() else study.unavailable('comparison_worker_failure:' + result.stderr[-2000:])
                        except subprocess.TimeoutExpired:
                            value = study.unavailable('pair_process_hard_timeout_or_study_budget')
                elapsed = time.monotonic() - start
            state['new_comparison_seconds'] += elapsed
            state['population_comparison_seconds'][population] = state['population_comparison_seconds'].get(population, 0.) + elapsed
            state['pairs'][key] = {'left': left, 'right': right, 'comparison': value, 'comparison_seconds': elapsed,
                                   'journal_status': 'completed', 'measurement_origin': 'new_checkpoint_measurement'}
            if previous is not None:
                state['pairs'][key]['resume_recovery'] = 'worker_result_recovered' if output.exists() else 'interruption_recorded_missing'
                state['pairs'][key]['comparison_seconds_basis'] = 'conservative_full_pair_guard_budget_charge'
            save_state(state)
            print('PAIR', population, len(state['pairs']), value['architecture']['status'], value['strategy']['status'], value['strategy'].get('reason', ''), flush=True)
    assert len(state['candidates']) == 140 and len(state['pairs']) == 495
    state['completed'] = True
    save_state(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measure-only', action='store_true')
    parser.add_argument('--summarize-only', action='store_true')
    args = parser.parse_args()
    members, populations, groups, metadata, clang, env = provenance()
    state = initialize(members, populations, groups, metadata)
    if not args.summarize_only:
        measure(state, members, clang, env)
    if not args.measure_only:
        assert state['completed'], 'Run without --summarize-only to finish or resume measurements.'
        from checkpoint_diversity_reporting import summarize
        summarize(state)


if __name__ == '__main__':
    main()
