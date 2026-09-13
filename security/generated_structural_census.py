#!/usr/bin/env python3
"""Blind, deterministic structural census of frozen generated candidates.

This module never reads security results.  Candidate membership comes only
from a checked-in manifest derived with the existing lineage population rules;
the host filesystem can make a frozen member unavailable, but cannot add a
member to the scientific denominator.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from security.common.callgraph import (  # noqa: E402
    CALL_GRAPH_SCHEMA_VERSION,
    analyze_source_bytes,
    measurement_universe_functions,
)

SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
OUTPUT_FILES = {
    "summary": "generated_reachability_summary.json",
    "environment": "generated_reachability_environment.json",
    "candidates": "generated_reachability_per_candidate.csv",
    "functions": "generated_reachability_functions.csv",
    "utility": "generated_reachability_by_utility.csv",
    "stage": "generated_reachability_by_stage.csv",
    "utility_stage": "generated_reachability_by_utility_stage.csv",
    "depth": "generated_depth_distribution.csv",
}

MANIFEST_CANDIDATE_FIELDS = {
    "candidate_id",
    "formal_run_id",
    "lineage_id",
    "checkpoint_id",
    "checkpoint_name",
    "utility",
    "attempt_id",
    "candidate_source",
    "candidate_source_sha256",
    "functional_population_status",
    "final_population_member",
}


class CensusError(ValueError):
    """Fail-closed manifest or census error."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def repository_candidate_bytes(
    repo: Path, relative_source: str
) -> tuple[bytes, str]:
    """Return cross-host-stable source bytes plus their retrieval method.

    Formal candidates are tracked files.  Git's committed blob is the
    scientific byte identity, while ``git diff`` verifies that the local
    checkout has no substantive modification.  This makes CRLF checkout
    conversion irrelevant without normalizing arbitrary bytes ourselves.  A
    non-Git fixture falls back to its literal filesystem bytes.
    """
    relative_source = safe_repo_path(relative_source, "candidate_source")
    path = repo.joinpath(*PurePosixPath(relative_source).parts)
    if not path.is_file():
        raise FileNotFoundError(path)
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative_source],
        cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if tracked.returncode != 0:
        return path.read_bytes(), "filesystem_bytes"
    clean = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", relative_source], cwd=repo,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if clean.returncode != 0:
        return path.read_bytes(), "modified_worktree_bytes"
    blob = subprocess.run(
        ["git", "show", f"HEAD:{relative_source}"], cwd=repo,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if blob.returncode != 0:
        raise CensusError(
            f"cannot read committed candidate blob {relative_source}: "
            f"{blob.stderr.decode('utf-8', 'replace').strip()}"
        )
    return blob.stdout, "repository_git_blob"


def safe_repo_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CensusError(f"{label} must be a non-empty repository-relative path")
    normalized = value.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if relative.is_absolute() or ".." in relative.parts or PureWindowsPath(value).drive:
        raise CensusError(f"{label} must not be absolute or escape the repository: {value}")
    return relative.as_posix()


def manifest_fingerprint_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": manifest.get("schema_version"),
        "population_definition": manifest.get("population_definition"),
        "formal_runs": manifest.get("formal_runs"),
        "candidates": manifest.get("candidates"),
    }


