"""Reporting only: select measured pairs and reuse frozen threshold summaries."""
from __future__ import annotations

from collections import Counter
import copy
import csv
from fractions import Fraction
import itertools
import json
import math
from pathlib import Path
import statistics
import tempfile
from unittest.mock import patch

from checkpoint_diversity_trajectories import ROOT, STATE, SPECS, read, pair_key, study, analyze_population

OUT = ROOT / 'docs/checkpoint_diversity_trajectories.json'
CSV = ROOT / 'docs/checkpoint_diversity_trajectories.csv'
MD = ROOT / 'docs/checkpoint_diversity_trajectories.md'
BASE = {'mkdir': 'create directory operands', 'grep': 'fixed-string line selection',
        'chmod': 'octal/symbolic permission changes', 'sort': 'bytewise stdin line sorting'}


def ratio(a):
    return Fraction(a['atom_discrepancy'], a['atom_size_sum']) if a['atom_size_sum'] else Fraction(0)


def cohort_summary(group, candidates, pairs, name):
    analysis = analyze_population(candidates, pairs)
    a = analysis['matrices']['architecture_summary']
    s = analysis['matrices']['strategy_summary']
    identities = {c['candidate_id']: c['lineage_id'] for c in candidates}
    exact = [p for p in pairs if p['comparison']['architecture']['status'] == 'success']
    extremes = {}
    if exact:
        for label, op in [('closest', min), ('most_distant', max)]:
            value = op(ratio(p['comparison']['architecture']) for p in exact)
            extremes[label] = {'distance': float(value), 'exact_fraction': str(value), 'scope': 'measured_pairs_only',
                'lineage_pairs': [[identities[p['left']], identities[p['right']]] for p in exact if ratio(p['comparison']['architecture']) == value]}
    missing = {metric: [{'left': p['left'], 'right': p['right'], 'lineage_pair': [identities[p['left']], identities[p['right']]],
                        'status': p['comparison'][metric]['status'], 'reason': p['comparison'][metric].get('reason', p['comparison'][metric]['status'])}
                       for p in pairs if p['comparison'][metric]['status'] != 'success'] for metric in ('architecture', 'strategy')}
    scenario = analysis['scenarios']['architecture_exact']
    families = None
    if scenario['status'] == 'success':
        families = [[identities[c] for c in f] for f in next(r['families'] for r in scenario['rows'] if r['threshold'] == .30)]
    feature = group['feature_requirements']
    return {'utility': group['utility'], 'checkpoint': group['checkpoint'], 'formal_run_id': group['formal_run_id'],
            'cohort': name, 'feature_requirements': feature,
            'candidate_count': len(candidates), 'candidate_ids': sorted(identities), 'lineage_ids': sorted(identities.values()),
            'pair_keys': [pair_key(p['left'], p['right']) for p in pairs], 'total_pairs': a['total_pairs'],
            'architecture': {**a, 'full_cohort_mean': a['mean'] if a['complete'] else None,
                             'available_pair_mean': a['mean'], 'extremes': extremes},
            'strategy': s, 'missing_comparisons': missing,
            'missing_reason_counts': {metric: dict(Counter(p['reason'] for p in rows)) for metric, rows in missing.items()},
            'legacy_030_lineage_clusters': families, 'analysis': analysis}


def paired_changes(previous, current, state):
    def by_lineage(summary):
        result = {}
        for key in summary['pair_keys']:
            pair = state['pairs'][key]
            ids = tuple(sorted(state['candidates'][pair[side]]['lineage_id'] for side in ('left', 'right')))
            result[ids] = pair
        return result
    before, after = by_lineage(previous), by_lineage(current)
    assert set(before) == set(after)
    rows = []
    for ids in sorted(before):
        a, b = before[ids]['comparison']['architecture'], after[ids]['comparison']['architecture']
        row = {'lineage_pair': list(ids), 'before_status': a['status'], 'after_status': b['status']}
        if a['status'] == b['status'] == 'success':
            delta = ratio(b) - ratio(a)
            row.update(before_distance=float(ratio(a)), after_distance=float(ratio(b)), delta=float(delta),
                       delta_exact_fraction=str(delta), direction='increased' if delta > 0 else 'decreased' if delta < 0 else 'equal')
        else:
            row.update(delta=None, direction='unavailable', before_reason=a.get('reason'), after_reason=b.get('reason'))
        rows.append(row)
    values = [r['delta'] for r in rows if r['delta'] is not None]
    counts = Counter(r['direction'] for r in rows)
    return {'utility': current['utility'], 'cohort': current['cohort'], 'from_checkpoint': previous['checkpoint'],
            'to_checkpoint': current['checkpoint'], 'added_feature': current['feature_requirements'],
            'total_fixed_lineage_pairs': len(rows), 'paired_coverage': len(values),
            'direction_counts': {k: counts[k] for k in ('increased', 'decreased', 'equal', 'unavailable')},
            'mean_paired_delta': statistics.mean(values) if values else None,
            'median_paired_delta': statistics.median(values) if values else None,
            'minimum_paired_delta': min(values) if values else None, 'maximum_paired_delta': max(values) if values else None,
            'estimate_scope': 'same_lineage_pairs_observed_at_both_checkpoints_only', 'pairs': rows}


