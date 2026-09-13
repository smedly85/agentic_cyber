#!/usr/bin/env python3
"""Compare four Fedora Coreutils 8.17 sort scopes without changing the manifest."""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from security.historical.analysis import analyze_versioned_records, load_records, load_source_manifest
from security.historical.derive_coreutils_8_17_sort_scope import derive_scope


VULNERABILITY_PATH_FILES = {"src/sort.c"}


def path_edge_count(graph: dict[str, object]) -> int:
    edges = set()
    for row in graph.get("function_reachability", []):
        if row.get("source_file") != "src/sort.c":
            continue
        for callee in (*row.get("direct_callees", []), *row.get("callback_callees", [])):
            edges.add((str(row["function_id"]), str(callee)))
    return len(edges)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--src-makefile", required=True, type=Path)
    parser.add_argument("--lib-makefile", required=True, type=Path)
    parser.add_argument("--link-map", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    records = [item for item in load_records(args.records) if item["id"] == "CVE-2013-0221"]
    if len(records) != 1:
        raise RuntimeError("exactly one CVE-2013-0221 record is required")
    record = records[0]
    entry = next(
        item for item in load_source_manifest(args.source_manifest)
        if item["upstream_project"] == record["upstream_project"]
        and item["affected_version"] == record["affected_version"]
        and item["source_revision"] == record["source_revision"]
        and item.get("downstream_revision") == record.get("downstream_revision")
        and "sort" in item["programs"]
    )
    source_tree = Path(entry["resolved_source_tree"])
    derived = derive_scope(source_tree, args.src_makefile, args.lib_makefile, args.link_map)
    formal = entry["programs"]["sort"]["source_files"]
    if formal != derived["analyzed_source_files"]:
        raise RuntimeError("formal manifest scope no longer matches GNU ld closure")
    scopes = {
        "minimal_vulnerability_path_units": ["src/sort.c"],
        "frozen_linker_exact_scope": formal,
        "configured_archive_source_superset": derived["archive_source_superset_files"],
        "whole_release_c_diagnostic": sorted(
            path.relative_to(source_tree).as_posix()
            for path in source_tree.rglob("*.c") if path.is_file()
        ),
    }

    rows = []
    for name, source_files in scopes.items():
        scoped = copy.deepcopy(entry)
        scoped.pop("resolved_source_tree", None)
        scoped["source_tree"] = str(source_tree)
        scoped["programs"]["sort"]["source_files"] = source_files
        result = analyze_versioned_records(records, [scoped])
        graph = next(iter(result["call_graphs"].values()), None)
        names = Counter(str(item["function"]) for item in graph["function_reachability"]) if graph else Counter()
        rows.append({
            "scope": name,
            "source_file_count": len(source_files),
            "analysis_method": graph["analysis_method"] if graph else None,
            "function_count": len(graph["function_reachability"]) if graph else None,
            "reachable_function_count": graph["reachable_function_count"] if graph else None,
            "max_reachable_call_depth": graph["max_reachable_call_depth"] if graph else None,
            "duplicate_function_name_count": sum(count > 1 for count in names.values()),
            "unresolved_ambiguous_call_count": sum(
                item.get("reason") == "ambiguous_target" for item in graph["unresolved_direct_calls"]
            ) if graph else None,
            "resolved_edges_from_vulnerability_path_units": path_edge_count(graph) if graph else None,
            "mappings": [{key: mapping[key] for key in (
                "vulnerability_id", "vulnerable_function", "mapping_status",
                "mapped_function_id", "mapped_source_file", "call_depth_status",
                "call_depth", "shortest_call_path", "direct_callers", "direct_callees",
            )} for mapping in result["historical_function_mappings"]],
        })
    output = {
        "vulnerability_ids": ["CVE-2013-0221"],
        "formal_scope": "frozen_linker_exact_scope",
        "scopes": rows,
    }
    rendered = json.dumps(output, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
