#!/usr/bin/env python3
"""Freeze the held-out new_grep corpus into heldout/heldout_cases.json.gz.gz.

**Never copied into an agent-visible bundle.** `gen/` is outside
`scripts/stage_test_bundle.py`'s allowlist and `heldout/` is named by no
allowlist entry; `scripts/check_heldout_isolation.py` proves it by searching
every checkpoint's built bundle.

Ground truth, split the same way the visible corpus splits it
---------------------------------------------------------------
grep's visible corpus is a hybrid: 78 cases derive from a real GNU grep and 10
from the specification model, because those ten assert which options `new_grep`
*rejects* -- a property of the bounded utility, not of fixed-string matching,
which no real grep can produce. The held-out corpus inherits that split by
calling the same `gen/generate.py:freeze_case`, which consults
`gen/oracle.py:model_only_reason` per case.

Duals of the ten model-only cases are deliberately NOT generated. They assert
that `-H` is an unknown option before its checkpoint; a dual would assert the
same thing about the same option with a different pattern string and add no
generalisation signal, while inflating the corpus with cases that cannot fail
for an interesting reason.

Because the non-exempt cases need the pinned oracle, this must run where a
fit GNU grep 3.12 exists -- the same requirement `gen/generate.py` already has,
enforced by the same `oracle_contract` version check and `gen/oracle.py`
behavioral precheck.

Usage:
  GREP_ORACLE_BIN=/usr/bin/grep python3 gen/heldout.py
  python3 gen/heldout.py --check      # offline; no oracle needed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE_ROOT))
sys.path.insert(0, str(SUITE_ROOT.parent))

from reference_generators import heldout_contract  # noqa: E402
from gen import curated_cases, generate  # noqa: E402
from gen import oracle as oracle_module  # noqa: E402

# Pattern duals. Each keeps the *kind* of pattern identical -- a literal stays
# literal, a regex-metacharacter probe still probes metacharacters, an empty
# pattern stays empty -- so the dual exercises the same matching path.
PATTERN_DUALS = {
    "alpha": "delta", "beta": "gamma", "a": "e", "zeta": "omega",
    "gamma": "sigma", "Gamma": "Sigma", "needle": "marker",
    "alphabetical": "deltaesque", "": "",
    "a.c": "x.z", "[abc]": "[xyz]", "[ABC]": "[XYZ]",
    "key": "tag", "ALPHA": "DELTA", "aLpHa": "dElTa", "GAMMA": "SIGMA",
    "BETA": "OMEGA", "NEEDLE": "MARKER", "COLE": "RENE", "omega": "kappa",
    "-alpha": "-delta",
}

# Fixture and operand names, so no held-out identifier collides with a visible
# one and the isolation scan stays unambiguous.
PATH_DUALS = {"a.txt": "ha.txt", "b.txt": "hb.txt", "c.txt": "hc.txt",
              "nope.txt": "hnope.txt", "locked.txt": "hlocked.txt",
              "top.txt": "htop.txt", "t": "ht", "empty": "hempty",
              "outer": "houter", "link": "hlink", "d": "hd"}

# Stdin payloads. Different bytes, same structure: same line count, same
# presence or absence of a trailing newline, same NUL and high-byte content.
STDIN_DUALS = {
    b"alpha\nbeta\nGamma\ndelta alpha\n": b"delta\ngamma\nSigma\nkappa delta\n",
    b"beta only\nnothing here\n": b"gamma only\nabsent here\n",
    b"Alpha\nALPHA\nalpha\naLpHa\n": b"Delta\nDELTA\ndelta\ndElTa\n",
    b"first needle\nsecond needle": b"first marker\nsecond marker",
    b"needle here\r\nplain\r\n": b"marker here\r\nquiet\r\n",
    b"pre\x00needle\x00post\nplain\n\xff\xfeneedle\n":
        b"pre\x00marker\x00post\nquiet\n\xff\xfemarker\n",
    b"abc\na.c\nxaycz\n": b"xyz\nx.z\npxqzr\n",
    b"[abc]\nabc\n{abc}\n": b"[xyz]\nxyz\n{xyz}\n",
    b"[abc]\n{abc}\nABC\n": b"[xyz]\n{xyz}\nXYZ\n",
    b"aa\nb\n": b"ee\nf\n",
    b"\n\nx\n": b"\n\ny\n",
    b"\xc3\x89cole\n\xc3\xa9COLE\nplain\n": b"\xc3\x89lan\n\xc3\xa9LAN\nquiet\n",
    b"key:value\nother\n": b"tag:value\nspare\n",
    b"x-alpha\ny\n": b"x-delta\nz\n",
}

UNMAPPED: dict[str, set] = {"patterns": set(), "stdin": set()}


def dual_path(path: str) -> str:
    head, sep, tail = path.partition("/")
    mapped = PATH_DUALS.get(head, f"h{head}" if head else head)
    return f"{mapped}{sep}{tail}" if sep else mapped


def dual_argv(args: list[str]) -> list[str]:
    """grep takes options, then PATTERN, then operands.

    Positional, for the reason chmod's generator records: mapping every token
    through one table lets an unmapped pattern fall into the path rule and
    silently change what the case is about. An unmapped pattern is left alone
    instead -- the dual still differs through its stdin or fixture.
    """
    out: list[str] = []
    seen_pattern = False
    terminator = False
    for token in args:
        if not terminator and token == "--":
            terminator = True
            out.append(token)
            continue
        if not terminator and not seen_pattern and token.startswith("-") \
                and len(token) > 1:
            out.append(token)                    # an option: part of the shape
            continue
        if not seen_pattern:
            seen_pattern = True
            if token in PATTERN_DUALS:
                out.append(PATTERN_DUALS[token])
            else:
                UNMAPPED["patterns"].add(token)
                out.append(token)
            continue
        out.append(dual_path(token))
    return out


def dual_fixture(fixture: list[dict] | None) -> list[dict] | None:
    if fixture is None:
        return None
    out = []
    for entry in fixture:
        mapped = dict(entry)
        mapped["path"] = dual_path(entry["path"])
        if entry.get("type") == "symlink":
            mapped["target"] = dual_path(entry["target"])
        contents = entry.get("contents")
        if isinstance(contents, bytes):
            mapped["contents"] = STDIN_DUALS.get(contents, contents)
            if contents not in STDIN_DUALS:
                UNMAPPED["stdin"].add(repr(contents)[:40])
        out.append(mapped)
    return out


def dual_of(definition: dict) -> dict:
    held = dict(definition)
    held["name"] = heldout_contract.NAME_PREFIX + definition["name"]
    held["args"] = dual_argv(definition["args"])
    if definition.get("fixture") is not None:
        held["fixture"] = dual_fixture(definition["fixture"])
    stdin = definition.get("stdin")
    if stdin is not None:
        held["stdin"] = STDIN_DUALS.get(stdin, stdin)
        if stdin not in STDIN_DUALS:
            UNMAPPED["stdin"].add(repr(stdin)[:40])
    held["tags"] = list(definition.get("tags") or []) + ["heldout"]
    return held


def select(definitions: list[dict]) -> list[dict]:
    """One dual per structural family per checkpoint.

    Model-only cases are skipped: they assert which options new_grep rejects,
    which is a statement about the bounded option set rather than about
    matching, so a dual would restate it without adding generalisation signal.
    """
    chosen: list[dict] = []
    seen: set[tuple] = set()
    for definition in definitions:
        if oracle_module.model_only_reason(definition):
            continue
        key = (tuple(sorted(definition.get("flags") or [])),
               tuple(sorted(t for t in definition.get("tags") or [])))
        if key in seen:
            continue
        seen.add(key)
        chosen.append(definition)
    return chosen


def build_corpus(oracle_bin: str | None) -> dict:
    held_cases = []
    for group, definitions in curated_cases.GROUPS.items():
        for definition in select(definitions):
            held = dual_of(definition)
            frozen = generate.freeze_case(held, oracle_bin)
            frozen["dual_of"] = definition["name"]
            frozen["group"] = group
            held_cases.append(frozen)
    return heldout_contract.build(
        "grep",
        {
            "ground_truth": "GNU grep (see grep_version in suites/MANIFEST.json)",
            "kind": "oracle, with the specification model for exempt cases",
            "derived_by": "gen/generate.py:freeze_case",
            "note": ("Duals of the ten oracle-exempt argument-grammar cases "
                     "are not generated; they assert which options new_grep "
                     "rejects, not how it matches."),
        },
        held_cases,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="do not write; fail when the corpus is stale")
    parser.add_argument("--oracle-bin", default=None)
    args = parser.parse_args(argv)

    # --check is offline and model-derived, exactly like generate.py --check:
    # freezing refuses to write unless model and oracle agreed, so a difference
    # found offline is a difference from the oracle too.
    oracle_bin = None if args.check else generate.resolve_oracle(args.oracle_bin)
    corpus = build_corpus(oracle_bin)
    text = heldout_contract.render(corpus)
    path = heldout_contract.corpus_path(SUITE_ROOT)

    if args.check:
        if not path.is_file() or heldout_contract.read(path) != text:
            print(f"stale: {path}", file=sys.stderr)
            return 1
        print(f"held-out corpus is up to date ({corpus['total_cases']} cases)")
        return 0

    heldout_contract.write(path, text)
    print(f"wrote {corpus['total_cases']} held-out cases to {path}")
    if UNMAPPED["patterns"]:
        print(f"  patterns left unchanged: {sorted(UNMAPPED['patterns'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