def summarize(state):
    summaries, changes, cohorts, attrition = [], [], {}, []
    for utility, expected in SPECS.items():
        populations = [g for g in state['populations'] if g['utility'] == utility]
        final = [state['candidates'][cid] for cid in populations[-1]['candidate_ids']]
        fixed = {c['lineage_id'] for c in final if c['final_population_member'] or utility == 'sort'}
        assert len(fixed) == expected[-1]
        if utility == 'sort':
            assert all(not c['final_population_member'] for c in final)
        cohort_name = 'fixed_public_completion' if utility == 'sort' else 'fixed_survivor'
        cohorts[utility] = {'fixed_cohort_name': cohort_name, 'fixed_lineage_ids': sorted(fixed),
                            'definition': 'lineages present at 004; public-completion only, failed extra validation' if utility == 'sort' else 'final_population_member=true at final checkpoint, traced backwards by lineage ID'}
        previous_fixed = None
        previous_ids = None
        for group in populations:
            candidates = [state['candidates'][cid] for cid in group['candidate_ids']]
            pairs = [state['pairs'][pair_key(a, b)] for a, b in itertools.combinations(group['candidate_ids'], 2)]
            fixed_candidates = [c for c in candidates if c['lineage_id'] in fixed]
            assert {c['lineage_id'] for c in fixed_candidates} == fixed
            fixed_ids = {c['candidate_id'] for c in fixed_candidates}
            fixed_pairs = [p for p in pairs if p['left'] in fixed_ids and p['right'] in fixed_ids]
            all_summary = cohort_summary(group, candidates, pairs, 'all_stage')
            fixed_summary = cohort_summary(group, fixed_candidates, fixed_pairs, cohort_name)
            summaries += [all_summary, fixed_summary]
            if previous_fixed:
                changes.append(paired_changes(previous_fixed, fixed_summary, state))
            current_ids = {c['lineage_id'] for c in candidates}
            attrition.append({'utility': utility, 'checkpoint': group['checkpoint'], 'all_stage_n': len(candidates),
                              'fixed_n': len(fixed_candidates), 'all_stage_only_lineages': sorted(current_ids - fixed),
                              'lineages_lost_since_previous': sorted(previous_ids - current_ids) if previous_ids is not None else [],
                              'lineages_added_since_previous': sorted(current_ids - previous_ids) if previous_ids is not None else [],
                              'extraction_unavailable_lineages': sorted(c['lineage_id'] for c in candidates if not c['comparison_eligible'])})
            previous_fixed, previous_ids = fixed_summary, current_ids
    checks = validate(state, summaries, changes)
    report = {'schema_version': 1, 'study': 'descriptive_longitudinal_frozen_order_aware_C_diversity',
              'profile': study.PROFILE, 'measurement_evidence': str(STATE.relative_to(ROOT)),
              'measurement_evidence_sha256': study.sha(STATE.read_bytes()), 'provenance': state['provenance'],
              'runner_sha256': {p: study.sha((ROOT / p).read_bytes()) for p in
                  ('docs/checkpoint_diversity_trajectories.py', 'docs/checkpoint_diversity_reporting.py')},
              'counts': {'candidate_observations': 140, 'all_stage_populations': 18, 'all_stage_pairs': 495,
                         'reused_final_pairs': 102, 'new_pair_records': 393, 'cohort_summary_rows': 36,
                         'fixed_cohort_pairs': sum(r['total_pairs'] for r in summaries if r['cohort'] != 'all_stage')},
              'cohort_definitions': cohorts, 'attrition': attrition, 'summaries': summaries, 'paired_changes': changes,
              'measurement_totals': {'new_comparison_seconds': state['new_comparison_seconds'],
                    'population_comparison_seconds': state['population_comparison_seconds'],
                    'extraction_statuses': dict(Counter(c['extraction_status'] for c in state['candidates'].values())),
                    'architecture_statuses': dict(Counter(p['comparison']['architecture']['status'] for p in state['pairs'].values())),
                    'strategy_statuses': dict(Counter(p['comparison']['strategy']['status'] for p in state['pairs'].values()))},
              'checks': checks, 'legacy_030': 'reference only, no threshold selected',
              'sort_status': 'PUBLIC-CHECKPOINT-SUCCESS exploratory; fixed public-completion cohort is not end-to-end successful'}
    study.save(OUT, report)
    write_csv(summaries)
    write_markdown(report, state)
    print(json.dumps({'counts': report['counts'], 'measurement_totals': report['measurement_totals'], 'checks': checks}), flush=True)


