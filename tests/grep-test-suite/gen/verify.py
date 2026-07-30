#!/usr/bin/env python3
"""Audit the frozen new_grep suite.

Three independent checks, all offline and all runnable on any platform (they
never execute a candidate):

  1. Freshness -- what is on disk is byte-identical to what gen/generate.py
     would write from the current case definitions and model.
  2. Invariants -- every frozen case satisfies reference_generators/grep_invariants.case_invariants(), which
     asserts properties that hold no matter how the golden was produced (exit
     status agrees with stdout, exit 2 carries a diagnostic, every emitted line
     really is a matching line of some input, declared flags match the options
     actually used).
  3. Checkpoint reachability -- each checkpoint's cumulative flag list selects
     at least one case that exercises its new feature, and selects every case
     the previous checkpoint selected.

Check 3 is what keeps the cumulative-filtering contract honest: without it a
mislabelled `flags` list could silently drop a checkpoint's coverage to zero and
the suite would still pass.

Usage:
  python3 gen/verify.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE_ROOT))
# The specification model and the model-dependent invariants live outside this
# suite, so they can never be copied into an experimental sandbox. Reaching them
# needs tests/ on the path, not the suite directory.
sys.path.insert(0, str(SUITE_ROOT.parent))

from reference_generators import grep_invariants as invariants  # noqa: E402
import runner  # noqa: E402
from gen import generate  # noqa: E402

# Must match experiments/utilities/grep.json. Duplicated deliberately: the suite
# has to be auditable on its own, and a divergence here is exactly the kind of
# drift this script exists to surface (see the manifest cross-check in
# tests/test_measure_diversity.py).
CHECKPOINTS = [
    ("000", []),
    ("001", ["-H"]),
    ("002", ["-H", "-h"]),
    ("003", ["-H", "-h", "-r"]),
    ("004", ["-H", "-h", "-r", "-i"]),
]


def load_frozen() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(SUITE_ROOT.glob("suites/*.json")):
        if path.name == "MANIFEST.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data["cases"]:
            case["_suite"] = path.name
            cases.append(case)
    return cases


def selected_names(cases: list[dict], implemented: list[str]) -> set[str]:
    manifest = {"implemented": implemented, "excluded_tags": [],
                "unimplemented_policy": "skip"}
    return {
        case["name"]
        for case in cases
        if runner.case_selected(case, manifest)[0]
    }


def check_premature_cases(cases: list[dict]) -> list[str]:
    """A case asserting a feature is absent must be live exactly until it isn't.

    It has to be selected at every checkpoint before its flag is introduced --
    otherwise nothing detects a candidate that built the whole ladder at 000 --
    and dropped at every checkpoint from that flag onward, where the feature is
    required and the same invocation must now succeed.
    """
    problems: list[str] = []
    for case in cases:
        absent = set(case.get("absent_flags") or [])
        if not absent:
            continue
        for checkpoint_id, implemented in CHECKPOINTS:
            selected = case["name"] in selected_names([case], implemented)
            expected = not (absent & set(implemented))
            if selected != expected:
                problems.append(
                    f"{case['name']}: requires {sorted(absent)} absent but is "
                    f"{'selected' if selected else 'not selected'} at "
                    f"checkpoint {checkpoint_id} (implemented={implemented})"
                )
    return problems


def main() -> int:
    problems: list[str] = []

    if generate_check() != 0:
        problems.append("suites/ is stale; run python3 gen/generate.py")

    cases = load_frozen()
    if not cases:
        problems.append("no frozen cases found under suites/")
        for line in problems:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    for case in cases:
        problems.extend(invariants.case_invariants(case))

    # Regression coverage must grow monotonically -- but only over cases that
    # assert a feature is PRESENT. A case asserting a feature is still absent is
    # meant to disappear at the checkpoint that introduces it, so including it
    # here would make the correct behavior look like lost coverage.
    premature = {
        case["name"] for case in cases if case.get("absent_flags")
    }
    problems.extend(check_premature_cases(cases))

    previous_names: set[str] = set()
    previous_id = None
    for checkpoint_id, implemented in CHECKPOINTS:
        names = selected_names(cases, implemented)
        if not names:
            problems.append(f"checkpoint {checkpoint_id} selects no cases")
        missing = (previous_names - names) - premature
        if missing:
            problems.append(
                f"checkpoint {checkpoint_id} stops selecting "
                f"{len(missing)} case(s) covered at {previous_id}: "
                f"{sorted(missing)[:3]}"
            )
        if previous_id is not None:
            added = names - previous_names
            if not added:
                problems.append(
                    f"checkpoint {checkpoint_id} adds no new coverage over "
                    f"{previous_id}"
                )
        print(f"  checkpoint {checkpoint_id}: {len(names)} cases selected "
              f"(implemented={implemented or '[]'})")
        previous_names, previous_id = names, checkpoint_id

    if problems:
        for line in problems:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print(f"\nOK: {len(cases)} frozen cases, all invariants hold")
    return 0


def generate_check() -> int:
    """Run generate.py's --check without re-entering its argument parser."""
    suites = generate.build_suites()
    payloads = {name: generate.render(data) for name, data in suites.items()}
    payloads["MANIFEST.json"] = generate.render(generate.manifest(suites))
    for name, text in payloads.items():
        path = generate.SUITE_DIR / name
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            return 1
    extra = [
        path.name
        for path in generate.SUITE_DIR.glob("*.json")
        if path.name not in payloads
    ]
    return 1 if extra else 0


if __name__ == "__main__":
    raise SystemExit(main())
