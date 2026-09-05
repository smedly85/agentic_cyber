from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "scripts" / "run_experiment.sh"
FAKE_OUTPUT = "fake aider invocation output"


@unittest.skipIf(os.name == "nt", "requires the POSIX experiment runner")
class RunExperimentAiderLogTests(unittest.TestCase):
    def _write_fake_aider(self, root: Path, exit_code: int) -> Path:
        path = root / "fake-aider"
        path.write_text(
            "#!/bin/sh\n"
            "if [ \"${1-}\" = --version ]; then\n"
            "    printf '%s\\n' 'fake-aider 1.0'\n"
            "    exit 0\n"
            "fi\n"
            "source_path=\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "    if [ \"$1\" = --file ]; then\n"
            "        source_path=$2\n"
            "        shift 2\n"
            "    else\n"
            "        shift\n"
            "    fi\n"
            "done\n"
            "printf '%s\\n' 'int main(void) { return 0; }' >\"$source_path\"\n"
            f"printf '%s\\n' {shlex.quote(FAKE_OUTPUT)}\n"
            f"exit {exit_code}\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def _write_disappearing_tee(self, root: Path) -> Path:
        real_tee = shutil.which("tee")
        self.assertIsNotNone(real_tee)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        wrapper = bin_dir / "tee"
        wrapper.write_text(
            "#!/bin/sh\n"
            f"{shlex.quote(real_tee)} \"$@\"\n"
            "status=$?\n"
            "for path do\n"
            "    case \"$path\" in\n"
            "        */.aider-current.log) rm -f -- \"$path\" ;;\n"
            "    esac\n"
            "done\n"
            "exit \"$status\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        return bin_dir

    def _run(self, *, exit_code: int, remove_current_log: bool):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        prompt = root / "prompt.md"
        prompt.write_text("Write the requested source file.\n", encoding="utf-8")
        output = root / "output"
        fake_aider = self._write_fake_aider(root, exit_code)

        environment = os.environ.copy()
        environment["AIDER_BIN"] = str(fake_aider)
        environment["PYTHON_BIN"] = sys.executable
        if remove_current_log:
            bin_dir = self._write_disappearing_tee(root)
            environment["PATH"] = os.pathsep.join(
                (str(bin_dir), environment.get("PATH", ""))
            )

        completed = subprocess.run(
            [
                "bash",
                str(RUNNER),
                "--model",
                "fake/architect",
                "--editor-model",
                "fake/editor",
                "--prompt",
                str(prompt),
                "--source",
                "candidate.c",
                "--source-mode",
                "new",
                "--temperature",
                "0",
                "--runs",
                "1",
                "--max-loops",
                "0",
                "--timeout",
                "0",
                "--output-dir",
                str(output),
                "--no-analysis",
            ],
            cwd=REPO,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        attempt = output / "temp-0p0" / "attempt-001"
        metadata = json.loads(
            (attempt / "metadata.json").read_text(encoding="utf-8")
        )
        durable_log = (attempt / "aider.log").read_text(encoding="utf-8")
        current_log_exists = (attempt / ".aider-current.log").exists()
        return completed, metadata, durable_log, current_log_exists

    def test_normal_current_log_is_parsed(self) -> None:
        completed, metadata, durable_log, _ = self._run(
            exit_code=0, remove_current_log=False
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(metadata["overall_success"])
        self.assertTrue(metadata["agent_log_capture_complete"])
        self.assertFalse(metadata["agent_log_capture_issue_observed"])
        loop = metadata["loops"][0]
        self.assertTrue(loop["agent_current_log_available"])
        self.assertEqual(loop["agent_log_capture_tee_exit_code"], 0)
        self.assertIsNone(loop["agent_log_capture_condition"])
        self.assertFalse(loop["agent_token_limit"])
        self.assertFalse(loop["agent_invalid_editor_output"])
        self.assertIn(FAKE_OUTPUT, durable_log)

    def test_missing_current_log_is_an_unknown_capture_observation(self) -> None:
        completed, metadata, durable_log, current_log_exists = self._run(
            exit_code=0, remove_current_log=True
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(metadata["overall_success"])
        self.assertFalse(metadata["agent_execution_failure"])
        self.assertIsNone(metadata["agent_execution_failure_stage"])
        self.assertIsNone(metadata["agent_failure_reason"])
        self.assertFalse(metadata["agent_log_capture_complete"])
        self.assertTrue(metadata["agent_log_capture_issue_observed"])
        loop = metadata["loops"][0]
        self.assertEqual(loop["agent_exit_code"], 0)
        self.assertFalse(loop["agent_current_log_available"])
        self.assertEqual(loop["agent_log_capture_tee_exit_code"], 0)
        self.assertTrue(loop["agent_log_parent_directory_available"])
        self.assertTrue(loop["agent_log_parent_directory_writable"])
        self.assertTrue(loop["agent_durable_log_available"])
        self.assertEqual(
            loop["agent_log_capture_condition"],
            "current_log_missing_after_pipeline",
        )
        self.assertIsNone(loop["agent_token_limit"])
        self.assertIsNone(loop["agent_invalid_editor_output"])
        self.assertIn(FAKE_OUTPUT, durable_log)
        self.assertNotIn("current log unavailable", durable_log)
        self.assertFalse(current_log_exists)
        self.assertIn("current log unavailable after pipeline", completed.stderr)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)
        self.assertNotRegex(
            completed.stdout + completed.stderr,
            r"grep: .*\.aider-current\.log.*No such file",
        )

    def test_missing_current_log_preserves_nonzero_aider_exit(self) -> None:
        completed, metadata, durable_log, current_log_exists = self._run(
            exit_code=7, remove_current_log=True
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(metadata["agent_exit_code"], 7)
        self.assertEqual(metadata["initial_agent_exit_code"], 7)
        self.assertTrue(metadata["agent_execution_failure"])
        self.assertEqual(metadata["agent_execution_failure_stage"], "aider")
        self.assertIsNone(metadata["agent_failure_reason"])
        self.assertFalse(metadata["overall_success"])
        loop = metadata["loops"][0]
        self.assertEqual(loop["agent_exit_code"], 7)
        self.assertIsNone(loop["agent_failure_reason"])
        self.assertIsNone(loop["agent_token_limit"])
        self.assertIsNone(loop["agent_invalid_editor_output"])
        self.assertEqual(
            loop["agent_log_capture_condition"],
            "current_log_missing_after_pipeline",
        )
        self.assertIn(FAKE_OUTPUT, durable_log)
        self.assertNotIn("current log unavailable", durable_log)
        self.assertFalse(current_log_exists)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)
        self.assertNotRegex(
            completed.stdout + completed.stderr,
            r"grep: .*\.aider-current\.log.*No such file",
        )


if __name__ == "__main__":
    unittest.main()
