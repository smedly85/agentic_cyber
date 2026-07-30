#!/usr/bin/env python3
"""Model-dependent invariants for the frozen new_chmod cases.

These assert properties that hold no matter how a golden was produced: exit
status agrees with the diagnostic class, only `-c`/`-v` cases write to stdout,
every report line is well formed and names a fixture path, each line's octal and
symbolic renderings agree, every fixture path has an expected mode, and each
case's declared `flags` match the options its argv actually uses.
`tests/chmod-test-suite/gen/verify.py` runs them over every committed case,
which is what makes the frozen suite auditable without trusting the module that
generated it.

They live outside the suite because several of them are written in terms of the
specification model, and the model must never reach an experimental sandbox. See
README.md.
"""
from __future__ import annotations

import base64
import re

from . import chmod_reference as reference

# Kept in step with tests/chmod-test-suite/engine.py, which records a symlink by
# this marker rather than by a mode: a symlink's own permission bits are not
# portably meaningful, and the contract says a link found during traversal is
# left alone entirely.
SYMLINK_MARKER = "link"

CHANGED_LINE = re.compile(
    rb"^mode of '(?P<path>.*)' changed from "
    rb"(?P<before>[0-7]{4}) \((?P<before_sym>.{9})\) to "
    rb"(?P<after>[0-7]{4}) \((?P<after_sym>.{9})\)$"
)
RETAINED_LINE = re.compile(
    rb"^mode of '(?P<path>.*)' retained as "
    rb"(?P<mode>[0-7]{4}) \((?P<symbolic>.{9})\)$"
)


def _b64(value: str | None) -> bytes:
    return base64.b64decode(value) if value else b""


def _options_used(args: list[str]) -> set[str]:
    """Short and long options appearing before MODE, normalized to their short
    form. Mirrors chmod_reference.parse_args: options are recognized only up to
    the first non-option argument, and `--` ends option processing."""
    used: set[str] = set()
    for token in args:
        if token == "--":
            break
        if not token.startswith("-") or token == "-":
            break
        if token in reference.LONG_OPTIONS:
            name = reference.LONG_OPTIONS[token]
            used.update(
                flag for flag, mapped in reference.SHORT_OPTIONS.items()
                if mapped == name
            )
            continue
        if token.startswith("--"):
            break
        for letter in token[1:]:
            flag = f"-{letter}"
            if flag in reference.SHORT_OPTIONS:
                used.add(flag)
    return used


def case_invariants(case: dict) -> list[str]:
    """Model-independent checks on one frozen case. Returns a list of
    violations, empty when the case is self-consistent."""
    violations: list[str] = []
    name = case.get("name", "<unnamed>")

    for required in ("name", "args", "flags", "exit_code", "tags",
                     "expected_tree"):
        if required not in case:
            violations.append(f"{name}: missing required field {required!r}")
    if violations:
        return violations

    if case.get("stdout_b64") is None and case.get("check", "golden") == "golden":
        violations.append(f"{name}: golden case has no stdout_b64")
        return violations

    stdout = _b64(case.get("stdout_b64"))
    exit_code = case["exit_code"]

    if exit_code not in (0, 1):
        violations.append(f"{name}: exit_code {exit_code} outside 0/1")

    # Exit 1 always carries a diagnostic, and exit 0 never does. -f turns a
    # per-operand failure into neither, which is exactly why this has to hold
    # for the frozen goldens too.
    if exit_code == 0 and case.get("stderr_class") != "empty":
        violations.append(f"{name}: exit 0 must pair with an empty stderr")
    if exit_code == 1 and case.get("stderr_class") != "nonempty":
        violations.append(f"{name}: exit 1 must pair with a non-empty stderr")

    if stdout and not stdout.endswith(b"\n"):
        violations.append(f"{name}: stdout does not end with a newline")

    # Reporting is a -c / -v feature: no other case may write to stdout.
    reporting = bool({"-c", "-v"} & set(case["flags"]))
    if stdout and not reporting:
        violations.append(
            f"{name}: wrote to stdout without declaring -c or -v"
        )

    fixture_paths = {entry["path"] for entry in case.get("fixture") or []}
    for path in case["expected_tree"]:
        if path not in fixture_paths:
            violations.append(
                f"{name}: expected_tree names {path!r}, which the fixture "
                "does not create"
            )
    for entry in case.get("fixture") or []:
        expected = case["expected_tree"].get(entry["path"])
        if expected is None:
            violations.append(
                f"{name}: fixture path {entry['path']!r} has no expected mode"
            )
            continue
        if entry["type"] == "symlink":
            if expected != SYMLINK_MARKER:
                violations.append(
                    f"{name}: symlink {entry['path']!r} expects {expected!r} "
                    f"rather than {SYMLINK_MARKER!r}"
                )
        elif not re.fullmatch(r"[0-7]{4}", expected):
            violations.append(
                f"{name}: {entry['path']!r} expects a malformed mode "
                f"{expected!r}"
            )

    violations.extend(_report_line_violations(name, case, stdout))

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
    if absent and case.get("exit_code") != reference.EXIT_FAIL:
        violations.append(
            f"{name}: requires {sorted(absent)} to be absent, so it must "
            f"exit {reference.EXIT_FAIL}, not {case.get('exit_code')}"
        )

    return violations


def _report_line_violations(name: str, case: dict, stdout: bytes) -> list[str]:
    """Each report line must be well formed, must name a fixture path, and its
    rendered octal and symbolic values must agree with each other."""
    violations: list[str] = []
    known = {entry["path"].rstrip("/") for entry in case.get("fixture") or []}
    for line in stdout.split(b"\n"):
        if not line:
            continue
        changed = CHANGED_LINE.match(line)
        retained = RETAINED_LINE.match(line)
        match = changed or retained
        if match is None:
            violations.append(f"{name}: unrecognized report line {line!r}")
            continue
        path = match.group("path").decode("utf-8", "replace")
        if path.rstrip("/") not in known:
            violations.append(
                f"{name}: report line names {path!r}, which the fixture does "
                "not create"
            )
        pairs = (
            [("before", "before_sym"), ("after", "after_sym")]
            if changed
            else [("mode", "symbolic")]
        )
        for octal_key, symbolic_key in pairs:
            octal = int(match.group(octal_key), 8)
            symbolic = match.group(symbolic_key).decode("ascii", "replace")
            if reference.render_symbolic(octal) != symbolic:
                violations.append(
                    f"{name}: {match.group(octal_key)!r} renders as "
                    f"{reference.render_symbolic(octal)!r}, not {symbolic!r}"
                )
        if changed and match.group("before") == match.group("after"):
            violations.append(
                f"{name}: a 'changed' line reports the same mode twice"
            )
    return violations
