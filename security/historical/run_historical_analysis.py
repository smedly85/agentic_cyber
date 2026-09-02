#!/usr/bin/env python3
"""Analyze exact historical function mappings against an upstream C tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from security.common.callgraph import analyze_source_tree  # noqa: E402
from security.historical.analysis import (  # noqa: E402
    coverage_study,
    load_records,
    map_historical_records,
    summarize_historical_analysis,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-tree", required=True, type=Path)
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--k", nargs="*", type=int, default=[])
    parser.add_argument("--percent", nargs="*", type=float, default=[10, 25, 50, 100])
    parser.add_argument("--random-seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--force-fallback", action="store_true")
    args = parser.parse_args(argv)
    if not args.source_tree.is_dir():
        parser.error(f"source tree not found: {args.source_tree}")
    if not args.records.is_file():
        parser.error(f"records file not found: {args.records}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    records = load_records(args.records)
    graph = analyze_source_tree(args.source_tree, force_fallback=args.force_fallback)
    mappings = map_historical_records(records, graph)
    report = {
        "schema_version": 1,
        "dataset": str(args.records),
        "source_tree": str(args.source_tree),
        "call_graph_summary": {
            key: graph[key] for key in (
                "analysis_method", "entry_points", "resolved_entry_points",
                "reachable_function_count", "unreachable_function_count",
                "max_reachable_call_depth", "functions_by_call_depth",
            )
        },
        "historical_summary": summarize_historical_analysis(mappings),
        "historical_function_mappings": mappings,
        **coverage_study(
            graph, mappings, k_values=args.k, percent_values=args.percent,
            random_seeds=args.random_seeds,
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

