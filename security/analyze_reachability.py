#!/usr/bin/env python3
"""Report call-depth characterization and deterministic selection controls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from security.common.callgraph import (  # noqa: E402
    analyze_source_file,
    reachability_report,
    select_functions,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    budget = parser.add_mutually_exclusive_group()
    budget.add_argument("--k", type=int, default=3)
    budget.add_argument("--percent", type=float)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--include-entry-points", action="store_true")
    parser.add_argument("--force-fallback", action="store_true")
    args = parser.parse_args(argv)
    if not args.source.is_file():
        parser.error(f"source not found: {args.source}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    analysis = analyze_source_file(args.source, force_fallback=args.force_fallback)
    budget = {"percent": args.percent} if args.percent is not None else {"k": args.k}
    report = {
        **analysis,
        "reachability_report": reachability_report(analysis),
        "selection_demonstration": [
            select_functions(
                analysis, policy=policy, seed=args.seed,
                include_entry_points=args.include_entry_points, **budget,
            )
            for policy in ("SHALLOW", "RANDOM", "DEEP")
        ],
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
