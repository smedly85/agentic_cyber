#!/usr/bin/env python3
"""Compare diagnostic GNU grep 2.10 scopes without changing the manifest."""

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
from security.historical.derive_grep_2_10_scope import (
    LIB_VARIABLES,
    SRC_VARIABLES,
    derive_scope,
    expand_make_variables,
)


MINIMAL_SOURCE_FILES = [
    # argmatch.c contains a test-only main behind preprocessing that this
    # source parser does not model.  Retaining it preserves the formal graph's
    # source-qualified ID for src/main.c::main in this diagnostic scope.
    "lib/argmatch.c", "src/dfa.c", "src/dfasearch.c", "src/grep.c", "src/main.c",
]
VULNERABILITY_PATH_FILES = {
    "src/dfa.c", "src/dfasearch.c", "src/grep.c", "src/main.c",
}


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
    parser.add_argument("--src-makefile", required=True, type=Path)
    parser.add_argument("--lib-makefile", required=True, type=Path)
    parser.add_argument("--link-map", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    record = next(
        item for item in load_records(arguments.records)
        if item["id"] == "CVE-2012-5667"
    )
    manifest_entry = next(
        item for item in load_source_manifest(arguments.source_manifest)
        if item["upstream_project"] == "gnu-grep"
        and item["affected_version"] == record["affected_version"]
        and item["source_revision"] == record["source_revision"]
        and "grep" in item["programs"]
    )
    source_tree = Path(manifest_entry["resolved_source_tree"])
    derived = derive_scope(
        source_tree,
        expand_make_variables(
            arguments.src_makefile, SRC_VARIABLES, "print-grep210-sensitivity-src",
        ),
        expand_make_variables(
            arguments.lib_makefile, LIB_VARIABLES, "print-grep210-sensitivity-lib",
        ),
        arguments.link_map,
    )
    formal = manifest_entry["programs"]["grep"]["source_files"]
    if formal != derived["analyzed_source_files"]:
        raise RuntimeError("formal manifest scope no longer matches the GNU ld closure")
    scopes = {
        "minimal_known_vulnerability_path_units": MINIMAL_SOURCE_FILES,
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
        scoped_manifest["programs"]["grep"]["source_files"] = source_files
        result = analyze_versioned_records([record], [scoped_manifest])
        graph = next(iter(result["call_graphs"].values()), None)
        mappings = result["historical_function_mappings"]
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
                    "vulnerable_function", "mapping_status", "mapped_function_id",
                    "mapped_source_file", "call_depth_status", "call_depth",
                    "shortest_call_path", "direct_callers", "direct_callees",
                )
            } for mapping in mappings],
        })
    output = {
        "vulnerability_id": record["id"],
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
