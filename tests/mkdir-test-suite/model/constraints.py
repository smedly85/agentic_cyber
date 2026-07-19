#!/usr/bin/env python3
"""
Constraint table for GNU mkdir (coreutils 9.x) option combinations and
operand/filesystem errors.

is_valid(flag_ids, values) -> Verdict
    Verdict is OK, or (CONFLICT, rule_id). mkdir has almost no mutually
    exclusive flags (-p, -m, -v, -Z/--context all freely combine), so the
    only flag-level legality check is whether -m's value parses as a valid
    chmod-style mode. Filesystem-driven errors (EEXIST/ENOENT/ENOTDIR/
    EACCES/missing operand) are NOT flag-combination issues -- they depend
    on the case's target paths and starting fixture, not on flags alone, so
    those cases assign rule_id directly (see gen/curated_cases.py) rather
    than being routed through is_valid().

predict_error(rule_id) -> ExpectedError(exit_code)
    The expected process exit code (and a loose stderr substring) for a
    rule violation. Exact stderr text is NOT hardcoded here -- freeze.py
    captures it from GNU mkdir through the engine (so argv[0]="mkdir"
    wording is always correct). predict_error is cross-checked against
    observed GNU exit codes during freeze; a mismatch aborts generation (it
    means the model is wrong).

All rules and exit codes were confirmed empirically against a GNU
coreutils 9.11 mkdir.
"""
from __future__ import annotations

from dataclasses import dataclass

OK = "OK"
CONFLICT = "CONFLICT"


@dataclass
class ExpectedError:
    exit_code: int
    # a substring that must appear in stderr (loose cross-check only)
    stderr_contains: str = ""


# rule_id -> ExpectedError. GNU mkdir uses exit code 1 uniformly for both
# usage errors and operand/filesystem errors (unlike sort's usage-exits-2
# convention).
RULES: dict[str, ExpectedError] = {
    "M_bad_mode": ExpectedError(1, "invalid mode"),
    "unknown_flag": ExpectedError(1, "unrecognized option"),
    "no_operand": ExpectedError(1, "missing operand"),
    "EEXIST": ExpectedError(1, "File exists"),
    "ENOENT": ExpectedError(1, "No such file or directory"),
    "ENOTDIR": ExpectedError(1, "Not a directory"),
    "EACCES": ExpectedError(1, "Permission denied"),
}


def predict_error(rule_id: str) -> ExpectedError:
    return RULES[rule_id]


# --- -m mode syntax validator (chmod-style symbolic or octal) --------------

_OCTAL_DIGITS = set("01234567")
_WHO = set("ugoa")
_OPS = set("+-=")
_PERMS = set("rwxXst")


def _valid_octal_mode(v: str) -> bool:
    if v == "" or not v.isdigit() or len(v) > 4:
        return False
    return all(ch in _OCTAL_DIGITS for ch in v)


def _valid_clause(c: str) -> bool:
    """One comma-separated symbolic clause: [ugoa]* ( [+-=][rwxXst]* )+.
    Chained actions with no separator are legal (e.g. 'u++w'); a clause with
    a 'who' prefix but no action, or any unrecognized character, is not."""
    i = 0
    n = len(c)
    while i < n and c[i] in _WHO:
        i += 1
    had_action = False
    while i < n:
        if c[i] not in _OPS:
            return False
        i += 1
        had_action = True
        while i < n and c[i] in _PERMS:
            i += 1
    return had_action


def _valid_symbolic_mode(v: str) -> bool:
    if v == "":
        return False
    return all(_valid_clause(c) for c in v.split(","))


def valid_mode(v: str) -> bool:
    return _valid_octal_mode(v) or _valid_symbolic_mode(v)


def is_valid(flag_ids: list[str], values: dict[str, list[str]]):
    """flag_ids: canonical IDs present. values: id -> list of the actual
    values supplied. Returns OK or (CONFLICT, rule_id)."""
    for v in values.get("-m", []):
        if not valid_mode(v):
            return (CONFLICT, "M_bad_mode")
    for v in values.get("--context", []):
        if v == "":
            return (CONFLICT, "M_bad_mode")  # not actually reachable today
    return OK
