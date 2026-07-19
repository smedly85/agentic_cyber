#!/usr/bin/env python3
"""
Aggregate runner.py / diff_fuzz.py --json-report output into one overall
PASS/FAIL summary, suitable for pasting into a report.

Any of --normal / --asan / --fuzz may be omitted (or point at a missing
file) if that pass wasn't run; it's reported as "(not run)".

Usage:
  report_summary.py --normal normal.json --asan asan.json --fuzz fuzz.json
"""
from __future__ import annotations

import argparse
import json
import os


def _load(path):
    if not path or not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _golden_line(label: str, report: dict | None) -> tuple[str, int]:
    if report is None:
        return f"  {label:22} (not run)", 0
    counts = report["counts"]
    total = sum(counts.values())
    passed = counts.get("PASS", 0)
    skipped = counts.get("SKIP", 0) + counts.get("XFAIL", 0)
    # denominator excludes SKIP/XFAIL: those are unimplemented flags, not
    # candidate failures, and would otherwise deflate the pass rate.
    scored = total - skipped
    pct = 100.0 * passed / scored if scored else 100.0
    bad = {k: v for k, v in counts.items() if k not in ("PASS", "SKIP", "XFAIL")}
    bad_n = sum(bad.values())
    detail = "  ".join(f"{k}={v}" for k, v in sorted(bad.items())) or "none"
    line = (f"  {label:22} {passed}/{scored} pass ({pct:.1f}%)   "
            f"skipped(unimplemented)={skipped}   problems: {detail}")
    return line, bad_n


def _fuzz_block(report: dict | None) -> tuple[str, int]:
    if report is None:
        return "  (not run)", 0
    lines = [
        f"  rounds:                    {report['rounds']}",
        f"  pass:                      {report['pass']} ({report['pass_pct']:.1f}%)",
        f"  fail (raw):                {report['fail']} ({report['fail_pct']:.1f}%)"
        f"   <- includes repeated hits of the same bug",
        f"  distinct issues:           {report['distinct_issues']}"
        f"   <- unique bugs found; use THIS number, not 'fail (raw)', for a bug count",
        f"  new regressions recorded:  {report['new_regressions']}",
    ]
    return "\n".join(lines), report["distinct_issues"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--normal")
    ap.add_argument("--asan")
    ap.add_argument("--fuzz")
    args = ap.parse_args()

    normal = _load(args.normal)
    asan = _load(args.asan)
    fuzz = _load(args.fuzz)

    print("========== OVERALL SUMMARY ==========")
    print("-- golden suites (pass/total excludes SKIP/XFAIL for unimplemented flags) --")
    problems = 0
    for label, report in (("pass 1 normal:", normal), ("pass 2 ASan/UBSan:", asan)):
        line, bad_n = _golden_line(label, report)
        problems += bad_n
        print(line)

    print()
    print("-- differential fuzz vs GNU mkdir --")
    fuzz_line, fuzz_issues = _fuzz_block(fuzz)
    print(fuzz_line)
    problems += fuzz_issues

    print()
    if problems == 0:
        print("VERDICT: CLEAN")
    else:
        print(f"VERDICT: {problems} PROBLEM(S) "
              f"(golden FAIL/TIMEOUT/SANITIZER/CRASH counted individually, "
              f"fuzz counted as distinct issues, not raw deviations)")
    print("======================================")


if __name__ == "__main__":
    main()
