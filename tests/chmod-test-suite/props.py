#!/usr/bin/env python3
"""Runtime property checks for the new_chmod suite.

`runner.py` looks a case's `"check": "property:<name>"` up in `CHECKS` when the
case asks to be judged by a property instead of by an exact stdout golden.

**This module is part of the agent-visible stage bundle, so it must never
import, embed, or otherwise expose a reference implementation of chmod.** The
one check kept here states a necessary condition the prompts already imply --
that a report line names a path the invocation was actually given -- and it is
written with a regex over the line format, not with the specification model.

Every frozen case in this suite is currently a `golden` case, so nothing
dispatches here today; the check remains available for a case whose exact output
is uninteresting but whose soundness is not.

The invariants that audit the frozen goldens are written in terms of the model
and therefore live offline in
`tests/reference_generators/chmod_invariants.py`, next to the model itself.
`gen/verify.py` runs them; the judge never does.
"""
from __future__ import annotations

import re

# Kept in step with tests/reference_generators/chmod_invariants.py. The line
# format is part of the -c/-v contract the prompts state, so restating its shape
# here reveals nothing the agent was not already told.
CHANGED_LINE = re.compile(
    rb"^mode of '(?P<path>.*)' changed from "
    rb"(?P<before>[0-7]{4}) \((?P<before_sym>.{9})\) to "
    rb"(?P<after>[0-7]{4}) \((?P<after_sym>.{9})\)$"
)
RETAINED_LINE = re.compile(
    rb"^mode of '(?P<path>.*)' retained as "
    rb"(?P<mode>[0-7]{4}) \((?P<symbolic>.{9})\)$"
)


def check_reported_paths_are_fixture_paths(case: dict, result) -> tuple[bool, str]:
    """Every report line must be well formed and name a path the case's fixture
    actually contains."""
    known = {entry["path"] for entry in case.get("fixture") or []}
    for line in result.stdout.split(b"\n"):
        if not line:
            continue
        match = CHANGED_LINE.match(line) or RETAINED_LINE.match(line)
        if match is None:
            return False, f"unrecognized report line: {line!r}"
        path = match.group("path").decode("utf-8", "replace")
        if path.rstrip("/") not in known:
            return False, f"reported a path not in the fixture: {path!r}"
    return True, ""


CHECKS = {
    "property:reported-paths-are-fixture-paths": check_reported_paths_are_fixture_paths,
}
