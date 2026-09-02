"""Version-specific historical function mapping and coverage metrics."""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from security.common.callgraph import SELECTION_POLICIES, analyze_source_tree, select_functions

SCHEMA_VERSION = 2
ALLOWED_UTILITIES = {"sort", "mkdir", "chmod", "grep"}
ALLOWED_PROJECTS = {"gnu-coreutils", "gnu-grep"}
REQUIRED_FIELDS = {
    "id": str, "utility": str, "upstream_project": str,
    "affected_version": str, "fixed_version": str, "source_revision": str,
    "vulnerable_function": str, "patched_functions": list, "cwe": str,
    "bug_type": str, "attacker_input": str, "source_reference": str,
    "patch_reference": str, "notes": str, "verified": bool,
}
MANIFEST_FIELDS = {
    "upstream_project": str, "affected_version": str, "source_revision": str,
    "source_tree": str, "source_tree_sha256": str,
}
MAPPED_STATES = {"mapped_and_reachable", "mapped_but_unreachable"}


class HistoricalDataError(ValueError):
    pass


def _validate_fields(value: Mapping[str, Any], fields: Mapping[str, type]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(value) - set(fields))
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    for field, expected in fields.items():
        if field not in value:
            errors.append(f"missing field: {field}")
        elif not isinstance(value[field], expected) or (
            expected is bool and type(value[field]) is not bool
        ):
            errors.append(f"{field} must be {expected.__name__}")
    return errors


def validate_record(record: Mapping[str, Any]) -> list[str]:
    errors = _validate_fields(record, REQUIRED_FIELDS)
    for field in ("id", "vulnerable_function", "source_revision"):
        if isinstance(record.get(field), str) and not record[field].strip():
            errors.append(f"{field} must not be empty")
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


def validate_manifest_entry(entry: Mapping[str, Any]) -> list[str]:
    errors = _validate_fields(entry, MANIFEST_FIELDS)
    for field in ("affected_version", "source_revision", "source_tree"):
        if isinstance(entry.get(field), str) and not entry[field].strip():
            errors.append(f"{field} must not be empty")
    if entry.get("upstream_project") not in ALLOWED_PROJECTS:
        errors.append("upstream_project must be gnu-coreutils or gnu-grep")
    fingerprint = entry.get("source_tree_sha256")
    if isinstance(fingerprint, str) and not (
        len(fingerprint) == 64
        and all(character in "0123456789abcdef" for character in fingerprint.lower())
    ):
        errors.append("source_tree_sha256 must be a 64-character hexadecimal digest")
    return errors


