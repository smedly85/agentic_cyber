"""Portable runtime measurements and Python diagnostic preflight; no model calls."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO/'scripts/run_experiment.sh'
CONTROLLER = REPO/'scripts/run_lineage_experiment.sh'
PYTHON_UTILITIES = {'python-cp': 4, 'python-mv': 3, 'python-sort': 5, 'python-mkdir': 3}


def shell_function(name):
    # Load only function definitions, never the runner's top-level experiment.
    match = re.search(r'^'+name+r'\(\) \{\n.*?^\}', RUNNER.read_text(), re.M | re.S)
    if not match:
        raise AssertionError('missing shell function: '+name)
    return match.group(0)


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'requires POSIX bash')
class RuntimePortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='runtime portability ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.python_log = self.root/'python calls'
        self.wrapper = self.root/'selected python'
        self.wrapper.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PYTHON_SELECTION_LOG"\nexec '
                                +shlex.quote(sys.executable)+' "$@"\n')
        self.wrapper.chmod(0o755)
        self.env = dict(os.environ, PYTHON_BIN=str(self.wrapper),
                        PYTHON_SELECTION_LOG=str(self.python_log), PYTHONDONTWRITEBYTECODE='1',
                        AIDER_BIN=str(self.root/'no-model-backend'))

    def run_shell(self, body):
        # Emulate a host without GNU nanosecond date support. Any date call is
        # an error in these timing-only tests; real ISO timestamps are unchanged.
        script = 'set -uo pipefail\ndate() { echo "unexpected date invocation" >&2; return 99; }\n'
        script += '\n'.join(shell_function(n) for n in ('monotonic_ns','run_logged_command','run_final_command'))
        result = subprocess.run(['bash','-c',script+'\n'+body], cwd=self.root,
                                env=self.env, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return result.stdout

    def test_clock_is_monotonic_and_uses_configured_interpreter(self):
        values = [int(v) for v in self.run_shell('monotonic_ns; monotonic_ns').splitlines()]
        self.assertEqual(len(values), 2)
        self.assertGreaterEqual(values[0], 0)
        self.assertGreaterEqual(values[1], values[0])
        self.assertEqual(self.python_log.read_text().count('time.monotonic_ns()'), 2)

    def test_logged_commands_preserve_status_output_and_nonnegative_ms(self):
        for status in (0, 7):
            with self.subTest(status=status):
                output = self.run_shell(f'''run_logged_command validation.log 'printf payload; sleep 0.02; exit {status}' 2 build''')
                observed, runtime_ms = map(int, output.split())
                self.assertEqual(observed, status)
                self.assertGreaterEqual(runtime_ms, 20)
                self.assertIn('VALIDATION LOOP 2: build', (self.root/'validation.log').read_text())
                self.assertIn('payload', (self.root/'validation.log').read_text())

    def test_final_commands_preserve_status_output_and_nonnegative_ms(self):
        for status in (0, 9):
            with self.subTest(status=status):
                output = self.run_shell(f'''run_final_command final.log 'printf payload; sleep 0.02; exit {status}' ''')
                observed, runtime_ms = map(int, output.split())
                self.assertEqual(observed, status)
                self.assertGreaterEqual(runtime_ms, 20)
                self.assertEqual((self.root/'final.log').read_text(), 'payload')

    def test_empty_commands_keep_zero_runtime(self):
        output = self.run_shell('run_logged_command empty.log "" 1 build; run_final_command final.log ""')
        self.assertEqual(output.splitlines(), ['0 0','0 0'])
        self.assertFalse(self.python_log.exists())
        self.assertEqual((self.root/'final.log').read_text(), '')

    def test_runtime_remains_integer_milliseconds(self):
        for invocation in ('run_logged_command log true 1 build', 'run_final_command log true'):
            with self.subTest(invocation=invocation):
                # Controlled nanosecond samples verify units and truncation,
                # independently of interpreter startup speed or wall time.
                output = self.run_shell('''
printf '1000000000\n' > clock_sample
monotonic_ns() {
    local sample
    read -r sample < clock_sample
    printf '%s\n' "$sample"
    printf '1045999999\n' > clock_sample
}
'''+invocation)
                self.assertEqual(output.strip(), '0 45')

    def test_all_timing_paths_use_portable_clock(self):
        for path in (RUNNER, CONTROLLER):
            self.assertNotRegex(path.read_text(), r'date\s+[^\n]*%N')
        for name in ('run_logged_command','run_final_command','run_aider'):
            self.assertEqual(shell_function(name).count('$(monotonic_ns)'), 2)

    def test_shell_syntax(self):
        for path in (RUNNER, CONTROLLER):
            result = subprocess.run(['bash','-n',str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def controller(self, utility, mode):
        output_dir = self.root/utility
        result = subprocess.run([
            'bash',str(CONTROLLER), '--utility',utility,
            '--model','ollama_chat/qwen3.8:27b',
            '--editor-model','ollama_chat/qwen3-coder-next:latest',
            '--architect-think','false','--temperature','0','--sampling-seed','42',
            '--num-ctx','65536','--lineages','1','--max-loops','3',
            '--remote-base-url','http://localhost:11434',
            '--output-dir',str(output_dir),mode,
        ], cwd=REPO, env=self.env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(output_dir.exists(), 'preflight must not create experiment output')
        return result

    def test_all_four_manifests_resolve_with_diagnostic_settings(self):
        for utility, count in PYTHON_UTILITIES.items():
            with self.subTest(utility=utility):
                result = self.controller(utility, '--print-plan')
                plan, _ = json.JSONDecoder().raw_decode(result.stdout.lstrip())
                self.assertEqual(plan['utility'], utility)
                self.assertEqual(len(plan['checkpoints']), count)
                self.assertEqual([c['source_mode'] for c in plan['checkpoints']], ['new']+['existing']*(count-1))
                self.assertIn('"$PYTHON_BIN"', plan['build_command'])
                self.assertIn('scripts/python_candidate.py', plan['build_command'])
                self.assertEqual(plan['sampling_seed'], 42)
                self.assertEqual(plan['num_ctx'], 65536)
                required = {'python-sort':'Darwin', 'python-mkdir':'Linux'}.get(utility)
                self.assertEqual(plan['required_platform'], required)

    def test_dry_plans_pin_interpreter_inherit_sources_and_disable_security(self):
        # Deliberately omit --no-security-evaluation: Python must disable it
        # itself. Dry-run prints commands only; no model backend exists here.
        for utility, count in PYTHON_UTILITIES.items():
            with self.subTest(utility=utility):
                self.python_log.unlink(missing_ok=True)
                result = self.controller(utility, '--dry-run')
                self.assertIn('import sys; print(sys.executable)', self.python_log.read_text())
                rows = re.findall(r'^\s+\[(\d+) [^]]+\] bash scripts/run_experiment.sh (.*)$', result.stdout, re.M)
                self.assertEqual(len(rows), count, result.stdout)
                for index, (checkpoint, command) in enumerate(rows):
                    args = shlex.split(command)
                    self.assertNotIn('--security-cmd', args)
                    self.assertIn('--no-analysis', args)
                    self.assertEqual(args[args.index('--source-mode')+1], 'existing' if index else 'new')
                    if index:
                        seed = args[args.index('--seed-file')+1]
                        self.assertIn(f'/lineage-001/{index-1:03}/', seed)
                        self.assertTrue(seed.endswith(':'+args[args.index('--source')+1]))
                    else:
                        self.assertNotIn('--seed-file', args)


if __name__ == '__main__':
    unittest.main()
