"""Reproduce this sample: python3 docs/final_checkpoint_diversity_sample.py (WSL)."""
import copy
import itertools
import json
from pathlib import Path
import subprocess
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import ordered_diversity_threshold_study as study
from scripts.analysis.ordered_thresholds import analyze_population

OUT = ROOT / 'docs/final_checkpoint_diversity_sample.json'
HISTORY = ROOT / 'docs/ordered_diversity_threshold_pairwise.json'


def verify_hash(path, expected):
    data = path.read_bytes()
    raw, lf = study.sha(data), study.sha(data.replace(b'\r\n', b'\n'))
    assert expected in (raw, lf), str(path)
    return {'raw_sha256': raw, 'lf_normalized_sha256': lf,
            'match': 'raw' if raw == expected else 'CRLF_to_LF_only'}


def select(manifest, specs):
    groups = []
    for utility, checkpoint, count in specs:
        members = sorted([c for c in manifest['candidates'] if c['utility'] == utility
                          and c['checkpoint_id'] == checkpoint], key=lambda c: c['candidate_id'])
        assert len(members) == count
        assert len({c['candidate_id'] for c in members}) == count
        assert len({c['formal_run_id'] for c in members}) == 1
        assert all(c['final_population_member'] == (utility != 'sort') for c in members)
        assert all(c['functional_population_status'] == 'public_checkpoint_stage_success' for c in members)
        groups.append(dict(utility=utility, checkpoint=checkpoint, formal_run_id=members[0]['formal_run_id'],
                           manifest_members=members, candidates=[], pairs=[]))
    return groups


