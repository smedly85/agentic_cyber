#!/usr/bin/env python3
"""
The oracle. Given an "unfrozen" case (args/flags/tags/fixture/umask/check
policy but no expected output), run GNU mkdir through the shared engine and
fill in the golden fields: exit_code, stdout_b64 (for -v cases), stderr
(exact for curated, else class), and `tree` -- the full post-run filesystem
snapshot (for check="golden" cases; mkdir's primary golden).

Because freeze uses the SAME engine.execute() as the runner, the golden is
produced under byte-identical conditions to how the candidate is judged
(env, argv[0]="mkdir", umask, fixture, faults).

For negative cases, freeze cross-checks the observed GNU exit code against
constraints.predict_error(rule_id); a mismatch raises (the model is wrong).
"""
from __future__ import annotations

import base64
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine  # noqa: E402
from model import constraints  # noqa: E402


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


class FreezeError(Exception):
    pass


def freeze_case(case: dict, mkdir_bin: str = "/usr/bin/mkdir") -> dict:
    """Return a frozen copy of `case`. Mutates a shallow copy; input case
    should carry:
      args, flags, tags, name, check, umask, fixture,
      optional: rule_id (for negative), exact_stderr (bool), faults,
      timeout, env, allow_signals.
    """
    c = dict(case)
    res = engine.execute(c, [mkdir_bin])

    if res.signal_name == "SKIP_ROOT":
        raise FreezeError(
            f"freeze must not run as root for permission-fault case "
            f"{c['name']} (chmod-based faults are no-ops for root)")
    if res.timed_out:
        raise FreezeError(f"GNU mkdir timed out freezing {c['name']}")
    allow = set(c.get("allow_signals", []))
    if res.crashed and res.signal_name not in allow:
        raise FreezeError(
            f"GNU mkdir crashed ({res.signal_name}) freezing {c['name']} "
            f"args={c.get('args')}")

    if not res.crashed and not c.pop("nondet_exit", False):
        c["exit_code"] = res.exit_code
    else:
        c.pop("exit_code", None)
        c.pop("nondet_exit", None)

    # stdout + tree: golden for golden-check cases; omitted for property/none
    check = c.get("check", "golden")
    if check == "golden":
        c["stdout_b64"] = _b64(res.stdout)
        c["tree"] = res.tree
    else:
        c.pop("stdout_b64", None)
        c.pop("tree", None)

    # stderr: exact for curated/negative cases; else record class only
    if c.get("exact_stderr"):
        c["stderr_b64"] = _b64(res.stderr)
        c.pop("stderr_class", None)
        c.pop("exact_stderr", None)
    else:
        c["stderr_class"] = "empty" if res.stderr == b"" else "nonempty"

    # negative-case cross-check
    rule_id = c.pop("rule_id", None)
    if rule_id is not None:
        exp = constraints.predict_error(rule_id)
        if res.exit_code != exp.exit_code:
            raise FreezeError(
                f"MODEL MISMATCH {c['name']}: rule {rule_id} predicts exit "
                f"{exp.exit_code} but GNU exited {res.exit_code} "
                f"(stderr={res.stderr[:120]!r})")
        if exp.stderr_contains and exp.stderr_contains.encode() not in res.stderr:
            raise FreezeError(
                f"MODEL MISMATCH {c['name']}: rule {rule_id} expects stderr "
                f"to contain {exp.stderr_contains!r}, got {res.stderr[:160]!r}")

    c.pop("exact_stderr", None)
    return c