def validate(state, summaries, changes):
    assert state['completed'] and len(state['candidates']) == 140 and len(state['pairs']) == 495
    assert len(summaries) == 36 and len(changes) == 14
    assert sum(s['total_pairs'] for s in summaries if s['cohort'] == 'all_stage') == 495
    assert sum(s['total_pairs'] for s in summaries if s['cohort'] != 'all_stage') == 468
    assert Counter(p['measurement_origin'] for p in state['pairs'].values()) == {'verified_final_cache': 102, 'new_checkpoint_measurement': 393}
    for group in state['populations']:
        assert len(group['candidate_ids']) == SPECS[group['utility']][int(group['checkpoint'])]
        for a, b in itertools.combinations(group['candidate_ids'], 2):
            ca, cb = state['candidates'][a], state['candidates'][b]
            assert study.population_key(ca) == study.population_key(cb)
            p = state['pairs'][pair_key(a, b)]
            assert p['left'] == a and p['right'] == b
    for s in summaries:
        pairs = [state['pairs'][key] for key in s['pair_keys']]
        assert len(pairs) == math.comb(s['candidate_count'], 2)
        exact = [p['comparison']['architecture'] for p in pairs if p['comparison']['architecture']['status'] == 'success']
        for a in exact:
            assert math.isclose(a['distance'], float(ratio(a)), abs_tol=1e-14)
        independent_mean = float(sum((ratio(a) for a in exact), Fraction()) / len(exact)) if exact else None
        assert independent_mean is None or math.isclose(independent_mean, s['architecture']['available_pair_mean'], abs_tol=1e-14)
        assert s['architecture']['available_pairs'] + len(s['missing_comparisons']['architecture']) == len(pairs)
        assert s['strategy']['available_pairs'] + len(s['missing_comparisons']['strategy']) == len(pairs)
        assert s['strategy']['singleton_pairs'] + s['strategy']['alignment_sensitive_pairs'] == s['strategy']['available_pairs']
        intervals = [p['comparison']['strategy']['alignment_range'] for p in pairs if p['comparison']['strategy']['status'] == 'success']
        assert all(0 <= low <= high <= 1 for low, high in intervals)
        if intervals:
            for endpoint in (0, 1):
                assert math.isclose(math.fsum(v[endpoint] for v in intervals) / len(intervals), s['strategy']['mean_interval'][endpoint], abs_tol=1e-14)
        else:
            assert s['strategy']['mean_interval'] == [None, None]
        assert (s['analysis']['scenarios']['architecture_exact']['status'] == 'success') == s['architecture']['complete']
        if not s['architecture']['complete']:
            assert s['architecture']['full_cohort_mean'] is None and s['legacy_030_lineage_clusters'] is None
        if not s['strategy']['complete']:
            assert s['analysis']['scenarios']['strategy_lower_endpoint']['status'] == 'unavailable'
        for metric in ('architecture', 'strategy'):
            assert sum(s['missing_reason_counts'][metric].values()) == len(s['missing_comparisons'][metric])
    old = read(ROOT / 'docs/final_checkpoint_diversity_sample.json')
    for g in old['populations']:
        fresh = next(s for s in summaries if s['utility'] == g['utility'] and s['checkpoint'] == g['checkpoint'] and s['cohort'] == 'all_stage')
        assert fresh['analysis'] == g['analysis']
    for change in changes:
        assert sum(change['direction_counts'].values()) == change['total_fixed_lineage_pairs']
        assert change['paired_coverage'] == change['total_fixed_lineage_pairs'] - change['direction_counts']['unavailable']
        assert len({tuple(p['lineage_pair']) for p in change['pairs']}) == change['total_fixed_lineage_pairs']
    resume_checks(state)
    return {'manifest_population_counts': 'passed: 140 / 18 / 495', 'pair_identity_and_population_isolation': 'passed',
            'fixed_cohort_selection': 'passed: 468 selected pairs; no recomputation',
            'architecture_means_independent_fraction_check': 'passed', 'strategy_endpoint_mean_check': 'passed',
            'coverage_missingness_and_interval_counts': 'passed',
            'incomplete_matrix_clustering_guard': 'passed', 'final_checkpoint_summary_reproduction': 'passed for all four populations',
            'adjacent_fixed_lineage_pair_matching': 'passed: 14 transitions',
            'resume_regression_checks': 'passed: completed outcomes skipped; completed worker recovered; interrupted worker without output preserved as missing',
            'historical_python_tests': 'Referenced tests/test_ordered_*.py files absent from checkout; not rerun. Existing tests unchanged.'}


