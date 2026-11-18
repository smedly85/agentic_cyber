"""Shared runner for the toy fixture suites (suite contract).

    run <project_dir> --report <report.json>

Exit 0 iff every case passes. Report: {passed, failed, cases:[{name,status,detail}]}.
The binary is <project_dir>/toy (C, via make) or <project_dir>/target/debug/toy (Rust).
"""
import json
import subprocess
import sys
from pathlib import Path


def find_binary(project: Path) -> Path | None:
    for candidate in (project / "toy", project / "target" / "debug" / "toy"):
        if candidate.is_file():
            return candidate
    return None


def run_suite(cases, argv):
    project = Path(argv[1]).resolve()
    report_path = Path(argv[argv.index("--report") + 1]) if "--report" in argv else None
    binary = find_binary(project)
    results = []
    for name, args, want_out, want_code in cases:
        if binary is None:
            results.append({"name": name, "status": "error", "detail": "toy binary not found"})
            continue
        try:
            proc = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            results.append({"name": name, "status": "timeout", "detail": "exceeded 10s"})
            continue
        problems = []
        if proc.returncode != want_code:
            problems.append(f"exit {proc.returncode}, expected {want_code}")
        if want_out is not None and proc.stdout != want_out:
            problems.append(f"stdout {proc.stdout!r}, expected {want_out!r}")
        results.append({"name": name, "status": "fail" if problems else "pass", "detail": "; ".join(problems)})
    passed = sum(r["status"] == "pass" for r in results)
    report = {"passed": passed, "failed": len(results) - passed, "cases": results}
    if report_path:
        report_path.write_text(json.dumps(report, indent=2))
    print(f"{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1