def validate_manifest(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CensusError("candidate population manifest must be a JSON object")
    manifest = dict(raw)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise CensusError(
            f"candidate population schema_version must be {MANIFEST_SCHEMA_VERSION}"
        )
    runs = manifest.get("formal_runs")
    candidates = manifest.get("candidates")
    if not isinstance(runs, list) or not isinstance(candidates, list):
        raise CensusError("formal_runs and candidates must be arrays")
    run_ids: set[str] = set()
    for run in runs:
        if not isinstance(run, Mapping):
            raise CensusError("every formal run must be an object")
        run_id = run.get("formal_run_id")
        if not isinstance(run_id, str) or not run_id or run_id in run_ids:
            raise CensusError(f"invalid or duplicate formal_run_id: {run_id!r}")
        run_ids.add(run_id)
        safe_repo_path(run.get("lineage_root"), f"formal run {run_id} lineage_root")
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise CensusError("every candidate must be an object")
        unknown = set(candidate) - MANIFEST_CANDIDATE_FIELDS
        if unknown:
            raise CensusError(
                "candidate manifest contains unsupported fields "
                f"{sorted(unknown)}; security outcomes and host metadata are forbidden"
            )
        missing = MANIFEST_CANDIDATE_FIELDS - set(candidate)
        if missing:
            raise CensusError(f"candidate manifest fields missing: {sorted(missing)}")
        row = dict(candidate)
        identifier = row.get("candidate_id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise CensusError(f"invalid or duplicate candidate_id: {identifier!r}")
        seen.add(identifier)
        if row.get("formal_run_id") not in run_ids:
            raise CensusError(f"{identifier}: unknown formal_run_id")
        row["candidate_source"] = safe_repo_path(
            row.get("candidate_source"), f"{identifier} candidate_source"
        )
        digest = row.get("candidate_source_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise CensusError(f"{identifier}: invalid candidate_source_sha256")
        if row.get("functional_population_status") != "public_checkpoint_stage_success":
            raise CensusError(f"{identifier}: candidate is not a successful checkpoint")
        if not isinstance(row.get("final_population_member"), bool):
            raise CensusError(f"{identifier}: final_population_member must be boolean")
        ordered.append(row)
    expected_order = sorted(
        ordered,
        key=lambda row: (
            str(row["utility"]), str(row["formal_run_id"]),
            str(row["lineage_id"]), str(row["checkpoint_id"]),
            str(row["candidate_id"]),
        ),
    )
    if ordered != expected_order:
        raise CensusError("candidate manifest is not in deterministic order")
    expected = content_sha256(manifest_fingerprint_payload(manifest))
    if manifest.get("candidate_population_sha256") != expected:
        raise CensusError(
            "candidate_population_sha256 mismatch: expected "
            f"{expected}, got {manifest.get('candidate_population_sha256')}"
        )
    manifest["candidates"] = ordered
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CensusError(f"cannot read candidate population manifest {path}: {error}") from error
    return validate_manifest(raw)


def _relative_to_repo(path: Path, repo: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError as error:
        raise CensusError(f"candidate source escapes repository: {path}") from error


def freeze_population(repo: Path, lineage_roots: Sequence[str]) -> dict[str, Any]:
    """Derive a frozen manifest from explicitly named lineage roots only."""
    from scripts.analyze_lineages import (  # imported only for the freeze path
        checkpoint_order,
        load_run,
        population_members,
        resolve_stage_paths,
    )

    repo = repo.resolve()
    formal_runs: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for root_text in sorted(set(lineage_roots)):
        relative_root = safe_repo_path(root_text, "lineage root")
        root = repo.joinpath(*PurePosixPath(relative_root).parts)
        metadata, lineages, _ = load_run(root)
        utility = metadata.get("utility")
        if not isinstance(utility, str) or not utility:
            raise CensusError(f"{relative_root}: lineage metadata has no utility")
        formal_run_id = root.name
        order = checkpoint_order(metadata, lineages)
        final_lineages = {
            lineage_id for lineage_id, _, _ in population_members(lineages, None)
        }
        formal_runs.append({
            "formal_run_id": formal_run_id,
            "utility": utility,
            "lineage_root": relative_root,
            "checkpoint_ids": order,
            "generation_repository_commit": metadata.get("repository_commit"),
        })
        for checkpoint in order:
            for lineage_id, lineage_dir, stage in population_members(lineages, checkpoint):
                located = resolve_stage_paths(lineage_dir, stage)
                candidate = located["candidate"]
                if not candidate.is_file():
                    raise CensusError(f"cannot freeze missing candidate: {candidate}")
                relative_source = _relative_to_repo(candidate, repo)
                source_bytes, _ = repository_candidate_bytes(repo, relative_source)
                actual_hash = hashlib.sha256(source_bytes).hexdigest()
                recorded_hash = stage.get("candidate_sha256")
                if recorded_hash != actual_hash:
                    raise CensusError(
                        f"{formal_run_id}/{lineage_id}/{checkpoint}: recorded source "
                        f"hash {recorded_hash} does not match {actual_hash}"
                    )
                candidate_id = f"{formal_run_id}/{lineage_id}/{checkpoint}"
                candidates.append({
                    "candidate_id": candidate_id,
                    "formal_run_id": formal_run_id,
                    "lineage_id": lineage_id,
                    "checkpoint_id": str(checkpoint),
                    "checkpoint_name": stage.get("checkpoint_name"),
                    "utility": utility,
                    "attempt_id": located["attempt_dir"].name,
                    "candidate_source": relative_source,
                    "candidate_source_sha256": actual_hash,
                    "functional_population_status": "public_checkpoint_stage_success",
                    "final_population_member": (
                        lineage_id in final_lineages
                        and str(stage.get("checkpoint_id")) == str(order[-1])
                    ),
                })
    formal_runs.sort(key=lambda row: (str(row["utility"]), str(row["formal_run_id"])))
    candidates.sort(key=lambda row: (
        str(row["utility"]), str(row["formal_run_id"]),
        str(row["lineage_id"]), str(row["checkpoint_id"]),
        str(row["candidate_id"]),
    ))
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "population_definition": {
            "checkpoint_population": "every successful public checkpoint candidate",
            "checkpoint_zero_included": True,
            "later_failure_preserves_earlier_success": True,
            "final_population": "last checkpoint candidate of every end-to-end functionally successful lineage",
            "selection_source": "existing lineage population_members semantics",
            "host_filesystem_discovery": False,
        },
        "formal_runs": formal_runs,
        "candidates": candidates,
    }
    manifest["candidate_population_sha256"] = content_sha256(
        manifest_fingerprint_payload(manifest)
    )
    return validate_manifest(manifest)


def _ordered_depth_dict(values: Mapping[int, Any]) -> dict[str, Any]:
    return {str(depth): values[depth] for depth in sorted(values)}


def structural_metrics(analysis: Mapping[str, Any]) -> dict[str, Any]:
    functions = [dict(item) for item in analysis.get("function_reachability", [])]
    numeric = measurement_universe_functions(analysis)
    numeric.sort(key=lambda item: (int(item["call_depth"]), str(item["function_id"])))
    by_depth: dict[int, list[str]] = defaultdict(list)
    counts: dict[int, int] = defaultdict(int)
    loc: dict[int, int] = defaultdict(int)
    ast_values: dict[int, list[Any]] = defaultdict(list)
    for item in numeric:
        depth = int(item["call_depth"])
        by_depth[depth].append(str(item["function_id"]))
        counts[depth] += 1
        loc[depth] += int(item.get("lines_of_code") or 0)
        ast_values[depth].append(item.get("ast_node_count"))
    ast = {
        depth: (
            sum(int(value) for value in values)
            if all(isinstance(value, int) and not isinstance(value, bool) for value in values)
            else None
        )
        for depth, values in ast_values.items()
    }
    resolved_entries = list(analysis.get("resolved_entry_points", []))
    reachable_count = int(analysis.get("reachable_function_count") or 0)
    diversification_count = int(
        analysis.get("diversification_eligible_function_count") or 0
    )
    total_ast = (
        sum(int(item["ast_node_count"]) for item in numeric)
        if all(isinstance(item.get("ast_node_count"), int) for item in numeric)
        else None
    )
    resolutions = list(analysis.get("entry_point_resolutions", []))
    statuses = [item.get("status") for item in resolutions]
    resolution_status = (
        "resolved" if statuses and all(status == "resolved" for status in statuses)
        else "unresolved" if statuses and all(status == "not_found" for status in statuses)
        else "partial_or_ambiguous"
    )
    return {
        "defined_function_count": len(functions),
        "reachable_function_count": reachable_count,
        "numeric_depth_function_count": len(numeric),
        "unreachable_function_count": int(analysis.get("unreachable_function_count") or 0),
        "measurement_universe_function_count": len(numeric),
        "diversification_eligible_function_count": diversification_count,
        "entry_point_function_count": len(resolved_entries),
        "entry_point_only_reachable": bool(resolved_entries) and reachable_count == len(resolved_entries),
        "diversification_universe_empty": diversification_count == 0,
        "max_reachable_call_depth": analysis.get("max_reachable_call_depth"),
        "functions_by_call_depth": _ordered_depth_dict(by_depth),
        "function_count_by_call_depth": _ordered_depth_dict(counts),
        "lines_of_code_by_call_depth": _ordered_depth_dict(loc),
        "ast_node_count_by_call_depth": _ordered_depth_dict(ast),
        "total_reachable_lines_of_code": sum(
            int(item.get("lines_of_code") or 0) for item in numeric
        ),
        "total_reachable_ast_node_count": total_ast,
        "entry_point_resolution_status": resolution_status,
        "entry_point_resolutions": resolutions,
    }


def _function_rows(candidate: Mapping[str, Any], analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for function in sorted(
        analysis.get("function_reachability", []),
        key=lambda item: str(item.get("function_id")),
    ):
        rows.append({
            "candidate_id": candidate["candidate_id"],
            "utility": candidate["utility"],
            "checkpoint_id": candidate["checkpoint_id"],
            "function_id": function.get("function_id"),
            "function": function.get("function"),
            "source_file": function.get("source_file"),
            "start_line": function.get("start_line"),
            "end_line": function.get("end_line"),
            "lines_of_code": function.get("lines_of_code"),
            "ast_node_count": function.get("ast_node_count"),
            "call_depth": function.get("call_depth"),
            "reachable_from_entry": function.get("reachable_from_entry"),
            "measurement_universe_member": isinstance(function.get("call_depth"), int),
            "diversification_eligible": function.get("diversification_eligible"),
            "analysis_method": analysis.get("analysis_method"),
        })
    return rows


def analyze_manifest_candidate(
    candidate: Mapping[str, Any], repo: Path, *, formal: bool,
    force_fallback: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = {
        key: candidate[key] for key in (
            "candidate_id", "formal_run_id", "lineage_id", "checkpoint_id",
            "checkpoint_name", "utility", "attempt_id", "candidate_source",
            "candidate_source_sha256", "functional_population_status",
            "final_population_member",
        )
    }
    base["reachability_source"] = "recomputed_from_candidate_source"
    path = repo.joinpath(*PurePosixPath(str(candidate["candidate_source"])).parts)
    if not path.is_file():
        return {
            **base,
            "analysis_status": "unavailable",
            "unavailable_reason": "frozen_candidate_source_missing",
            "actual_candidate_source_sha256": None,
            "analysis_method": None,
        }, []
    data, byte_origin = repository_candidate_bytes(
        repo, str(candidate["candidate_source"])
    )
    actual = hashlib.sha256(data).hexdigest()
    if actual != candidate["candidate_source_sha256"]:
        return {
            **base,
            "analysis_status": "source_hash_mismatch",
            "unavailable_reason": "candidate source bytes do not match frozen SHA-256",
            "actual_candidate_source_sha256": actual,
            "candidate_source_byte_origin": byte_origin,
            "analysis_method": None,
        }, []
    analysis = analyze_source_bytes(
        data,
        source_file=PurePosixPath(str(candidate["candidate_source"])).name,
        force_fallback=force_fallback,
    )
    method = analysis.get("analysis_method")
    if formal and method != "tree_sitter":
        return {
            **base,
            "analysis_status": "formal_method_unavailable",
            "unavailable_reason": (
                f"formal census requires tree_sitter; analyzer used {method}"
            ),
            "actual_candidate_source_sha256": actual,
            "candidate_source_byte_origin": byte_origin,
            "analysis_method": method,
        }, []
    metrics = structural_metrics(analysis)
    return {
        **base,
        "analysis_status": "analyzed",
        "unavailable_reason": None,
        "actual_candidate_source_sha256": actual,
        "candidate_source_byte_origin": byte_origin,
        "analysis_method": method,
        **metrics,
    }, _function_rows(candidate, analysis)


def _stats(values: Iterable[Any]) -> dict[str, Any]:
    numbers = [
        float(value) for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    if not numbers:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(numbers),
        "mean": statistics.fmean(numbers),
        "median": statistics.median(numbers),
        "min": min(numbers),
        "max": max(numbers),
    }


AGGREGATE_METRICS = (
    "defined_function_count",
    "reachable_function_count",
    "measurement_universe_function_count",
    "diversification_eligible_function_count",
    "max_reachable_call_depth",
)


def aggregate_group(rows: Sequence[Mapping[str, Any]], label: Mapping[str, Any]) -> dict[str, Any]:
    analyzed = [row for row in rows if row.get("analysis_status") == "analyzed"]
    total = len(rows)
    complete = len(analyzed) == total
    tree_sitter_count = sum(row.get("analysis_method") == "tree_sitter" for row in analyzed)
    entry_only = sum(row.get("entry_point_only_reachable") is True for row in analyzed)
    empty = sum(row.get("diversification_universe_empty") is True for row in analyzed)
    unreachable = sum(int(row.get("unreachable_function_count") or 0) > 0 for row in analyzed)
    result = {
        **label,
        "candidate_count": total,
        "characterized_candidate_count": len(analyzed),
        "tree_sitter_candidate_count": tree_sitter_count,
        "tree_sitter_coverage": tree_sitter_count / total if total else None,
        "entry_point_only_candidate_count": entry_only,
        "entry_point_only_prevalence": entry_only / total if total and complete else None,
        "empty_diversification_universe_count": empty,
        "empty_diversification_universe_prevalence": empty / total if total and complete else None,
        "candidate_with_unreachable_functions_count": unreachable,
        "candidate_with_unreachable_functions_prevalence": (
            unreachable / total if total and complete else None
        ),
    }
    for metric in AGGREGATE_METRICS:
        result[metric] = _stats(row.get(metric) for row in analyzed)
    return result


def aggregate_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    ordered = list(rows)
    grouped: dict[str, list[dict[str, Any]]] = {
        "overall": [aggregate_group(ordered, {"group": "overall"})],
        "utility": [],
        "stage": [],
        "utility_stage": [],
        "final_population": [],
        "final_population_by_utility": [],
    }
    utilities = sorted({str(row["utility"]) for row in ordered})
    stages = sorted({str(row["checkpoint_id"]) for row in ordered})
    for utility in utilities:
        subset = [row for row in ordered if row["utility"] == utility]
        grouped["utility"].append(aggregate_group(subset, {"utility": utility}))
    for stage in stages:
        subset = [row for row in ordered if str(row["checkpoint_id"]) == stage]
        grouped["stage"].append(aggregate_group(subset, {"checkpoint_id": stage}))
    for utility in utilities:
        utility_rows = [row for row in ordered if row["utility"] == utility]
        for stage in sorted({str(row["checkpoint_id"]) for row in utility_rows}):
            subset = [
                row for row in utility_rows if str(row["checkpoint_id"]) == stage
            ]
            grouped["utility_stage"].append(aggregate_group(
                subset, {"utility": utility, "checkpoint_id": stage}
            ))
    final_rows = [row for row in ordered if row.get("final_population_member") is True]
    grouped["final_population"].append(aggregate_group(
        final_rows, {"group": "end_to_end_functionally_successful_final_population"}
    ))
    for utility in utilities:
        subset = [row for row in final_rows if row["utility"] == utility]
        grouped["final_population_by_utility"].append(aggregate_group(
            subset, {"utility": utility}
        ))
    return grouped


def depth_distribution(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    analyzed = [row for row in rows if row.get("analysis_status") == "analyzed"]
    depths = sorted({
        int(depth)
        for row in analyzed
        for depth in row.get("function_count_by_call_depth", {})
    })
    complete = len(analyzed) == len(rows)
    result = []
    for depth in depths:
        key = str(depth)
        containing = sum(int(row.get("function_count_by_call_depth", {}).get(key, 0)) > 0 for row in analyzed)
        depth_rows = [
            row for row in analyzed
            if key in row.get("function_count_by_call_depth", {})
        ]
        result.append({
            "call_depth": depth,
            "candidate_denominator": len(rows),
            "characterized_candidate_count": len(analyzed),
            "function_count": sum(
                int(row.get("function_count_by_call_depth", {}).get(key, 0))
                for row in analyzed
            ),
            "candidates_with_depth_count": containing,
            "candidate_prevalence": containing / len(rows) if rows and complete else None,
            "lines_of_code": sum(
                int(row.get("lines_of_code_by_call_depth", {}).get(key, 0))
                for row in analyzed
            ),
            "ast_node_count": (
                sum(int(row["ast_node_count_by_call_depth"][key]) for row in depth_rows)
                if all(
                    isinstance(row.get("ast_node_count_by_call_depth", {}).get(key), int)
                    for row in depth_rows
                )
                else None
            ),
        })
    return result


def scientific_payload(
    manifest: Mapping[str, Any], candidate_rows: list[dict[str, Any]],
    function_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    aggregates = aggregate_rows(candidate_rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_population_sha256": manifest["candidate_population_sha256"],
        "call_graph_schema_version": CALL_GRAPH_SCHEMA_VERSION,
        "measurement_universe_definition": (
            "all statically reachable functions with numeric raw call depth, including configured entry points"
        ),
        "diversification_priority_universe_definition": (
            "statically reachable numeric-depth functions excluding configured entry points by default"
        ),
        "expected_candidate_count": len(manifest["candidates"]),
        "candidate_rows": candidate_rows,
        "function_rows": function_rows,
        "aggregates": aggregates,
        "depth_distribution": depth_distribution(candidate_rows),
    }


def environment_provenance(repo: Path, *, formal: bool, host_role: str) -> dict[str, Any]:
    probe = analyze_source_bytes("int main(void) { return 0; }\n")
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {
        "schema_version": SCHEMA_VERSION,
        "execution_role": "formal_frozen_census" if formal else "development_smoke_census",
        "host_role": host_role,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "os": platform.system(),
        "os_release": platform.release(),
        "host_name": platform.node(),
        "absolute_working_directory": str(repo.resolve()),
        "tree_sitter_available": probe.get("analysis_method") == "tree_sitter",
        "parser_probe_analysis_method": probe.get("analysis_method"),
        "call_graph_schema_version": CALL_GRAPH_SCHEMA_VERSION,
        "repository_commit_sha": commit,
        "formal_tree_sitter_required": formal,
    }


def run_census(
    manifest: Mapping[str, Any], repo: Path, *, formal: bool = False,
    host_role: str = "other", force_fallback: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if formal and host_role != "vessel":
        raise CensusError("formal census requires --host-role vessel")
    if formal and force_fallback:
        raise CensusError("formal census cannot use --force-fallback")
    candidate_rows: list[dict[str, Any]] = []
    function_rows: list[dict[str, Any]] = []
    for candidate in manifest["candidates"]:
        row, functions = analyze_manifest_candidate(
            candidate, repo, formal=formal, force_fallback=force_fallback
        )
        candidate_rows.append(row)
        function_rows.extend(functions)
    candidate_rows.sort(key=lambda row: str(row["candidate_id"]))
    function_rows.sort(key=lambda row: (str(row["candidate_id"]), str(row["function_id"])))
    scientific = scientific_payload(manifest, candidate_rows, function_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "candidate_population_sha256": manifest["candidate_population_sha256"],
        "structural_census_sha256": content_sha256(scientific),
        "scientific_results": scientific,
    }
    environment = environment_provenance(repo, formal=formal, host_role=host_role)
    return summary, environment


def _flatten_aggregate(row: Mapping[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Mapping):
            for subkey, subvalue in value.items():
                flat[f"{key}_{subkey}"] = subvalue
        else:
            flat[key] = value
    return flat


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = [dict(row) for row in rows]
    columns = sorted({key for row in materialized for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in materialized:
            writer.writerow({
                key: (
                    json.dumps(value, sort_keys=True, separators=(",", ":"))
                    if isinstance(value, (dict, list)) else value
                )
                for key, value in row.items()
            })


def write_outputs(output_dir: Path, summary: Mapping[str, Any], environment: Mapping[str, Any]) -> None:
    science = summary["scientific_results"]
    write_json(output_dir / OUTPUT_FILES["summary"], summary)
    write_json(output_dir / OUTPUT_FILES["environment"], environment)
    write_csv(output_dir / OUTPUT_FILES["candidates"], science["candidate_rows"])
    write_csv(output_dir / OUTPUT_FILES["functions"], science["function_rows"])
    write_csv(
        output_dir / OUTPUT_FILES["utility"],
        [_flatten_aggregate(row) for row in science["aggregates"]["utility"]],
    )
    write_csv(
        output_dir / OUTPUT_FILES["stage"],
        [_flatten_aggregate(row) for row in science["aggregates"]["stage"]],
    )
    write_csv(
        output_dir / OUTPUT_FILES["utility_stage"],
        [_flatten_aggregate(row) for row in science["aggregates"]["utility_stage"]],
    )
    write_csv(output_dir / OUTPUT_FILES["depth"], science["depth_distribution"])


def compare_summaries(
    left: Mapping[str, Any], right: Mapping[str, Any],
    left_environment: Mapping[str, Any] | None = None,
    right_environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []
    left_science = left.get("scientific_results")
    right_science = right.get("scientific_results")
    if left.get("candidate_population_sha256") != right.get("candidate_population_sha256"):
        differences.append({"category": "candidate_population", "detail": "population fingerprint differs"})
    left_rows = {
        row["candidate_id"]: row for row in (left_science or {}).get("candidate_rows", [])
    }
    right_rows = {
        row["candidate_id"]: row for row in (right_science or {}).get("candidate_rows", [])
    }
    for identifier in sorted(set(left_rows) | set(right_rows)):
        if identifier not in left_rows or identifier not in right_rows:
            differences.append({"category": "candidate_missing", "candidate_id": identifier})
            continue
        left_row, right_row = left_rows[identifier], right_rows[identifier]
        for field in (
            "candidate_source_sha256", "actual_candidate_source_sha256",
            "analysis_status", "analysis_method", "entry_point_resolution_status",
            "defined_function_count", "reachable_function_count",
            "numeric_depth_function_count", "unreachable_function_count",
            "measurement_universe_function_count",
            "diversification_eligible_function_count", "max_reachable_call_depth",
            "functions_by_call_depth", "function_count_by_call_depth",
            "lines_of_code_by_call_depth", "ast_node_count_by_call_depth",
        ):
            if left_row.get(field) != right_row.get(field):
                differences.append({
                    "category": "candidate_structural_result",
                    "candidate_id": identifier,
                    "field": field,
                    "left": left_row.get(field),
                    "right": right_row.get(field),
                })
    if (left_science or {}).get("function_rows") != (right_science or {}).get("function_rows"):
        differences.append({"category": "function_set_or_depth", "detail": "function rows differ"})
    if (left_science or {}).get("aggregates") != (right_science or {}).get("aggregates"):
        differences.append({"category": "aggregate", "detail": "aggregate summaries differ"})
    if (left_science or {}).get("depth_distribution") != (right_science or {}).get("depth_distribution"):
        differences.append({"category": "depth_distribution", "detail": "depth distributions differ"})
    environment_differences: list[dict[str, Any]] = []
    if left_environment is not None and right_environment is not None:
        for key in sorted(set(left_environment) | set(right_environment)):
            if left_environment.get(key) != right_environment.get(key):
                environment_differences.append({
                    "field": key,
                    "left": left_environment.get(key),
                    "right": right_environment.get(key),
                })
    identical = not differences and left.get("structural_census_sha256") == right.get("structural_census_sha256")
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_population_identical": (
            left.get("candidate_population_sha256") == right.get("candidate_population_sha256")
        ),
        "scientific_results_identical": identical,
        "scientific_differences": differences,
        "environment_differences": environment_differences,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CensusError(f"{path} is not a JSON object")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze", help="derive a manifest from explicit formal lineage roots")
    freeze.add_argument("--repo-root", type=Path, default=REPO)
    freeze.add_argument("--lineage-root", action="append", required=True)
    freeze.add_argument("--output", type=Path, required=True)

    census = subparsers.add_parser("census", help="analyze exactly the frozen manifest")
    census.add_argument("--repo-root", type=Path, default=REPO)
    census.add_argument("--manifest", type=Path, required=True)
    census.add_argument("--output-dir", type=Path, required=True)
    census.add_argument("--formal", action="store_true")
    census.add_argument("--host-role", choices=("wsl", "vessel", "other"), default="other")
    census.add_argument("--force-fallback", action="store_true")

    compare = subparsers.add_parser("compare", help="compare scientific results and separately report environment differences")
    compare.add_argument("--left-dir", type=Path, required=True)
    compare.add_argument("--right-dir", type=Path, required=True)
    compare.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "freeze":
        manifest = freeze_population(args.repo_root, args.lineage_root)
        write_json(args.output, manifest)
        print(
            f"froze {len(manifest['candidates'])} candidates; "
            f"candidate_population_sha256={manifest['candidate_population_sha256']}"
        )
        return 0
    if args.command == "census":
        manifest = load_manifest(args.manifest)
        summary, environment = run_census(
            manifest, args.repo_root.resolve(), formal=args.formal,
            host_role=args.host_role, force_fallback=args.force_fallback,
        )
        write_outputs(args.output_dir, summary, environment)
        rows = summary["scientific_results"]["candidate_rows"]
        unavailable = [row for row in rows if row["analysis_status"] != "analyzed"]
        print(
            f"analyzed {len(rows) - len(unavailable)}/{len(rows)} frozen candidates; "
            f"structural_census_sha256={summary['structural_census_sha256']}"
        )
        for row in unavailable:
            print(
                f"UNAVAILABLE {row['candidate_id']}: {row['analysis_status']}: "
                f"{row['unavailable_reason']}", file=sys.stderr,
            )
        return 2 if args.formal and unavailable else 0
    left = _read_json(args.left_dir / OUTPUT_FILES["summary"])
    right = _read_json(args.right_dir / OUTPUT_FILES["summary"])
    left_environment = _read_json(args.left_dir / OUTPUT_FILES["environment"])
    right_environment = _read_json(args.right_dir / OUTPUT_FILES["environment"])
    result = compare_summaries(left, right, left_environment, right_environment)
    if args.output:
        write_json(args.output, result)
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["scientific_results_identical"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CensusError as error:
        print(f"generated structural census: {error}", file=sys.stderr)
        raise SystemExit(2) from error