def resume_checks(state):
    """Exercise recovery on in-memory copies; forbid all compiler/worker calls."""
    import checkpoint_diversity_trajectories as runner
    candidate = next((key, p) for key, p in state['pairs'].items()
                     if p['measurement_origin'] == 'new_checkpoint_measurement'
                     and (runner.BUILD / (study.sha(key.encode()) + '.comparison.json')).exists())
    key, original = candidate
    with patch.object(runner, 'save_state'), patch.object(study, 'extract_member', side_effect=AssertionError('unexpected re-extraction')), \
            patch.object(runner.subprocess, 'run', side_effect=AssertionError('unexpected recomparison')):
        skipped = copy.deepcopy(state)
        runner.measure(skipped, {}, None, {})
        assert skipped == state
        recovered = copy.deepcopy(state)
        recovered['pairs'][key] = {'left': original['left'], 'right': original['right'], 'journal_status': 'running'}
        runner.measure(recovered, {}, None, {})
        assert recovered['pairs'][key]['comparison'] == original['comparison']
        assert recovered['pairs'][key]['resume_recovery'] == 'worker_result_recovered'
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='trajectory-resume-check-') as directory:
            missing = copy.deepcopy(state)
            missing['pairs'][key] = {'left': original['left'], 'right': original['right'], 'journal_status': 'running'}
            with patch.object(runner, 'BUILD', Path(directory)):
                runner.measure(missing, {}, None, {})
            assert missing['pairs'][key]['comparison']['architecture']['reason'] == 'interrupted_comparison_not_retried'
            assert missing['pairs'][key]['resume_recovery'] == 'interruption_recorded_missing'


def feature_label(s):
    feature = s['feature_requirements']
    if s['checkpoint'] == '000':
        return BASE[s['utility']] + ' (base)'
    return feature['name'] + '; cumulative ' + ' '.join(feature['implemented_flags'])


def write_csv(summaries):
    rows = []
    for s in summaries:
        a, strategy = s['architecture'], s['strategy']
        rows.append({'utility': s['utility'], 'formal_run_id': s['formal_run_id'], 'checkpoint': s['checkpoint'],
            'cohort': s['cohort'], 'population_status': 'public_checkpoint_success_only_exploratory' if s['utility'] == 'sort' else 'public_checkpoint_stage_success',
            'feature_requirements': feature_label(s), 'candidate_n': s['candidate_count'], 'total_pairs': s['total_pairs'],
            'exact_A_pairs': a['available_pairs'], 'A_coverage': a['coverage'], 'A_complete': a['complete'],
            'A_full_cohort_mean': a['full_cohort_mean'], 'A_available_pair_mean': a['available_pair_mean'], 'A_estimate_scope': a['estimate_scope'],
            'A_closest': json.dumps(a['extremes'].get('closest')), 'A_most_distant': json.dumps(a['extremes'].get('most_distant')),
            'S_pairs': strategy['available_pairs'], 'S_coverage': strategy['coverage'], 'S_mean_lower': strategy['mean_interval'][0],
            'S_mean_upper': strategy['mean_interval'][1], 'S_alignment_invariant_pairs': strategy['singleton_pairs'],
            'S_alignment_sensitive_pairs': strategy['alignment_sensitive_pairs'],
            'A_missing_reasons': json.dumps(s['missing_reason_counts']['architecture'], sort_keys=True),
            'S_missing_reasons': json.dumps(s['missing_reason_counts']['strategy'], sort_keys=True),
            'A_merge_heights': json.dumps(s['analysis']['scenarios']['architecture_exact'].get('merge_heights')),
            'legacy_030_lineage_clusters': json.dumps(s['legacy_030_lineage_clusters']), 'legacy_030_reference_only': True})
    with CSV.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def fmt(value, digits=6):
    return 'NA' if value is None else f'{value:.{digits}f}'


