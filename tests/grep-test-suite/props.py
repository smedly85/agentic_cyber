#!/usr/bin/env python3
"""Runtime property checks for the new_grep suite.

`runner.py` looks a case's `"check": "property:<name>"` up in `CHECKS` when the
case asks to be judged by a property instead of by an exact stdout golden.

**This module is part of the agent-visible stage bundle, so it must never
import, embed, or otherwise expose a reference implementation of grep.** Every
frozen case in this suite is a `golden` case -- its expected stdout, exit status
and stderr class were computed offline and are compared byte for byte -- so no
case dispatches here, and `CHECKS` is deliberately empty.

The invariants that audit the frozen goldens *are* written in terms of the
specification model, and for that reason they live offline in
`tests/reference_generators/grep_invariants.py`, next to the model itself.
`gen/verify.py` runs them; the judge never does.

Adding a property check here means writing a rule the agent can read. That is
acceptable only for a rule stating a *necessary* condition the prompt already
implies (for example "every emitted line came from the input"), never one that
amounts to the answer. A rule that needs the model belongs offline.
"""
from __future__ import annotations

CHECKS: dict[str, object] = {}
