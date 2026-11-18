#!/usr/bin/env python3
"""
Property checks for cases whose output shouldn't (or can't usefully) be
pinned to an exact golden tree.

Unlike sort -- where -R/--random-sort is genuinely implementation-defined
(the hash function isn't specified, so GNU's exact output ordering is not a
valid oracle) -- mkdir is fully deterministic given its fixture and umask,
so almost everything in this suite IS golden-checked exactly (see
runner.py's `check == "golden"` path, which diffs the full filesystem
tree). Property checks here cover the narrower cases where an exact tree
pin would be either meaningless or needlessly brittle:

  - idempotency: `mkdir -p` on an ALREADY-EXISTING target must leave it
    completely untouched (mode unchanged) even if `-m` is given -- GNU
    mkdir does not chmod pre-existing directories. What matters is that
    specific paths keep specific modes, not the whole tree.
  - existence-only: very-many-operand adversarial cases (hundreds of
    targets) are about volume-handling robustness, not exact-mode
    correctness already covered elsewhere -- pinning an exact 200-entry
    golden tree is brittle for little benefit; existence is what matters.

A check function takes (case, result) and returns (ok: bool, detail: str).
"""
from __future__ import annotations

from engine import Result


def _tree_by_path(res: Result) -> dict[str, dict]:
    return {e["path"]: e for e in res.tree}


def check_created(case: dict, res: Result) -> tuple[bool, str]:
    """Every path in case['targets'] must exist as a directory afterward."""
    if res.exit_code != 0:
        return False, f"expected success, exit={res.exit_code}"
    by_path = _tree_by_path(res)
    missing = [t for t in case.get("targets", [])
              if by_path.get(t, {}).get("type") != "dir"]
    if missing:
        return False, f"not created as directories: {missing}"
    return True, ""


def check_idempotent_p(case: dict, res: Result) -> tuple[bool, str]:
    """`-p` on an already-existing target must succeed AND must not modify
    the pre-existing path's mode, per case['preserve_mode'] = {path: octal
    mode string}."""
    if res.exit_code != 0:
        return False, f"expected success (idempotent -p), exit={res.exit_code}"
    by_path = _tree_by_path(res)
    bad = []
    for path, want_mode in case.get("preserve_mode", {}).items():
        entry = by_path.get(path)
        if entry is None:
            bad.append(f"{path}: missing after run")
            continue
        want = int(want_mode, 8)
        if entry["mode"] != want:
            bad.append(f"{path}: mode changed {oct(want)} -> {oct(entry['mode'])}")
    if bad:
        return False, "; ".join(bad)
    return True, ""


def check_partial(case: dict, res: Result) -> tuple[bool, str]:
    """Multi-operand partial failure: every path in case['targets_ok'] must
    exist as a directory, and the process must have exited nonzero (at
    least one operand failed)."""
    if res.exit_code == 0:
        return False, "expected nonzero exit (partial failure), got 0"
    by_path = _tree_by_path(res)
    missing = [t for t in case.get("targets_ok", [])
              if by_path.get(t, {}).get("type") != "dir"]
    if missing:
        return False, f"good operands not created: {missing}"
    return True, ""


CHECKS = {
    "property:created": check_created,
    "property:idempotent_p": check_idempotent_p,
    "property:partial": check_partial,
}
