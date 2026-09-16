#!/usr/bin/env python3
"""Localize frozen generated static findings and descriptors by raw call depth."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scripts.analysis.security_diagnostics import (  # noqa: E402
    CONSTRUCT_FIELDS,
    FLAWFINDER_FINDING_FIELDS,
    PINNED_FLAWFINDER_VERSION,
    default_security_configuration,
    flawfinder_crosscheck,
    flawfinder_provenance,
    security_configuration_fingerprint,
    security_descriptor_occurrences,
    security_profile,
    validate_security_configuration,
)
from security.common.callgraph import (  # noqa: E402
    CALL_GRAPH_SCHEMA_VERSION,
    analyze_source_bytes,
)
from security.generated_structural_census import (  # noqa: E402
    CensusError,
    content_sha256,
    load_manifest,
    repository_candidate_bytes,
    run_census,
)

SCHEMA_VERSION = 1
FROZEN_CANDIDATE_POPULATION_SHA256 = (
    "a9fc9f1a8e42e00760a75589922feb9e889c0b8a14783572d578b55fd61f04c3"
)
FROZEN_STRUCTURAL_CENSUS_SHA256 = (
    "fe29f2be62855692c21e2a9e97c4fb337698fec695cfe5484b765afe74ab33b2"
)
FROZEN_SECURITY_CONFIGURATION_SHA256 = (
    "fe1ac9b4d58313bde6231d02814e040dcba8caa7f85092845aaf6c9c2b465488"
)
MAPPING_STATES = (
    "outside_function",
    "mapped_without_numeric_depth",
    "ambiguous_function",
    "invalid_source_location",
)
OUTPUT_FILES = {
    "summary": "generated_security_depth_summary.json",
    "environment": "generated_security_depth_environment.json",
    "candidates": "generated_security_depth_candidates.csv",
    "findings": "generated_flawfinder_findings_by_depth.csv",
    "descriptors": "generated_security_descriptor_occurrences_by_depth.csv",
    "opportunity": "generated_security_depth_function_opportunity.csv",
    "finding_summary": "generated_flawfinder_depth_summary.csv",
    "descriptor_summary": "generated_security_descriptor_depth_summary.csv",
}


class LocalizationError(ValueError):
    """Fail-closed frozen-population localization error."""


def _package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _source_lines(source: bytes) -> list[str]:
    """Decode the UTF-8 candidate bytes using Flawfinder-compatible line units."""
    return source.decode("utf-8").splitlines()


def flawfinder_position_to_tree_sitter(
    source: bytes, line: Any, column: Any
) -> tuple[int | None, int | None, str | None]:
    """Convert Flawfinder 1-based character positions to Tree-sitter points.

    Flawfinder 2.0.20 initializes line numbering at one and its ``find_column``
    returns a one-based Python string-character column.  Tree-sitter points use
    zero-based rows and UTF-8 byte columns.  The returned point therefore uses
    zero-based Tree-sitter conventions.
    """
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        return None, None, "line_must_be_a_positive_one_based_integer"
    if isinstance(column, bool) or not isinstance(column, int) or column < 1:
        return None, None, "column_must_be_a_positive_one_based_integer"
    try:
        lines = _source_lines(source)
    except UnicodeDecodeError:
        return None, None, "candidate_source_is_not_utf8"
    if line > len(lines):
        return None, None, "line_exceeds_candidate_source"
    text = lines[line - 1]
    if column > len(text):
        return None, None, "column_exceeds_candidate_source_line"
    byte_column = len(text[: column - 1].encode("utf-8"))
    return line - 1, byte_column, None


def _point_in_function(row: int, column: int, function: Mapping[str, Any]) -> bool:
    start_row = int(function["start_line"]) - 1
    end_row = int(function["end_line"]) - 1
    start_column = function.get("start_column")
    end_column = function.get("end_column")
    if not isinstance(start_column, int) or not isinstance(end_column, int):
        return False
    return (row, column) >= (start_row, start_column) and (
        row, column
    ) < (end_row, end_column)


def _mapped_fields(function: Mapping[str, Any]) -> dict[str, Any]:
    depth = function.get("call_depth")
    numeric = isinstance(depth, int) and not isinstance(depth, bool)
    return {
        "function_mapping_status": (
            "mapped" if numeric else "mapped_without_numeric_depth"
        ),
        "function_mapping_reason": None,
        "function_id": function.get("function_id"),
        "function_name": function.get("function"),
        "function_start_line": function.get("start_line"),
        "function_end_line": function.get("end_line"),
        "raw_call_depth": depth if numeric else None,
        "reachable_from_entry": function.get("reachable_from_entry"),
        "entry_point": function.get("function_id") in set(
            function.get("_resolved_entry_points", [])
        ),
        "shortest_call_path": function.get("shortest_call_path"),
    }


def _unmapped_fields(status: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "function_mapping_status": status,
        "function_mapping_reason": reason,
        "function_id": None,
        "function_name": None,
        "function_start_line": None,
        "function_end_line": None,
        "raw_call_depth": None,
        "reachable_from_entry": None,
        "entry_point": None,
        "shortest_call_path": None,
    }


def localize_source_position(
    *,
    source: bytes,
    line: Any,
    column: Any,
    functions: Sequence[Mapping[str, Any]],
    column_semantics: str,
) -> dict[str, Any]:
    """Conservatively map a valid source position to one parsed function."""
    if column_semantics == "flawfinder_one_based_character":
        row, byte_column, invalid = flawfinder_position_to_tree_sitter(
            source, line, column
        )
    elif column_semantics == "tree_sitter_one_based_byte":
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            row, byte_column, invalid = None, None, "invalid_tree_sitter_line"
        elif isinstance(column, bool) or not isinstance(column, int) or column < 1:
            row, byte_column, invalid = None, None, "invalid_tree_sitter_column"
        else:
            lines = source.splitlines()
            if line > len(lines) or column - 1 > len(lines[line - 1]):
                row, byte_column, invalid = None, None, "tree_sitter_position_out_of_range"
            else:
                row, byte_column, invalid = line - 1, column - 1, None
    else:
        raise LocalizationError(f"unsupported column semantics: {column_semantics}")
    if invalid is not None:
        return _unmapped_fields("invalid_source_location", invalid)

    line_candidates = [
        function
        for function in functions
        if int(function["start_line"]) <= int(line) <= int(function["end_line"])
    ]
    if not line_candidates:
        return _unmapped_fields("outside_function")
    if len(line_candidates) == 1:
        return _mapped_fields(line_candidates[0])

    # Columns are consulted only when line containment is ambiguous.  The
    # conversion above makes the Flawfinder/Tree-sitter unit difference explicit.
    point_candidates = [
        function
        for function in line_candidates
        if _point_in_function(int(row), int(byte_column), function)
    ]
    if len(point_candidates) == 1:
        return _mapped_fields(point_candidates[0])
    if not point_candidates:
        return _unmapped_fields(
            "outside_function", "column_outside_same_line_function_spans"
        )
    return _unmapped_fields(
        "ambiguous_function", "multiple_function_spans_contain_source_position"
    )


def _function_signature(function: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        function.get("function_id"),
        function.get("function"),
        function.get("source_file"),
        function.get("start_line"),
        function.get("end_line"),
        function.get("call_depth"),
        function.get("reachable_from_entry"),
    )


def _analyze_candidate_functions(
    candidate: Mapping[str, Any], repo: Path, structural_functions: Sequence[Mapping[str, Any]]
) -> tuple[bytes, list[dict[str, Any]]]:
    source, _ = repository_candidate_bytes(repo, str(candidate["candidate_source"]))
    actual = hashlib.sha256(source).hexdigest()
    if actual != candidate["candidate_source_sha256"]:
        raise LocalizationError(
            f"{candidate['candidate_id']}: candidate source hash mismatch"
        )
    analysis = analyze_source_bytes(
        source,
        source_file=PurePosixPath(str(candidate["candidate_source"])).name,
        include_source_columns=True,
    )
    if analysis.get("analysis_method") != "tree_sitter":
        raise LocalizationError(
            f"{candidate['candidate_id']}: localization requires tree_sitter; "
            f"used {analysis.get('analysis_method')}"
        )
    resolved_entries = list(analysis.get("resolved_entry_points", []))
    functions = []
    for raw in analysis.get("function_reachability", []):
        function = dict(raw)
        function["_resolved_entry_points"] = resolved_entries
        functions.append(function)
    expected = sorted(
        (
            row.get("function_id"), row.get("function"), row.get("source_file"),
            row.get("start_line"), row.get("end_line"), row.get("call_depth"),
            row.get("reachable_from_entry"),
        )
        for row in structural_functions
    )
    observed = sorted(_function_signature(function) for function in functions)
    if observed != expected:
        raise LocalizationError(
            f"{candidate['candidate_id']}: reconstructed function identity/span/depth "
            "does not match the structural census"
        )
    return source, functions


def _scan_source_bytes(
    source: bytes,
    candidate: Mapping[str, Any],
    configuration: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    basename = PurePosixPath(str(candidate["candidate_source"])).name
    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / basename
        source_path.write_bytes(source)
        return flawfinder_crosscheck(
            source_path,
            run_id=str(candidate["candidate_id"]),
            source_identifier=str(candidate["candidate_source"]),
            configuration=configuration,
            provenance=provenance,
        )


def _load_reused_findings(
    reuse_dir: Path,
    *,
    manifest: Mapping[str, Any],
    structural_sha256: str,
    configuration_sha256: str,
    formal: bool,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], str]:
    path = reuse_dir / OUTPUT_FILES["summary"]
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LocalizationError(f"cannot load reused localization {path}: {error}") from error
    if prior.get("candidate_population_sha256") != manifest["candidate_population_sha256"]:
        raise LocalizationError("reused findings have a different candidate population")
    if prior.get("structural_census_sha256") != structural_sha256:
        raise LocalizationError("reused findings have a different structural census")
    if prior.get("security_configuration_sha256") != configuration_sha256:
        raise LocalizationError("reused findings have a different security configuration")
    if prior.get("flawfinder_version") != PINNED_FLAWFINDER_VERSION:
        raise LocalizationError("reused findings were not produced by Flawfinder 2.0.20")
    if formal and prior.get("formal_analysis") is not True:
        raise LocalizationError("formal localization cannot reuse a development result")
    science = prior.get("scientific_results") or {}
    candidate_rows = {
        str(row["candidate_id"]): dict(row)
        for row in science.get("candidate_rows", [])
    }
    findings: dict[str, list[dict[str, Any]]] = {
        str(candidate["candidate_id"]): [] for candidate in manifest["candidates"]
    }
    candidates_by_id = {
        str(candidate["candidate_id"]): candidate for candidate in manifest["candidates"]
    }
    for localized in science.get("finding_rows", []):
        identifier = str(localized.get("candidate_id"))
        if identifier not in findings:
            raise LocalizationError(f"reused findings contain unknown candidate {identifier}")
        original = {
            field: localized.get(field) for field in FLAWFINDER_FINDING_FIELDS
        }
        if original["run_id"] != identifier:
            raise LocalizationError(f"{identifier}: reused finding run identity differs")
        if original["source_identifier"] != candidates_by_id[identifier]["candidate_source"]:
            raise LocalizationError(f"{identifier}: reused finding source identity differs")
        if original["tool_version"] != PINNED_FLAWFINDER_VERSION:
            raise LocalizationError(f"{identifier}: reused finding tool version differs")
        findings[identifier].append(original)
    if set(candidate_rows) != set(findings):
        raise LocalizationError("reused localization candidate coverage is incomplete")
    for identifier, row in candidate_rows.items():
        if row.get("candidate_sha256") != next(
            candidate["candidate_source_sha256"]
            for candidate in manifest["candidates"]
            if candidate["candidate_id"] == identifier
        ):
            raise LocalizationError(f"{identifier}: reused candidate hash differs")
        expected = row.get("flawfinder_finding_count")
        if row.get("flawfinder_status") == "available" and expected != len(findings[identifier]):
            raise LocalizationError(f"{identifier}: reused finding count does not reconcile")
        if row.get("flawfinder_status") != "available" and findings[identifier]:
            raise LocalizationError(f"{identifier}: unavailable reused scan has finding rows")
    return findings, candidate_rows, str(prior["flawfinder_version"])


def _candidate_base(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "utility": candidate["utility"],
        "checkpoint": candidate["checkpoint_id"],
        "checkpoint_name": candidate["checkpoint_name"],
        "lineage": candidate["lineage_id"],
        "formal_run_id": candidate["formal_run_id"],
        "source_identifier": candidate["candidate_source"],
        "candidate_sha256": candidate["candidate_source_sha256"],
    }


def _localize_findings(
    findings: Sequence[Mapping[str, Any]],
    candidate: Mapping[str, Any],
    source: bytes,
    functions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    base = _candidate_base(candidate)
    rows = []
    for finding in findings:
        original = {field: finding.get(field) for field in FLAWFINDER_FINDING_FIELDS}
        mapping = localize_source_position(
            source=source,
            line=original["line"],
            column=original["column"],
            functions=functions,
            column_semantics="flawfinder_one_based_character",
        )
        rows.append({**base, **original, **mapping})
    return sorted(
        rows,
        key=lambda row: (
            str(row["candidate_id"]), int(row["line"]), int(row["column"]),
            str(row.get("flawfinder_fingerprint") or ""),
        ),
    )


def _localize_descriptors(
    candidate: Mapping[str, Any],
    source: bytes,
    functions: Sequence[Mapping[str, Any]],
    configuration: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    occurrences = security_descriptor_occurrences(source, configuration)
    profile = security_profile(source, configuration)
    reconstructed = Counter(str(row["descriptor"]) for row in occurrences)
    if profile != {field: reconstructed[field] for field in CONSTRUCT_FIELDS}:
        raise LocalizationError(
            f"{candidate['candidate_id']}: occurrence counts do not reconstruct security_profile"
        )
    base = _candidate_base(candidate)
    rows = []
    for occurrence in occurrences:
        mapping = localize_source_position(
            source=source,
            line=occurrence["line"],
            column=occurrence["column"],
            functions=functions,
            column_semantics="tree_sitter_one_based_byte",
        )
        rows.append({
            **base,
            "descriptor": occurrence["descriptor"],
            "specific_symbol": occurrence.get("call_name"),
            "line": occurrence["line"],
            "column": occurrence["column"],
            **mapping,
        })
    rows.sort(key=lambda row: (
        str(row["candidate_id"]), int(row["line"]), int(row["column"]),
        str(row["descriptor"]), str(row.get("specific_symbol") or ""),
    ))
    return rows, profile


def _groups(candidate_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups = [{
        "group_type": "overall", "utility": None, "checkpoint": None,
        "candidate_ids": {str(row["candidate_id"]) for row in candidate_rows},
    }]
    utilities = sorted({str(row["utility"]) for row in candidate_rows})
    checkpoints = sorted({str(row["checkpoint"]) for row in candidate_rows})
    for utility in utilities:
        groups.append({
            "group_type": "utility", "utility": utility, "checkpoint": None,
            "candidate_ids": {
                str(row["candidate_id"]) for row in candidate_rows
                if row["utility"] == utility
            },
        })
    for checkpoint in checkpoints:
        groups.append({
            "group_type": "stage", "utility": None, "checkpoint": checkpoint,
            "candidate_ids": {
                str(row["candidate_id"]) for row in candidate_rows
                if str(row["checkpoint"]) == checkpoint
            },
        })
    for utility in utilities:
        utility_checkpoints = sorted({
            str(row["checkpoint"]) for row in candidate_rows
            if row["utility"] == utility
        })
        for checkpoint in utility_checkpoints:
            groups.append({
                "group_type": "utility_stage", "utility": utility,
                "checkpoint": checkpoint,
                "candidate_ids": {
                    str(row["candidate_id"]) for row in candidate_rows
                    if row["utility"] == utility
                    and str(row["checkpoint"]) == checkpoint
                },
            })
    return groups


def _depth_category(row: Mapping[str, Any]) -> str:
    depth = row.get("raw_call_depth")
    return str(depth) if isinstance(depth, int) and not isinstance(depth, bool) else str(
        row["function_mapping_status"]
    )


def aggregate_localization(
    candidate_rows: Sequence[Mapping[str, Any]],
    structural_functions: Sequence[Mapping[str, Any]],
    finding_rows: Sequence[Mapping[str, Any]],
    descriptor_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    numeric_depths = sorted({
        int(row["call_depth"])
        for row in structural_functions
        if isinstance(row.get("call_depth"), int)
        and not isinstance(row.get("call_depth"), bool)
    })
    depth_categories = [*(str(depth) for depth in numeric_depths), *MAPPING_STATES]
    opportunities: list[dict[str, Any]] = []
    finding_summary: list[dict[str, Any]] = []
    descriptor_summary: list[dict[str, Any]] = []
    for group in _groups(candidate_rows):
        ids = group["candidate_ids"]
        candidates = [row for row in candidate_rows if row["candidate_id"] in ids]
        eligible = len(candidates)
        structural_measured = sum(row["structural_status"] == "available" for row in candidates)
        flawfinder_measured = sum(row["flawfinder_status"] == "available" for row in candidates)
        descriptor_measured = sum(row["descriptor_status"] == "available" for row in candidates)
        group_functions = [row for row in structural_functions if row["candidate_id"] in ids]
        group_findings = [row for row in finding_rows if row["candidate_id"] in ids]
        group_descriptors = [row for row in descriptor_rows if row["candidate_id"] in ids]
        opportunity_by_depth: dict[str, dict[str, Any]] = {}
        label = {
            "group_type": group["group_type"],
            "utility": group["utility"],
            "checkpoint": group["checkpoint"],
        }
        for depth in numeric_depths:
            at_depth = [row for row in group_functions if row.get("call_depth") == depth]
            ast_complete = all(isinstance(row.get("ast_node_count"), int) for row in at_depth)
            candidates_at_depth = {str(row["candidate_id"]) for row in at_depth}
            opportunity = {
                **label,
                "raw_call_depth": depth,
                "eligible_candidate_count": eligible,
                "measured_candidate_count": structural_measured,
                "measurement_coverage": structural_measured / eligible if eligible else None,
                "function_count": len(at_depth),
                "candidate_count_with_depth": len(candidates_at_depth),
                "candidate_prevalence_with_depth": (
                    len(candidates_at_depth) / eligible
                    if eligible and structural_measured == eligible else None
                ),
                "physical_LOC": sum(int(row.get("lines_of_code") or 0) for row in at_depth),
                "AST_node_count": (
                    sum(int(row["ast_node_count"]) for row in at_depth)
                    if ast_complete else None
                ),
            }
            opportunities.append(opportunity)
            opportunity_by_depth[str(depth)] = opportunity
        for category in depth_categories:
            at_depth = [row for row in group_findings if _depth_category(row) == category]
            candidate_ids = {str(row["candidate_id"]) for row in at_depth}
            levels = Counter(str(row["level"]) for row in at_depth)
            cwes = Counter(
                cwe
                for row in at_depth
                for cwe in json.loads(row.get("cwe_ids") or "[]")
            )
            opportunity = opportunity_by_depth.get(category)
            function_count = opportunity["function_count"] if opportunity else None
            loc = opportunity["physical_LOC"] if opportunity else None
            complete = flawfinder_measured == eligible and structural_measured == eligible
            finding_summary.append({
                **label,
                "depth_category": category,
                "eligible_candidate_count": eligible,
                "measured_candidate_count": flawfinder_measured,
                "measurement_coverage": flawfinder_measured / eligible if eligible else None,
                "finding_count": len(at_depth),
                "candidates_with_at_least_one_finding": len(candidate_ids),
                "candidate_prevalence": (
                    len(candidate_ids) / eligible
                    if eligible and flawfinder_measured == eligible else None
                ),
                "flawfinder_level_counts": dict(sorted(levels.items(), key=lambda item: int(item[0]))),
                "distinct_CWE_count": len(cwes),
                "CWE_occurrence_counts": dict(sorted(cwes.items())),
                "function_count_denominator": function_count,
                "physical_LOC_denominator": loc,
                "findings_per_100_functions": (
                    100.0 * len(at_depth) / function_count
                    if complete and function_count else None
                ),
                "findings_per_KLOC_at_depth": (
                    1000.0 * len(at_depth) / loc if complete and loc else None
                ),
            })
        for descriptor in CONSTRUCT_FIELDS:
            for category in depth_categories:
                at_depth = [
                    row for row in group_descriptors
                    if row["descriptor"] == descriptor
                    and _depth_category(row) == category
                ]
                candidate_ids = {str(row["candidate_id"]) for row in at_depth}
                opportunity = opportunity_by_depth.get(category)
                function_count = opportunity["function_count"] if opportunity else None
                loc = opportunity["physical_LOC"] if opportunity else None
                complete = descriptor_measured == eligible and structural_measured == eligible
                descriptor_summary.append({
                    **label,
                    "descriptor": descriptor,
                    "depth_category": category,
                    "eligible_candidate_count": eligible,
                    "measured_candidate_count": descriptor_measured,
                    "measurement_coverage": descriptor_measured / eligible if eligible else None,
                    "occurrence_count": len(at_depth),
                    "candidates_with_at_least_one_occurrence": len(candidate_ids),
                    "candidate_prevalence": (
                        len(candidate_ids) / eligible
                        if eligible and descriptor_measured == eligible else None
                    ),
                    "function_count_denominator": function_count,
                    "physical_LOC_denominator": loc,
                    "occurrences_per_100_functions": (
                        100.0 * len(at_depth) / function_count
                        if complete and function_count else None
                    ),
                    "occurrences_per_KLOC_at_depth": (
                        1000.0 * len(at_depth) / loc if complete and loc else None
                    ),
                })
    return opportunities, finding_summary, descriptor_summary


def run_localization(
    manifest: Mapping[str, Any],
    repo: Path,
    *,
    security_configuration: Mapping[str, Any] | None = None,
    formal: bool = False,
    host_role: str = "other",
    explicit_executable: str | Path | None = None,
    reuse_dir: Path | None = None,
    force_fallback: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if formal and host_role != "vessel":
        raise LocalizationError("formal localization requires --host-role vessel")
    if force_fallback:
        # Retained as an explicit test hook. Localization never accepts fallback.
        raise LocalizationError("security-depth localization requires tree_sitter; fallback rejected")
    configuration = validate_security_configuration(
        security_configuration or default_security_configuration()
    )
    configuration_sha256 = security_configuration_fingerprint(configuration)
    if configuration_sha256 != FROZEN_SECURITY_CONFIGURATION_SHA256:
        raise LocalizationError(
            "security-depth localization requires the frozen security "
            f"configuration {FROZEN_SECURITY_CONFIGURATION_SHA256}; got "
            f"{configuration_sha256}"
        )
    try:
        structural, _ = run_census(
            manifest, repo, formal=formal, host_role=host_role, force_fallback=False
        )
    except CensusError as error:
        raise LocalizationError(str(error)) from error
    structural_sha256 = str(structural["structural_census_sha256"])
    if manifest["candidate_population_sha256"] == FROZEN_CANDIDATE_POPULATION_SHA256:
        if structural_sha256 != FROZEN_STRUCTURAL_CENSUS_SHA256:
            raise LocalizationError(
                "frozen structural census changed: expected "
                f"{FROZEN_STRUCTURAL_CENSUS_SHA256}, got {structural_sha256}"
            )
    science_structure = structural["scientific_results"]
    structural_candidates = {
        str(row["candidate_id"]): row for row in science_structure["candidate_rows"]
    }
    structural_functions_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for row in science_structure["function_rows"]:
        structural_functions_by_candidate.setdefault(str(row["candidate_id"]), []).append(row)

    scanner = flawfinder_provenance(configuration, explicit_executable)
    reused_findings: dict[str, list[dict[str, Any]]] | None = None
    reused_candidates: dict[str, dict[str, Any]] = {}
    flawfinder_version = scanner.get("version")
    if reuse_dir is not None:
        reused_findings, reused_candidates, flawfinder_version = _load_reused_findings(
            reuse_dir,
            manifest=manifest,
            structural_sha256=structural_sha256,
            configuration_sha256=configuration_sha256,
            formal=formal,
        )

    candidate_rows: list[dict[str, Any]] = []
    finding_rows: list[dict[str, Any]] = []
    descriptor_rows: list[dict[str, Any]] = []
    for candidate in manifest["candidates"]:
        identifier = str(candidate["candidate_id"])
        base = _candidate_base(candidate)
        structural_row = structural_candidates[identifier]
        row = {
            **base,
            "structural_status": "unavailable",
            "structural_unavailable_reason": structural_row.get("unavailable_reason"),
            "analysis_method": structural_row.get("analysis_method"),
            "descriptor_status": "unavailable",
            "descriptor_unavailable_reason": None,
            "descriptor_occurrence_count": None,
            "flawfinder_status": "unavailable",
            "flawfinder_unavailable_reason": None,
            "flawfinder_finding_count": None,
        }
        if structural_row.get("analysis_status") != "analyzed":
            reason = str(structural_row.get("unavailable_reason"))
            row["descriptor_unavailable_reason"] = reason
            row["flawfinder_unavailable_reason"] = reason
            candidate_rows.append(row)
            continue
        try:
            source, functions = _analyze_candidate_functions(
                candidate, repo, structural_functions_by_candidate.get(identifier, [])
            )
        except (OSError, UnicodeError, LocalizationError) as error:
            row["structural_unavailable_reason"] = str(error)
            row["descriptor_unavailable_reason"] = str(error)
            row["flawfinder_unavailable_reason"] = str(error)
            candidate_rows.append(row)
            continue
        row["structural_status"] = "available"
        row["structural_unavailable_reason"] = None
        row["analysis_method"] = "tree_sitter"
        try:
            localized_descriptors, profile = _localize_descriptors(
                candidate, source, functions, configuration
            )
        except Exception as error:
            row["descriptor_unavailable_reason"] = f"descriptor_localization_failed: {error}"
        else:
            row["descriptor_status"] = "available"
            row["descriptor_occurrence_count"] = len(localized_descriptors)
            row.update(profile)
            descriptor_rows.extend(localized_descriptors)

        if reused_findings is not None:
            prior = reused_candidates[identifier]
            scan_status = prior.get("flawfinder_status")
            scan_reason = prior.get("flawfinder_unavailable_reason")
            findings = reused_findings[identifier] if scan_status == "available" else []
        else:
            scan = _scan_source_bytes(
                source, candidate, configuration, scanner
            )
            scan_status = scan["status"]
            scan_reason = scan["reason"]
            findings = list(scan.get("findings") or [])
        row["flawfinder_status"] = scan_status
        row["flawfinder_unavailable_reason"] = scan_reason
        if scan_status == "available":
            row["flawfinder_finding_count"] = len(findings)
            finding_rows.extend(_localize_findings(findings, candidate, source, functions))
        candidate_rows.append(row)

    candidate_rows.sort(key=lambda row: str(row["candidate_id"]))
    finding_rows.sort(key=lambda row: (
        str(row["candidate_id"]), int(row["line"]), int(row["column"]),
        str(row.get("flawfinder_fingerprint") or ""),
    ))
    descriptor_rows.sort(key=lambda row: (
        str(row["candidate_id"]), int(row["line"]), int(row["column"]),
        str(row["descriptor"]), str(row.get("specific_symbol") or ""),
    ))
    opportunities, finding_summary, descriptor_summary = aggregate_localization(
        candidate_rows, science_structure["function_rows"], finding_rows, descriptor_rows
    )
    scientific = {
        "schema_version": SCHEMA_VERSION,
        "candidate_population_sha256": manifest["candidate_population_sha256"],
        "structural_census_sha256": structural_sha256,
        "security_configuration_sha256": configuration_sha256,
        "security_configuration": configuration,
        "flawfinder_version": flawfinder_version,
        "call_graph_schema_version": CALL_GRAPH_SCHEMA_VERSION,
        "tree_sitter_required": True,
        "tree_sitter_version": _package_version("tree-sitter"),
        "tree_sitter_c_version": _package_version("tree-sitter-c"),
        "measurement_universe_definition": (
            "all statically reachable functions with numeric raw call depth, including configured entry points"
        ),
        "finding_line_column_semantics": (
            "Flawfinder 2.0.20 line and column are one-based; columns count decoded "
            "characters and are converted to Tree-sitter zero-based UTF-8 byte columns "
            "only to disambiguate multiple line-containing function spans"
        ),
        "descriptor_line_column_semantics": (
            "one-based line and one-based UTF-8 byte column derived from Tree-sitter points"
        ),
        "candidate_rows": candidate_rows,
        "finding_rows": finding_rows,
        "descriptor_occurrence_rows": descriptor_rows,
        "function_opportunity_rows": opportunities,
        "finding_depth_summary_rows": finding_summary,
        "descriptor_depth_summary_rows": descriptor_summary,
    }
    localization_sha256 = content_sha256(scientific)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "formal_analysis": formal,
        "candidate_population_sha256": manifest["candidate_population_sha256"],
        "structural_census_sha256": structural_sha256,
        "security_configuration_sha256": configuration_sha256,
        "flawfinder_version": flawfinder_version,
        "security_depth_localization_sha256": localization_sha256,
        "scientific_results": scientific,
    }
    environment = {
        "schema_version": SCHEMA_VERSION,
        "execution_role": (
            "formal_vessel_security_depth_localization"
            if formal else "development_reproducibility_security_depth_localization"
        ),
        "host_role": host_role,
        "host_name": platform.node(),
        "absolute_working_directory": str(repo.resolve()),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "repository_commit_sha": _repository_commit(repo),
        "flawfinder_executable_path": scanner.get("executable_path"),
        "flawfinder_status": scanner.get("status") if reuse_dir is None else "reused",
        "flawfinder_unavailable_reason": scanner.get("reason") if reuse_dir is None else None,
        "finding_origin": "reused" if reuse_dir is not None else "deterministically_reproduced",
        "reused_localization_directory": str(reuse_dir.resolve()) if reuse_dir else None,
        "tree_sitter_version": _package_version("tree-sitter"),
        "tree_sitter_c_version": _package_version("tree-sitter-c"),
    }
    return summary, environment


def _repository_commit(repo: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fields = sorted({key for row in materialized for key in row})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in materialized:
            writer.writerow({key: _csv_value(value) for key, value in row.items()})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_outputs(
    output_dir: Path, summary: Mapping[str, Any], environment: Mapping[str, Any]
) -> None:
    science = summary["scientific_results"]
    write_json(output_dir / OUTPUT_FILES["summary"], summary)
    write_json(output_dir / OUTPUT_FILES["environment"], environment)
    write_csv(output_dir / OUTPUT_FILES["candidates"], science["candidate_rows"])
    write_csv(output_dir / OUTPUT_FILES["findings"], science["finding_rows"])
    write_csv(output_dir / OUTPUT_FILES["descriptors"], science["descriptor_occurrence_rows"])
    write_csv(output_dir / OUTPUT_FILES["opportunity"], science["function_opportunity_rows"])
    write_csv(output_dir / OUTPUT_FILES["finding_summary"], science["finding_depth_summary_rows"])
    write_csv(output_dir / OUTPUT_FILES["descriptor_summary"], science["descriptor_depth_summary_rows"])


def compare_summaries(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    left_environment: Mapping[str, Any] | None = None,
    right_environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    scientific_identical = (
        left.get("scientific_results") == right.get("scientific_results")
        and left.get("security_depth_localization_sha256")
        == right.get("security_depth_localization_sha256")
    )
    environment_differences = []
    if left_environment is not None and right_environment is not None:
        for field in sorted(set(left_environment) | set(right_environment)):
            if left_environment.get(field) != right_environment.get(field):
                environment_differences.append({
                    "field": field,
                    "left": left_environment.get(field),
                    "right": right_environment.get(field),
                })
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_population_identical": (
            left.get("candidate_population_sha256")
            == right.get("candidate_population_sha256")
        ),
        "structural_census_identical": (
            left.get("structural_census_sha256")
            == right.get("structural_census_sha256")
        ),
        "scientific_results_identical": scientific_identical,
        "left_security_depth_localization_sha256": left.get(
            "security_depth_localization_sha256"
        ),
        "right_security_depth_localization_sha256": right.get(
            "security_depth_localization_sha256"
        ),
        "environment_differences": environment_differences,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LocalizationError(f"{path} is not a JSON object")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    localize = subparsers.add_parser("localize", help="localize the frozen manifest")
    localize.add_argument("--repo-root", type=Path, default=REPO)
    localize.add_argument("--manifest", type=Path, required=True)
    localize.add_argument(
        "--security-config", type=Path,
        default=REPO / "scripts/security-analysis-config-v1.json",
    )
    localize.add_argument("--output-dir", type=Path, required=True)
    localize.add_argument("--host-role", choices=("wsl", "vessel", "other"), default="other")
    localize.add_argument("--formal", action="store_true")
    localize.add_argument("--flawfinder-executable", type=Path)
    localize.add_argument("--reuse-localization-dir", type=Path)

    compare = subparsers.add_parser("compare", help="compare scientific localization outputs")
    compare.add_argument("--left-dir", type=Path, required=True)
    compare.add_argument("--right-dir", type=Path, required=True)
    compare.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "localize":
        manifest = load_manifest(args.manifest)
        try:
            security_configuration = json.loads(
                args.security_config.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise LocalizationError(
                f"cannot read security configuration {args.security_config}: {error}"
            ) from error
        summary, environment = run_localization(
            manifest,
            args.repo_root.resolve(),
            security_configuration=security_configuration,
            formal=args.formal,
            host_role=args.host_role,
            explicit_executable=args.flawfinder_executable,
            reuse_dir=args.reuse_localization_dir,
        )
        write_outputs(args.output_dir, summary, environment)
        rows = summary["scientific_results"]["candidate_rows"]
        unavailable = [
            row for row in rows
            if row["structural_status"] != "available"
            or row["descriptor_status"] != "available"
            or row["flawfinder_status"] != "available"
        ]
        print(
            f"localized {len(rows) - len(unavailable)}/{len(rows)} frozen candidates; "
            "security_depth_localization_sha256="
            f"{summary['security_depth_localization_sha256']}"
        )
        for row in unavailable:
            print(
                f"UNAVAILABLE {row['candidate_id']}: "
                f"structural={row['structural_unavailable_reason']}; "
                f"descriptor={row['descriptor_unavailable_reason']}; "
                f"flawfinder={row['flawfinder_unavailable_reason']}",
                file=sys.stderr,
            )
        return 2 if args.formal and unavailable else 0

    left = _read_json(args.left_dir / OUTPUT_FILES["summary"])
    right = _read_json(args.right_dir / OUTPUT_FILES["summary"])
    left_environment = _read_json(args.left_dir / OUTPUT_FILES["environment"])
    right_environment = _read_json(args.right_dir / OUTPUT_FILES["environment"])
    comparison = compare_summaries(left, right, left_environment, right_environment)
    if args.output:
        write_json(args.output, comparison)
    else:
        print(json.dumps(comparison, indent=2, sort_keys=True))
    return 0 if comparison["scientific_results_identical"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CensusError, LocalizationError) as error:
        print(f"generated security-depth localization: {error}", file=sys.stderr)
        raise SystemExit(2) from error
