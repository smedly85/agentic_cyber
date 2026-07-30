#!/usr/bin/env python3
"""Model-dependent invariants for the frozen new_grep cases.

These assert properties that hold no matter how a golden was produced: exit
status agrees with stdout, exit 2 carries a diagnostic, every emitted line
really is a matching line of some input, and each case's declared `flags` match
the options its argv actually uses. `tests/grep-test-suite/gen/verify.py` runs
them over every committed case, which is what makes the frozen suite auditable
without trusting the module that generated it — a hand-edited golden, or a model
that drifted from the prompt contract, shows up as a violated invariant.

They live outside the suite because several of them are written in terms of the
specification model, and the model must never reach an experimental sandbox. See
README.md.
"""
from __future__ import annotations

import base64

from . import grep_reference as reference


def _b64(value: str | None) -> bytes:
    return base64.b64decode(value) if value else b""


def _pattern_of(case: dict) -> tuple[bytes, bool]:
    options = reference.parse_args(list(case.get("args", [])))
    return options.pattern, options.ignore_case


def _prefixed(case: dict) -> bool:
    return bool(case.get("expect_filename_prefix"))


def _input_lines(case: dict) -> set[bytes]:
    lines: set[bytes] = set()
    if "stdin_b64" in case:
        lines.update(reference.split_lines(_b64(case["stdin_b64"])))
    for entry in case.get("fixture") or []:
        if entry.get("type") == "file":
            lines.update(reference.split_lines(_b64(entry.get("contents_b64"))))
    return lines


def case_invariants(case: dict) -> list[str]:
    """Model-independent checks on one frozen case. Returns a list of
    violations, empty when the case is self-consistent."""
    violations: list[str] = []
    name = case.get("name", "<unnamed>")

    for required in ("name", "args", "flags", "exit_code", "tags"):
        if required not in case:
            violations.append(f"{name}: missing required field {required!r}")
    if violations:
        return violations

    if case.get("stdout_b64") is None and case.get("check", "golden") == "golden":
        violations.append(f"{name}: golden case has no stdout_b64")
        return violations

    stdout = _b64(case.get("stdout_b64"))
    exit_code = case["exit_code"]

    if exit_code not in (0, 1, 2):
        violations.append(f"{name}: exit_code {exit_code} outside 0/1/2")

    # Exit status and stdout must agree: 0 means something was selected, 1 means
    # nothing was, and neither may carry a diagnostic.
    if exit_code == 0 and not stdout:
        violations.append(f"{name}: exit 0 but no line was emitted")
    if exit_code == 1 and stdout:
        violations.append(f"{name}: exit 1 but stdout is non-empty")
    if exit_code in (0, 1) and case.get("stderr_class") != "empty":
        violations.append(
            f"{name}: exit {exit_code} must pair with an empty stderr"
        )
    if exit_code == 2 and case.get("stderr_class") != "nonempty":
        violations.append(f"{name}: exit 2 must pair with a non-empty stderr")

    if stdout and not stdout.endswith(b"\n"):
        violations.append(f"{name}: stdout does not end with a newline")

    # Every option in argv must be accounted for, either as a flag the case
    # REQUIRES (`flags`) or as one it requires to be ABSENT (`absent_flags`) --
    # otherwise cumulative filtering would run a case at a checkpoint whose
    # feature it secretly needs, or withhold one it does not.
    declared = set(case["flags"])
    absent = set(case.get("absent_flags", []))
    used = _options_used(case["args"])
    if declared & absent:
        violations.append(
            f"{name}: {sorted(declared & absent)} is declared both required "
            "and absent"
        )
    if used != declared | absent:
        violations.append(
            f"{name}: flags {sorted(declared)} + absent {sorted(absent)} do "
            f"not match options used {sorted(used)}"
        )
    # A case asserting an option is not implemented yet must be a rejection: the
    # prompts make an option that has not been introduced an unknown option.
    if absent and case.get("exit_code") != 2:
        violations.append(
            f"{name}: requires {sorted(absent)} to be absent, so it must "
            f"exit 2, not {case.get('exit_code')}"
        )

    if case.get("check", "golden") == "golden":
        try:
            pattern, ignore_case = _pattern_of(case)
        except reference.UsageError:
            # A rejected command line has no pattern; the exit/stdout/stderr
            # agreement checks above are the whole contract for those cases.
            return violations
        available = _input_lines(case)
        for raw in reference.split_lines(stdout):
            line = raw.split(b":", 1)[1] if _prefixed(case) and b":" in raw else raw
            if line not in available:
                violations.append(
                    f"{name}: golden emits a line present in no input: {line!r}"
                )
                break
            if not reference.matches(line, pattern, ignore_case):
                violations.append(
                    f"{name}: golden emits a non-matching line: {line!r}"
                )
                break

    return violations


def _options_used(args: list[str]) -> set[str]:
    """Short and long options appearing before an operand-terminating '--',
    normalized to their short form. Scanning past operands rather than stopping
    at the first one mirrors grep_reference.parse_args, which permutes."""
    used: set[str] = set()
    for token in args:
        if token == "--":
            break
        if not token.startswith("-") or token == "-":
            continue
        if token in reference.LONG_OPTIONS:
            name = reference.LONG_OPTIONS[token]
            used.update(
                flag for flag, mapped in reference.SHORT_OPTIONS.items()
                if mapped == name
            )
            continue
        if token.startswith("--"):
            continue
        for letter in token[1:]:
            flag = f"-{letter}"
            if flag in reference.SHORT_OPTIONS:
                used.add(flag)
    return used
