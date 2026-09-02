"""Validation, exact function mapping, and historical coverage metrics."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from security.common.callgraph import SELECTION_POLICIES, select_functions

SCHEMA_VERSION = 1
ALLOWED_UTILITIES = {"sort", "mkdir", "chmod", "grep"}
ALLOWED_PROJECTS = {"gnu-coreutils", "gnu-grep"}
REQUIRED_FIELDS = {
    "id": str,
    "utility": str,
    "upstream_project": str,
    "affected_version": str,
    "fixed_version": str,
    "vulnerable_function": str,
    "patched_functions": list,
    "cwe": str,
    "bug_type": str,
    "attacker_input": str,
    "source_reference": str,
    "patch_reference": str,
    "notes": str,
    "verified": bool,
}


class HistoricalDataError(ValueError):
    pass


def validate_record(record: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(record) - set(REQUIRED_FIELDS))
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    for field, expected in REQUIRED_FIELDS.items():
        if field not in record:
            errors.append(f"missing field: {field}")
        elif not isinstance(record[field], expected) or (
            expected is bool and type(record[field]) is not bool
        ):
            errors.append(f"{field} must be {expected.__name__}")
    if isinstance(record.get("id"), str) and not record["id"].strip():
        errors.append("id must not be empty")
    if isinstance(record.get("vulnerable_function"), str) and not record["vulnerable_function"].strip():
        errors.append("vulnerable_function must not be empty")
    if record.get("utility") not in ALLOWED_UTILITIES:
        errors.append("utility must be sort, mkdir, chmod, or grep")
    if record.get("upstream_project") not in ALLOWED_PROJECTS:
        errors.append("upstream_project must be gnu-coreutils or gnu-grep")
    patched = record.get("patched_functions")
    if isinstance(patched, list):
        if any(not isinstance(item, str) for item in patched):
            errors.append("patched_functions entries must be strings")
        if len(set(item for item in patched if isinstance(item, str))) != len(patched):
            errors.append("patched_functions entries must be unique")
    return errors


def validate_records(records: Any) -> list[str]:
    if not isinstance(records, list):
        return ["dataset root must be an array"]
    errors: list[str] = []
    identifiers: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            errors.append(f"record {index}: must be an object")
            continue
        errors.extend(f"record {index}: {error}" for error in validate_record(record))
        identifier = record.get("id")
        if isinstance(identifier, str):
            if identifier in identifiers:
                errors.append(f"record {index}: duplicate id: {identifier}")
            identifiers.add(identifier)
    return errors


def load_records(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HistoricalDataError(f"cannot read historical dataset: {error}") from error
    errors = validate_records(raw)
    if errors:
        raise HistoricalDataError("; ".join(errors))
    return [dict(item) for item in raw]


def map_historical_records(
    records: Iterable[Mapping[str, Any]], analysis: Mapping[str, Any],
) -> list[dict[str, Any]]:
    functions = list(analysis.get("function_reachability", []))
    maximum = analysis.get("max_reachable_call_depth")
    output: list[dict[str, Any]] = []
    for record in records:
        target = str(record["vulnerable_function"])
        matches = [
            item for item in functions
            if item.get("function") == target or item.get("function_id") == target
        ]
        unique = {str(item.get("function_id")): item for item in matches}
        if not unique:
            status, matched = "function_not_found", None
        elif len(unique) > 1:
            status, matched = "ambiguous_function_name", None
        else:
            status, matched = "mapped_exact", next(iter(unique.values()))
        depth = matched.get("call_depth") if matched else None
        normalized = (
            depth / maximum
            if isinstance(depth, int) and isinstance(maximum, int) and maximum > 0
            else None
        )
        output.append({
            "vulnerability_id": record["id"],
            "utility": record["utility"],
            "vulnerable_function": target,
            "mapping_status": status,
            "verified": record["verified"],
            "eligible_for_hvc": status == "mapped_exact" and record["verified"] is True,
            "mapped_function_id": matched.get("function_id") if matched else None,
            "call_depth": depth,
            "reachable_from_main": matched.get("reachable_from_entry") if matched else None,
            "total_reachable_functions": analysis.get("reachable_function_count"),
            "maximum_reachable_depth": maximum,
            "normalized_depth": normalized,
        })
    return output


def historical_vulnerability_coverage(
    analysis: Mapping[str, Any], mappings: Sequence[Mapping[str, Any]], *,
    policy: str, k: int | None = None, percent: float | None = None, seed: int = 1,
) -> dict[str, Any]:
    selection = select_functions(analysis, policy=policy, k=k, percent=percent, seed=seed)
    selected = set(selection["selected_functions"])
    valid = [item for item in mappings if item.get("eligible_for_hvc") is True]
    covered = [item for item in valid if item.get("mapped_function_id") in selected]
    denominator = len(valid)
    return {
        **selection,
        "historical_vulnerabilities_with_valid_mappings": denominator,
        "historical_vulnerabilities_covered": len(covered),
        "covered_vulnerability_ids": sorted(str(item["vulnerability_id"]) for item in covered),
        "historical_vulnerability_coverage_at_budget": len(covered) / denominator if denominator else None,
    }


def coverage_study(
    analysis: Mapping[str, Any], mappings: Sequence[Mapping[str, Any]], *,
    k_values: Iterable[int] = (), percent_values: Iterable[float] = (10, 25, 50, 100),
    random_seeds: Iterable[int] = (1,),
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seeds = list(random_seeds)
    if not seeds:
        raise ValueError("at least one random seed is required")
    budgets = [("k", value) for value in k_values] + [("percent", value) for value in percent_values]
    for kind, value in budgets:
        arguments = {kind: value}
        for policy in SELECTION_POLICIES:
            policy_seeds = seeds if policy == "RANDOM" else [None]
            for policy_seed in policy_seeds:
                rows.append(historical_vulnerability_coverage(
                    analysis, mappings, policy=policy,
                    seed=policy_seed if policy_seed is not None else 1,
                    **arguments,
                ))
    aggregates: list[dict[str, Any]] = []
    random_groups: dict[tuple[Any, Any], list[float]] = {}
    for row in rows:
        if row["selection_policy"] == "RANDOM" and row["historical_vulnerability_coverage_at_budget"] is not None:
            budget = row["selection_budget"]
            random_groups.setdefault((budget["k"], budget["percent"]), []).append(
                row["historical_vulnerability_coverage_at_budget"]
            )
    for (k_value, percent_value), values in random_groups.items():
        mean = statistics.fmean(values)
        half_width = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None
        aggregates.append({
            "selection_policy": "RANDOM",
            "selection_budget": {"k": k_value, "percent": percent_value},
            "repetitions": len(values),
            "mean_historical_vulnerability_coverage": mean,
            "normal_approximation_95pct_ci": (
                [max(0.0, mean - half_width), min(1.0, mean + half_width)]
                if half_width is not None else None
            ),
        })
    return {"coverage_rows": rows, "random_coverage_aggregates": aggregates}


def summarize_historical_analysis(mappings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    mapped = [item for item in mappings if item.get("mapping_status") == "mapped_exact"]
    eligible = [item for item in mapped if item.get("eligible_for_hvc") is True]
    depths = [item["call_depth"] for item in eligible if isinstance(item.get("call_depth"), int)]
    return {
        "historical_record_count": len(mappings),
        "mapped_vulnerability_count": len(mapped),
        "unmapped_vulnerability_count": len(mappings) - len(mapped),
        "verified_mapped_vulnerability_count": len(eligible),
        "unverified_mapped_vulnerability_count": len(mapped) - len(eligible),
        "reachable_mapped_vulnerability_count": len(depths),
        "vulnerability_depth_distribution": {
            str(depth): depths.count(depth) for depth in sorted(set(depths))
        },
        "mean_vulnerable_function_depth": statistics.fmean(depths) if depths else None,
        "median_vulnerable_function_depth": statistics.median(depths) if depths else None,
    }
