#!/usr/bin/env python3
"""Freeze the held-out new_mkdir corpus into heldout/heldout_cases.json.gz.gz.

**Never copied into an agent-visible bundle.** `gen/` is outside
`scripts/stage_test_bundle.py`'s allowlist and `heldout/` is named by no
allowlist entry; `scripts/check_heldout_isolation.py` proves it by searching
every checkpoint's built bundle.

Scope: the bounded ladder, not the whole suite
----------------------------------------------
The visible corpus covers more of GNU mkdir than the `new_mkdir` experiment
asks for. The bounded ladder is base -> -p -> -m, so duals are drawn only from
visible cases whose flags fall inside `{-p, -m}`. A dual using `-v` would test
something no checkpoint introduces, and its failure would report a scope
mismatch as a generalisation failure.

How values change
-----------------
Path components are rewritten by a byte map that rotates within character class
and fixes everything else -- the same device sort's held-out generator uses, and
for the same reason: this corpus is largely generated (150-deep paths, hundreds
of operands), so a lexical table of literal names would never match it.
Rotation is length-preserving, which matters more here than anywhere else: `/`,
`.`, `-` and every byte >= 0x80 are fixed points, so path depth, the `..` and
`.` components, leading-dash operands and any case sitting exactly on a NAME_MAX
or PATH_MAX boundary all keep their meaning. A rename like `d0` -> `hd0` would
silently move those boundary cases off the boundary.

Modes are NOT rotated. They get an explicit table, because rotating digits can
produce an `8` or a `9` and would turn `-m 0644` into an invalid-mode parse
error -- a different case entirely. A mode with no dual is left unchanged and
reported; the dual still differs from its twin through its paths.

Requires the pinned GNU coreutils 9.11 mkdir, on Darwin (see the suite's
platform contract).

Usage:
  MKDIR_ORACLE_BIN=~/opt/coreutils-9.11/bin/mkdir python3 gen/heldout.py
  MKDIR_ORACLE_BIN=~/opt/coreutils-9.11/bin/mkdir python3 gen/heldout.py --check
  python3 gen/heldout.py --preview     # offline: show the duals, freeze nothing

Both generation and the freshness check need the oracle: every expectation here
comes from executing mkdir, so there is no offline model to check against.
`--preview` is the exception, and it deliberately produces no corpus.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE_ROOT))
sys.path.insert(0, str(SUITE_ROOT.parent))

from reference_generators import heldout_contract, oracle_contract  # noqa: E402

# `gen.freeze` is imported lazily, inside build_corpus. It pulls in engine.py,
# which imports the POSIX-only `resource` module -- so an eager import would
# make `--preview` unrunnable on any non-POSIX host, which is precisely where
# reviewing the duals without an oracle is most useful.

# The bounded new_mkdir ladder. Held-out cases never leave it.
LADDER_FLAGS = {"-p", "-m"}

# Modes, mapped by hand. Each dual keeps the *kind* of its twin: a valid octal
# stays a valid octal, a symbolic clause stays a symbolic clause of the same
# shape, and an invalid mode stays invalid in the same way.
MODE_DUALS = {
    "0111": "0222", "0644": "0640", "0700": "0705", "0755": "0750",
    "0777": "0707", "1777": "1707", "2755": "2750", "4755": "4750",
    "a-w": "a-r", "a=rx": "a=rw", "go-w": "go-r", "o+w": "o+r",
    "u+rwx": "g+rwx", "u=rwx,g=rx,o=": "u=rwx,g=rw,o=",
    "08": "09", "0999": "0888",
    # Left alone on purpose:
    #   "0000"  -- the zero-permission case; any dual stops being that case.
    #   "+t", "u+s", "g+s"  -- single special-bit forms with no same-shape twin.
    #   "8", "9", "u+z", ",", ""  -- malformed inputs whose exact text is the
    #                               point of the case.
}

UNMAPPED_MODES: set[str] = set()

# Fault keys whose value names a path in the case's own fixture, and so has to
# be rotated with it. Named explicitly rather than "rotate every string in
# faults": sort's fault block carries sentinels like `/dev/full`, `closed-pipe`
# and `missing` which are not fixture paths at all, and rotating one would
# produce a case about a device node that does not exist. mkdir's other faults
# are an int (`rlimit_nofile`) and a bool (`unwritable_cwd`).
PATH_VALUED_FAULTS = frozenset({"readonly_parent"})

# String-valued fault keys this generator does not know how to map. Any entry
# here is a hard failure rather than a shrug: `readonly_parent` was already
# copied through verbatim once while the fixture around it was rotated, so the
# engine made `ro` read-only, the dual had created `yv`, the parent stayed
# writable and `fault-readonly-parent` exited 0 where its twin exits 1.
UNMAPPED_FAULTS: set[str] = set()


def _rotation() -> bytes:
    """Rotate a-z, A-Z and 0-9 within class; fix every other byte."""
    table = bytearray(range(256))
    for base, size, shift in ((ord("a"), 26, 7), (ord("A"), 26, 7),
                              (ord("0"), 10, 5)):
        for index in range(size):
            table[base + index] = base + (index + shift) % size
    return bytes(table)


ROTATION = _rotation()


def dual_path(path: str) -> str:
    return path.encode("utf-8", "surrogateescape") \
               .translate(ROTATION).decode("utf-8", "surrogateescape")


def dual_mode(mode: str) -> str:
    if mode in MODE_DUALS:
        return MODE_DUALS[mode]
    UNMAPPED_MODES.add(mode)
    return mode


def dual_argv(args: list[str]) -> list[str]:
    """mkdir takes options, then operands, which are all paths.

    Positional, for the reason chmod's and sort's generators record: routing
    every token through one lookup lets an unmapped token fall into the wrong
    rule and silently change what the case is about. Here the specific hazard is
    `-m`'s argument, which must go to the mode table and never to the path map.
    """
    out: list[str] = []
    terminator = False
    want_mode = False
    for token in args:
        if want_mode:
            want_mode = False
            out.append(dual_mode(token))
            continue
        if not terminator and token == "--":
            terminator = True
            out.append(token)
            continue
        if not terminator and token.startswith("-") and len(token) > 1:
            if token == "-m" or token == "--mode":
                want_mode = True
                out.append(token)
            elif token.startswith("--mode="):
                out.append("--mode=" + dual_mode(token[len("--mode="):]))
            elif token.startswith("-m") and token != "-m":
                out.append("-m" + dual_mode(token[2:]))
            else:
                out.append(token)          # an option: part of the shape
            continue
        out.append(dual_path(token))
    return out


def dual_entry(entry: dict) -> dict:
    mapped = dict(entry)
    if isinstance(entry.get("path"), str):
        mapped["path"] = dual_path(entry["path"])
    if isinstance(entry.get("target"), str):
        mapped["target"] = dual_path(entry["target"])
    # `tree` records modes as ints (already parsed); `fixture` as octal strings.
    # Only the string form goes through the mode table.
    if isinstance(entry.get("mode"), str):
        mapped["mode"] = dual_mode(entry["mode"])
    return mapped


def dual_faults(faults: dict | None) -> dict | None:
    """Rotate the paths a fault block points at, so it still points at them."""
    if not faults:
        return faults
    mapped = dict(faults)
    for key, value in faults.items():
        if not isinstance(value, str):
            continue                      # ints and bools carry no path
        if key in PATH_VALUED_FAULTS:
            mapped[key] = dual_path(value)
        else:
            UNMAPPED_FAULTS.add(key)
    return mapped


def dual_preserve_mode(preserve: dict | None, fixture: list[dict] | None) -> dict | None:
    """Rotate a `preserve_mode` block, which is KEYED by path.

    Easy to miss, and missing it is silent: this case asserts that `-p -m` on an
    existing directory leaves its mode alone. Rotate the fixture and argv while
    leaving this behind, and the assertion names a path the dual never creates,
    so the one thing the case exists to check is simply not checked -- and the
    exit code stays 0, so the outcome guard sees nothing wrong.

    The value is the mode the directory should still have afterwards, so it has
    to agree with the (already mapped) fixture entry for the same path.
    """
    if not preserve:
        return preserve
    modes = {entry["path"]: entry.get("mode") for entry in (fixture or [])}
    mapped = {}
    for path, expected in preserve.items():
        held_path = dual_path(path)
        held_mode = dual_mode(expected) if isinstance(expected, str) else expected
        fixture_mode = modes.get(held_path)
        if isinstance(fixture_mode, str) and fixture_mode != held_mode:
            raise RuntimeError(
                f"preserve_mode for {held_path} says {held_mode} but its "
                f"fixture entry says {fixture_mode}; the two mode tables have "
                f"drifted apart"
            )
        mapped[held_path] = held_mode
    return mapped


def visible_cases() -> list[dict]:
    """Frozen visible cases that fall inside the bounded ladder."""
    found: list[dict] = []
    for path in sorted((SUITE_ROOT / "suites").iterdir()):
        if path.name == "MANIFEST.json" or path.suffix not in (".json", ".gz"):
            continue
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
        cases = data["cases"] if isinstance(data, dict) and "cases" in data else data
        for case in cases:
            if set(case.get("flags") or []) <= LADDER_FLAGS:
                found.append(case)
    return found


def select(cases: list[dict]) -> list[dict]:
    """One dual per (flags, check-kind, tag-shape) family."""
    chosen: list[dict] = []
    seen: set[tuple] = set()
    for case in cases:
        key = (tuple(sorted(case.get("flags") or [])),
               case.get("check"),
               tuple(sorted(t for t in case.get("tags") or [])))
        if key in seen:
            continue
        seen.add(key)
        chosen.append(case)
    return chosen


def dual_of(case: dict) -> dict:
    held = {
        key: value for key, value in case.items()
        # Everything derived by the oracle is dropped and re-derived.
        if key not in ("exit_code", "stdout_b64", "stderr_b64", "stderr_class")
    }
    held["name"] = heldout_contract.NAME_PREFIX + case["name"]
    held["args"] = dual_argv(case["args"])
    for key in ("tree", "fixture"):
        if case.get(key):
            held[key] = [dual_entry(entry) for entry in case[key]]
    if case.get("targets"):
        held["targets"] = [dual_path(target) for target in case["targets"]]
    # Both of these REFERENCE paths the rotation just renamed. Leaving either
    # behind leaves the case pointing at something the dual never creates.
    if case.get("faults"):
        held["faults"] = dual_faults(case["faults"])
    if case.get("preserve_mode"):
        held["preserve_mode"] = dual_preserve_mode(
            case["preserve_mode"], held.get("fixture"))
    held["tags"] = list(case.get("tags") or []) + ["heldout"]
    return held


def build_duals() -> list[tuple[dict, dict]]:
    """(visible, dual) pairs, with the identity check applied."""
    pairs = []
    for case in select(visible_cases()):
        held = dual_of(case)
        # A dual that did not actually change is not held out: its values are in
        # the agent's bundle, and it measures nothing the visible pass did not.
        if held["args"] == case["args"] and held.get("tree") == case.get("tree"):
            raise RuntimeError(
                f"{held['name']} is identical to {case['name']}: nothing in it "
                f"is affected by the rotation or the mode table")
        pairs.append((case, held))
    if UNMAPPED_FAULTS:
        raise RuntimeError(
            f"fault keys with a string value this generator does not know how "
            f"to map: {sorted(UNMAPPED_FAULTS)}. If the value names a path in "
            f"the case's fixture, add it to PATH_VALUED_FAULTS so it is "
            f"rotated with the fixture; if it is a sentinel, add it to the "
            f"comment there saying so."
        )
    return pairs


def build_corpus(mkdir_bin: str) -> dict:
    from gen import freeze                       # POSIX-only; see note above

    held_cases = []
    for case, held in build_duals():
        frozen = freeze.freeze_case(held, mkdir_bin=mkdir_bin)
        frozen["dual_of"] = case["name"]
        # The strongest invariant available without re-deriving the case by
        # hand: a dual walks the same path with different values, so a
        # different outcome means the substitution changed what the case is
        # about. grep's corpus had eight duals silently flip their exit code --
        # a mapped pattern searching unmapped file bodies -- and every
        # individual step had done exactly what it was told.
        if "exit_code" in case and "exit_code" in frozen \
                and case["exit_code"] != frozen["exit_code"]:
            raise RuntimeError(
                f"{frozen['name']} exits {frozen['exit_code']} but its twin "
                f"{case['name']} exits {case['exit_code']}: the dual is no "
                f"longer the same kind of case. Check that every path and "
                f"every mode it touches has a mapping."
            )
        held_cases.append(frozen)
    return heldout_contract.build(
        "mkdir",
        {
            "ground_truth": "GNU coreutils mkdir (see mkdir_version in suites/MANIFEST.json)",
            "kind": "oracle",
            "derived_by": "gen/freeze.py:freeze_case",
            "note": ("Drawn only from visible cases inside the bounded ladder "
                     "(-p, -m); the suite covers more of GNU mkdir than the "
                     "experiment asks for."),
        },
        held_cases,
    )


def preview() -> int:
    """Show what the duals would be, without an oracle and without writing."""
    pairs = build_duals()
    print(f"{len(pairs)} duals would be generated\n")
    for case, held in pairs[:12]:
        print(f"  {case['name']}\n    {case['args']}\n"
              f"  -> {held['name']}\n    {held['args']}")
    if len(pairs) > 12:
        print(f"  ... and {len(pairs) - 12} more")
    if UNMAPPED_MODES:
        print(f"\nmodes left unchanged: {sorted(UNMAPPED_MODES)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="do not write; fail when the corpus is stale")
    parser.add_argument("--preview", action="store_true",
                        help="offline: print the duals and exit")
    parser.add_argument("--mkdir-bin", default=None)
    args = parser.parse_args(argv)

    if args.preview:
        return preview()

    config = SUITE_ROOT / "config.json"
    mkdir_bin = oracle_contract.resolve("mkdir", config, args.mkdir_bin)
    problems = oracle_contract.verify("mkdir", SUITE_ROOT, mkdir_bin, config)
    if problems:
        for problem in problems:
            print(f"oracle_contract: {problem}", file=sys.stderr)
        return 2

    corpus = build_corpus(mkdir_bin)
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
    if UNMAPPED_MODES:
        print(f"  modes left unchanged: {sorted(UNMAPPED_MODES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