def main():
    manifest_path = ROOT / 'security/generated_candidate_population.json'
    manifest = json.loads(manifest_path.read_bytes())
    old = json.loads(HISTORY.read_bytes())
    assert old['completed'] and old['profile'] == study.PROFILE and old['profile_verification_error'] is None
    verification = {'manifest': verify_hash(manifest_path, old['manifest_sha256']),
                    'phase27_evidence': verify_hash(ROOT / 'docs/ordered_diversity_phase27_feasibility.json', old['phase27_evidence_sha256']),
                    'algorithms': {p: verify_hash(ROOT / p, h) for p, h in old['algorithm_sha256'].items()},
                    'candidates': {}}
    reused = copy.deepcopy(old['populations'])
    for group, selected in zip(reused, select(manifest, [('mkdir', '002', 7), ('grep', '004', 10)])):
        members = {c['candidate_id']: c for c in selected['manifest_members']}
        assert set(members) == {c['candidate_id'] for c in group['candidates']}
        for row in group['candidates']:
            member = members[row['candidate_id']]
            assert all(row[k] == v for k, v in member.items())
            source = ROOT / member['candidate_source']
            verification['candidates'][row['candidate_id']] = {
                'manifest_source': verify_hash(source, member['candidate_source_sha256']),
                'saved_extracted_source': verify_hash(source, row['source_sha256']),
                'experiment': verify_hash(ROOT / row['experiment']['path'], row['experiment']['sha256'])}
            assert row['comparison_eligible'] and row['source_unchanged']
        expected = {tuple(sorted(p)) for p in itertools.combinations(members, 2)}
        assert {tuple(sorted((p['left'], p['right']))) for p in group['pairs']} == expected
        assert len(group['pairs']) == len(expected)
        group['measurement_origin'] = 'verified_reuse'
    study.REPORT = ROOT / 'docs/final_checkpoint_diversity_new_pairwise.json'
    study.select_populations = lambda m: select(m, [('chmod', '004', 6), ('sort', '004', 7)])
    study.report_thresholds = lambda r: None
    original_extract = study.extract_member
    directory = ROOT / 'build/final-checkpoint-diversity-sample'
    directory.mkdir(parents=True, exist_ok=True)
    study.extract_member = lambda member, clang, env, unused, error: original_extract(member, clang, env, directory, error)
    if '--summarize-only' not in sys.argv:
        study.run()
    new = json.loads(study.REPORT.read_bytes())
    new['comparison_order'] = 'chmod then sort; sorted candidate IDs; unordered within-population pairs only'
    new['extraction_budget'] = '13 AST calls maximum; existing 120-second timeout and two provenance calls per candidate'
    study.save(study.REPORT, new)
    assert new['profile_verification_error'] is None
    assert new['compiler_binary_sha256'] == old['compiler_binary_sha256']
    assert new['scope'] == old['scope'] and new['comparison_limits'] == old['comparison_limits']
    report = {'schema_version': 1, 'profile': study.PROFILE, 'verification': verification,
              'reuse_evidence': {'path': str(HISTORY.relative_to(ROOT)), 'sha256': study.sha(HISTORY.read_bytes())},
              'new_evidence': {'path': str(study.REPORT.relative_to(ROOT)), 'sha256': study.sha(study.REPORT.read_bytes())},
              'runner_sha256': study.sha(Path(__file__).read_bytes()),
              'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'legacy_threshold': '0.30 reference only; no threshold selected or frozen', 'populations': []}
    for group in reused + new['populations']:
        candidate_ids = {c['candidate_id'] for c in group['candidates']}
        expected_pairs = {tuple(sorted(p)) for p in itertools.combinations(candidate_ids, 2)}
        assert len(group['pairs']) == len(expected_pairs)
        assert {tuple(sorted((p['left'], p['right']))) for p in group['pairs']} == expected_pairs
        for row in group['candidates']:
            path = ROOT / row['candidate_source']
            verify_hash(path, row['source_sha256'])
            committed = subprocess.check_output(['git', 'show', 'HEAD:' + row['candidate_source']], cwd=ROOT)
            assert committed.replace(b'\r\n', b'\n') == path.read_bytes().replace(b'\r\n', b'\n')
            row['sample_committed_source_verified'] = True
            for item in row['preprocessing']['input_files']:
                if not item['path'].endswith('.c'):
                    verify_hash(Path(item['path']), item['sha256'])
            row['sample_current_headers_verified'] = True
        group['population_status'] = ('public-success-only exploratory; final_population_member=false; failed extra validation'
                                      if group['utility'] == 'sort' else 'final_population_member=true')
        group.setdefault('measurement_origin', 'new_computation')
        group['analysis'] = analyze_population(group['candidates'], group['pairs'])
        exact = [p for p in group['pairs'] if p['comparison']['architecture']['status'] == 'success']
        group['extreme_pairs'] = {}
        if exact:
            for label, op in [('closest', min), ('most_distant', max)]:
                value = op(p['comparison']['architecture']['distance'] for p in exact)
                group['extreme_pairs'][label] = {'distance': value, 'scope': 'available_exact_pairs',
                    'pairs': [[p['left'], p['right']] for p in exact if p['comparison']['architecture']['distance'] == value]}
        group['missing_reasons'] = {metric: dict(Counter(p['comparison'][metric].get('reason', p['comparison'][metric]['status'])
            for p in group['pairs'] if p['comparison'][metric]['status'] != 'success')) for metric in ('architecture', 'strategy')}
        scenario = group['analysis']['scenarios']['architecture_exact']
        group['legacy_030_lineage_clusters'] = None
        if scenario['status'] == 'success':
            families = next(r['families'] for r in scenario['rows'] if r['threshold'] == .30)
            ids = {c['candidate_id']: c['lineage_id'] for c in group['candidates']}
            group['legacy_030_lineage_clusters'] = [[ids[c] for c in family] for family in families]
        report['populations'].append(group)
    study.save(OUT, report)
    render(report)


def render(report):
    reason_labels = {
        'no_scope_compatible_architecture_optimum': 'no scope-compatible Architecture optimum',
        'architecture_optima_not_exhausted:optimal_alignment_count_limit': 'optimal-alignment enumeration limit',
        'comparison_work_limit': 'Strategy work limit',
        'candidate_extraction_or_provenance_unavailable': 'candidate extraction failure',
    }
    def reasons(counts):
        return '; '.join(f'{count} {reason_labels.get(reason, reason)}' for reason, count in counts.items()) or 'none'
    lines = ['# Final-checkpoint C diversity sample', '',
        'Descriptive, separate populations; frozen order-aware Architecture (A) and Strategy (S), '
        '`c11-posix2008-v1`, unchanged scope and budgets. mkdir/grep measurements were reused after '
        'candidate, source, experiment, manifest, profile-evidence and algorithm hash verification. '
        'chmod/sort were computed afresh. Raw and LF-normalized hashes are recorded separately.', '',
        'mkdir, grep and chmod are final-population members. **sort is public-success-only exploratory:** '
        'all seven have `final_population_member=false` and failed extra validation. It is not an '
        'end-to-end successful population. No populations are pooled.', '',
        '| Population | n | Exact A pairs | Full-population mean A | S pairs | Available-pair mean S interval |',
        '|---|---:|---:|---:|---:|---|']
    for g in report['populations']:
        a = g['analysis']['matrices']['architecture_summary']; s = g['analysis']['matrices']['strategy_summary']
        mean = f"{a['mean']:.10f}" if a['complete'] else 'unavailable'
        interval = ', '.join(f'{v:.10f}' if v is not None else 'unavailable' for v in s['mean_interval'])
        lines.append(f"| {g['utility']}/{g['checkpoint']} | {len(g['candidates'])} | {a['available_pairs']}/{a['total_pairs']} | {mean} | {s['available_pairs']}/{s['total_pairs']} | [{interval}] |")
    for g in report['populations']:
        s = g['analysis']['matrices']['strategy_summary']; scenario = g['analysis']['scenarios']['architecture_exact']
        lines += ['', f"## {g['utility']}/{g['checkpoint']}", '']
        for label, value in g['extreme_pairs'].items():
            pairs = '; '.join(' / '.join(c.split('/')[-2] for c in pair) for pair in value['pairs'])
            lines.append(f"{label.replace('_', ' ').capitalize()} available architectural pair(s): {pairs}, A={value['distance']:.10f}.")
        lines += ['', f"S interval counts: {s['singleton_pairs']} singleton; {s['alignment_sensitive_pairs']} alignment-sensitive. Missing A: {reasons(g['missing_reasons']['architecture'])}. Missing S: {reasons(g['missing_reasons']['strategy'])}."]
        for c in g['candidates']:
            if not c['comparison_eligible']:
                diagnostics = c.get('diagnostics', '')
                errors = [line.split('error:', 1)[1].strip() for line in diagnostics.splitlines() if 'error:' in line]
                lines += ['', f"Extraction unavailable for {c['lineage_id']}: {'; '.join(errors) or c['failure_reason']}. Full compiler diagnostics are retained in the JSON; flags were not changed."]
        if scenario['status'] == 'success':
            grid = '; '.join(f"{r['threshold']:.2f}: {r['raw_family_count']}" for r in scenario['rows'])
            heights = ', '.join(f'{h:.10f}' for h in scenario['merge_heights'])
            stability = next(r for r in scenario['continuous_partition_stability'] if r['lower_inclusive'] <= .30 < r['upper_exclusive'])
            clusters = '; '.join('{' + ', '.join(f) + '}' for f in g['legacy_030_lineage_clusters'])
            lines += ['', f'Average-linkage threshold grid (threshold: cluster count): {grid}.', '',
                      f'Continuous merge heights: {heights}.', '', f'Legacy 0.30 clusters: {clusters}.', '',
                      f"The 0.30 partition persists on [{stability['lower_inclusive']:.10f}, {stability['upper_exclusive']:.10f}); merge heights are included at the lower bound."]
        else:
            lines += ['', 'Full-population threshold sensitivity, merge heights and 0.30 clusters are unavailable because the Architecture matrix is incomplete. No reduced-population clustering substitutes for them.']
    lines += ['', '## Interpretation and reproduction', '',
        'Means weight unordered pairs equally. S averages available lower and upper endpoints separately; '
        'incomplete coverage is not a full-population estimate. Scope-incompatible optima, enumeration limits '
        'and extraction failures remain missing, never zero. Alignment intervals describe all enumerated '
        'admissible Architecture-optimal correspondences, not semantic homology. The inherited name-based '
        'exclusion policy affects S scope and coverage. A describes function decomposition and directed '
        'call/API connectivity, including external API atoms. Pairs share candidates and are dependent; '
        'these success-conditioned observations from one model/configuration do not establish generality, '
        'functional equivalence or security effects.', '',
        'Average linkage, the existing 0.05–0.95 grid and continuous merge heights are descriptive. '
        '**0.30 is only the legacy reference; no threshold is selected or frozen.**', '',
        'Validation checked committed candidate bytes (allowing CRLF-to-LF conversion), current header hashes, '
        'complete pair identity sets and frozen algorithm hashes. No tracked existing files or tests were changed. '
        'The historical reports reference Python test files that are absent from this checkout; those tests were not rerun.', '',
        'Reproduce in the recorded WSL environment: `python3 docs/final_checkpoint_diversity_sample.py`. '
        'Use `--summarize-only` to recheck provenance and regenerate reports without recomputing pairs. '
        'The [combined machine-readable results](final_checkpoint_diversity_sample.json) include all pair '
        'measurements, identities, provenance checks, matrices and threshold summaries. '
        '[New computation evidence](final_checkpoint_diversity_new_pairwise.json) records compiler commands, '
        'diagnostics, preprocessing hashes and budgets. Historical evidence and frozen implementations are unchanged. '
        'No LLM calls, implementations, functional reruns or semantic-depth analysis were used.', '']
    (ROOT / 'docs/final_checkpoint_diversity_sample.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
