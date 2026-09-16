"""Run non-scientific fixture compilation and prototype comparison.

Tree-sitter is called only as the frozen prototype comparator.  Its output is
never passed to the semantic backend or used to create semantic edges.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from security.common.callgraph import analyze_sources
from security.semantic_callgraph import analyze_build, build_bitcode, inventory_toolchain, stable_json


ROOT = Path(__file__).resolve().parent


def prototype_summary(source_files: list[str], entry_point: str) -> dict:
    analysis = analyze_sources(
        [(name, (ROOT / name).read_bytes()) for name in source_files],
        entry_points=(entry_point,),
    )
    edges = []
    for row in analysis["function_reachability"]:
        for outgoing in row["outgoing_call_edges"]:
            edges.append({
                "caller": row["function_id"],
                "callee": outgoing["target"],
                "edge_type": outgoing["edge_type"],
            })
    return {
        "analysis_method": analysis["analysis_method"],
        "direct_or_special_case_edges": sorted(edges, key=lambda row: (row["caller"], row["callee"])),
        "unresolved_direct_calls": analysis["unresolved_direct_calls"],
        "unresolved_callback_targets": analysis["unresolved_callback_targets"],
    }


def semantic_summary(result: dict) -> dict:
    return {
        "functions": [
            {
                "identity": row["identity"],
                "name": row["name"],
                "raw_call_depth": row["raw_call_depth"],
                "semantic_status": row["semantic_status"],
                "shortest_call_path": row["shortest_call_path"],
            }
            for row in result["functions"]
        ],
        "call_edges": result["call_edges"],
        "unresolved_indirect_callsites": result["unresolved_indirect_callsites"],
        "external_calls": result["external_calls"],
    }


def validate_observation(fixture: dict, build_status: str, semantic: dict) -> list[str]:
    errors: list[str] = []
    expected_status = fixture.get("expected_status", "success")
    if build_status != expected_status and expected_status != "success":
        errors.append(f"build status {build_status!r} != {expected_status!r}")
    if semantic["analysis_status"] != expected_status:
        errors.append(
            f"analysis status {semantic['analysis_status']!r} != {expected_status!r}"
        )
    if expected_status != "success":
        return errors

    functions = semantic["functions"]
    by_name: dict[str, list[dict]] = {}
    for row in functions:
        by_name.setdefault(row["name"], []).append(row)
    for name, expected_depth in fixture.get("expected_depths", {}).items():
        matches = by_name.get(name, [])
        if len(matches) != 1:
            errors.append(f"expected one function named {name!r}, found {len(matches)}")
        elif matches[0]["raw_call_depth"] != expected_depth:
            errors.append(
                f"depth for {name!r} is {matches[0]['raw_call_depth']!r}, "
                f"expected {expected_depth!r}"
            )

    names_by_identity = {row["identity"]: row["name"] for row in functions}
    indirect: dict[str, list[str]] = {}
    for edge in semantic["call_edges"]:
        if edge["edge_type"] != "indirect_resolved":
            continue
        location = edge["callsite"]
        key = f"{location['source_file']}:{location['line']}"
        indirect.setdefault(key, []).append(names_by_identity[edge["callee"]])
    actual_indirect = {key: sorted(set(value)) for key, value in sorted(indirect.items())}
    expected_indirect = {
        key: sorted(value)
        for key, value in fixture.get("expected_indirect_targets", {}).items()
    }
    if actual_indirect != expected_indirect:
        errors.append(
            f"indirect targets {actual_indirect!r} != {expected_indirect!r}"
        )

    actual_external = sorted(row["callee_name"] for row in semantic["external_calls"])
    expected_external = sorted(fixture.get("expected_external_calls", []))
    if actual_external != expected_external:
        errors.append(f"external calls {actual_external!r} != {expected_external!r}")

    identities = {row["identity"] for row in functions}
    for identity in fixture.get("expected_distinct_identities", []):
        if identity not in identities:
            errors.append(f"missing distinct function identity {identity!r}")
    return errors


def run(*, svf_helper: Path | None = None) -> dict:
    manifest = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
    inventory = inventory_toolchain(helper=svf_helper)
    rows = []
    build_root = ROOT.parents[2] / "build" / "semantic-callgraph-calibration"
    build_root.mkdir(parents=True, exist_ok=True)
    for fixture in manifest["fixtures"]:
        output = build_root / fixture["id"]
        build = build_bitcode(
            ROOT, fixture["source_files"], output,
            compile_flags=manifest["compile_flags"], inventory=inventory,
        )
        semantic = analyze_build(build, entry_point=fixture["entry_point"], inventory=inventory)
        validation_errors = validate_observation(fixture, build.status, semantic)
        rows.append({
            "fixture": fixture["id"],
            "expected": {key: value for key, value in fixture.items() if key.startswith("expected_")},
            "llvm_build_status": build.status,
            "semantic_analysis_status": semantic["analysis_status"],
            "semantic_failure_reason": (
                semantic["failures"][0].get("reason") if semantic["failures"] else None
            ),
            "validation_passed": not validation_errors,
            "validation_errors": validation_errors,
            "semantic": semantic_summary(semantic) if semantic["analysis_status"] == "success" else None,
            "prototype": prototype_summary(fixture["source_files"], fixture["entry_point"]),
        })
    return {
        "schema_version": 1,
        "scientific_population": False,
        "toolchain": inventory,
        "pointer_analysis": "andersen_wave_diff",
        "tree_sitter_role": "prototype_comparison_only",
        "fixtures": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--svf-helper", type=Path,
        help="path to the repository-local semantic-callgraph-svf executable",
    )
    args = parser.parse_args()
    text = stable_json(run(svf_helper=args.svf_helper))
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
