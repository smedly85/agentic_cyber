#!/usr/bin/env python3
"""Analyze each historical record against its exact vulnerable source tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from security.historical.analysis import (  # noqa: E402
    analyze_versioned_records,
    coverage_study,
    load_records,
    load_source_manifest,
    summarize_historical_analysis,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--k", nargs="*", type=int, default=[])
    parser.add_argument("--percent", nargs="*", type=float, default=[10, 25, 50, 100])
    parser.add_argument("--random-seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--include-entry-points", action="store_true")
    parser.add_argument("--force-fallback", action="store_true")
    args = parser.parse_args(argv)
    if not args.source_manifest.is_file():
        parser.error(f"source manifest not found: {args.source_manifest}")
    if not args.records.is_file():
        parser.error(f"records file not found: {args.records}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    records = load_records(args.records)
    manifest = load_source_manifest(args.source_manifest)
    versioned = analyze_versioned_records(
        records, manifest, force_fallback=args.force_fallback
    )
    mappings = versioned["historical_function_mappings"]
    graph_summaries = {
        identifier: {
            key: graph[key] for key in (
                "analysis_method", "entry_points", "resolved_entry_points",
                "reachable_function_count", "diversification_eligible_function_count",
                "unreachable_function_count", "max_reachable_call_depth",
                "functions_by_call_depth",
            )
        }
        for identifier, graph in versioned["call_graphs"].items()
    }
    report = {
        "schema_version": 2,
        "dataset": str(args.records),
        "source_manifest": str(args.source_manifest),
        "call_graphs_constructed": versioned["call_graphs_constructed"],
        "call_graph_cache_hits": versioned["call_graph_cache_hits"],
        "call_graph_summaries": graph_summaries,
        "historical_summary": summarize_historical_analysis(mappings),
        "historical_function_mappings": mappings,
        **coverage_study(
            versioned, k_values=args.k, percent_values=args.percent,
            random_seeds=args.random_seeds,
            include_entry_points=args.include_entry_points,
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
