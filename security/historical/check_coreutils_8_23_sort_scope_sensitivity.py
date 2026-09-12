#!/usr/bin/env python3
"""Compare Fedora Coreutils 8.23 sort scopes without changing the manifest."""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from security.historical.analysis import (
    analyze_versioned_records,
    load_records,
    load_source_manifest,
)
from security.historical.derive_coreutils_8_23_sort_scope import derive_scope


VULNERABILITY_PATH_FILES = {"src/sort.c"}


def _resolved_path_unit_edge_count(graph: dict[str, object]) -> int:
    edges: set[tuple[str, str]] = set()
    for row in graph.get("function_reachability", []):
        if row.get("source_file") not in VULNERABILITY_PATH_FILES:
            continue
        caller = str(row["function_id"])
        for callee in (*row.get("direct_callees", []), *row.get("callback_callees", [])):
            edges.add((caller, str(callee)))
    return len(edges)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--makefile", required=True, type=Path)
    parser.add_argument("--link-map", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    records = [
        item for item in load_records(arguments.records)
        if item["id"] in {"CVE-2015-4041", "CVE-2015-4042"}
    ]
    if [item["id"] for item in records] != ["CVE-2015-4041", "CVE-2015-4042"]:
        raise RuntimeError("both downstream sort records are required")
    first = records[0]
    manifest_entry = next(
        item for item in load_source_manifest(arguments.source_manifest)
        if item["upstream_project"] == first["upstream_project"]
        and item["affected_version"] == first["affected_version"]
        and item["source_revision"] == first["source_revision"]
        and item.get("downstream_revision") == first.get("downstream_revision")
        and "sort" in item["programs"]
    )
    source_tree = Path(manifest_entry["resolved_source_tree"])
    derived = derive_scope(source_tree, arguments.makefile, arguments.link_map)
    formal = manifest_entry["programs"]["sort"]["source_files"]
    if formal != derived["analyzed_source_files"]:
        raise RuntimeError("formal manifest scope no longer matches GNU ld closure")
    scopes = {
        "minimal_sort_owned_translation_unit": ["src/sort.c"],
        "frozen_linker_exact_scope": formal,
        "configured_archive_source_superset": derived["archive_source_superset_files"],
        "whole_release_c_diagnostic": sorted(
            path.relative_to(source_tree).as_posix()
            for path in source_tree.rglob("*.c") if path.is_file()
        ),
    }

    rows = []
    for name, source_files in scopes.items():
        scoped_manifest = copy.deepcopy(manifest_entry)
        scoped_manifest.pop("resolved_source_tree", None)
        scoped_manifest["source_tree"] = str(source_tree)
        scoped_manifest["programs"]["sort"]["source_files"] = source_files
        result = analyze_versioned_records(records, [scoped_manifest])
        graph = next(iter(result["call_graphs"].values()), None)
        names = Counter(
            str(item["function"]) for item in graph["function_reachability"]
        ) if graph else Counter()
        rows.append({
            "scope": name,
            "source_file_count": len(source_files),
            "analysis_method": graph["analysis_method"] if graph else None,
            "function_count": len(graph["function_reachability"]) if graph else None,
            "reachable_function_count": graph["reachable_function_count"] if graph else None,
            "max_reachable_call_depth": graph["max_reachable_call_depth"] if graph else None,
            "duplicate_function_name_count": sum(count > 1 for count in names.values()),
            "unresolved_ambiguous_call_count": sum(
                item.get("reason") == "ambiguous_target"
                for item in graph["unresolved_direct_calls"]
            ) if graph else None,
            "resolved_edges_from_vulnerability_path_units": (
                _resolved_path_unit_edge_count(graph) if graph else None
            ),
            "mappings": [{
                key: mapping[key] for key in (
                    "vulnerability_id", "vulnerable_function", "mapping_status",
                    "mapped_function_id", "mapped_source_file", "call_depth_status",
                    "call_depth", "shortest_call_path", "direct_callers",
                    "direct_callees",
                )
            } for mapping in result["historical_function_mappings"]],
        })
    output = {
        "vulnerability_ids": [item["id"] for item in records],
        "formal_scope": "frozen_linker_exact_scope",
        "scopes": rows,
    }
    rendered = json.dumps(output, indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
