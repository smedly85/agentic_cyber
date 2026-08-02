#!/usr/bin/env python3
"""Freeze the held-out new_chmod corpus into heldout/heldout_cases.json.

**Never copied into an agent-visible bundle.** `gen/` is outside
`scripts/stage_test_bundle.py`'s allowlist, and the corpus it writes lives in
`heldout/`, which no allowlist entry names. `scripts/check_heldout_isolation.py`
proves that by searching every checkpoint's built bundle.

The hidden-dual pattern
-----------------------
Each held-out case is a dual of a visible one: the same checkpoint, the same
cumulative flag list, the same structural shape, different concrete values. A
dual of `base-octal-three-digits` (`chmod 644 f`, starting 0600) is
`heldout-base-octal-three-digits` (`chmod 751 hf`, starting 0640). That keeps
the hidden pass measuring the same functional scope the checkpoint declares --
if it tested broader behavior, a failure would report a scope mismatch as a
generalisation failure.

Ground truth comes from the same place the visible cases get it:
`gen/generate.py:freeze_case`, which derives every expected value from
`tests/reference_generators/chmod_reference.py`. There is no second
implementation of the contract to drift from the first.

Usage:
  python3 gen/heldout.py            # rewrite heldout/heldout_cases.json
  python3 gen/heldout.py --check    # fail if it is stale
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

# How a visible case becomes its dual. Every substitution keeps the *kind* of
# value identical -- an octal mode stays an octal mode, a symbolic clause stays
# a symbolic clause of the same shape -- so the dual exercises the same code
# path with different data.
MODE_DUALS = {
    "644": "751", "755": "700", "700": "705", "600": "640", "640": "604",
    "4755": "2750", "1777": "3711", "0": "0", "0700": "0605", "0644": "0641",
    "777": "707", "444": "440", "666": "606", "555": "500", "711": "744",
    "u+x": "g+w", "+x": "+r", "a+w": "a+r", "u+w": "o+x", "g+x": "u+r",
    "a+X": "a+X", "u=rw": "g=rx", "o=": "g=", "go-rwx": "uo-rwx",
    "a=rx": "a=rw", "u-w": "g-r", "a-x": "a-w", "ug+rw": "go+rx",
}

# Fixture paths, renamed so no held-out identifier collides with a visible one.
PATH_DUALS = {"f": "hf", "d": "hd", "empty": "hempty", "link": "hlink",
              "nope": "hnope", "locked": "hlocked"}

# Starting modes, so the dual begins from a different departure point.
START_MODE_DUALS = {"0644": "0640", "0755": "0705", "0600": "0604",
                    "0000": "0000", "0444": "0404", "0777": "0770",
                    "0700": "0710", "4755": "2755", "1777": "1707"}


UNMAPPED_MODES: set[str] = set()


def dual_argv(args: list[str]) -> list[str]:
    """Map argv positionally: chmod takes MODE first, then operands.

    Positional rather than by-lookup on purpose. An earlier version mapped each
    token through the mode table and fell back to the path rule, which silently
    rewrote the unmapped symbolic mode `uuu+x` into the path-like `huuu+x` --
    turning a case about repeated class letters into a case about an invalid
    mode. A mode with no dual is left unchanged instead; the dual still differs
    from its visible twin through the fixture, and the substitution can never
    change what the case is about.
    """
    out: list[str] = []
    seen_mode = False
    terminator = False
    for token in args:
        if not terminator and token == "--":
            terminator = True
            out.append(token)
            continue
        if not terminator and token.startswith("-") and not seen_mode and len(token) > 1 \
                and not token.lstrip("-").startswith(("r", "w", "x", "X")):
            out.append(token)             # an option: part of the shape
            continue
        if not seen_mode:
            seen_mode = True
            if token in MODE_DUALS:
                out.append(MODE_DUALS[token])
            else:
                UNMAPPED_MODES.add(token)
                out.append(token)
            continue
        out.append(dual_path(token))
    return out


def dual_path(path: str) -> str:
    head, sep, tail = path.partition("/")
    mapped = PATH_DUALS.get(head, f"h{head}" if head else head)
    return f"{mapped}{sep}{tail}" if sep else mapped


def dual_fixture(fixture: list[dict] | None) -> list[dict] | None:
    if fixture is None:
        return None
    out = []
    for entry in fixture:
        mapped = dict(entry)
        mapped["path"] = dual_path(entry["path"])
        if "mode" in entry:
            mapped["mode"] = START_MODE_DUALS.get(entry["mode"], entry["mode"])
        if entry["type"] == "symlink":
            mapped["target"] = dual_path(entry["target"])
        out.append(mapped)
    return out


def dual_of(definition: dict) -> dict:
    """The held-out twin of one visible case definition."""
    held = dict(definition)
    held["name"] = heldout_contract.NAME_PREFIX + definition["name"]
    held["args"] = dual_argv(definition["args"])
    held["fixture"] = dual_fixture(definition.get("fixture"))
    held["tags"] = list(definition.get("tags") or []) + ["heldout"]
    return held


def select(definitions: list[dict]) -> list[dict]:
    """A representative subset: every distinct (flags, tag-shape) combination.

    Not every visible case -- the held-out pass is a generalisation probe, not a
    second full corpus -- but at least one dual per structural family per
    checkpoint, so no family goes unmeasured.
    """
    chosen: list[dict] = []
    seen: set[tuple] = set()
    for definition in definitions:
        # A case asserting a flag is NOT yet implemented is a statement about
        # the checkpoint ladder, not about behavior; its dual would assert the
        # same thing twice and add no generalisation signal.
        if definition.get("absent_flags"):
            continue
        key = (tuple(sorted(definition.get("flags") or [])),
               tuple(sorted(t for t in definition.get("tags") or []
                            if t not in ("heldout",))))
        if key in seen:
            continue
        seen.add(key)
        chosen.append(definition)
    return chosen


def build_corpus() -> dict:
    held_cases = []
    for group, definitions in curated_cases.GROUPS.items():
        for definition in select(definitions):
            held = dual_of(definition)
            frozen = generate.freeze_case(held)
            frozen["dual_of"] = definition["name"]
            frozen["group"] = group
            held_cases.append(frozen)
    return heldout_contract.build(
        "chmod",
        {
            "ground_truth": "tests/reference_generators/chmod_reference.py",
            "kind": "specification model",
            "derived_by": "gen/generate.py:freeze_case",
            "note": "chmod has no oracle binary; the model is the contract.",
        },
        held_cases,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="do not write; fail when the corpus is stale")
    args = parser.parse_args(argv)

    corpus = build_corpus()
    text = heldout_contract.render(corpus)
    path = heldout_contract.corpus_path(SUITE_ROOT)

    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            print(f"stale: {path}", file=sys.stderr)
            return 1
        print(f"held-out corpus is up to date ({corpus['total_cases']} cases)")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {corpus['total_cases']} held-out cases to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
