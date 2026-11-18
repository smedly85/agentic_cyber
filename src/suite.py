"""Test-suite contract and feedback formatting (stdlib only; used in containers).

A suite is a directory with an executable `run`:

    <suite>/run <project_dir> --report <report.json>

Exit 0 iff every case passed. The report is
    {"passed": int, "failed": int, "cases": [{"name", "status", "detail"}]}
A suite that exits without writing a report is summarized from its exit
code and output tail.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping


class SuiteRunner:
    def __init__(self, timeout_s: float = 900):
        self.timeout_s = timeout_s

    def run(self, suite: Path, project: Path, report: Path) -> dict[str, Any]:
        runner = Path(suite) / "run"
        if not runner.is_file():
            return {"ok": False, "passed": 0, "failed": 0, "cases": [], "error": f"suite has no executable `run`: {suite}"}
        start = time.monotonic()
        try:
            proc = subprocess.run(
                [str(runner), str(project), "--report", str(report)],
                cwd=str(suite),
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
            code, out, err, timed_out = proc.returncode, proc.stdout, proc.stderr, False
        except subprocess.TimeoutExpired as exc:
            code, out, err, timed_out = 124, _s(exc.stdout), _s(exc.stderr), True
        data: dict[str, Any] = {}
        if report.is_file():
            try:
                data = json.loads(report.read_text())
            except json.JSONDecodeError:
                data = {}
        cases = data.get("cases", []) if isinstance(data, dict) else []
        result = {
            "ok": code == 0 and not timed_out,
            "exit_code": code,
            "timed_out": timed_out,
            "elapsed_s": round(time.monotonic() - start, 3),
            "passed": data.get("passed", sum(c.get("status") == "pass" for c in cases)),
            "failed": data.get("failed", sum(c.get("status") != "pass" for c in cases)),
            "cases": cases,
            "stdout_tail": out[-4000:],
            "stderr_tail": err[-4000:],
        }
        return result


def _s(value) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


class SummaryFormatter:
    """Pass/fail counts plus a capped list of failing cases with short details."""

    def __init__(self, max_failures: int = 25, max_detail_chars: int = 300):
        self.max_failures = max_failures
        self.max_detail_chars = max_detail_chars

    @classmethod
    def from_config(cls, feedback: Mapping[str, Any]) -> "SummaryFormatter":
        return cls(feedback.get("max_failures", 25), feedback.get("max_detail_chars", 300))

    def format(self, result: Mapping[str, Any]) -> str:
        total = result.get("passed", 0) + result.get("failed", 0)
        lines = [f"TESTS: {'PASS' if result.get('ok') else 'FAIL'} ({result.get('passed', 0)}/{total} passed)"]
        if result.get("timed_out"):
            lines.append("The test suite timed out.")
        if result.get("error"):
            lines.append(result["error"])
        failing = [c for c in result.get("cases", []) if c.get("status") != "pass"]
        for case in failing[: self.max_failures]:
            detail = str(case.get("detail", ""))
            if len(detail) > self.max_detail_chars:
                detail = detail[: self.max_detail_chars] + "..."
            lines.append(f"  - {case.get('status', 'fail').upper()} {case.get('name', '?')}: {detail}")
        if len(failing) > self.max_failures:
            lines.append(f"  ... {len(failing) - self.max_failures} more failing cases omitted")
        if not result.get("ok") and not failing:
            tail = (result.get("stdout_tail", "") + result.get("stderr_tail", "")).strip()
            if tail:
                lines.append("Suite output (tail):\n" + tail[-1500:])
        return "\n".join(lines)
