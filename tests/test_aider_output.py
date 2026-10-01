"""Aider recovery classification and real controller-loop regressions.

Agents/builds are deterministic test doubles, not utility implementations.
All candidate markers live in temporary directories outside the repository.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from aider_output import has_invalid_editor_output

ERROR = "The LLM did not conform to the edit format.\n1 SEARCH/REPLACE block failed to match!\n"
APPLIED = "Applied edit to specimen.rs\n"
RECOVERED = ERROR + "<<<<<<< SEARCH\n=======\n// marker\n>>>>>>> REPLACE\n" + APPLIED
DIAGNOSTIC = "error: unused import: `PathBuf`\n= note: `-D unused-imports` implied by `-D warnings`"


class OutputClassificationTests(unittest.TestCase):
    def classify(self, text, code=0, candidate=True, fmt="editor-diff"):
        return has_invalid_editor_output(text, fmt, agent_exit_code=code,
                                         candidate_available=candidate)

    def test_unrecovered_diagnostics(self):
        for line in ERROR.splitlines():
            with self.subTest(line=line):
                self.assertTrue(self.classify(line))

    def test_recovered_edit(self):
        self.assertFalse(self.classify(RECOVERED))

    def test_recovery_requires_successful_exit_and_candidate(self):
        for code, candidate in ((1, True), (124, True), (0, False)):
            with self.subTest(code=code, candidate=candidate):
                self.assertTrue(self.classify(RECOVERED, code, candidate))
        self.assertTrue(has_invalid_editor_output(RECOVERED, "editor-diff"))

    def test_later_error_is_not_recovered(self):
        self.assertTrue(self.classify(RECOVERED + ERROR))
        self.assertTrue(self.classify(APPLIED + ERROR))

    def test_malformed_markers_recover_only_before_applied_edit(self):
        malformed = "<<<<<<< SEARCH\n>>>>>>> REPLACE\n"
        self.assertTrue(self.classify(malformed))
        self.assertFalse(self.classify(malformed + APPLIED))
        self.assertTrue(self.classify(RECOVERED + malformed))

    def test_quoted_or_proposed_success_is_not_recovery(self):
        for line in ("> Applied edit to specimen.rs\n", "I will print Applied edit to specimen.rs\n"):
            self.assertTrue(self.classify(ERROR + line))

    def test_clean_sessions_unchanged(self):
        for text in ("", "Ordinary response\n", APPLIED,
                     "<<<<<<< SEARCH\n=======\n// marker\n>>>>>>> REPLACE\n"):
            self.assertFalse(self.classify(text))

    def test_whole_format_recovery(self):
        self.assertTrue(self.classify(ERROR, fmt="whole"))
        self.assertFalse(self.classify(RECOVERED, fmt="whole"))


@unittest.skipUnless(os.name == "posix", "requires bash controller")
class ControllerRecoveryTests(unittest.TestCase):
    def run_case(self, log=RECOVERED, code=0, candidate="// defective\n",
                 max_loops=0, build_fails=True):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = root / "fake-aider"
            agent.write_text(f'''#!/usr/bin/env python3
import pathlib, sys
if "--version" in sys.argv:
    print("aider-controller-test-double")
    raise SystemExit(0)
source = pathlib.Path(sys.argv[sys.argv.index("--file") + 1])
prompt = pathlib.Path(sys.argv[sys.argv.index("--message-file") + 1]).read_text()
if source.exists() and source.read_text() == "// defective\\n":
    assert {DIAGNOSTIC!r} in prompt, "compiler feedback missing from repair"
    source.write_text("// repaired\\n")
    print({APPLIED!r})
else:
    assert not source.exists(), "controller must not create a starter"
    if {candidate!r} is not None:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text({candidate!r})
    print({log!r})
    raise SystemExit({code})
''')
            agent.chmod(0o755)
            builder = root / "build-check.py"
            builder.write_text(f'''import pathlib, sys
p = pathlib.Path("specimen.rs")
failed = not p.is_file() or not p.stat().st_size or ({build_fails!r} and p.read_text() != "// repaired\\n")
if failed:
    print({DIAGNOSTIC!r}, file=sys.stderr)
raise SystemExit(int(failed))
''')
            prompt = root / "task.md"
            prompt.write_text("Create specimen.rs. Controller test only.")
            output = root / "run"
            command = ["bash", str(REPO / "scripts/run_experiment.sh"),
                       "--model", "test-model", "--editor-model", "test-editor",
                       "--editor-edit-format", "editor-diff", "--temperature", "0",
                       "--runs", "1", "--max-loops", str(max_loops), "--timeout", "30",
                       "--prompt", str(prompt), "--source", "specimen.rs",
                       "--source-mode", "new", "--build-cmd",
                       shlex.join([sys.executable, str(builder)]),
                       "--feature-test-cmd", "true", "--output-dir", str(output), "--no-analysis"]
            result = subprocess.run(command, cwd=REPO, text=True, capture_output=True,
                                    env=dict(os.environ, AIDER_BIN=str(agent), PYTHON_BIN=sys.executable),
                                    timeout=90)
            paths = list(output.glob("temp-*/attempt-*/metadata.json"))
            self.assertEqual(len(paths), 1, result.stdout + result.stderr)
            data = json.loads(paths[0].read_text())
            attempt = paths[0].parent
            return data, {p.name: p.read_text() for p in attempt.glob("*.log")}

    def test_unrecovered_invalid_edit_is_execution_failure(self):
        data, _ = self.run_case(log=ERROR, max_loops=1)
        self.assertTrue(data["agent_execution_failure"])
        self.assertEqual(data["agent_failure_reason"], "invalid_edit_format")
        self.assertFalse(data["repair_eligible"])
        self.assertEqual(data["repair_loops"], 0)

    def test_recovered_edit_proceeds_to_successful_build(self):
        data, _ = self.run_case(build_fails=False)
        self.assertFalse(data["agent_execution_failure"])
        self.assertTrue(data["initial_session_completed"])
        self.assertTrue(data["candidate_available_after_initial_session"])
        self.assertEqual(data["build_exit_code"], 0)
        self.assertTrue(data["public_validation_success"])

    def test_recovered_edit_build_failure_is_validation_failure(self):
        data, logs = self.run_case()
        self.assertFalse(data["agent_execution_failure"])
        self.assertTrue(data["initial_session_completed"])
        self.assertEqual(data["build_exit_code"], 1)
        self.assertFalse(data["public_validation_success"])
        self.assertEqual(data["repair_eligibility_reason"], "no_repair_budget")
        self.assertIn(DIAGNOSTIC, logs["build.log"])

    def test_recovered_build_failure_receives_one_repair_with_compiler_feedback(self):
        data, logs = self.run_case(max_loops=1)
        self.assertFalse(data["agent_execution_failure"])
        self.assertTrue(data["repair_eligible"])
        self.assertEqual(data["repair_eligibility_reason"], "controller_validation_feedback")
        self.assertEqual(data["repair_loops"], 1)
        self.assertEqual(data["llm_invocations"], 2)
        self.assertEqual([loop["build_exit_code"] for loop in data["loops"]], [1, 0])
        self.assertTrue(data["public_validation_success"])
        self.assertIn("REPAIR LOOP 1", logs["aider.log"])

    def test_clean_success_unchanged(self):
        data, _ = self.run_case(log=APPLIED, build_fails=False)
        self.assertFalse(data["agent_execution_failure"])
        self.assertTrue(data["public_validation_success"])

    def test_empty_output_without_protocol_error_keeps_existing_classification(self):
        data, _ = self.run_case(log="", candidate="")
        self.assertFalse(data["agent_execution_failure"])
        self.assertFalse(data["candidate_available_after_initial_session"])
        self.assertFalse(data["public_validation_success"])
        self.assertFalse(data["repair_eligible"])
        self.assertEqual(data["repair_eligibility_reason"], "no_candidate_after_initial_session")

    def test_claimed_recovery_without_candidate_is_failure(self):
        for candidate in (None, ""):
            with self.subTest(candidate=candidate):
                data, _ = self.run_case(candidate=candidate, max_loops=1)
                self.assertTrue(data["agent_execution_failure"])
                self.assertEqual(data["agent_failure_reason"], "invalid_edit_format")
                self.assertEqual(data["repair_loops"], 0)

    def test_claimed_recovery_with_unsuccessful_exit_is_failure(self):
        data, _ = self.run_case(code=1, max_loops=1)
        self.assertTrue(data["agent_execution_failure"])
        self.assertEqual(data["agent_failure_reason"], "invalid_edit_format")
        self.assertEqual(data["repair_loops"], 0)

    def test_token_limit_still_takes_precedence(self):
        data, _ = self.run_case(log=RECOVERED + "model has hit a token limit!\n", max_loops=1)
        self.assertTrue(data["agent_execution_failure"])
        self.assertEqual(data["agent_failure_reason"], "output_token_limit")
        self.assertEqual(data["repair_loops"], 0)

    def test_provider_exit_failure_unchanged(self):
        data, _ = self.run_case(log="Provider error\n", code=1, max_loops=1)
        self.assertTrue(data["agent_execution_failure"])
        self.assertEqual(data["agent_execution_failure_stage"], "aider")
        self.assertEqual(data["repair_loops"], 0)

    def test_timeout_with_candidate_still_repairs(self):
        data, _ = self.run_case(log=APPLIED, code=124, max_loops=1)
        self.assertTrue(data["candidate_available_after_timeout"])
        self.assertFalse(data["initial_session_completed"])
        self.assertEqual(data["repair_eligibility_reason"], "controller_validation_after_timeout")
        self.assertEqual(data["repair_loops"], 1)
        self.assertTrue(data["public_validation_success"])

    def test_timeout_without_candidate_unchanged(self):
        data, _ = self.run_case(log="", code=124, candidate=None, max_loops=1)
        self.assertTrue(data["agent_execution_failure"])
        self.assertEqual(data["agent_execution_failure_stage"], "timeout")
        self.assertEqual(data["repair_loops"], 0)


if __name__ == "__main__":
    unittest.main()
