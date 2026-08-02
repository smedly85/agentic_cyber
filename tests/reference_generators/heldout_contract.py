#!/usr/bin/env python3
"""Shared shape, storage and invariants for the held-out test corpora.

**Offline only. Never copied into an agent-visible bundle.** It lives beside
oracle_contract.py and platform_contract.py for the same reason:
`scripts/stage_test_bundle.py` builds a stage bundle from a five-file allowlist
plus `suites/`, and this directory is reachable from neither.

Why a second corpus exists
--------------------------
Each suite already has a *visible* frozen corpus: the agent can read it, the
judge filters it by implemented flags, and its failures come back as repair
feedback. That measures whether a candidate can be driven to pass the cases it
was shown. It cannot measure generalisation, because the cases it is scored on
are the cases it could read.

The held-out corpus is the second pass. It is generated from the same ground
truth as the visible cases for that utility -- the pinned GNU binary for sort,
mkdir and grep; the specification model for chmod and for grep's ten
oracle-exempt cases -- and it is never shown to the agent, never copied into a
sandbox, and never fed back as repair feedback. `scripts/run_experiment.sh`
runs it once per attempt through `--extra-test-cmd`, after the repair loop has
finished.

The hidden-dual pattern
-----------------------
A held-out case is a *dual* of a visible one: same checkpoint, same cumulative
flag set, same structural shape, different concrete argument and fixture values.
That keeps the held-out pass measuring the same functional scope the checkpoint
declares, rather than quietly testing broader functionality and reporting the
difference as a generalisation failure. A dual records `dual_of` so the pairing
stays auditable.

Why the corpus lives outside `suites/`
--------------------------------------
`suites/` is exactly what the bundle copies. Anything placed there reaches the
sandbox at some checkpoint. The held-out corpus therefore lives in
`tests/<utility>-test-suite/heldout/`, which no allowlist entry names, and the
`extra_test_command` in each manifest reaches it by absolute path through
`$HELDOUT_ROOT` -- resolved by the controller, outside the working directory the
agent can see. `scripts/check_heldout_isolation.py` proves the separation holds
by building every checkpoint's bundle and searching its bytes.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# The directory name, per suite. Deliberately NOT "suites": that one is copied.
HELDOUT_DIRNAME = "heldout"
# Gzipped, like the visible suites and for the same reason. sort's held-out
# cases include megabyte-long single-line inputs; stored as raw base64 JSON that
# corpus is 78M, which has no business in a git history. Compressed it is a
# fraction of that, and `write()` pins the gzip mtime so identical content
# always produces identical bytes.
CORPUS_FILENAME = "heldout_cases.json.gz"

# Every held-out case name carries this prefix. It makes a leak unambiguous:
# the isolation checker can search bundle bytes for one token and know that any
# hit is a real exposure rather than a coincidental substring of a visible case.
NAME_PREFIX = "heldout-"

# Case fields that are metadata rather than case-identifying content, and so
# are NOT searched for. Every one of them is drawn from vocabulary the visible
# suite already uses, so scanning them would manufacture leaks rather than find
# them -- `dual_of` in particular names the VISIBLE case a held-out case was
# derived from, which is in the bundle by design.
#
# An exclusion list rather than an inclusion list on purpose: a suite that grows
# a new field gets scanned automatically, so the failure direction is "we
# checked something we did not need to" rather than "we silently stopped
# checking". Only the top level is excluded; a `path` nested inside `fixture`
# is still content and is still searched.
NON_IDENTIFYING_KEYS = frozenset({
    "dual_of", "group", "tags", "check", "schema", "stderr_class",
    "stdin_modes", "faults", "allow_signals", "env", "timeout", "umask",
    "exit_code", "nondet_exit", "rule_id", "flags", "absent_flags",
})

# Expected values shorter than this are not searched for during the leak scan.
# A one-byte expected stdout would match nearly any file and drown the signal;
# case names and fixture values carry the identifying information instead.
MIN_SCANNABLE_VALUE = 12


class HeldoutError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"heldout_contract: {message}")


def corpus_path(suite_root: Path) -> Path:
    return suite_root / HELDOUT_DIRNAME / CORPUS_FILENAME


def render(payload: dict[str, Any]) -> str:
    """Deterministic on-disk form, so a freshness check can compare content."""
    return json.dumps(payload, indent=1, sort_keys=True) + "\n"


def write(path: Path, text: str) -> None:
    """Write the rendered corpus, compressed and byte-reproducible.

    `mtime=0` matters: gzip stores a timestamp by default, so the same corpus
    written twice would differ in bytes and show up as a spurious diff on every
    regeneration.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))


def read(path: Path) -> str:
    """The rendered text of a corpus, whether it is compressed or not."""
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8")


def load(suite_root: Path) -> dict[str, Any]:
    path = corpus_path(suite_root)
    if not path.is_file():
        raise HeldoutError(f"no held-out corpus at {path}")
    try:
        data = json.loads(read(path))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HeldoutError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise HeldoutError(f"{path} must contain a JSON object")
    return data


def cases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(payload.get("cases") or [])