def trajectory(rows):
    return ' → '.join(fmt(s['architecture']['available_pair_mean']) + ('*' if not s['architecture']['complete'] else '') for s in rows)


def trend(rows):
    values = [s['architecture']['full_cohort_mean'] for s in rows]
    if any(v is None for v in values):
        complete = [(s['checkpoint'], v) for s, v in zip(rows, values) if v is not None]
        prefix = (f"Complete-cohort A is {complete[0][1]:.6f} at {complete[0][0]} and {complete[-1][1]:.6f} at {complete[-1][0]}. "
                  if len(complete) > 1 else '')
        available = [s['architecture']['available_pair_mean'] for s in rows]
        if all(v is not None for v in available):
            deltas = [b-a for a, b in zip(available, available[1:])]
            shape = 'increases monotonically' if all(d >= 0 for d in deltas) else 'decreases monotonically' if all(d <= 0 for d in deltas) else 'fluctuates'
            prefix += f'The available-pair mean {shape}, but its measured pair set changes. '
        return prefix + 'The incomplete full-cohort trajectory does not establish an overall full-cohort direction.'
    deltas = [b-a for a, b in zip(values, values[1:])]
    shape = 'increases monotonically' if all(d >= 0 for d in deltas) and any(d > 0 for d in deltas) else 'decreases monotonically' if all(d <= 0 for d in deltas) and any(d < 0 for d in deltas) else 'is constant' if all(d == 0 for d in deltas) else 'fluctuates'
    return f'A MPD {shape}; the final-minus-base change is {values[-1]-values[0]:+.6f}.'


def table(rows):
    lines = ['| Checkpoint | Feature requirements | n | Exact A coverage | Mean A | S coverage | Available-pair S interval |',
             '|---|---|---:|---:|---:|---:|---|']
    for s in rows:
        a, strategy = s['architecture'], s['strategy']
        lines.append(f"| {s['checkpoint']} | {feature_label(s)} | {s['candidate_count']} | {a['available_pairs']}/{s['total_pairs']} | {fmt(a['available_pair_mean'])}{'*' if not a['complete'] else ''} | {strategy['available_pairs']}/{s['total_pairs']} | [{fmt(strategy['mean_interval'][0])}, {fmt(strategy['mean_interval'][1])}] |")
    return lines


def strategy_trend(rows):
    directions = []
    for endpoint in (0, 1):
        values = [r['strategy']['mean_interval'][endpoint] for r in rows]
        if any(v is None for v in values):
            directions.append('unavailable at one or more stages')
            continue
        deltas = [b-a for a, b in zip(values, values[1:])]
        directions.append('constant' if all(d == 0 for d in deltas) else 'nondecreasing' if all(d >= 0 for d in deltas)
                          else 'nonincreasing' if all(d <= 0 for d in deltas) else 'fluctuating')
    coverage = ' → '.join(f"{r['strategy']['available_pairs']}/{r['total_pairs']}" for r in rows)
    return f'Available-pair S endpoint trends are {directions[0]} (lower) and {directions[1]} (upper), with coverage {coverage}. This describes available subsets, not a full-cohort scalar trajectory.'


