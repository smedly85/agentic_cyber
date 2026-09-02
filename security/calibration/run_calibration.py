#!/usr/bin/env python3
"""Validate the evaluator against isolated, intentionally vulnerable toys."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from security.common.evaluator import evaluate  # noqa: E402

SEEDED = {
    "oob": {"asan"},
    "uaf": {"asan"},
    "integer_overflow": {"ubsan"},
    "recursion": {"asan", "crash", "timeout", "resource"},
    "nontermination": {"timeout", "resource"},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/security-calibration"))
    parser.add_argument("--compiler", default="cc")
    parser.add_argument("--security-timeout", type=float, default=0.5)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, expected in SEEDED.items():
        target = args.output / name
        result = evaluate(
            utility="sort", source=Path(__file__).parent / "fixtures" / f"{name}.c",
            output=target / "security_results.json", artifacts=target / "artifacts",
            seed=1, fuzz_seconds=max(1.0, args.security_timeout * 2), max_inputs=1,
            timeout=args.security_timeout, compiler=args.compiler,
        )
        observed = {item.get("kind") for item in result.get("unique_security_findings", [])}
        rows.append({
            "fixture": name, "expected_any_of": sorted(expected),
            "observed": sorted(observed), "detected": bool(expected & observed),
            "evaluation_completed": result.get("security_evaluation_completed"),
        })
    detected = sum(row["detected"] for row in rows)
    report = {
        "schema_version": 1,
        "seeded_vulnerabilities_total": len(rows),
        "seeded_vulnerabilities_detected": detected,
        "seeded_vulnerabilities_missed": len(rows) - detected,
        "detection_rate": detected / len(rows) if rows else None,
        "results": rows,
        "calibration_only": True,
    }
    (args.output / "calibration_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0 if detected == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
