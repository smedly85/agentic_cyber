#!/usr/bin/env python3
"""Render the continuation prompt for one repair loop.

The experiment controller (scripts/run_experiment.sh) calls this after a
validation stage fails. It fills prompts/repair_continuation_template.md with
the original task, the paths the agent must work within, and a compact,
deterministic description of what failed.

Failure extraction prefers structured data and degrades gracefully:

  1. a --json-report written by the suite runner (run_all.sh already writes one)
  2. the suite runner's own text output (FAIL <name> [<suite>] + detail line)
  3. Python unittest output
  4. compiler diagnostics
  5. a raw tail of the log

The compact list matters: a single suite case can print a multi-kilobyte
``args=`` line, so tailing raw output alone lets a few pathological cases crowd
out every other failure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VALIDATION_MARKER = re.compile(
    r"^===== VALIDATION LOOP \d+:[^\n]*=====\s*$", re.M
)

# Verdict vocabulary from tests/*/runner.py (SEVERITY / FAILING).
SUITE_FAILURE = re.compile(
    r"^(FAIL|TIMEOUT|SANITIZER|CRASH)\s+(\S+)\s+\[([^\]]+)\]", re.M
)
SUITE_TOTALS = re.compile(r"^(\d+)/(\d+) pass\s*$", re.M)
SUITE_PROBLEMS = re.compile(r"^(\d+) PROBLEM\(S\)\s*$", re.M)

UNITTEST_FAILURE = re.compile(r"^(FAIL|ERROR):\s+(\S+)\s*(?:\(([^)]*)\))?", re.M)
UNITTEST_RAN = re.compile(r"\bRan\s+(\d+)\s+tests?\b")

COMPILER_DIAGNOSTIC = re.compile(
    r"^([^\s:]+):(\d+):(?:(\d+):)?\s*(error|fatal error):\s*(.+)$", re.M
)


class Failure:
    def __init__(self, name: str, group: str = "", detail: str = "") -> None:
        self.name = name
        self.group = group
        self.detail = detail

    def render(self, max_detail_chars: int) -> str:
        heading = f"- {self.name}"
        if self.group:
            heading += f"  [{self.group}]"
        detail = collapse(self.detail)
        if not detail:
            return heading
        if len(detail) > max_detail_chars:
            detail = detail[:max_detail_chars].rstrip() + " ..."
        return f"{heading}\n      {detail}"


def collapse(text: str) -> str:
    """One-line, whitespace-normalised detail."""
    return " ".join(text.split())


def read_text(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def current_loop_section(text: str) -> str:
    """Keep only output from the most recent validation loop."""
    markers = list(VALIDATION_MARKER.finditer(text))
    if markers:
        return text[markers[-1].end():]
    return text


def failures_from_json_report(report_dir: Path | None) -> tuple[list[Failure], str]:
    """Read the newest --json-report emitted by a suite runner, if any."""
    if report_dir is None or not report_dir.is_dir():
        return [], ""
    reports = sorted(
        report_dir.rglob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in reports:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "failures" not in data:
            continue
        failures = []
        for entry in data.get("failures") or []:
            if isinstance(entry, (list, tuple)) and entry:
                name = str(entry[0])
                verdict = str(entry[1]) if len(entry) > 1 else ""
                detail = str(entry[2]) if len(entry) > 2 else ""
                failures.append(Failure(name, verdict, detail))
        if failures:
            counts = data.get("counts")
            summary = ""
            if isinstance(counts, dict):
                scored = sum(int(v) for v in counts.values() if isinstance(v, int))
                passed = int(counts.get("PASS", 0) or 0)
                summary = f"{passed}/{scored} pass"
            return failures, summary
    return [], ""


def failures_from_suite_text(text: str) -> tuple[list[Failure], str]:
    lines = text.splitlines()
    failures: list[Failure] = []
    for index, line in enumerate(lines):
        match = SUITE_FAILURE.match(line)
        if not match:
            continue
        verdict, name, suite = match.group(1), match.group(2), match.group(3)
        detail = ""
        if index + 1 < len(lines):
            following = lines[index + 1]
            # runner.py prints the detail indented directly beneath the case.
            if following.startswith("    ") and not SUITE_FAILURE.match(following):
                detail = following.strip()
        group = suite if verdict == "FAIL" else f"{suite}, {verdict}"
        failures.append(Failure(name, group, detail))

    summary = ""
    totals = SUITE_TOTALS.findall(text)
    if totals:
        passed, scored = totals[-1]
        summary = f"{passed}/{scored} pass"
    problems = SUITE_PROBLEMS.findall(text)
    if problems:
        summary = f"{summary}, {problems[-1]} failing".lstrip(", ")
    return failures, summary


def unittest_detail(text: str, start: int) -> str:
    """The assertion line beneath a unittest FAIL:/ERROR: header.

    unittest prints a dashed rule, then a traceback, then a blank line. The
    last non-empty line of that block is the AssertionError or exception, which
    is the part worth surfacing.
    """
    block = text[start:]
    end = re.search(r"\n\s*\n", block)
    if end:
        block = block[: end.start()]
    lines = [line.strip() for line in block.splitlines()]
    body = [
        line
        for line in lines
        if line and not set(line) <= {"-", "="} and not line.startswith("File ")
    ]
    return body[-1] if body else ""


def failures_from_unittest(text: str) -> tuple[list[Failure], str]:
    failures = []
    for match in UNITTEST_FAILURE.finditer(text):
        detail = unittest_detail(text, match.end())
        if not detail or detail.startswith("Traceback"):
            detail = match.group(1)
        failures.append(
            Failure(match.group(2), (match.group(3) or "").strip(), detail)
        )
    summary = ""
    ran = UNITTEST_RAN.search(text)
    if ran:
        summary = f"ran {ran.group(1)} tests"
    if failures:
        summary = f"{summary}, {len(failures)} failing".lstrip(", ")
    return failures, summary


def failures_from_compiler(text: str) -> tuple[list[Failure], str]:
    failures = []
    for match in COMPILER_DIAGNOSTIC.finditer(text):
        path, line, column, kind, message = match.groups()
        location = f"{path}:{line}:{column}" if column else f"{path}:{line}"
        failures.append(Failure(location, kind, message))
    summary = f"{len(failures)} compiler errors" if failures else ""
    return failures, summary


def extract_failures(text: str, report_dir: Path | None) -> tuple[list[Failure], str]:
    """Try each extractor in precedence order; first with results wins."""
    failures, summary = failures_from_json_report(report_dir)
    if failures:
        return failures, summary
    for extractor in (
        failures_from_suite_text,
        failures_from_unittest,
        failures_from_compiler,
    ):
        failures, summary = extractor(text)
        if failures:
            return failures, summary
    return [], ""


def render_failures(
    stages: list[tuple[str, int, str, Path | None]],
    max_failures: int,
    max_detail_chars: int,
) -> str:
    blocks = []
    for name, exit_code, text, report_dir in stages:
        if exit_code == 0:
            continue
        failures, summary = extract_failures(text, report_dir)
        heading = f"{name} (exit {exit_code}"
        heading += f", {summary})" if summary else ")"
        if not failures:
            blocks.append(
                f"{heading}\n\n"
                "    No individual failures could be identified; see the raw "
                "output below."
            )
            continue
        shown = failures[:max_failures]
        rendered = "\n".join(
            failure.render(max_detail_chars) for failure in shown
        )
        remaining = len(failures) - len(shown)
        if remaining > 0:
            rendered += f"\n- ... and {remaining} more failing"
        blocks.append(f"{heading}\n\n{rendered}")

    if not blocks:
        return "No individual failing tests were reported."
    return "\n\n".join(blocks)


def render_raw_tails(
    stages: list[tuple[str, int, str, Path | None]],
    tail_chars: int,
) -> str:
    blocks = []
    for name, exit_code, text, _ in stages:
        if exit_code == 0:
            blocks.append(f"{name}: passed; output omitted.")
            continue
        body = text.rstrip()
        if not body:
            blocks.append(f"{name}: failed without output.")
            continue
        if len(body) > tail_chars:
            body = (
                f"[truncated deterministically to final {tail_chars} characters]\n"
                + body[-tail_chars:]
            )
        blocks.append(f"{name}:\n\n```\n{body}\n```")
    return "\n\n".join(blocks)


def demote_headings(text: str, levels: int = 2) -> str:
    """Push quoted-document headings below the host document's own sections.

    The original task is a complete prompt with its own `## Visible tests` and
    `## Final response`. Splicing it in verbatim produces two sections with the
    same name and contradictory contents.
    """
    return re.sub(
        r"^(#{1,4})(\s)",
        lambda match: "#" * min(6, len(match.group(1)) + levels) + match.group(2),
        text,
        flags=re.M,
    )


def indent_block(text: str, prefix: str = "    ") -> str:
    if not text:
        return ""
    return "\n".join(
        prefix + line if line.strip() else line for line in text.splitlines()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--original-prompt", required=True, type=Path)
    parser.add_argument("--program", default="the implementation")
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--loop-number", required=True, type=int)
    parser.add_argument("--max-loops", required=True, type=int)
    parser.add_argument("--test-dir", action="append", default=[])
    parser.add_argument("--build-command", default="")
    parser.add_argument("--validation-command", action="append", default=[])
    parser.add_argument("--build-log", type=Path)
    parser.add_argument("--build-exit", type=int, default=0)
    parser.add_argument("--base-test-log", type=Path)
    parser.add_argument("--base-test-exit", type=int, default=0)
    parser.add_argument("--feature-test-log", type=Path)
    parser.add_argument("--feature-test-exit", type=int, default=0)
    parser.add_argument(
        "--json-report-dir",
        type=Path,
        default=None,
        help="Directory searched for a suite runner --json-report file.",
    )
    parser.add_argument("--max-failures", type=int, default=25)
    parser.add_argument("--max-detail-chars", type=int, default=300)
    parser.add_argument("--tail-chars", type=int, default=16000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    template = args.template.read_text(encoding="utf-8")
    original_prompt = demote_headings(
        args.original_prompt.read_text(encoding="utf-8", errors="replace").strip()
    )

    stages = [
        (
            "Build",
            args.build_exit,
            current_loop_section(read_text(args.build_log)),
            None,
        ),
        (
            "Base tests",
            args.base_test_exit,
            current_loop_section(read_text(args.base_test_log)),
            args.json_report_dir,
        ),
        (
            "Checkpoint tests",
            args.feature_test_exit,
            current_loop_section(read_text(args.feature_test_log)),
            args.json_report_dir,
        ),
    ]

    test_dirs = args.test_dir or ["(no visible test directory was provided)"]
    validation_commands = [
        command for command in args.validation_command if command.strip()
    ] or ["(no validation command configured)"]

    replacements = {
        "[PROGRAM]": args.program,
        "[LOOP_NUMBER]": str(args.loop_number),
        "[MAX_LOOPS]": str(args.max_loops),
        "[SOURCE_PATH]": args.source_path,
        "[ORIGINAL_PROMPT]": original_prompt,
        "[BUILD_EXIT_CODE]": str(args.build_exit),
        "[BASE_TEST_EXIT_CODE]": str(args.base_test_exit),
        "[FEATURE_TEST_EXIT_CODE]": str(args.feature_test_exit),
        "[STRUCTURED_FAILURES]": render_failures(
            stages, args.max_failures, args.max_detail_chars
        ),
        "[RAW_OUTPUT_TAILS]": render_raw_tails(stages, args.tail_chars),
        "[TEST_DIR_PATHS]": "\n".join(test_dirs),
        "[BUILD_COMMAND]": args.build_command or "(no build command configured)",
        "[VALIDATION_COMMANDS]": "\n".join(validation_commands),
    }

    # Placeholders sitting inside a 4-space literal block keep that indentation
    # when their replacement spans several lines.
    rendered = template
    for placeholder, value in replacements.items():
        pattern = re.compile(
            r"^(?P<indent>[ \t]*)" + re.escape(placeholder) + r"[ \t]*$", re.M
        )

        def substitute(match: re.Match[str], value: str = value) -> str:
            indent = match.group("indent")
            if not indent:
                return value
            return indent_block(value, indent)

        rendered = pattern.sub(substitute, rendered)
        rendered = rendered.replace(placeholder, value)

    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
