"""Read-only real-source feasibility audit. Never preprocesses/builds candidates.

Uses existing successful-candidate manifest membership and verifies source hashes.
Raw parser census is diagnostic only; failed extractions never become graphs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import re
import time

from .analysis.diversity_validation import iter_nodes, parse_source
from .analysis.ordered_callgraph import analyze_source_bytes, _identifier, stable_json
from .analysis.ordered_distances import (
    DEFAULT_EXCLUDE, Limits, alignment_search_size, compare, coverage, provenance,
    Budget, _align,
)

ROOT = Path(__file__).resolve().parents[1]


def syntax_census(data):
    """Count visible unpreprocessed syntax without recovering failed measurements."""
    parsed = parse_source(data)
    nodes = list(iter_nodes(parsed.root))
    functions = [n for n in nodes if n.type == "function_definition"]
    names = [_identifier(f.child_by_field_name("declarator"), data)[0] for f in functions]
    return {
        "purpose": "diagnostic_unpreprocessed_syntax_not_a_successful_extraction",
        "parse_has_error": parsed.root.has_error,
        "function_definitions": len(functions), "helpers_excluding_main": sum(n != "main" for n in names),
        "named_function_events": sum(n.is_named and n.type != "comment" for f in functions for n in iter_nodes(f)),
        "call_expression_nodes": sum(n.type == "call_expression" for n in nodes),
        "preprocessor_kinds": dict(sorted(Counter(n.type for n in nodes if n.type.startswith("preproc_")).items())),
        "includes": [data[n.start_byte:n.end_byte].decode("utf-8", "replace").strip() for n in nodes if n.type == "preproc_include"],
        "name_policy_excluded_functions": [n for n in names if n and re.search(DEFAULT_EXCLUDE, n, re.I)],
    }


def audit_group(root, population, utility, checkpoint):
    members = sorted((c for c in population["candidates"] if c["utility"] == utility and c["checkpoint_id"] == checkpoint), key=lambda c: c["candidate_id"])
    if not members:
        raise ValueError("No recorded successful candidates for requested group")
    if len({c["formal_run_id"] for c in members}) != 1:
        raise ValueError("Different formal runs must be audited separately")
    limits = Limits()
    rows, extracted = [], {}
    for member in members:
        if member["functional_population_status"] != "public_checkpoint_stage_success":
            raise ValueError("Manifest membership is not successful checkpoint evidence")
        path = (root / member["candidate_source"]).resolve()
        path.relative_to(root.resolve())
        if path.suffix != ".c":
            raise ValueError("Only C sources may enter a feasibility group")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        lf_digest = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
        if member["candidate_source_sha256"] not in {digest, lf_digest}:
            raise ValueError("Source hash mismatch: " + member["candidate_id"])
        start = time.perf_counter()
        result = analyze_source_bytes(data, source_file=member["candidate_source"])
        elapsed = time.perf_counter() - start
        census = syntax_census(data)
        extracted[member["candidate_id"]] = result
        ok = result["status"] == "success"
        unresolved = [c for c in result["call_sites"] if c["resolution"].startswith("unresolved")]
        measured = coverage(result)
        blockers = []
        if not ok:
            blockers.append("extraction:" + result["status"])
        if ok and measured["event_count"] > limits.max_events:
            blockers.append("event_limit")
        if unresolved:
            blockers.append("unresolved_call_targets")
        rows.append({
            **member, "observed_source_sha256": digest, "lf_normalized_sha256": lf_digest,
            "source_verification": "byte_identical" if digest == member["candidate_source_sha256"] else "only_CRLF_to_LF_normalization_matches_manifest",
            "extraction_status": result["status"], "diagnostics": result["diagnostics"],
            "extraction_seconds_observed": elapsed,
            "function_count": measured["function_count"] if ok else None,
            "event_count": measured["event_count"] if ok else None,
            "call_count": measured["call_count"] if ok else None,
            "unresolved_call_count": len(unresolved) if ok else None,
            "unresolved_calls_by_name": dict(sorted(Counter(c["callee_name"] or "<computed>" for c in unresolved).items())) if ok else None,
            "unresolved_calls_by_reason": dict(Counter(c["resolution"] for c in unresolved)) if ok else None,
            "known_comparison_blockers": blockers, "syntax_census": census,
        })
    empty = analyze_source_bytes("", source_file="empty_new_source_baseline.c")
    pairs = []
    for a, b in itertools.combinations(rows, 2):
        aid, bid = a["candidate_id"], b["candidate_id"]
        n = a["syntax_census"]["helpers_excluding_main"]
        m = b["syntax_census"]["helpers_excluding_main"]
        count = alignment_search_size(n, m)
        start = time.perf_counter()
        measurement = compare(extracted[aid], extracted[bid], scope_reference=empty)
        elapsed = time.perf_counter() - start
        pairs.append({
            "left": aid, "right": bid, "comparison_seconds_observed": elapsed,
            "architecture": measurement["architecture"], "strategy": measurement["strategy"],
            "alignment": measurement["alignment"],
            "all_known_candidate_blockers": sorted(set(a["known_comparison_blockers"] + b["known_comparison_blockers"])),
            "capacity_diagnostic": {
                "left_helpers": n, "right_helpers": m, "partial_injections": count,
                "exceeds_alignment_limit": count > limits.max_alignments,
                "note": "Capacity estimate from visible syntax only; not a comparison of failed/incomplete graphs",
            },
        })
    return {
        "utility": utility, "checkpoint": checkpoint, "formal_run_id": members[0]["formal_run_id"],
        "scope_reference": "empty_new_source_baseline; no arbitrary candidate selected",
        "selection": "All hash-verified public_checkpoint_stage_success members in the manifest for this run/utility/checkpoint",
        "candidates": rows, "pairs_excluding_diagonal": pairs,
        "summary": {
            "candidates": len(rows), "extraction_statuses": dict(Counter(r["extraction_status"] for r in rows)),
            "extraction_diagnostics": dict(Counter(d for r in rows for d in r["diagnostics"])),
            "pair_count": len(pairs),
            "pairs_with_two_successful_extractions": sum(extracted[p["left"]]["status"] == extracted[p["right"]]["status"] == "success" for p in pairs),
            "architecture_available": sum(p["architecture"]["status"] == "success" for p in pairs),
            "strategy_available": sum(p["strategy"]["status"] == "success" for p in pairs),
            "architecture_failure_reasons": dict(Counter(p["architecture"].get("reason") for p in pairs if p["architecture"]["status"] != "success")),
            "strategy_failure_reasons": dict(Counter(p["strategy"].get("reason") for p in pairs if p["strategy"]["status"] != "success")),
            "capacity_exceeds_alignment_limit": sum(p["capacity_diagnostic"]["exceeds_alignment_limit"] for p in pairs),
            "scope_reference_sensitivity": "Not estimable on pairs with unavailable A; controlled reference-sensitivity probes are separate",
        },
    }


def benchmark_oracle():
    """Synthetic stars measure oracle overhead, never stand in for real graphs."""
    results = []
    for n in range(8):
        declarations = "".join(f"void f{i}(void) {{}}" for i in range(n))
        calls = "".join(f"f{i}();" for i in range(n))
        extraction = analyze_source_bytes(declarations + "int main(void){" + calls + "}")
        count = alignment_search_size(n, n)
        row = {"helpers_each": n, "partial_injections": count}
        if count > Limits().max_alignments:
            row.update(status="alignment_search_limit", seconds_observed=None)
        else:
            budget = Budget(Limits())
            start = time.perf_counter()
            distance, mappings = _align(extraction, extraction, budget)
            row.update(status="success", seconds_observed=time.perf_counter() - start,
                       distance=distance, optimal_mapping_count=len(mappings), work_units=budget.work)
        results.append(row)
    return {"purpose": "Synthetic exact-oracle scalability calibration; no approximate matcher", "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = ROOT / "security/generated_candidate_population.json"
    data = manifest_path.read_bytes()
    population = json.loads(data)
    report = {
        "provenance": provenance(), "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "population_manifest": str(manifest_path.relative_to(ROOT)),
        "population_manifest_sha256": hashlib.sha256(data).hexdigest(),
        "timing_policy": "Observed wall times are diagnostic and not deterministic distance features",
        "groups": [audit_group(ROOT, population, u, c) for u, c in [("mkdir", "002"), ("grep", "004")]],
        "exact_oracle_benchmark": benchmark_oracle(),
    }
    args.output.write_text(stable_json(report), encoding="utf-8")
    for group in report["groups"]:
        print(group["utility"], group["checkpoint"], json.dumps(group["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
