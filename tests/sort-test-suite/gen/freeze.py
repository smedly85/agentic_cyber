#!/usr/bin/env python3
"""
The oracle. Given an "unfrozen" case (args/flags/tags/input/check policy but
no expected output), run GNU sort through the shared engine and fill in the
golden fields: exit_code, stdout_b64 (for golden checks), stderr (exact for
curated, else class), output_file contents.

Because freeze uses the SAME engine.execute() as the runner, the golden is
produced under byte-identical conditions to how the candidate is judged
(env, argv[0]="sort", faults, rlimits, stdin mode).

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


def freeze_case(case: dict, sort_bin: str = "/usr/bin/sort",
                stdin_mode: str = "pipe") -> dict:
    """Return a frozen copy of `case`. Mutates a shallow copy; input case
    should carry:
      args, flags, tags, name, check, and one of stdin_b64/files_b64,
      optional: rule_id (for negative), exact_stderr (bool), output_file spec
      (path only), faults, timeout, env, stdin_modes.
    """
    c = dict(case)
    res = engine.execute(c, [sort_bin], stdin_mode=stdin_mode)

    if res.signal_name == "SKIP_ROOT":
        # The engine refused to run a permission-sensitive case because we are
        # root. Freezing whatever came back would bake root's privileges into
        # the golden -- an "unwritable output directory" case would record a
        # successful write. Abort instead; selfcheck.sh also refuses to run as
        # root, so reaching here means the generator was invoked directly.
        raise FreezeError(
            f"cannot freeze {c['name']} as root: it asserts that a permission "
            f"bit REFUSES the operation, and root ignores permission bits. "
            f"Re-run the generator as an unprivileged user.")

    if res.timed_out:
        raise FreezeError(f"GNU sort timed out freezing {c['name']}")
    allow = set(c.get("allow_signals", []))
    if res.crashed and res.signal_name not in allow:
        raise FreezeError(
            f"GNU sort crashed ({res.signal_name}) freezing {c['name']} "
            f"args={c.get('args')}")

    # exit_code stays absent when the process died by an allowed signal (the
    # candidate may exit 2 instead) or when the case is marked nondet_exit
    # (e.g. -R + check-mode without a fixed --random-source).
    if not res.crashed and not c.pop("nondet_exit", False):
        c["exit_code"] = res.exit_code
    else:
        c.pop("exit_code", None)
        c.pop("nondet_exit", None)

    # stdout: golden for golden-check cases; omitted for property/none checks
    check = c.get("check", "golden")
    if check == "golden":
        c["stdout_b64"] = _b64(res.stdout)
    else:
        c.pop("stdout", None)
        c.pop("stdout_b64", None)

    # stderr: exact for curated/negative cases; else record class only
    if c.get("exact_stderr"):
        c["stderr_b64"] = _b64(res.stderr)
        c.pop("stderr_class", None)
        c.pop("exact_stderr", None)
    else:
        c["stderr_class"] = "empty" if res.stderr == b"" else "nonempty"

    # output file golden
    spec = c.get("output_file")
    if spec is not None:
        got = res.outfiles.get(spec["path"], b"")
        spec["contents_b64"] = _b64(got)

    # negative-case cross-check
    rule_id = c.pop("rule_id", None)
    if rule_id is not None:
        exp = constraints.predict_error(rule_id)
        if res.exit_code != exp.exit_code:
            raise FreezeError(
                f"MODEL MISMATCH {c['name']}: rule {rule_id} predicts exit "
                f"{exp.exit_code} but GNU exited {res.exit_code} "
                f"(stderr={res.stderr[:120]!r})")
        # A tuple of accepted substrings means "any of these": see
        # constraints.ExpectedError. This is a loose model cross-check, not
        # candidate scoring, so accepting several documented wordings of one
        # error category does not weaken how candidates are judged.
        accepted = exp.stderr_contains
        if isinstance(accepted, str):
            accepted = (accepted,) if accepted else ()
        if accepted and not any(text.encode() in res.stderr for text in accepted):
            raise FreezeError(
                f"MODEL MISMATCH {c['name']}: rule {rule_id} expects stderr "
                f"to contain one of {list(accepted)!r}, got {res.stderr[:160]!r}. "
                f"If this is a wording change in a newer GNU coreutils, add it "
                f"to that rule in model/constraints.py; if the oracle version "
                f"is simply wrong, the suite's oracle pin should have caught it "
                f"first (see selfcheck.sh gate 0).")

    c.pop("exact_stderr", None)
    return c
