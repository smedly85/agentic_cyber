#!/usr/bin/env python3
"""Freeze the held-out new_sort corpus into heldout/heldout_cases.json.gz.gz.

**Never copied into an agent-visible bundle.** `gen/` is outside
`scripts/stage_test_bundle.py`'s allowlist and `heldout/` is named by no
allowlist entry; `scripts/check_heldout_isolation.py` proves it by searching
every checkpoint's built bundle.

Scope: the bounded ladder, not the whole suite
----------------------------------------------
This suite's visible corpus is 1065 cases covering far more of GNU sort than
the `new_sort` experiment asks for -- `-n`, `-k`, `-t`, `-o`, `-m`, `--sort`
and more. The bounded ladder is base -> -r -> -f -> -u -> -c, and only 69
visible cases fall inside it. A held-out case must exercise the same functional
scope as its checkpoint, so duals are drawn only from those 69; a dual using
`-k` would be testing something no checkpoint introduces and would report the
scope mismatch as a generalisation failure.

Duals are built from the FROZEN visible cases rather than from
`gen/curated_cases.py`, because sort's case definitions are assembled from
corpus generators whose inputs are chosen per flag. Taking the frozen case and
substituting its input payload keeps the structural shape exactly -- same argv,
same flags, same stdin mode, same fault configuration -- while changing the
data the candidate actually sorts. Expected values are then re-derived by
`gen/freeze.py:freeze_case`, the same function and the same pinned oracle the
visible corpus uses.

Requires the pinned GNU coreutils 9.11 sort on Darwin, the suite's frozen
platform. The visible Darwin corpus omits the Linux-only fault-devfull case.

Usage:
  SORT_ORACLE_BIN=~/opt/cu-9.11/bin/sort python3 gen/heldout.py
  SORT_ORACLE_BIN=~/opt/cu-9.11/bin/sort python3 gen/heldout.py --check

Both modes need the oracle: every expectation here comes from executing sort,
so there is no offline model to check against.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import subprocess
import sys
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE_ROOT))
sys.path.insert(0, str(SUITE_ROOT.parent))
sys.path.insert(0, str(SUITE_ROOT / "gen"))

from reference_generators import (  # noqa: E402
    heldout_contract,
    oracle_contract,
    platform_contract,
)
# The bounded new_sort ladder. Held-out cases never leave it.
LADDER_FLAGS = {"-r", "-f", "-u", "-c"}


def _rotation() -> bytes:
    """A byte map that rotates within character class and fixes everything else.

    Not a lookup table of literal strings. An earlier version substituted whole
    lines from a hand-written dictionary and 14 of 24 duals came out
    byte-identical to their visible twin -- sort's corpus is largely *generated*
    (megabyte-long runs of one character, numeric discriminator sets, fuzz
    seeds), so a lexical table never matches it. Identical duals are worse than
    useless: they measure no generalisation and their bytes really are in the
    agent's bundle.

    Rotating within class preserves every structural property these cases were
    built to probe:

      * lower and upper rotate by the SAME amount, so two lines that were
        case-variants of each other still are -- which is the whole point of the
        `-f` checkpoint.
      * the map is a function, so duplicate lines stay duplicate and distinct
        lines stay distinct -- which is what `-u` and the tie cases probe.
      * tabs, spaces, punctuation, NUL and every byte >= 0x80 are fixed points,
        so field structure, blank lines, line lengths and deliberately invalid
        UTF-8 survive unchanged.
    """
    table = bytearray(range(256))
    for base, size, shift in ((ord("a"), 26, 7), (ord("A"), 26, 7),
                              (ord("0"), 10, 5)):
        for index in range(size):
            table[base + index] = base + (index + shift) % size
    return bytes(table)


ROTATION = _rotation()


def dual_payload(raw: bytes) -> bytes:
    return raw.translate(ROTATION)


def realign(raw: bytes, case: dict, sort_bin: str) -> bytes:
    """Re-order a dual whose visible twin asserts that its input is ordered.

    Rotation is not order-preserving -- it cannot be, since the only
    order-preserving permutation of a finite ordered alphabet onto itself is the
    identity. That is harmless for every case except check mode: a `-c` case
    whose twin exits 0 exists to assert that ALREADY-SORTED input is accepted,
    and a dual that exits 1 instead would have quietly become a case about
    rejection. Running the pinned oracle with the same argv minus the check flag
    restores the ordered-input property with the rotated bytes.
    """
    args = [a for a in case["args"]
            if a not in ("-c", "-C", "--check", "--check=quiet",
                         "--check=silent", "--check=diagnose-first")]
    result = subprocess.run([sort_bin, *args], input=raw,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"cannot realign {case['name']}: sort exited "
                           f"{result.returncode}")
    return result.stdout


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
        # A case whose input we cannot vary would be a duplicate of its twin.
        if not case.get("stdin_b64"):
            continue
        key = (tuple(sorted(case.get("flags") or [])),
               case.get("check"),
               tuple(sorted(t for t in case.get("tags") or [])))
        if key in seen:
            continue
        seen.add(key)
        chosen.append(case)
    return chosen


def dual_of(case: dict, sort_bin: str) -> dict:
    held = {
        key: value for key, value in case.items()
        # Everything derived by the oracle is dropped and re-derived.
        if key not in ("exit_code", "stdout_b64", "stderr_b64", "stderr_class",
                       "outfile_b64")
    }
    held["name"] = heldout_contract.NAME_PREFIX + case["name"]
    raw = dual_payload(base64.b64decode(case["stdin_b64"]))
    check_mode = any(a in ("-c", "-C", "--check") or a.startswith("--check=")
                     for a in case["args"])
    if check_mode and case.get("exit_code") == 0:
        raw = realign(raw, case, sort_bin)
    held["stdin_b64"] = base64.b64encode(raw).decode("ascii")
    held["tags"] = list(case.get("tags") or []) + ["heldout"]
    return held


def build_corpus(sort_bin: str) -> dict:
    from gen import freeze

    held_cases = []
    for case in select(visible_cases()):
        held = dual_of(case, sort_bin)
        # A dual that did not actually change is not held out: its bytes are in
        # the agent's bundle, and it measures nothing the visible pass did not.
        if held["stdin_b64"] == case["stdin_b64"]:
            raise RuntimeError(
                f"{held['name']} is byte-identical to {case['name']}: its "
                f"input contains nothing the rotation changes")
        frozen = freeze.freeze_case(held, sort_bin=sort_bin)
        frozen["dual_of"] = case["name"]
        # A different outcome means the rotation changed what the case is
        # about, not just its data. grep's corpus had eight duals flip their
        # exit code this way before the check existed.
        if "exit_code" in case and "exit_code" in frozen \
                and case["exit_code"] != frozen["exit_code"]:
            raise RuntimeError(
                f"{frozen['name']} exits {frozen['exit_code']} but its twin "
                f"{case['name']} exits {case['exit_code']}: the dual is no "
                f"longer the same kind of case."
            )
        held_cases.append(frozen)
    return heldout_contract.build(
        "sort",
        {
            "ground_truth": "GNU coreutils sort (see sort_version in suites/MANIFEST.json)",
            "kind": "oracle",
            "derived_by": "gen/freeze.py:freeze_case",
            "note": ("Drawn only from visible cases inside the bounded ladder "
                     "(-r, -f, -u, -c); the suite covers far more of GNU sort "
                     "than the experiment asks for."),
        },
        held_cases,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--sort-bin", default=None)
    args = parser.parse_args(argv)

    config = SUITE_ROOT / "config.json"
    platform_problems = platform_contract.check(config, "sort")
    if platform_problems:
        for problem in platform_problems:
            print(problem, file=sys.stderr)
        return 2
    sort_bin = oracle_contract.resolve("sort", config, args.sort_bin)
    # Verified for --check too, unlike chmod's and grep's generators. Those can
    # re-derive expectations from a model offline; every sort expectation comes
    # from executing the binary, so a freshness check run against an unpinned
    # sort would report a version difference as a stale corpus.
    problems = oracle_contract.verify("sort", SUITE_ROOT, sort_bin, config)
    if problems:
        for problem in problems:
            print(f"oracle_contract: {problem}", file=sys.stderr)
        return 2

    corpus = build_corpus(sort_bin)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