def validate_source_manifest(entries: Any) -> list[str]:
    if not isinstance(entries, list):
        return ["source manifest root must be an array"]
    errors: list[str] = []
    identities: set[tuple[str, str, str]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            errors.append(f"source {index}: must be an object")
            continue
        errors.extend(f"source {index}: {error}" for error in validate_manifest_entry(entry))
        identity = tuple(str(entry.get(field, "")) for field in (
            "upstream_project", "affected_version", "source_revision"
        ))
        if identity in identities:
            errors.append(f"source {index}: duplicate source identity: {'/'.join(identity)}")
        identities.add(identity)
    return errors


def _load_array(path: Path, validator: Any, label: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HistoricalDataError(f"cannot read {label}: {error}") from error
    errors = validator(raw)
    if errors:
        raise HistoricalDataError("; ".join(errors))
    return [dict(item) for item in raw]


def load_records(path: Path) -> list[dict[str, Any]]:
    return _load_array(path, validate_records, "historical dataset")


def load_source_manifest(path: Path) -> list[dict[str, Any]]:
    entries = _load_array(path, validate_source_manifest, "source manifest")
    for entry in entries:
        candidate = Path(entry["source_tree"])
        entry["resolved_source_tree"] = str(
            candidate.resolve() if candidate.is_absolute()
            else (path.parent / candidate).resolve()
        )
    return entries


def source_tree_sha256(source_tree: Path) -> str:
    """Fingerprint the C inputs used to construct a historical call graph."""
    digest = hashlib.sha256()
    for source in sorted(
        path for path in source_tree.rglob("*")
        if path.is_file() and path.suffix in {".c", ".h"}
    ):
        relative = source.relative_to(source_tree).as_posix().encode()
        contents = source.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def _identity(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(record["upstream_project"]), str(record["affected_version"]),
        str(record["source_revision"]),
    )


def _source_resolution(
    record: Mapping[str, Any], manifest: Sequence[Mapping[str, Any]],
) -> tuple[str, Mapping[str, Any] | None, str | None]:
    project_version = [
        item for item in manifest
        if item.get("upstream_project") == record["upstream_project"]
        and item.get("affected_version") == record["affected_version"]
    ]
    exact = [item for item in project_version if item.get("source_revision") == record["source_revision"]]
    if not exact:
        return (
            "source_version_mismatch" if project_version else "source_version_unavailable",
            None,
            "no manifest entry matches the record's exact source revision"
            if project_version else "no manifest entry matches the project and affected version",
        )
    if len(exact) != 1:
        return "source_version_mismatch", None, "source identity is not unique in the manifest"
    entry = exact[0]
    source_tree = Path(str(entry.get("resolved_source_tree", entry["source_tree"])))
    if not source_tree.is_dir():
        return "source_version_unavailable", entry, f"source tree is unavailable: {source_tree}"
    observed = source_tree_sha256(source_tree)
    if observed.lower() != str(entry["source_tree_sha256"]).lower():
        return "source_version_mismatch", entry, "source tree fingerprint does not match manifest metadata"
    return "source_version_matched", entry, None


def map_record_to_graph(
    record: Mapping[str, Any], analysis: Mapping[str, Any], *,
    source_analysis_id: str | None = None,
) -> dict[str, Any]:
    target = str(record["vulnerable_function"])
    matches = [
        item for item in analysis.get("function_reachability", [])
        if item.get("function") == target or item.get("function_id") == target
    ]
    unique = {str(item.get("function_id")): item for item in matches}
    if not unique:
        status, matched = "function_not_found", None
    elif len(unique) > 1:
        status, matched = "ambiguous_function_name", None
    else:
        matched = next(iter(unique.values()))
        status = (
            "mapped_and_reachable"
            if matched.get("reachable_from_entry") is True
            else "mapped_but_unreachable"
        )
    depth = matched.get("call_depth") if matched else None
    maximum = analysis.get("max_reachable_call_depth")
    normalized = (
        depth / maximum
        if isinstance(depth, int) and isinstance(maximum, int) and maximum > 0
        else None
    )
    return {
        "vulnerability_id": record["id"], "utility": record["utility"],
        "upstream_project": record["upstream_project"],
        "affected_version": record["affected_version"],
        "source_revision": record["source_revision"],
        "vulnerable_function": target,
        "source_version_status": "source_version_matched",
        "mapping_status": status, "verified": record["verified"],
        "eligible_for_hvc": record["verified"] is True and status in MAPPED_STATES,
        "source_analysis_id": source_analysis_id,
        "mapped_function_id": matched.get("function_id") if matched else None,
        "call_depth": depth,
        "reachable_from_main": matched.get("reachable_from_entry") if matched else None,
        "total_reachable_functions": analysis.get("reachable_function_count"),
        "diversification_eligible_function_count": analysis.get("diversification_eligible_function_count"),
        "maximum_reachable_depth": maximum,
        "normalized_depth": normalized,
    }


def _unevaluable_mapping(
    record: Mapping[str, Any], status: str, reason: str | None,
) -> dict[str, Any]:
    return {
        "vulnerability_id": record["id"], "utility": record["utility"],
        "upstream_project": record["upstream_project"],
        "affected_version": record["affected_version"],
        "source_revision": record["source_revision"],
        "vulnerable_function": record["vulnerable_function"],
        "source_version_status": status, "source_version_error": reason,
        "mapping_status": status, "verified": record["verified"],
        "eligible_for_hvc": False, "source_analysis_id": None,
        "mapped_function_id": None, "call_depth": None,
        "reachable_from_main": None, "total_reachable_functions": None,
        "diversification_eligible_function_count": None,
        "maximum_reachable_depth": None, "normalized_depth": None,
    }


def analyze_versioned_records(
    records: Sequence[Mapping[str, Any]], manifest: Sequence[Mapping[str, Any]], *,
    force_fallback: bool = False,
) -> dict[str, Any]:
    """Analyze every record against its exact vulnerable source identity."""
    cache: dict[tuple[str, str, str, str], tuple[str, dict[str, Any]]] = {}
    mappings: list[dict[str, Any]] = []
    graphs: dict[str, dict[str, Any]] = {}
    hits = 0
    for record in records:
        source_status, source, reason = _source_resolution(record, manifest)
        if source_status != "source_version_matched" or source is None:
            mappings.append(_unevaluable_mapping(record, source_status, reason))
            continue
        source_tree = Path(str(source.get("resolved_source_tree", source["source_tree"])))
        cache_key = (*_identity(record), str(source_tree))
        if cache_key in cache:
            analysis_id, graph = cache[cache_key]
            hits += 1
        else:
            analysis_id = hashlib.sha256(json.dumps({
                "identity": _identity(record), "source_tree": str(source_tree),
                "source_tree_sha256": source["source_tree_sha256"],
            }, sort_keys=True).encode()).hexdigest()
            graph = analyze_source_tree(source_tree, force_fallback=force_fallback)
            cache[cache_key] = (analysis_id, graph)
            graphs[analysis_id] = graph
        mapping = map_record_to_graph(record, graph, source_analysis_id=analysis_id)
        mapping["source_tree"] = str(source_tree)
        mapping["source_tree_sha256"] = source["source_tree_sha256"]
        mappings.append(mapping)
    return {
        "schema_version": SCHEMA_VERSION,
        "historical_function_mappings": mappings, "call_graphs": graphs,
        "call_graphs_constructed": len(graphs), "call_graph_cache_hits": hits,
    }


def version_specific_hvc(
    versioned: Mapping[str, Any], *, policy: str, k: int | None = None,
    percent: float | None = None, seed: int = 1,
    include_entry_points: bool = False,
) -> dict[str, Any]:
    mappings = list(versioned.get("historical_function_mappings", []))
    graphs = versioned.get("call_graphs", {})
    valid = [item for item in mappings if item.get("eligible_for_hvc") is True]
    details: list[dict[str, Any]] = []
    covered: list[str] = []
    for mapping in valid:
        selection = select_functions(
            graphs[mapping["source_analysis_id"]], policy=policy, k=k,
            percent=percent, seed=seed, include_entry_points=include_entry_points,
        )
        is_covered = mapping["mapped_function_id"] in set(selection["selected_functions"])
        if is_covered:
            covered.append(str(mapping["vulnerability_id"]))
        details.append({
            "vulnerability_id": mapping["vulnerability_id"],
            "source_revision": mapping["source_revision"],
            "source_analysis_id": mapping["source_analysis_id"],
            "mapped_function_id": mapping["mapped_function_id"],
            "covered": is_covered, **selection,
        })
    denominator = len(valid)
    return {
        "selection_policy": policy.upper(),
        "selection_seed": seed if policy.upper() == "RANDOM" else None,
        "include_entry_points": include_entry_points,
        "selection_budget": {"k": k, "percent": percent},
        "selection_budget_unit": "function_count",
        "historical_vulnerabilities_with_valid_version_specific_mappings": denominator,
        "historical_vulnerabilities_covered": len(covered),
        "covered_vulnerability_ids": sorted(covered),
        "historical_vulnerability_coverage_at_budget": len(covered) / denominator if denominator else None,
        "per_vulnerability_selections": details,
    }


def _percentile_bootstrap_ci(
    values: Sequence[float], *, seed: int = 0, replicates: int = 2000,
) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    means = sorted(
        statistics.fmean(rng.choice(values) for _ in values)
        for _ in range(replicates)
    )
    return [
        means[int(0.025 * (replicates - 1))],
        means[int(0.975 * (replicates - 1))],
    ]


def coverage_study(
    versioned: Mapping[str, Any], *, k_values: Iterable[int] = (),
    percent_values: Iterable[float] = (10, 25, 50, 100),
    random_seeds: Iterable[int] = (1,), include_entry_points: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seeds = list(random_seeds)
    if not seeds:
        raise ValueError("at least one random seed is required")
    budgets = [("k", value) for value in k_values] + [("percent", value) for value in percent_values]
    for kind, value in budgets:
        for policy in SELECTION_POLICIES:
            for policy_seed in (seeds if policy == "RANDOM" else [1]):
                rows.append(version_specific_hvc(
                    versioned, policy=policy, seed=policy_seed,
                    include_entry_points=include_entry_points, **{kind: value},
                ))
    aggregates: list[dict[str, Any]] = []
    random_groups: dict[tuple[Any, Any], list[float]] = {}
    for row in rows:
        value = row["historical_vulnerability_coverage_at_budget"]
        if row["selection_policy"] == "RANDOM" and value is not None:
            budget = row["selection_budget"]
            random_groups.setdefault((budget["k"], budget["percent"]), []).append(value)
    for (k_value, percent_value), values in random_groups.items():
        aggregates.append({
            "selection_policy": "RANDOM",
            "selection_budget": {"k": k_value, "percent": percent_value},
            "selection_budget_unit": "function_count", "repetitions": len(values),
            "mean_historical_vulnerability_coverage": statistics.fmean(values),
            "percentile_bootstrap_95pct_ci": _percentile_bootstrap_ci(values),
            "bootstrap_seed": 0, "bootstrap_replicates": 2000,
        })
    return {"coverage_rows": rows, "random_coverage_aggregates": aggregates}


def summarize_historical_analysis(mappings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(item.get("mapping_status")) for item in mappings)
    valid = [item for item in mappings if item.get("eligible_for_hvc") is True]
    depths = [item["call_depth"] for item in valid if isinstance(item.get("call_depth"), int)]
    return {
        "historical_record_count": len(mappings),
        "mapping_status_counts": dict(sorted(status_counts.items())),
        "valid_version_specific_mapping_count": len(valid),
        "unverified_record_count": sum(item.get("verified") is not True for item in mappings),
        "reachable_mapped_vulnerability_count": len(depths),
        "vulnerability_depth_distribution": {
            str(depth): depths.count(depth) for depth in sorted(set(depths))
        },
        "mean_vulnerable_function_depth": statistics.fmean(depths) if depths else None,
        "median_vulnerable_function_depth": statistics.median(depths) if depths else None,
    }
