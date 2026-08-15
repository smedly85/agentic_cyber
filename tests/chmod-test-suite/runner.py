#!/usr/bin/env python3
"""
Runner: judge a candidate new_chmod binary against frozen golden suites.

Consumes the schema-v1 suite JSON written by gen/generate.py through the shared
engine.py, so the candidate runs under the same fixture, argv and environment
conditions the goldens were derived under.

  - bytes I/O for stdout (report lines are compared exactly)
  - **resulting file modes compared against the golden tree**, which is the
    point of a chmod suite: correct output with the wrong bits on disk is a
    failure, and so is the reverse
  - config-driven flag filtering: only run cases whose flags are implemented
    (see config.json / config.py -- no path or flag list is hardcoded here)
  - crash/sanitizer/timeout classified distinctly from wrong-output
  - stderr matched by class (empty/nonempty) plus an optional regex, because the
    prompts specify which conditions are diagnosed rather than the exact wording
  - parallel across cases
  - suite files may be plain .json or gzipped .json.gz, transparently

Usage:
  runner.py suites/*.json --config config.json -- ./my-chmod
  runner.py suites/*.json --config config.json --sanitizer -- ./my-chmod-asan
  runner.py suites/*.json --all-flags -- ./my-chmod      # ignore the filter
"""
from __future__ import annotations

import argparse
import base64
import glob
import gzip
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import engine
import props

# --- verdict severities (higher = worse; drives exit code + reporting) ------
PASS = "PASS"
SKIP = "SKIP"
XFAIL = "XFAIL"
FAIL = "FAIL"
TIMEOUT = "TIMEOUT"
SANITIZER = "SANITIZER"
CRASH = "CRASH"

SEVERITY = {PASS: 0, SKIP: 0, XFAIL: 0,
            FAIL: 1, TIMEOUT: 2, SANITIZER: 3, CRASH: 4}
FAILING = {FAIL, TIMEOUT, SANITIZER, CRASH}


def case_result_id(case: dict, executed_name: str) -> str:
    """Stable identity for one frozen case variant and invocation mode."""
    return (
        f"{case.get('_suite', '?')}::"
        f"{int(case['_case_ordinal']):06d}::{executed_name}"
    )


def load_manifest(path: str | None, all_flags: bool) -> dict:
    """Load the flag/tag-filtering manifest out of config.json (or whatever
    --config points at). --all-flags bypasses it entirely."""
    if all_flags:
        return {"implemented": None, "excluded_tags": [],
                "unimplemented_policy": "skip"}
    if not path or not os.path.exists(path):
        return {"implemented": None, "excluded_tags": [],
                "unimplemented_policy": "skip"}
    with open(path) as handle:
        manifest = json.load(handle)
    manifest.setdefault("excluded_tags", [])
    manifest.setdefault("unimplemented_policy", "skip")
    return manifest


