"""Seed protocol tests; no model requests, Docker runs, or formal trials."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import lineage_plan
import lineage_state
import analyze_lineages

CONTROLLER = (ROOT / 'scripts/run_lineage_experiment.sh').read_text()


def plan(**kwargs):
    return lineage_plan.resolve_plan(ROOT, 'c-cp', 'ollama_chat/architect',
                                     '0', None, 3, 1800, **kwargs)


def test_legacy_plan_and_fingerprint_match_main(tmp_path):
    # Pin the pre-schedule implementation so this remains a regression after merge.
    original = tmp_path / 'original_plan.py'
    original.write_bytes(subprocess.check_output(
        ['git', 'show', '5c128adb4b44477545fa2b8bea344c51b42f9ecb:scripts/lineage_plan.py'],
        cwd=ROOT))
    spec = importlib.util.spec_from_file_location('original_plan', original)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for seed in (None, 0, 42):
        old = module.resolve_plan(ROOT, 'c-cp', 'ollama_chat/architect',
                                  '0', None, 3, 1800, sampling_seed=seed)
        assert plan(sampling_seed=seed) == old


def test_protocol_fingerprint():
    scheduled = plan(lineage_seed_base=42)
    assert scheduled['sampling_seed'] == 'per_lineage'
    assert scheduled['sampling_seed_schedule'] == {
        'version': 1, 'base_seed': 42, 'scope': 'architect',
        'formula': 'base_seed + lineage_number - 1'}
    assert scheduled == plan(lineage_seed_base='042')
    assert len({p['config_fingerprint'] for p in (
        scheduled, plan(lineage_seed_base=43), plan(sampling_seed=42), plan())}) == 4
    assert scheduled['editor_sampling_seed'] == 0
    assert scheduled['editor_temperature'] == 0.0


@pytest.mark.parametrize('base', ['-1', '1.5', 'invalid'])
def test_invalid_base(base):
    with pytest.raises(lineage_plan.ManifestError):
        plan(lineage_seed_base=base)


def test_mutual_exclusion():
    with pytest.raises(lineage_plan.ManifestError, match='mutually exclusive'):
        plan(lineage_seed_base=42, sampling_seed=0)


@pytest.mark.parametrize('args', [('--lineage-seed-base', ''),
    ('--lineage-seed-base', '-1'),
    ('--lineage-seed-base', '42', '--sampling-seed', '0')])
def test_cli_rejects_invalid_schedule(tmp_path, args):
    result = subprocess.run(['bash', 'scripts/run_lineage_experiment.sh',
        '--utility', 'c-cp', '--model', 'ollama_chat/architect',
        '--output-dir', str(tmp_path / 'out'), '--dry-run', *args],
        cwd=ROOT, text=True, capture_output=True,
        env={**os.environ, 'AIDER_BIN': '/nonexistent-aider', 'PYTHON_BIN': sys.executable})
    assert result.returncode == 2
    assert '--lineage-seed-base' in result.stderr
    assert not (tmp_path / 'out').exists()


def dry_run(tmp_path, *args):
    result = subprocess.run([
        'bash', 'scripts/run_lineage_experiment.sh', '--utility', 'c-cp',
        '--model', 'ollama_chat/architect', '--output-dir', str(tmp_path / 'out'),
        '--dry-run', *map(str, args)], cwd=ROOT, text=True, capture_output=True,
        env={**os.environ, 'AIDER_BIN': '/nonexistent-aider', 'PYTHON_BIN': sys.executable})
    assert result.returncode == 0, result.stderr
    commands = [shlex.split(line.split('bash scripts/run_experiment.sh', 1)[1])
                for line in result.stdout.splitlines()
                if 'bash scripts/run_experiment.sh' in line]
    return result.stdout, commands


def value(command, key):
    return command[command.index(key) + 1]


def test_dry_run_batching_and_legacy(tmp_path):
    text, commands = dry_run(tmp_path, '--lineage-seed-base', 42, '--lineages', 4)
    assert 'Sampling seed: base 42 + lineage number - 1' in text
    by_id = {}
    for command in commands:
        lineage = Path(value(command, '--output-dir')).parent.name
        by_id.setdefault(lineage, set()).add(int(value(command, '--sampling-seed')))
    assert by_id == {f'lineage-{i:03d}': {41+i} for i in range(1, 5)}
    _, later = dry_run(tmp_path, '--lineage-seed-base', 42, '--lineage-start', 4)
    assert later == commands[-len(later):]
    assert not (tmp_path / 'out').exists()
    for args, expected in [((), None), (('--sampling-seed', 42), '42'),
                           (('--lineage-seed-base', '000'), '0')]:
        _, rows = dry_run(tmp_path, *args)
        for row in rows:
            assert (value(row, '--sampling-seed') if '--sampling-seed' in row else None) == expected


def heredoc_after(marker):
    return CONTROLLER.split(marker, 1)[1].split("<<'PY'", 1)[1].split('\n', 1)[1].split('\nPY\n', 1)[0]


def test_run_metadata_resume_and_lineage_provenance(tmp_path):
    scheduled = plan(lineage_seed_base=42)
    path = tmp_path / 'lineages.json'
    writer = heredoc_after('if [[ "$DRY_RUN" -eq 0 ]]; then\n    "$PYTHON_BIN" - "$RUN_METADATA"')
    for start, count in [(1, 3), (4, 1), (4, 1)]:
        subprocess.run([sys.executable, '-', str(path), json.dumps(scheduled), str(ROOT),
                        'commit', str(start), str(count), 'now', '0', '0', '10', '1',
                        '2', '100', 'null'], input=writer, text=True, check=True)
    data = json.loads(path.read_text())
    assert data['sampling_seed_schedule'] == scheduled['sampling_seed_schedule']
    assert data['sampling_seed'] == 'per_lineage'
    assert data['planned_lineage_ids'] == [f'lineage-{i:03d}' for i in range(1, 5)]
    guard = heredoc_after('    mismatch="$(')
    for candidate, mismatch in [(scheduled, False), (plan(lineage_seed_base=43), True),
                                 (plan(), True), (plan(sampling_seed=42), True)]:
        result = subprocess.run([sys.executable, '-', str(path), candidate['config_fingerprint'],
            'c-cp', 'ollama_chat/architect', candidate['editor_model'], 'unknown', '0', '3',
            '__NONE__', '__NONE__', '__NONE__', '__NONE__', '__NONE__', 'editor-diff',
            json.dumps(candidate)], input=guard, text=True, capture_output=True, check=True)
        assert bool(result.stdout.strip()) == mismatch
    for number in range(1, 5):
        args = lineage_state.parse_args(['--path', str(tmp_path / 'lineage.json'),
            '--now', 'now', 'init', '--lineage-id', f'lineage-{number:03d}',
            '--utility', 'c-cp', '--sampling-seed', str(41+number), '--fingerprint', scheduled['config_fingerprint']])
        record = lineage_state.init_record(args)
        assert record['sampling_seed'] == 41+number
        assert record['config_fingerprint'] == data['config_fingerprint']
        lineage_state.write_atomic(tmp_path / record['lineage_id'] / 'lineage.json', record)
    _, population, never_started = analyze_lineages.load_run(tmp_path)
    assert len(population) == 4
    assert never_started == []


def test_legacy_resume_and_schedule_tampering(tmp_path):
    guard = heredoc_after('    mismatch="$(')
    path = tmp_path / 'lineages.json'
    for kwargs in ({}, {'sampling_seed': 42}, {'lineage_seed_base': 42}):
        original = plan(**kwargs)
        path.write_text(json.dumps(original))
        args = [sys.executable, '-', str(path), original['config_fingerprint'],
                'c-cp', 'ollama_chat/architect', original['editor_model'], 'unknown', '0', '3',
                '__NONE__', '__NONE__', '__NONE__', '__NONE__', '__NONE__', 'editor-diff',
                json.dumps(original)]
        result = subprocess.run(args, input=guard, text=True, capture_output=True, check=True)
        assert not result.stdout.strip()
        if 'lineage_seed_base' in kwargs:
            original['sampling_seed_schedule']['base_seed'] = 99
            path.write_text(json.dumps(original))
            result = subprocess.run(args, input=guard, text=True, capture_output=True, check=True)
            assert 'sampling_seed_schedule' in result.stdout


def test_actual_aider_settings_and_repair_invocations(tmp_path):
    # Execute the real stage controller against a deterministic local executable.
    # The stub only records settings and writes fixture text; it cannot call a model.
    stub = tmp_path / 'aider-stub'
    stub.write_text('''#!/usr/bin/env python3
import json, pathlib, sys
if '--version' in sys.argv:
    print('seed-test-stub')
    raise SystemExit()
def arg(k): return sys.argv[sys.argv.index(k)+1]
settings = pathlib.Path(arg('--model-settings-file'))
with (settings.parent / 'observed-settings.jsonl').open('a') as f:
    f.write(json.dumps(json.loads(settings.read_text())) + '\\n')
source = pathlib.Path(arg('--file'))
source.parent.mkdir(parents=True, exist_ok=True)
source.write_text('repaired' if source.exists() and source.stat().st_size else 'initial')
''')
    stub.chmod(0o755)
    prompt = tmp_path / 'prompt.md'
    prompt.write_text('Synthetic controller test.')
    _, commands = dry_run(tmp_path, '--lineage-seed-base', 42, '--lineage-start', 4)
    seed = value(commands[0], '--sampling-seed')
    output = tmp_path / 'stage'
    result = subprocess.run(['bash', 'scripts/run_experiment.sh', '--model', 'ollama_chat/architect',
        '--prompt', str(prompt), '--source', 'fixture.txt', '--source-mode', 'new',
        '--temperature', '0', '--sampling-seed', seed, '--max-loops', '1', '--timeout', '0',
        '--build-cmd', 'true', '--base-test-cmd', 'true',
        '--feature-test-cmd', 'test "$(cat fixture.txt)" = repaired', '--output-dir', str(output)],
        cwd=ROOT, text=True, capture_output=True,
        env={**os.environ, 'AIDER_BIN': str(stub), 'PYTHON_BIN': sys.executable})
    assert result.returncode == 0, result.stdout + result.stderr
    observed = list(output.rglob('observed-settings.jsonl'))
    assert len(observed) == 1
    settings = [json.loads(row) for row in observed[0].read_text().splitlines()]
    assert len(settings) == 2
    for setting in settings:
        assert setting[0]['extra_params']['seed'] == 45
        assert setting[1]['extra_params'] == {'temperature': 0.0, 'seed': 0}
    metadata = json.loads((observed[0].parent / 'metadata.json').read_text())
    assert metadata['sampling_seed'] == 45
    assert len(metadata['loops']) == 2
    assert all(row['sampling_seed'] == 45 for row in metadata['loops'])
