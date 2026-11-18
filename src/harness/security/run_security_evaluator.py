#!/usr/bin/env python3
"""Run post-validation security evaluation for one candidate source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from security.common.evaluator import evaluate  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--utility", required=True, choices=("grep", "sort", "mkdir", "chmod", "cp", "mv"))
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--security-fuzz-seconds", type=float, default=10.0)
    parser.add_argument("--security-seed", type=int, default=1)
    parser.add_argument("--security-timeout", type=float, default=2.0)
    parser.add_argument("--security-max-inputs", type=int, default=100)
    parser.add_argument("--compiler", default="cc")
    args = parser.parse_args(argv)
    if args.security_fuzz_seconds <= 0 or args.security_timeout <= 0 or args.security_max_inputs <= 0:
        parser.error("security budgets and timeout must be positive")
    if not args.source.is_file():
        parser.error(f"candidate source not found: {args.source}")
    if args.artifacts is None:
        args.artifacts = args.output.parent / "security_artifacts"
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.source.suffix.lower() == ".rs":
        result = {
            "schema_version": 1,
            "utility": args.utility,
            "security_evaluation_completed": False,
            "security_clean": None,
            "security_evaluator_exit_code": 2,
            "unsupported_reason": "Rust requires an explicit security backend; C parsers, sanitizers and call graphs are not applicable",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(result["unsupported_reason"], file=sys.stderr)
        return 2
    result = evaluate(
        utility=args.utility, source=args.source, output=args.output,
        artifacts=args.artifacts, seed=args.security_seed,
        fuzz_seconds=args.security_fuzz_seconds, max_inputs=args.security_max_inputs,
        timeout=args.security_timeout, compiler=args.compiler,
    )
    return int(result["security_evaluator_exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