def fingerprint(payload: dict[str, Any]) -> str:
    material = {k: v for k, v in payload.items() if k != "corpus_fingerprint"}
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build(utility: str, provenance: dict[str, Any],
          held_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """A corpus in the suite's OWN case format, plus provenance.

    Deliberately the native shape -- `{"group": ..., "cases": [...]}` -- rather
    than a bespoke one. Every suite already ships a runner.py that loads exactly
    this and filters it by the cumulative `implemented` flag list, so the
    held-out pass reuses the suite's real judging path instead of a parallel
    implementation that could disagree with it. Per-checkpoint selection then
    falls out of the flag filtering that already exists.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "group": "heldout",
        "utility": utility,
        # Where the expected values came from, so a reader can tell an
        # oracle-derived case from a specification-model one without rerunning
        # anything.
        "provenance": provenance,
        "cases": held_cases,
        "total_cases": len(held_cases),
    }
    payload["corpus_fingerprint"] = fingerprint(payload)
    return payload


# ---------------------------------------------------------------------------
# Invariants -- the audit discipline the visible suites already apply
# ---------------------------------------------------------------------------


def case_invariants(case: dict[str, Any]) -> list[str]:
    """Properties that hold however a held-out case was produced."""
    problems: list[str] = []
    name = case.get("name")
    if not isinstance(name, str) or not name:
        return [f"case has no name: {case!r}"]
    if not name.startswith(NAME_PREFIX):
        problems.append(
            f"{name}: every held-out case name must start with "
            f"{NAME_PREFIX!r} so the isolation scan can identify a leak"
        )
    if not isinstance(case.get("args"), list):
        problems.append(f"{name}: 'args' must be a list")
    if not isinstance(case.get("flags"), list):
        problems.append(f"{name}: 'flags' must be a list")
    if "exit_code" not in case:
        problems.append(f"{name}: no expected exit_code")
    if not case.get("dual_of"):
        problems.append(
            f"{name}: no dual_of -- a held-out case must name the visible case "
            "whose structure and flags it mirrors"
        )
    return problems


def corpus_invariants(payload: dict[str, Any],
                      ladder: list[list[str]]) -> list[str]:
    """Whole-corpus properties, including the scope rule.

    `ladder` is the cumulative flag list of each checkpoint in order. A held-out
    case may only use flags some checkpoint introduces -- never a flag outside
    the ladder entirely -- and every checkpoint must end up with at least one
    case selected, or the hidden pass is silently empty there.
    """
    problems: list[str] = []
    seen: set[str] = set()
    every_flag = {flag for flags in ladder for flag in flags}

    for case in cases(payload):
        problems.extend(case_invariants(case))
        name = case.get("name", "<unnamed>")
        if name in seen:
            problems.append(f"duplicate held-out case name: {name}")
        seen.add(name)
        used = set(case.get("flags") or [])
        if not used <= every_flag:
            problems.append(
                f"{name}: uses {sorted(used - every_flag)}, which no checkpoint "
                "introduces; a held-out case must stay inside the ladder's "
                "functional scope"
            )

    # Selection mirrors the visible suites: a case runs once every flag it
    # lists is implemented. Checking it here means a corpus that would leave a
    # checkpoint with nothing to judge fails the audit rather than the run.
    for index, implemented in enumerate(ladder):
        selected = [
            case for case in cases(payload)
            if set(case.get("flags") or []) <= set(implemented)
        ]
        if not selected:
            problems.append(
                f"checkpoint {index} (implemented={implemented or '[]'}) "
                "selects no held-out cases"
            )

    recorded = payload.get("corpus_fingerprint")
    if recorded and recorded != fingerprint(payload):
        problems.append(
            "corpus_fingerprint does not match the corpus; regenerate it"
        )
    return problems


def scannable_values(case: dict[str, Any]) -> list[str]:
    """The strings a leak scan should look for in bundle bytes.

    The case name always, plus every string anywhere in the case long enough
    that a hit means exposure rather than coincidence.

    Structural rather than a list of key names, and deliberately so. Two
    versions of this function enumerated the keys they knew about, and both had
    the same defect: they were written against one suite's case shape and went
    quietly blind on another. The first knew chmod's and grep's keys, so for
    sort it searched the case NAME and nothing else -- it would have reported
    clean with the entire input payload sitting in the bundle. The second added
    `*_b64` but still missed mkdir's `tree` and `targets`, where that suite
    keeps its paths.

    A key-name allowlist has to be updated every time a suite grows a field,
    and nothing fails when it is not -- the scan just silently checks less. So
    this walks the whole case instead. A suite can add any field it likes and
    the guarantee still covers it.
    """
    values = [case["name"]]

    def walk(node: Any) -> None:
        # Top-level metadata is skipped by `walk`'s caller, not here.
        if isinstance(node, str):
            if len(node) >= MIN_SCANNABLE_VALUE:
                values.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    for key, value in case.items():
        # `_`-prefixed keys are this repo's convention for annotations kept
        # alongside a case -- sort's fuzz regressions carry `_reason` ("exit 1
        # vs GNU 0"), which the visible suite carries verbatim too.
        if key not in NON_IDENTIFYING_KEYS and not key.startswith("_"):
            walk(value)

    # Base64 payloads are searched decoded as well as encoded: a suite file
    # carries them in encoded form, but a fixture or a stray comment would
    # carry the bytes themselves. (sort stores inputs and expected outputs this
    # way because they contain NULs and deliberately invalid UTF-8.)
    for key, value in case.items():
        if not key.endswith("_b64") or not isinstance(value, str):
            continue
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            continue
        if len(raw) >= MIN_SCANNABLE_VALUE:
            values.append(raw.decode("utf-8", "surrogateescape"))
    return values