def write_markdown(report, state):
    lines = ['# Longitudinal C structural-diversity results', '',
        'This descriptive analysis covers 140 public-checkpoint-success candidate observations in 18 separate '
        'utility/checkpoint populations and 495 within-checkpoint unordered pairs. The frozen order-aware Architecture '
        '(A) and Strategy (S) implementations, `c11-posix2008-v1`, scope rules and comparator defaults are unchanged. '
        'The 102 final-checkpoint pair records were verified and reused; 393 earlier-checkpoint pair records were added. '
        'A missing result is a recorded outcome, not a zero distance.', '',
        f"Coverage accounting: {report['measurement_totals']['architecture_statuses'].get('success', 0)}/495 exact A outcomes and "
        f"{report['measurement_totals']['strategy_statuses'].get('success', 0)}/495 available S intervals. These totals count "
        'records only; diversity statistics remain separate by utility, checkpoint and cohort.', '',
        '**Cohorts.** All-stage includes every public-checkpoint-success candidate at that stage, preserving successes '
        'before later failure. Fixed-survivor uses final-checkpoint `final_population_member=true` lineage IDs for '
        'mkdir/grep/chmod and traces those IDs backwards. Earlier rows need not have that flag. '
        '**Sort is public-checkpoint-success exploratory throughout:** its fixed **public-completion** cohort is the '
        'seven lineages present at 004; those final candidates failed extra validation and are not end-to-end successful.', '',
        '**Reading the tables.** A means are full-cohort MPD only with complete exact coverage. An asterisk marks an '
        'available-pair A mean, descriptive only; the full-cohort mean is unavailable. S intervals average the available '
        'lower and upper endpoints separately; they are never collapsed to scalars. Each denominator is the cohort\'s '
        'possible unordered-pair count. Feature columns summarize cumulative requirements; full recorded checkpoint '
        'metadata and prompt identities are in JSON. Rounding is for display only.', '']
    for utility in SPECS:
        all_rows = [s for s in report['summaries'] if s['utility'] == utility and s['cohort'] == 'all_stage']
        fixed_rows = [s for s in report['summaries'] if s['utility'] == utility and s['cohort'] != 'all_stage']
        fixed_name = 'Fixed public-completion' if utility == 'sort' else 'Fixed survivor'
        lines += [f'## {utility}' + (' — public-success-only exploratory' if utility == 'sort' else ''), '',
                  '**All-stage cohort**', '', *table(all_rows), '', f'**{fixed_name} cohort**', '', *table(fixed_rows), '',
                  f"Fixed lineage IDs: {', '.join(report['cohort_definitions'][utility]['fixed_lineage_ids'])}.", '',
                  f'All-stage: {trend(all_rows)} {fixed_name}: {trend(fixed_rows)}', '']
        dropped = [r for r in report['attrition'] if r['utility'] == utility and r['lineages_lost_since_previous']]
        lines += [('Population attrition: ' + '; '.join(r['checkpoint'] + ' loses ' + ', '.join(r['lineages_lost_since_previous']) for r in dropped) + '.') if dropped else 'There is no population attrition across these checkpoints.', '']
        different = [a['checkpoint'] for a, b in zip(all_rows, fixed_rows) if a['candidate_ids'] != b['candidate_ids']]
        lines += [('The cohort memberships differ at ' + ', '.join(different) + '; their means use different lineage-pair sets at those stages. Later cohort memberships coincide.')
                  if different else 'All-stage and fixed cohorts contain the same lineage IDs at every checkpoint; their summaries coincide.', '']
        lines += ['All-stage Strategy: ' + strategy_trend(all_rows), '', fixed_name + ' Strategy: ' + strategy_trend(fixed_rows), '']
        lines += ['Same fixed-cohort lineage-pair A changes (later minus earlier; equal means exact rational equality):', '',
                  '| Transition | Paired coverage | Increased | Decreased | Equal | Unavailable | Mean ΔA | Median ΔA | ΔA range |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---|']
        for c in [c for c in report['paired_changes'] if c['utility'] == utility]:
            d = c['direction_counts']
            lines.append(f"| {c['from_checkpoint']}→{c['to_checkpoint']} | {c['paired_coverage']}/{c['total_fixed_lineage_pairs']} | {d['increased']} | {d['decreased']} | {d['equal']} | {d['unavailable']} | {fmt(c['mean_paired_delta'])} | {fmt(c['median_paired_delta'])} | [{fmt(c['minimum_paired_delta'])}, {fmt(c['maximum_paired_delta'])}] |")
        lines += ['', 'Paired changes use only the same lineage pair measured at both stages. They separate changing '
                  'pair composition from measured distance changes, but not the effects of added feature requirements.', '']
    lines += ['## Pair extrema, uncertainty and missingness', '',
        'Every pair in the extrema column is a **measured-pair** extremum. Missing comparisons can conceal more extreme '
        'pairs. Lineage numbers below abbreviate `lineage-NNN`. I/V counts are alignment-invariant (singleton S interval) '
        'and alignment-sensitive (nonzero-width S interval), not claims of unique alignments. Identical cohort results '
        'are shown together; all 36 separate cohort summaries are retained in JSON/CSV.', '',
        'Missing-reason codes: **scope** = `no_scope_compatible_architecture_optimum`; **work** = `comparison_work_limit`; '
        '**optima** = `architecture_optima_not_exhausted:optimal_alignment_count_limit`; **extract** = '
        '`candidate_extraction_or_provenance_unavailable`. Any other reason is shown verbatim. JSON lists exact reasons '
        'for every unavailable pair.', '',
        '| Population | Cohort | Closest A: pair(s), distance | Most distant A: pair(s), distance | S I/V | Missing A | Missing S |',
        '|---|---|---|---|---|---|---|']
    aliases = {'no_scope_compatible_architecture_optimum': 'scope', 'comparison_work_limit': 'work',
               'architecture_optima_not_exhausted:optimal_alignment_count_limit': 'optima', 'candidate_extraction_or_provenance_unavailable': 'extract'}
    diagnostic_rows = []
    for group in state['populations']:
        rows = [s for s in report['summaries'] if (s['utility'], s['checkpoint']) == (group['utility'], group['checkpoint'])]
        if rows[0]['candidate_ids'] == rows[1]['candidate_ids']:
            diagnostic_rows.append((rows[0], 'both'))
        else:
            diagnostic_rows.extend((s, 'all-stage' if s['cohort'] == 'all_stage' else 'fixed') for s in rows)
    def extreme(s, label):
        e = s['architecture']['extremes'].get(label)
        return 'NA' if not e else '; '.join('/'.join(x.removeprefix('lineage-') for x in pair) for pair in e['lineage_pairs']) + ', ' + fmt(e['distance'])
    def reasons(s, metric):
        return '; '.join(f'{aliases.get(k, k)}: {v}' for k, v in s['missing_reason_counts'][metric].items()) or 'none'
    for s, cohort in diagnostic_rows:
        lines.append(f"| {s['utility']}/{s['checkpoint']} | {cohort} | {extreme(s, 'closest')} | {extreme(s, 'most_distant')} | {s['strategy']['singleton_pairs']}/{s['strategy']['alignment_sensitive_pairs']} | {reasons(s, 'architecture')} | {reasons(s, 'strategy')} |")
    failed = [c for c in state['candidates'].values() if not c['comparison_eligible']]
    if failed:
        lines += ['', 'Extraction failures (unchanged compiler flags; no candidate repairs):', '']
        for c in sorted(failed, key=lambda c: c['candidate_id']):
            errors = [line.split('error:', 1)[1].strip() for line in c.get('diagnostics', '').splitlines() if 'error:' in line]
            lines.append(f"- {c['utility']}/{c['checkpoint_id']} {c['lineage_id']}: {c['failure_reason']}; {'; '.join(dict.fromkeys(errors))}.")
    lines += ['', '## Exploratory Architecture threshold sensitivity', '',
        'The unchanged average-linkage method is evaluated at 0.05–0.95 in 0.05 steps. Full grid partitions, '
        'statistics and continuous stability intervals are in JSON. The table lists continuous merge heights and '
        'legacy 0.30 assignments; merge height ≤ threshold merges clusters. **0.30 is a reference only, not a '
        'selected or calibrated primary threshold.** Incomplete matrices have no clustering, imputation or '
        'candidate-dropping substitute.', '',
        '| Population | Cohort | Continuous A merge heights | Lineage clusters at legacy 0.30 |', '|---|---|---|---|']
    for s, cohort in diagnostic_rows:
        scenario = s['analysis']['scenarios']['architecture_exact']
        heights = ', '.join(fmt(h) for h in scenario.get('merge_heights', [])) or 'unavailable: incomplete matrix'
        clusters = '; '.join('{' + ','.join(x.removeprefix('lineage-') for x in family) + '}' for family in s['legacy_030_lineage_clusters']) if s['legacy_030_lineage_clusters'] is not None else 'unavailable'
        lines.append(f"| {s['utility']}/{s['checkpoint']} | {cohort} | {heights} | {clusters} |")
    lines += ['', '## Interpretation and limitations', '',
        'Attrition changes the all-stage population, while fixed cohorts hold lineage identity constant. Extraction '
        'and comparator limits instead change measurement coverage within a cohort. Neither is a measured distance '
        'change. Each feature checkpoint also changes the requested functionality: a longitudinal difference is '
        'not proof of autonomous drift alone. Available-pair S interval trajectories are descriptive of the observed '
        'subsets; changing coverage and interval width prevent reading them as a full-population scalar trend.', '',
        'A describes function decomposition and directed call/API connectivity, including external API atoms. '
        'S retains the inherited name-based helper-exclusion policy and evaluates compatible Architecture-optimal '
        'alignments. Helper naming can change inclusion and coverage; singleton intervals need not imply one '
        'alignment. Exhaustion and incompatibility remain unavailable. No full-population S family counts are '
        'reported from incomplete matrices. These syntax/structure measures do not establish behavioral equivalence '
        'or security effects. Pairs sharing candidates are dependent; no significance tests or cross-utility '
        'inferential treatment-effect comparisons are made. Results are conditional on the observed public successes '
        'and this generation configuration.', '', '## RQ2 results paragraph', '']
    sentences = ['Across 140 existing C candidate observations in 18 public-checkpoint-success populations, we '
                 'evaluated 495 within-checkpoint pairs using the frozen order-aware Architecture and Strategy measures.']
    for utility in SPECS:
        rows = [s for s in report['summaries'] if s['utility'] == utility and s['cohort'] != 'all_stage']
        cover = ', '.join(f"{s['architecture']['available_pairs']}/{s['total_pairs']}" for s in rows)
        name = 'fixed public-completion' if utility == 'sort' else 'fixed-survivor'
        sentences.append(f"For {utility}, the {name} Architecture mean trajectory was {trajectory(rows)} (exact-pair coverage: {cover}).")
    strategy_final = []
    for utility in SPECS:
        last = [s for s in report['summaries'] if s['utility'] == utility and s['cohort'] != 'all_stage'][-1]
        strategy_final.append(f"{utility} [{fmt(last['strategy']['mean_interval'][0])}, {fmt(last['strategy']['mean_interval'][1])}] ({last['strategy']['available_pairs']}/{last['total_pairs']} pairs)")
    sentences.append('Final available-pair mean Strategy intervals were ' + '; '.join(strategy_final) + '.')
    sentences += ['Asterisks identify available-pair descriptions where full-cohort means are unavailable. '
                  'All-stage and fixed-cohort views expose population-membership changes, while adjacent fixed-lineage-pair '
                  'comparisons describe structural-distance changes among the pairs measured at both stages. '
                  'Strategy results remain coverage-qualified intervals rather than scalars. Sort is exploratory '
                  'public-checkpoint success only: its final candidates failed extra validation. These descriptive '
                  'trajectories reflect both evolving implementations and added feature requirements, and do not '
                  'identify autonomous drift or an inferential effect across utilities.']
    lines += [' '.join(sentences), '', '## Reproduction and checks', '',
        '`python3 docs/checkpoint_diversity_trajectories.py` resumes completed measurements and writes reports. '
        '`--summarize-only` revalidates provenance and regenerates outputs without extraction or comparison. '
        'The durable [measurement journal](checkpoint_diversity_measurements.json) records candidates, all 495 '
        'pair outcomes, compiler diagnostics, raw/LF hashes and command provenance. ASTs and representations '
        'are cached under `build/checkpoint-diversity-trajectories/`. Final-checkpoint candidates are not re-extracted. '
        'The journal is atomically saved before and after each operation; completed failures are never retried. '
        'After interruption a completed worker result is recovered, while an interrupted extraction or comparison '
        'without a result remains explicitly unavailable.', '',
        f"Budget-charged new comparison time was {state['new_comparison_seconds']:.2f} seconds, within the prespecified "
        '3,600-second total and 900-second per-population budgets. The existing 100-second pair-process guard, '
        '45-second alignment/Strategy limits, 128-optimum limit, 2,000,000 Strategy work-unit limit and extraction '
        'timeouts were retained. Interrupted work is conservatively charged the full 100-second pair guard; '
        'this budget counter is not a pure wall-time benchmark. A completed worker result survives a journal-write '
        'interruption and is recovered without recomputation. Journal-write retries do not retry '
        'measurements. No failed measurement received increased limits.', '',
        'Checks verified manifest and committed source identities; formal run, checkpoint and lineage membership; '
        'raw and LF-normalized source hashes separately; historical profile and algorithm hashes; compiler and '
        'header hashes; 140/18/495 counts; all 36 cohort summaries; 468 fixed-cohort selected pair records; rational '
        'Architecture means; missingness accounting; incomplete-matrix clustering guards; all four final summaries '
        'against historical results; and 14 adjacent fixed-lineage-pair transitions. Resume regression checks on '
        'in-memory copies forbid all compiler/worker calls and verify completed-outcome skipping, worker-result '
        'recovery, and explicit missingness when interrupted work has no output. Historical reports reference '
        '`tests/test_ordered_*.py` files that are absent in this checkout, so those tests were not rerun. '
        'Existing candidate, metric, historical result and test files were preserved. No new generations, functional '
        'reruns, security-depth changes, threshold selection, commits or pushes were performed.', '',
        'Outputs: [JSON results](checkpoint_diversity_trajectories.json), '
        '[36-row CSV](checkpoint_diversity_trajectories.csv), '
        '[runner](checkpoint_diversity_trajectories.py), [reporting code](checkpoint_diversity_reporting.py).', '']
    MD.write_text('\n'.join(lines), encoding='utf-8')
