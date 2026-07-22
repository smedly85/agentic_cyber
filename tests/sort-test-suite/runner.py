#!/usr/bin/env python3
"""
Runner v2: judge a candidate sort binary against frozen golden suites.

Consumes schema-v2 suite JSON (see gen/generate.py) through the shared
engine.py, so the candidate runs under byte-identical conditions to how
the goldens were frozen from GNU sort.

Key differences from a naive text-mode runner:
  - bytes I/O (NUL / invalid-UTF-8 / -z safe)
  - config-driven flag filtering: only run cases whose flags are implemented
    (see config.json / config.py -- no path or flag list is hardcoded here)
  - crash/sanitizer/timeout classified distinctly from wrong-output
  - stderr matched by exact | regex | class(empty/nonempty)
  - -o output-file assertion; -R property checks
  - parallel across cases
  - suite files may be plain .json or gzipped .json.gz, transparently

Usage:
  runner.py suites/*.json.gz --config config.json -- ./my-sort
  runner.py suites/singles.json.gz --config config.json --sanitizer -- ./my-sort-asan
  runner.py suites/*.json.gz --all-flags -- /usr/bin/sort     # oracle self-check
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
XFAIL = "XFAIL"          # expected failure (unimplemented) - not a problem
FAIL = "FAIL"            # wrong exit / stdout / stderr / outfile
TIMEOUT = "TIMEOUT"
SANITIZER = "SANITIZER"
CRASH = "CRASH"

SEVERITY = {PASS: 0, SKIP: 0, XFAIL: 0,
            FAIL: 1, TIMEOUT: 2, SANITIZER: 3, CRASH: 4}
FAILING = {FAIL, TIMEOUT, SANITIZER, CRASH}


def load_manifest(path: str | None, all_flags: bool) -> dict:
    """Load the flag/tag-filtering manifest out of config.json (or whatever
    --config points at). --all-flags bypasses it entirely (oracle self-check:
    run every case regardless of what's "implemented")."""
    if all_flags:
        return {"implemented": None, "excluded_tags": [],
                "unimplemented_policy": "skip"}
    if not path or not os.path.exists(path):
        return {"implemented": None, "excluded_tags": [],
                "unimplemented_policy": "skip"}
    with open(path) as f:
        m = json.load(f)
    m.setdefault("excluded_tags", [])
    m.setdefault("unimplemented_policy", "skip")
    return m


def _open_suite(path: str):
    """Suite files may be plain JSON or gzipped (.json.gz) -- ship the
    latter to keep large adversarial-input suites small; both load
    transparently."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        return json.load(f)


def case_selected(case: dict, manifest: dict) -> tuple[bool, str]:
    """(runnable, reason). implemented=None means run everything."""
    tags = set(case.get("tags", []))
    excl = set(manifest.get("excluded_tags", []))
    if tags & excl:
        return False, f"excluded tag {sorted(tags & excl)}"
    if manifest.get("scope", {}).get("stdin_only") and "stdin_b64" not in case:
        return False, "outside stdin-only scope"
    impl = manifest.get("implemented")
    if impl is None:
        return True, ""
    impl = set(impl)
    needed = set(case.get("flags", []))
    missing = needed - impl
    if missing:
        return False, f"unimplemented {sorted(missing)}"
    return True, ""


def _stderr_ok(case: dict, err: bytes) -> tuple[bool, str]:
    if case.get("stderr") is not None:
        want = case["stderr"].encode() if isinstance(case["stderr"], str) else case["stderr"]
        if err != want:
            return False, f"stderr exact: got {err!r}, want {want!r}"
        return True, ""
    if case.get("stderr_b64") is not None:
        want = base64.b64decode(case["stderr_b64"])
        if err != want:
            return False, f"stderr exact: got {err!r}, want {want!r}"
        return True, ""
    rgx = case.get("stderr_regex")
    if rgx is not None:
        if not re.search(rgx.encode(), err, re.S):
            return False, f"stderr regex {rgx!r} did not match {err[:120]!r}"
        return True, ""
    cls = case.get("stderr_class")
    if cls == "empty":
        if err != b"":
            return False, f"stderr expected empty, got {err[:120]!r}"
    elif cls == "nonempty":
        if err == b"":
            return False, "stderr expected nonempty, got empty"
    return True, ""


def _stdout_expected(case: dict) -> bytes | None:
    if case.get("stdout_b64") is not None:
        return base64.b64decode(case["stdout_b64"])
    if case.get("stdout") is not None:
        return case["stdout"].encode()
    return None


def run_one(case: dict, cmd: list[str], stdin_mode: str,
            sanitizer: bool, xfail: bool) -> tuple[str, str]:
    check = case.get("check", "golden")
    res = engine.execute(case, cmd, stdin_mode=stdin_mode, sanitizer=sanitizer)

    if res.signal_name == "SKIP_ROOT":
        return SKIP, "unreadable fault needs non-root"
    if res.timed_out:
        return TIMEOUT, f"timed out after {case.get('timeout', 10)}s"
    if res.crashed:
        # An expected signal death (e.g. SIGPIPE on a closed output pipe) is
        # correct Unix behavior, not a defect.
        if res.signal_name in set(case.get("allow_signals", [])):
            return PASS, ""
        return CRASH, f"killed by {res.signal_name}"
    if sanitizer and res.sanitizer:
        return SANITIZER, res.sanitizer

    problems = []
    if case.get("exit_code") is not None and res.exit_code != case["exit_code"]:
        problems.append(f"exit: got {res.exit_code}, want {case['exit_code']}")

    if check == "golden":
        want = _stdout_expected(case)
        if want is not None and res.stdout != want:
            problems.append(f"stdout: got {res.stdout!r}, want {want!r}")
    elif check == "property:shuffle":
        ok, detail = props.check_shuffle(case, res)
        if not ok:
            problems.append(f"property: {detail}")
    elif check == "none":
        pass

    ok, detail = _stderr_ok(case, res.stderr)
    if not ok:
        problems.append(detail)

    spec = case.get("output_file")
    if spec is not None:
        want = base64.b64decode(spec["contents_b64"])
        got = res.outfiles.get(spec["path"])
        if got != want:
            problems.append(f"outfile {spec['path']}: got {got!r}, want {want!r}")

    if problems:
        verdict = XFAIL if xfail else FAIL
        return verdict, "; ".join(problems)
    return PASS, ""


def modes_for(case: dict) -> list[tuple[str, str]]:
    """(stdin_mode, name_suffix) pairs to run, honoring stdin_modes.
    Cases that use file operands / faults / --files0-from typically pin a
    single mode to avoid meaningless duplication."""
    declared = case.get("stdin_modes")
    default = [("file", ""), ("pipe", ".p"), ("redirect", ".r")]
    if declared is None:
        return default
    m = {"file": ("file", ""), "pipe": ("pipe", ".p"),
         "redirect": ("redirect", ".r")}
    return [m[x] for x in declared]


def main():
    # Split the candidate command (after the first "--") off ourselves;
    # argparse REMAINDER mis-handles options that precede positionals.
    argv = sys.argv[1:]
    if "--" not in argv:
        print("error: no candidate command; pass it after --", file=sys.stderr)
        sys.exit(2)
    split = argv.index("--")
    opt_argv, cmd = argv[:split], argv[split + 1:]

    ap = argparse.ArgumentParser()
    ap.add_argument("suites", nargs="+",
                    help="suite files (globs ok; .json or .json.gz)")
    ap.add_argument("--config", default="config.json",
                    help="path to config.json (default: ./config.json)")
    ap.add_argument("--all-flags", action="store_true",
                    help="ignore config's implemented-flags filter; run "
                         "every case (used for the oracle self-check)")
    ap.add_argument("--sanitizer", action="store_true")
    ap.add_argument("--only", help="only cases with this tag")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4))
    ap.add_argument("--json-report")
    ap.add_argument("--quiet", action="store_true",
                    help="only print failures + summary")
    args = ap.parse_args(opt_argv)

    if not cmd:
        print("error: empty candidate command after --", file=sys.stderr)
        sys.exit(2)
    cmd = [os.path.abspath(t) if os.path.exists(t) else t for t in cmd]

    manifest = load_manifest(args.config, args.all_flags)
    xfail = manifest.get("unimplemented_policy") == "xfail"

    files = []
    for pat in args.suites:
        files += sorted(glob.glob(pat)) or [pat]

    cases = []
    for fp in files:
        data = _open_suite(fp)
        entries = data.get("cases", data) if isinstance(data, dict) else data
        for c in entries:
            c["_suite"] = os.path.basename(fp)
            cases.append(c)

    jobs = []
    for case in cases:
        sel, reason = case_selected(case, manifest)
        if args.only and args.only not in case.get("tags", []):
            continue
        if not sel:
            # unimplemented -> skip (or xfail if policy says so, but xfail
            # still needs to run; here "skip" policy means don't run)
            if not (xfail and reason.startswith("unimplemented")):
                jobs.append((case, None, None, SKIP, reason))
                continue
        for mode, suffix in modes_for(case):
            jobs.append((case, mode, suffix, None, None))

    results = []

    def work(job):
        case, mode, suffix, forced, reason = job
        name = case["name"] + (suffix or "")
        if forced is not None:
            return (name, case, forced, reason)
        verdict, detail = run_one(case, cmd, mode, args.sanitizer, xfail)
        return (name, case, verdict, detail)

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for r in ex.map(work, jobs):
            results.append(r)

    counts = {}
    per_suite = {}
    failures = []
    for name, case, verdict, detail in results:
        counts[verdict] = counts.get(verdict, 0) + 1
        s = case.get("_suite", "?")
        per_suite.setdefault(s, {}).setdefault(verdict, 0)
        per_suite[s][verdict] += 1
        if verdict in FAILING:
            failures.append((name, case, verdict, detail))
        elif not args.quiet and verdict == PASS:
            pass  # too noisy; summary only

    for name, case, verdict, detail in sorted(
            failures, key=lambda x: -SEVERITY[x[2]]):
        print(f"{verdict:9} {name}  [{case.get('_suite')}]  "
              f"args={case.get('args')}")
        print(f"          {detail}")

    print("\n=== per-suite ===")
    for s in sorted(per_suite):
        line = "  ".join(f"{k}={v}" for k, v in sorted(per_suite[s].items()))
        print(f"  {s:28} {line}")

    total = len(results)
    ok = counts.get(PASS, 0)
    print(f"\n{ok}/{total} pass  |  " + "  ".join(
        f"{k}={counts[k]}" for k in sorted(counts) if k != PASS))

    if args.json_report:
        with open(args.json_report, "w") as f:
            json.dump({"counts": counts, "per_suite": per_suite,
                       "failures": [(n, v, d) for n, _, v, d in failures]},
                      f, indent=1)

    bad = sum(counts.get(k, 0) for k in FAILING)
    print("ALL GOOD" if bad == 0 else f"{bad} PROBLEM(S)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
