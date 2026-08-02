#!/usr/bin/env python3
"""Prove the held-out corpus never reaches a sandbox, at any checkpoint.

The held-out pass only measures generalisation if the agent could not read the
cases it is scored on. That is a claim about what `scripts/stage_test_bundle.py`
copies, so this checks the bundle itself rather than the intention behind it:
for every utility and every checkpoint, it builds the bundle payload in memory
and searches the bytes of every file that would land in the sandbox for any
held-out case name, input or expected value.

Checking the built payload rather than the source tree matters. The bundle is
not a copy of the suite directory -- it takes five allowlisted files, rewrites
config.json, and filters `suites/` per checkpoint -- so "the corpus is not in
suites/" is a weaker statement than "the corpus is in nothing the bundle
produces". A future allowlist entry, a stray file, or a case that quotes a
held-out value in a comment would all be caught here and by nothing else.

Exit status:
    0  no held-out material appears in any checkpoint's bundle
    1  a leak was found, named by utility, checkpoint, file and value
    2  the check could not run (missing corpus, unresolvable manifest)

Usage:
    python3 scripts/check_heldout_isolation.py                 # every utility
    python3 scripts/check_heldout_isolation.py --utility grep
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import lineage_plan  # noqa: E402
import stage_test_bundle  # noqa: E402
from reference_generators import heldout_contract  # noqa: E402


def suite_root(repo: Path, utility: str) -> Path:
    plan = lineage_plan.resolve_plan(repo, utility, "", "0", "build", 0, 0)
    return repo / plan["test_dir"], plan


def bundle_files(repo: Path, plan: dict[str, Any],
                 checkpoint: dict[str, Any]) -> dict[str, bytes]:
    """Exactly what this checkpoint's sandbox would contain."""
    payload = stage_test_bundle.build_payload(
        repo, plan["test_dir"], checkpoint, plan["utility"]
    )
    return payload["files"]


class NoCorpus(Exception):
    """This utility has no held-out corpus yet -- absence, not a leak."""


def scan_utility(repo: Path, utility: str) -> tuple[list[str], int, int]:
    """Returns (leaks, checkpoints_checked, values_searched)."""
    root, plan = suite_root(repo, utility)
    corpus_file = heldout_contract.corpus_path(root)
    if not corpus_file.is_file():
        raise NoCorpus(str(corpus_file))

    corpus = heldout_contract.load(root)
    needles: list[tuple[str, str]] = []
    for case in heldout_contract.cases(corpus):
        for value in heldout_contract.scannable_values(case):
            needles.append((case["name"], value))

    leaks: list[str] = []
    checked = 0
    for checkpoint in plan["checkpoints"]:
        files = bundle_files(repo, plan, checkpoint)
        checked += 1
        for filename, blob in files.items():
            for case_name, value in needles:
                if value.encode("utf-8", "surrogateescape") in blob:
                    leaks.append(
                        f"{utility} checkpoint {checkpoint['id']}: held-out "
                        f"case {case_name} leaked into bundle file "
                        f"{filename} (matched {value[:60]!r})"
                    )
    return leaks, checked, len(needles)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--utility", action="append", default=None,
                        help="check only this utility (repeatable)")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()

    utilities = args.utility or lineage_plan.available_utilities(repo)
    status = 0
    scanned = 0
    skipped: list[str] = []
    for utility in utilities:
        try:
            leaks, checked, needles = scan_utility(repo, utility)
        except NoCorpus:
            # Absence is not a failure: utilities are wired up one at a time,
            # and a missing corpus cannot leak.
            skipped.append(utility)
            continue
        except SystemExit as error:            # ManifestError / HeldoutError
            print(f"{utility}: cannot check -- {error}", file=sys.stderr)
            status = max(status, 2)
            continue
        if leaks:
            for leak in leaks:
                print(f"LEAK: {leak}", file=sys.stderr)
            status = 1
            continue
        scanned += 1
        print(f"{utility}: clean -- {needles} held-out values searched across "
              f"{checked} checkpoint bundles")

    if skipped:
        print(f"no held-out corpus yet (nothing to leak): {', '.join(skipped)}")
    if status == 0:
        print(f"\nheld-out isolation: {scanned} utilit"
              f"{'y' if scanned == 1 else 'ies'} verified"
              f"{' -- none reaches any sandbox' if scanned else ''}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