def _open_suite(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as handle:
        return json.load(handle)


def case_selected(case: dict, manifest: dict) -> tuple[bool, str]:
    """(runnable, reason). implemented=None means run everything.

    A case runs only when every flag it needs is declared implemented, so a
    checkpoint's cumulative flag list automatically re-runs every earlier
    checkpoint's applicable cases and never reaches a feature that does not
    exist yet.

    A case may also require a flag to be ABSENT (`absent_flags`): that is how a
    checkpoint asserts a later feature has not been built yet, by requiring the
    option to still be rejected as unknown. Such a case stops being selected as
    soon as that flag is introduced, and is skipped entirely when every flag is
    declared implemented, because there is then no checkpoint for it to
    describe.
    """
    tags = set(case.get("tags", []))
    excluded = set(manifest.get("excluded_tags", []))
    if tags & excluded:
        return False, f"excluded tag {sorted(tags & excluded)}"
    implemented = manifest.get("implemented")
    if implemented is None:
        # Every flag counts as implemented, so a case that requires one to
        # be absent has no checkpoint left to describe.
        if case.get("absent_flags"):
            return False, "requires flags to be unimplemented"
        return True, ""
    missing = set(case.get("flags", [])) - set(implemented)
    if missing:
        return False, f"unimplemented {sorted(missing)}"
    present = set(case.get("absent_flags", [])) & set(implemented)
    if present:
        return False, f"requires {sorted(present)} to be unimplemented"
    return True, ""


def _stdout_expected(case: dict) -> bytes | None:
    if case.get("stdout_b64") is not None:
        return base64.b64decode(case["stdout_b64"])
    return None


def _stderr_ok(case: dict, err: bytes) -> tuple[bool, str]:
    cls = case.get("stderr_class")
    if cls == "empty" and err != b"":
        return False, f"stderr expected empty, got {err[:120]!r}"
    if cls == "nonempty" and err == b"":
        return False, "stderr expected nonempty, got empty"
    pattern = case.get("stderr_regex")
    if pattern is not None and not re.search(pattern.encode(), err, re.S):
        return False, f"stderr regex {pattern!r} did not match {err[:160]!r}"
    return True, ""


def _tree_ok(case: dict, observed: dict[str, str]) -> tuple[bool, str]:
    expected = case.get("expected_tree")
    if expected is None:
        return True, ""
    differences = [
        f"{path}: got {observed.get(path, '<absent>')}, want {want}"
        for path, want in sorted(expected.items())
        if observed.get(path) != want
    ]
    if differences:
        return False, "modes: " + "; ".join(differences)
    return True, ""


def run_one(
    case: dict, cmd: list[str], sanitizer: bool, xfail: bool
) -> tuple[str, str]:
    result = engine.execute(case, cmd, sanitizer=sanitizer)

    if result.signal_name == "SKIP_ROOT":
        return SKIP, "permission-denied case needs non-root"
    if result.timed_out:
        return TIMEOUT, f"timed out after {case.get('timeout', 10)}s"
    if sanitizer and result.sanitizer:
        return SANITIZER, result.sanitizer
    if result.crashed:
        if result.signal_name in set(case.get("allow_signals", [])):
            return PASS, ""
        return CRASH, f"killed by {result.signal_name}"

    problems = []
    if case.get("exit_code") is not None and result.exit_code != case["exit_code"]:
        problems.append(f"exit: got {result.exit_code}, want {case['exit_code']}")

    check = case.get("check", "golden")
    if check == "golden":
        want = _stdout_expected(case)
        if want is not None and result.stdout != want:
            problems.append(f"stdout: got {result.stdout!r}, want {want!r}")
    elif check in props.CHECKS:
        ok, detail = props.CHECKS[check](case, result)
        if not ok:
            problems.append(f"property: {detail}")
    elif check == "none":
        pass

    ok, detail = _tree_ok(case, result.modes)
    if not ok:
        problems.append(detail)

    ok, detail = _stderr_ok(case, result.stderr)
    if not ok:
        problems.append(detail)

    if problems:
        return (XFAIL if xfail else FAIL), "; ".join(problems)
    return PASS, ""


def main() -> None:
    # Split the candidate command (after the first "--") off ourselves;
    # argparse REMAINDER mis-handles options that precede positionals.
    argv = sys.argv[1:]
    if "--" not in argv:
        print("error: no candidate command; pass it after --", file=sys.stderr)
        sys.exit(2)
    split = argv.index("--")
    opt_argv, cmd = argv[:split], argv[split + 1:]

    parser = argparse.ArgumentParser()
    parser.add_argument("suites", nargs="+",
                        help="suite files (globs ok; .json or .json.gz)")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--all-flags", action="store_true",
                        help="ignore config's implemented-flags filter")
    parser.add_argument("--sanitizer", action="store_true")
    parser.add_argument("--only", help="only cases with this tag")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4))
    parser.add_argument("--json-report")
    # This module is copied into the agent-visible stage bundle, so its own
    # option names must not collide with any long option new_chmod introduces at
    # a later checkpoint -- the bare string would be a hint. One such unused
    # argument was removed for that reason; do not reintroduce it.
    args = parser.parse_args(opt_argv)

    if not cmd:
        print("error: empty candidate command after --", file=sys.stderr)
        sys.exit(2)
    cmd = [os.path.abspath(t) if os.path.exists(t) else t for t in cmd]

    manifest = load_manifest(args.config, args.all_flags)
    xfail = manifest.get("unimplemented_policy") == "xfail"

    files: list[str] = []
    for pattern in args.suites:
        files += sorted(glob.glob(pattern)) or [pattern]

    cases = []
    for path in files:
        data = _open_suite(path)
        entries = data.get("cases", data) if isinstance(data, dict) else data
        for case_ordinal, case in enumerate(entries):
            case["_suite"] = os.path.basename(path)
            case["_case_ordinal"] = case_ordinal
            cases.append(case)

    jobs = []
    for case in cases:
        if args.only and args.only not in case.get("tags", []):
            continue
        selected, reason = case_selected(case, manifest)
        if not selected:
            if not (xfail and reason.startswith("unimplemented")):
                jobs.append((case, SKIP, reason))
                continue
        jobs.append((case, None, None))

    def work(job):
        case, forced, reason = job
        if forced is not None:
            return (case["name"], case, forced, reason)
        verdict, detail = run_one(case, cmd, args.sanitizer, xfail)
        return (case["name"], case, verdict, detail)

    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for record in pool.map(work, jobs):
            results.append(record)

    counts: dict[str, int] = {}
    per_suite: dict[str, dict[str, int]] = {}
    failures = []
    for name, case, verdict, detail in results:
        counts[verdict] = counts.get(verdict, 0) + 1
        suite = case.get("_suite", "?")
        per_suite.setdefault(suite, {}).setdefault(verdict, 0)
        per_suite[suite][verdict] += 1
        if verdict in FAILING:
            failures.append((name, case, verdict, detail))

    for name, case, verdict, detail in sorted(
        failures, key=lambda item: -SEVERITY[item[2]]
    ):
        print(f"{verdict:9} {name}  [{case.get('_suite')}]  "
              f"args={case.get('args')}")
        print(f"          {detail}")

    print("\n=== per-suite ===")
    for suite in sorted(per_suite):
        suite_counts = per_suite[suite]
        skipped = suite_counts.get(SKIP, 0) + suite_counts.get(XFAIL, 0)
        scored = sum(suite_counts.values()) - skipped
        other = {k: v for k, v in suite_counts.items()
                 if k not in (PASS, SKIP, XFAIL)}
        line = f"{suite_counts.get(PASS, 0)}/{scored} pass"
        if other:
            line += "  " + "  ".join(f"{k}={v}" for k, v in sorted(other.items()))
        print(f"  {suite:28} {line}")

    skipped = counts.get(SKIP, 0) + counts.get(XFAIL, 0)
    scored = len(results) - skipped
    print(f"\n{counts.get(PASS, 0)}/{scored} pass")

    if args.json_report:
        with open(args.json_report, "w") as handle:
            case_results = sorted(
                ({"case_id": case_result_id(case, name),
                  "verdict": verdict}
                 for name, case, verdict, _ in results),
                key=lambda item: item["case_id"],
            )
            json.dump({"schema_version": 2,
                       "counts": counts, "per_suite": per_suite,
                       "failures": [(n, v, d) for n, _, v, d in failures],
                       "results": case_results},
                      handle, indent=1)

    bad = sum(counts.get(key, 0) for key in FAILING)
    print("ALL GOOD" if bad == 0 else f"{bad} PROBLEM(S)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
