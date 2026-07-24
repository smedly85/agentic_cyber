#!/usr/bin/env python3
"""Analyze repeated OpenCode maintenance runs.

This is the unified analyzer used by ``run_llm_experiment.sh``.  It keeps the
original command-line contract (especially ``--cluster-threshold``), while
providing two distinct structural analyses:

1. Configured-source architecture clustering
    Uses non-duplicated Clang AST deltas, Tree-sitter C deltas, and GumTree edit
   actions.  Parser organization, helper creation, comparator changes, and
   other patch-wide structural decisions may all affect these clusters.

2. Implementation-strategy clustering
   Uses only baseline-relative Clang and Tree-sitter features from behavioral
   functions.  ``main`` and parser/usage helpers are excluded by default so
   argument-parsing structure does not dominate the strategy result.

Patch size, tests, runtime, construct-validation distances, and security
diagnostics are reported separately and cannot determine either clustering.

Default output directory: ``<experiment>/analysis``.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from analysis.diversity_metrics import (
    bootstrap_diversity_ci,
    cluster_statistics as family_statistics,
    compute_vendi_score,
    da_curve,
    deterministic_threshold_grid,
    exact_repetition_summary,
    nauadc_summary,
    threshold_sensitivity as family_threshold_sensitivity,
    wilson_interval,
)
from analysis.diversity_validation import (
    pairwise_spearman_correlations,
    validation_distances,
)
from analysis.security_diagnostics import flawfinder_crosscheck, security_profile


# ---------------------------------------------------------------------------
# Python dependencies
# ---------------------------------------------------------------------------


def require_python_packages() -> tuple[Any, Any, Any]:
    missing: list[str] = []

    try:
        import numpy as np
    except ImportError:
        missing.append("numpy")
        np = None

    try:
        from sklearn.cluster import AgglomerativeClustering
        from sklearn.metrics import silhouette_score
    except ImportError:
        missing.append("scikit-learn")
        AgglomerativeClustering = silhouette_score = None

    if missing:
        raise SystemExit(
            "Missing Python packages: "
            + ", ".join(missing)
            + "\nInstall them with:\n"
            + "  python3 -m pip install -r scripts/analysis-requirements.txt"
        )

    return np, AgglomerativeClustering, silhouette_score


np: Any = None
AgglomerativeClustering: Any = None
silhouette_score: Any = None


def require_diagnostic_packages() -> tuple[Any, Any, Any, Any, Any]:
    """Load packages used only by --diagnostic-output."""
    missing: list[str] = []
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        missing.append("matplotlib")
        plt = None
    try:
        from rapidfuzz.fuzz import ratio as levenshtein_ratio
    except ImportError:
        missing.append("rapidfuzz")
        levenshtein_ratio = None
    try:
        from scipy.cluster.hierarchy import dendrogram, linkage
        from scipy.spatial.distance import squareform
    except ImportError:
        missing.append("scipy")
        dendrogram = linkage = squareform = None

    if missing:
        raise SystemExit(
            "Diagnostic output requires missing Python packages: "
            + ", ".join(missing)
            + "\nInstall them with:\n"
            + "  python3 -m pip install -r scripts/analysis-requirements.txt"
        )
    return plt, levenshtein_ratio, linkage, dendrogram, squareform


ANALYZER_VERSION = "4.0.0"

PAPER_METRICS_COLUMNS = [
    "Issue",
    "Checkpoint",
    "Model",
    "Temp",
    "N Runs",
    "Successful Runs",
    "Overall Success Rate",
    "Initial Public Success Rate",
    "Final Public Success Rate",
    "Repair Recovery Rate",
    "Pass@1",
    "Pass@5",
    "Pass@10",
    "Architecture Population N",
    "Effective Architecture Families",
    "Dominant Architecture Family Share",
    "Architecture NAUADC@K",
    "Strategy Population N",
    "Effective Strategy Families",
    "Dominant Strategy Family Share",
    "Strategy NAUADC@K",
    "Exact Unique Rate",
    "Exact Modal Share",
    "Diversity K Max",
]

PAPER_DESCRIPTIVE_COLUMNS = [
    "Issue",
    "Checkpoint",
    "Model",
    "Temp",
    "Raw Architecture Families",
    "Mean Pairwise Architecture Distance",
    "Architecture Vendi Score",
    "Raw Strategy Families",
    "Mean Pairwise Strategy Distance",
    "Strategy Vendi Score",
    "Mean Repair Loops",
    "Median Repair Loops",
    "Max Repair Loops",
    "Mean LLM Invocations",
    "Mean Repair LLM Runtime (s)",
    "Mean Total Runtime (s)",
    "Median Total Runtime (s)",
    "Mean Lines Edited",
    "Mean Files Edited",
    "Mean Functions Edited",
    "Mean Functions Created",
    "Mean Functions Deleted",
    "Mean GumTree/AST Edit Magnitude",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    source_hash: str
    calls: tuple[str, ...]


@dataclass
class ParsedSource:
    clang_counts: Counter[str]
    clang_node_count: int | None
    clang_error: str | None
    tree_sitter_counts: Counter[str]
    tree_sitter_leaf_tokens: int | None
    tree_sitter_node_count: int | None
    tree_sitter_functions: dict[str, FunctionInfo] | None
    tree_sitter_error: str | None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


DEFAULT_STRATEGY_EXCLUDE_REGEX = (
    r"^(?:main|.*(?:parse|parser|argument|arguments|argv|option|options|"
    r"usage|help|flag|error|report|diagnostic).*)$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze an experiment produced by run_llm_experiment.sh."
    )
    parser.add_argument("--experiment", required=True, type=Path)
    parser.add_argument(
        "--source-path",
        type=Path,
        default=None,
        help=(
            "Configured source path override. Required for legacy sandbox run.json "
            "metadata that does not record source_path."
        ),
    )
    parser.add_argument(
        "--baseline-source",
        type=Path,
        default=None,
        help=(
            "Baseline source override for sandbox analysis. Seeded sandbox runs "
            "otherwise derive it from run.json; unseeded runs use an empty source."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Default: <experiment>/analysis",
    )
    parser.add_argument(
        "--cluster-threshold",
        type=float,
        default=0.30,
        help=(
            "Architecture cosine-distance cut. This preserves the "
            "argument used by run_llm_experiment.sh. Default: 0.30"
        ),
    )
    parser.add_argument(
        "--strategy-threshold",
        type=float,
        default=None,
        help=(
            "Implementation-strategy cosine-distance cut. Defaults to the value "
            "of --cluster-threshold."
        ),
    )
    parser.add_argument(
        "--thresholds",
        default=None,
        help=(
            "Optional comma-separated thresholds for sensitivity tables. "
            "Values are used exactly as supplied; "
            "otherwise a deterministic local grid surrounds each primary cut."
        ),
    )
    parser.add_argument(
        "--diversity-k-max",
        type=int,
        default=None,
        help=(
            "Optional common fixed sampling budget K for comparable NAUADC@K. "
            "The complete DA curve is always calculated."
        ),
    )
    parser.add_argument(
        "--bootstrap-repetitions",
        type=int,
        default=1000,
        help="Implementation-level bootstrap repetitions. Default: 1000",
    )
    parser.add_argument(
        "--bootstrap-seed",
        type=int,
        default=20260723,
        help="Deterministic bootstrap seed. Default: 20260723",
    )
    parser.add_argument(
        "--strategy-exclude-regex",
        default=DEFAULT_STRATEGY_EXCLUDE_REGEX,
        help=(
            "Function-name regex excluded from strategy clustering. The "
            "default excludes main and parser/usage helpers."
        ),
    )
    parser.add_argument(
        "--strategy-include-function",
        action="append",
        default=[],
        help=(
            "Force a function into strategy clustering even when excluded by "
            "the regex. May be repeated."
        ),
    )
    parser.add_argument(
        "--clang-extra-arg",
        action="append",
        default=[],
        help="Additional argument passed to Clang. May be repeated.",
    )
    parser.add_argument(
        "--clean-output",
        action="store_true",
        help="Delete the output directory before writing the new analysis.",
    )
    parser.add_argument(
        "--diagnostic-output",
        action="store_true",
        help=(
            "Write detailed clustering tables, plots, and per-run tool "
            "artifacts beneath analysis/diagnostics/."
        ),
    )
    parser.add_argument(
        "--security-diagnostics",
        action="store_true",
        help="Write optional static security profiles and Flawfinder cross-checks.",
    )
    parser.add_argument(
        "--paper-issue-label",
        default=None,
        help="Override the Issue label in the standardized paper metrics row.",
    )
    parser.add_argument(
        "--paper-checkpoint-label",
        default=None,
        help=(
            "Override the Checkpoint label in the standardized paper metrics "
            "row."
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------


def run_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=124,
            stdout=exc.stdout or "",
            stderr=f"Timed out after {timeout} seconds",
        )
    except OSError as exc:
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=127,
            stdout="",
            stderr=str(exc),
        )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fieldnames),
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def flatten_dict(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, item in value.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            flat.update(flatten_dict(item, full_key))
        elif isinstance(item, (list, tuple)):
            flat[full_key] = ";".join(str(entry) for entry in item)
        else:
            flat[full_key] = item
    return flat


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_numeric_mean(values: Iterable[Any]) -> float | None:
    numeric = [
        float(value)
        for value in values
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ]
    return statistics.fmean(numeric) if numeric else None


def public_validation_succeeded(metadata: Mapping[str, Any]) -> bool:
    explicit = metadata.get("public_validation_success")
    if isinstance(explicit, bool):
        return explicit
    return all(
        metadata.get(key) == 0
        for key in (
            "build_exit_code",
            "base_test_exit_code",
            "feature_test_exit_code",
        )
    )


def normalize_repair_metadata(
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Add repair fields without changing metadata from newer experiments."""
    normalized = dict(metadata)
    public_success = public_validation_succeeded(normalized)
    repair_loops = normalized.get("repair_loops", 0)
    if not isinstance(repair_loops, int) or isinstance(repair_loops, bool):
        repair_loops = 0
    setup_failed_before_invocation = (
        normalized.get("setup_exit_code") not in (None, 0)
        and normalized.get("opencode_exit_code") is None
    )
    default_invocations = 0 if setup_failed_before_invocation else repair_loops + 1
    llm_invocations = normalized.get("llm_invocations", default_invocations)
    if not isinstance(llm_invocations, int) or isinstance(llm_invocations, bool):
        llm_invocations = default_invocations

    initial_success = normalized.get("initial_success")
    if not isinstance(initial_success, bool):
        initial_success = public_success if repair_loops == 0 else False
    success_loop = normalized.get("success_loop")
    if not isinstance(success_loop, int) or isinstance(success_loop, bool):
        success_loop = 0 if initial_success else None

    old_opencode_runtime = normalized.get("opencode_runtime_ms", 0)
    if not isinstance(old_opencode_runtime, (int, float)) or isinstance(
        old_opencode_runtime, bool
    ):
        old_opencode_runtime = 0
    initial_runtime = normalized.get(
        "initial_opencode_runtime_ms",
        old_opencode_runtime if repair_loops == 0 else 0,
    )
    repair_runtime = normalized.get("repair_opencode_runtime_ms", 0)
    total_runtime = normalized.get(
        "total_opencode_runtime_ms",
        old_opencode_runtime,
    )

    normalized.update(
        {
            "initial_success": initial_success,
            "repair_loops": repair_loops,
            "llm_invocations": llm_invocations,
            "success_loop": success_loop,
            "loop_limit_reached": bool(
                normalized.get(
                    "loop_limit_reached",
                    not public_success and not setup_failed_before_invocation,
                )
            ),
            "public_validation_success": public_success,
            "initial_opencode_runtime_ms": initial_runtime,
            "repair_opencode_runtime_ms": repair_runtime,
            "total_opencode_runtime_ms": total_runtime,
            "loops": normalized.get("loops", []),
        }
    )
    return normalized


def build_repair_summary(
    rows: Sequence[Mapping[str, Any]],
    configured_max_loops: int | None = None,
) -> dict[str, Any]:
    n = len(rows)
    repair_loops = [int(row.get("repair_loops", 0)) for row in rows]
    llm_invocations = [int(row.get("llm_invocations", 1)) for row in rows]
    initial_successes = sum(bool(row.get("initial_success")) for row in rows)
    public_success_rows = [
        row for row in rows if bool(row.get("public_validation_success"))
    ]
    public_failed_rows = [
        row for row in rows if not bool(row.get("public_validation_success"))
    ]
    repair_assisted_successes = sum(
        bool(row.get("public_validation_success"))
        and not bool(row.get("initial_success"))
        for row in rows
    )
    repair_runtimes = [
        float(row.get("repair_opencode_runtime_ms", 0)) / 1000.0
        for row in rows
    ]

    observed_loops = max(repair_loops, default=0)
    curve_limit = max(observed_loops, configured_max_loops or 0)
    success_curve = []
    for loop in range(curve_limit + 1):
        successes = sum(
            isinstance(row.get("success_loop"), int)
            and not isinstance(row.get("success_loop"), bool)
            and int(row["success_loop"]) <= loop
            for row in rows
        )
        success_curve.append(
            {
                "loop": loop,
                "successful_runs": successes,
                "success_rate": successes / n if n else None,
            }
        )

    initially_failed = n - initial_successes
    return {
        "initial_public_successes": initial_successes,
        "initial_public_success_rate": initial_successes / n if n else None,
        "final_public_successes": len(public_success_rows),
        "final_public_success_rate": (
            len(public_success_rows) / n if n else None
        ),
        "recovered_initially_failed_runs": repair_assisted_successes,
        "repair_recovery_rate": (
            repair_assisted_successes / initially_failed
            if initially_failed
            else None
        ),
        "mean_repair_loops": (
            statistics.fmean(repair_loops) if repair_loops else None
        ),
        "median_repair_loops": (
            statistics.median(repair_loops) if repair_loops else None
        ),
        "max_repair_loops": max(repair_loops) if repair_loops else None,
        "mean_llm_invocations": (
            statistics.fmean(llm_invocations) if llm_invocations else None
        ),
        "mean_repair_loops_successful_runs": safe_numeric_mean(
            row.get("repair_loops") for row in public_success_rows
        ),
        "mean_repair_loops_failed_runs": safe_numeric_mean(
            row.get("repair_loops") for row in public_failed_rows
        ),
        "mean_repair_llm_runtime_seconds": (
            statistics.fmean(repair_runtimes) if repair_runtimes else None
        ),
        "success_curve": success_curve,
        "note": (
            "Repair metrics use independent attempt-* directories as runs. "
            "The success curve is cumulative public-validation success by "
            "repair-loop budget and is not Pass@k."
        ),
    }


def infer_paper_issue(
    experiment_metadata: Mapping[str, Any],
    explicit_label: str | None = None,
) -> str | None:
    if explicit_label and explicit_label.strip():
        return explicit_label.strip()
    for key in ("issue", "utility"):
        value = experiment_metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    source_path = experiment_metadata.get("source_path")
    if source_path is None:
        return None
    source_name = Path(str(source_path).replace("\\", "/")).stem
    inferred = re.sub(r"^new_", "", source_name)
    return inferred or None


def infer_paper_checkpoint(
    experiment_metadata: Mapping[str, Any],
    explicit_label: str | None = None,
) -> str | None:
    if explicit_label and explicit_label.strip():
        return explicit_label.strip()
    for key in ("checkpoint", "issue_id"):
        value = experiment_metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    prompt = experiment_metadata.get("prompt")
    if prompt is None:
        return None
    inferred = Path(str(prompt).replace("\\", "/")).stem
    return inferred or None


def select_primary_cluster_population(
    populations: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any]]:
    population = populations.get("passing_complete_runs")
    return (
        "passing_complete_runs",
        population if isinstance(population, Mapping) else {},
    )


def build_paper_metrics_row(
    experiment_metadata: Mapping[str, Any],
    summary: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    issue_label: str | None = None,
    checkpoint_label: str | None = None,
) -> dict[str, Any]:
    clustering = summary.get("clustering", {})
    architecture = clustering.get("architecture", {}) if isinstance(clustering, Mapping) else {}
    strategy = clustering.get("strategy", {}) if isinstance(clustering, Mapping) else {}
    _, architecture_primary = select_primary_cluster_population(architecture.get("populations", {}))
    _, strategy_primary = select_primary_cluster_population(strategy.get("populations", {}))
    pass_values = summary.get("pass_at_k", {})
    repair = summary.get("repair", {})
    exact = summary.get("exact_generation_convergence", {})
    return {
        "Issue": infer_paper_issue(experiment_metadata, issue_label),
        "Checkpoint": infer_paper_checkpoint(experiment_metadata, checkpoint_label),
        "Model": experiment_metadata.get("model", summary.get("model")),
        "Temp": experiment_metadata.get("temperature", summary.get("temperature")),
        "N Runs": summary.get("runs_analyzed", len(rows)),
        "Successful Runs": summary.get("successful_runs"),
        "Overall Success Rate": summary.get("success_ratio"),
        "Initial Public Success Rate": repair.get("initial_public_success_rate"),
        "Final Public Success Rate": repair.get("final_public_success_rate"),
        "Repair Recovery Rate": repair.get("repair_recovery_rate"),
        "Pass@1": pass_values.get("pass@1"),
        "Pass@5": pass_values.get("pass@5"),
        "Pass@10": pass_values.get("pass@10"),
        "Architecture Population N": architecture_primary.get("run_count"),
        "Effective Architecture Families": architecture_primary.get("effective_family_count"),
        "Dominant Architecture Family Share": architecture_primary.get("dominant_family_share"),
        "Architecture NAUADC@K": architecture_primary.get("nauadc_at_kmax"),
        "Strategy Population N": strategy_primary.get("run_count"),
        "Effective Strategy Families": strategy_primary.get("effective_family_count"),
        "Dominant Strategy Family Share": strategy_primary.get("dominant_family_share"),
        "Strategy NAUADC@K": strategy_primary.get("nauadc_at_kmax"),
        "Exact Unique Rate": exact.get("exact_unique_rate"),
        "Exact Modal Share": exact.get("exact_modal_share"),
        "Diversity K Max": summary.get("diversity_k_max"),
    }


def build_paper_descriptive_row(
    experiment_metadata: Mapping[str, Any],
    summary: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    issue_label: str | None = None,
    checkpoint_label: str | None = None,
) -> dict[str, Any]:
    clustering = summary.get("clustering", {})
    architecture = clustering.get("architecture", {}) if isinstance(clustering, Mapping) else {}
    strategy = clustering.get("strategy", {}) if isinstance(clustering, Mapping) else {}
    _, architecture_primary = select_primary_cluster_population(architecture.get("populations", {}))
    _, strategy_primary = select_primary_cluster_population(strategy.get("populations", {}))
    repair = summary.get("repair", {})
    runtime = summary.get("runtime_seconds", {})
    successful_rows = [row for row in rows if bool(row.get("overall_success"))]
    return {
        "Issue": infer_paper_issue(experiment_metadata, issue_label),
        "Checkpoint": infer_paper_checkpoint(experiment_metadata, checkpoint_label),
        "Model": experiment_metadata.get("model", summary.get("model")),
        "Temp": experiment_metadata.get("temperature", summary.get("temperature")),
        "Raw Architecture Families": architecture_primary.get("raw_family_count"),
        "Mean Pairwise Architecture Distance": architecture_primary.get("mean_pairwise_distance"),
        "Architecture Vendi Score": architecture_primary.get("vendi_score"),
        "Raw Strategy Families": strategy_primary.get("raw_family_count"),
        "Mean Pairwise Strategy Distance": strategy_primary.get("mean_pairwise_distance"),
        "Strategy Vendi Score": strategy_primary.get("vendi_score"),
        "Mean Repair Loops": repair.get("mean_repair_loops"),
        "Median Repair Loops": repair.get("median_repair_loops"),
        "Max Repair Loops": repair.get("max_repair_loops"),
        "Mean LLM Invocations": repair.get("mean_llm_invocations"),
        "Mean Repair LLM Runtime (s)": repair.get("mean_repair_llm_runtime_seconds"),
        "Mean Total Runtime (s)": runtime.get("mean"),
        "Median Total Runtime (s)": runtime.get("median"),
        "Mean Lines Edited": safe_numeric_mean(row.get("lines_edited") for row in successful_rows),
        "Mean Files Edited": safe_numeric_mean(row.get("files_edited") for row in successful_rows),
        "Mean Functions Edited": safe_numeric_mean(row.get("functions_edited_count") for row in successful_rows),
        "Mean Functions Created": safe_numeric_mean(row.get("functions_created_count") for row in successful_rows),
        "Mean Functions Deleted": safe_numeric_mean(row.get("functions_deleted_count") for row in successful_rows),
        "Mean GumTree/AST Edit Magnitude": safe_numeric_mean(
            row.get("gumtree_normalized_edit_distance") for row in successful_rows
        ),
    }


def paper_metrics_schema() -> dict[str, Any]:
    return {
        "schema_version": 4,
        "primary_csv_columns": PAPER_METRICS_COLUMNS,
        "descriptive_csv_columns": PAPER_DESCRIPTIVE_COLUMNS,
        "notes": {
            "primary_population": "successful final candidates with complete measurement for that representation; no fallback",
            "effective_families": "exp(Shannon entropy) of empirical family shares",
            "fixed_budget_nauadc": "null unless --diversity-k-max is supplied and supported by the population",
            "excluded_from_clustering": "lexical, APTED, API-call, security, complexity, runtime, and patch-size information",
            "missing_values": "Unavailable measurements are null in JSON and blank in CSV.",
        },
    }


def infer_repository_root(
    experiment: Path,
    experiment_metadata: Mapping[str, Any],
) -> Path:
    configured = experiment_metadata.get("repository")
    if configured:
        candidate = Path(str(configured)).expanduser()
        if candidate.is_dir():
            return candidate.resolve()

    for ancestor in experiment.resolve().parents:
        if ancestor.name == "experiments" and ancestor.parent.name == "runs":
            return ancestor.parent.parent
    return Path(__file__).resolve().parents[1]


def paper_metrics_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    temperature = row.get("Temp")
    try:
        numeric_temperature = float(temperature)
    except (TypeError, ValueError):
        temperature_key: tuple[Any, ...] = (1, str(temperature or ""))
    else:
        temperature_key = (
            (0, numeric_temperature)
            if math.isfinite(numeric_temperature)
            else (1, str(temperature))
        )
    return (
        str(row.get("Issue") or ""),
        str(row.get("Checkpoint") or ""),
        str(row.get("Model") or ""),
        *temperature_key,
    )


def rebuild_paper_metrics_aggregate(repository_root: Path) -> None:
    experiments_root = repository_root / "runs" / "experiments"
    rows_by_experiment: dict[Path, dict[str, Any]] = {}
    if experiments_root.is_dir():
        for row_path in sorted(
            experiments_root.rglob("analysis/paper_metrics_row.json")
        ):
            try:
                row = read_json(row_path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                continue
            if not isinstance(row, dict) or not all(
                column in row
                for column in ("Issue", "Checkpoint", "Model", "Temp")
            ):
                continue
            for column in PAPER_METRICS_COLUMNS:
                row.setdefault(column, None)
            canonical_experiment = row_path.parent.parent.resolve()
            rows_by_experiment.setdefault(canonical_experiment, row)

    aggregate_rows = sorted(
        rows_by_experiment.values(),
        key=paper_metrics_sort_key,
    )
    write_csv(
        experiments_root / "paper_metrics.csv",
        aggregate_rows,
        PAPER_METRICS_COLUMNS,
    )
    write_json(experiments_root / "paper_metrics.json", aggregate_rows)


# ---------------------------------------------------------------------------
# Patch, test, and usage metrics
# ---------------------------------------------------------------------------


def parse_change_metrics(attempt: Path) -> dict[str, Any]:
    added = 0
    deleted = 0
    tracked_paths: set[str] = set()
    untracked_paths: set[str] = set()

    numstat_path = attempt / "diff-numstat.txt"
    if numstat_path.exists():
        for line in numstat_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            add_text, delete_text, relative_path = (
                parts[0],
                parts[1],
                parts[-1],
            )
            if add_text.isdigit():
                added += int(add_text)
            if delete_text.isdigit():
                deleted += int(delete_text)
            tracked_paths.add(relative_path)

    untracked_path = attempt / "untracked-files.txt"
    if untracked_path.exists():
        for relative_path in untracked_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            relative_path = relative_path.strip()
            if not relative_path:
                continue
            untracked_paths.add(relative_path)
            candidate_file = attempt / "candidate" / relative_path
            if candidate_file.is_file():
                try:
                    data = candidate_file.read_bytes()
                except OSError:
                    continue
                if b"\x00" not in data:
                    added += len(data.splitlines())

    all_paths = tracked_paths | untracked_paths
    return {
        "lines_added": added,
        "lines_deleted": deleted,
        "lines_edited": added + deleted,
        "files_edited": len(all_paths),
        "tracked_files_edited": len(tracked_paths),
        "untracked_files_created": len(untracked_paths),
        "changed_paths": sorted(all_paths),
    }


def source_change_metrics(baseline: Path, candidate: Path) -> dict[str, Any]:
    """Source-only churn for sandbox runs that have no Git artifacts."""
    baseline_lines = baseline.read_text(encoding="utf-8", errors="replace").splitlines()
    candidate_lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    added = 0
    deleted = 0
    for line in difflib.ndiff(baseline_lines, candidate_lines):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            deleted += 1
    changed = added > 0 or deleted > 0
    return {
        "lines_added": added,
        "lines_deleted": deleted,
        "lines_edited": added + deleted,
        "files_edited": int(changed),
        "tracked_files_edited": None,
        "untracked_files_created": int(not baseline_lines and bool(candidate_lines)),
        "changed_paths": [str(candidate)] if changed else [],
    }


def sandbox_run_metadata(experiment: Path) -> tuple[Path, dict[str, Any]] | None:
    """Find run.json for a sandbox root or one selected temp-* condition."""
    candidates = [experiment / "run.json", experiment.parent / "run.json", experiment.parent.parent / "run.json"]
    for path in candidates:
        if path.is_file():
            return path, read_json(path)
    return None


def sandbox_attempts(experiment: Path, run_root: Path) -> list[Path]:
    if (experiment / "metadata.json").is_file():
        return [experiment]
    direct_repeats = sorted(
        path for path in experiment.glob("rep-*") if (path / "metadata.json").is_file()
    )
    if direct_repeats:
        return direct_repeats
    attempts = sorted(run_root.glob("temp-*/metadata.json"))
    attempts.extend(sorted(run_root.glob("temp-*/rep-*/metadata.json")))
    return [path.parent for path in attempts]


def resolve_sandbox_baseline(
    metadata: Mapping[str, Any],
    source_path: Path,
    override: Path | None,
    output_dir: Path,
) -> tuple[Path, str]:
    if override is not None:
        baseline = override.expanduser().resolve()
        if not baseline.is_file():
            raise SystemExit(f"Baseline source not found: {baseline}")
        return baseline, "cli_override"

    repository = Path(str(metadata.get("repository", "."))).expanduser()
    seed_specs = [item for item in str(metadata.get("seed_files", "")).split(",") if item]
    for spec in seed_specs:
        source_text, separator, destination_text = spec.partition(":")
        destination = Path(destination_text if separator else source_text)
        if destination != source_path:
            continue
        seed = Path(source_text).expanduser()
        if not seed.is_absolute():
            seed = repository / seed
        if seed.is_file():
            return seed.resolve(), "recorded_seed"

    baseline = output_dir / "diagnostics" / "reference" / "empty_baseline.c"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text("", encoding="utf-8")
    return baseline, "empty_from_scratch"


def parse_test_log(path: Path) -> dict[str, int | None]:
    result: dict[str, int | None] = {
        "tests_run": None,
        "failures": None,
        "errors": None,
        "tests_passed": None,
    }
    if not path.exists():
        return result

    text = path.read_text(encoding="utf-8", errors="replace")
    validation_markers = list(
        re.finditer(r"^===== VALIDATION LOOP \d+:[^\n]*=====\s*$", text, re.M)
    )
    if validation_markers:
        text = text[validation_markers[-1].end() :]
    run_match = re.search(r"\bRan\s+(\d+)\s+tests?\b", text)
    if run_match:
        result["tests_run"] = int(run_match.group(1))

    failed_summary = re.search(r"FAILED\s*\(([^)]*)\)", text, flags=re.I)
    if failed_summary:
        failures = 0
        errors = 0
        for label, value in re.findall(
            r"(failures|errors)=(\d+)",
            failed_summary.group(1),
            flags=re.I,
        ):
            if label.lower() == "failures":
                failures += int(value)
            else:
                errors += int(value)
        result["failures"] = failures
        result["errors"] = errors
    elif re.search(r"^\s*OK\s*$", text, flags=re.I | re.M):
        result["failures"] = 0
        result["errors"] = 0
    elif re.search(r"\bFAILED\b", text, flags=re.I):
        result["failures"] = 1
        result["errors"] = 0

    if (
        result["tests_run"] is not None
        and result["failures"] is not None
        and result["errors"] is not None
    ):
        result["tests_passed"] = max(
            0,
            result["tests_run"] - result["failures"] - result["errors"],
        )
    return result


TOKEN_ALIASES = {
    "input_tokens": {
        "input_tokens",
        "inputTokens",
        "prompt_tokens",
        "promptTokens",
    },
    "output_tokens": {
        "output_tokens",
        "outputTokens",
        "completion_tokens",
        "completionTokens",
    },
    "reasoning_tokens": {
        "reasoning_tokens",
        "reasoningTokens",
    },
    "cache_read_tokens": {
        "cache_read_tokens",
        "cacheReadTokens",
        "cached_tokens",
        "cachedTokens",
    },
    "total_tokens": {
        "total_tokens",
        "totalTokens",
    },
}


def collect_token_values(
    value: Any,
    collected: dict[str, list[int]],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            for canonical, aliases in TOKEN_ALIASES.items():
                if key in aliases and isinstance(item, (int, float)):
                    collected[canonical].append(int(item))
            collect_token_values(item, collected)
    elif isinstance(value, list):
        for item in value:
            collect_token_values(item, collected)


def parse_llm_tokens_text(text: str) -> dict[str, int | None]:
    result: dict[str, int | None] = {
        "input_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "cache_read_tokens": None,
        "total_tokens": None,
    }
    collected = {key: [] for key in TOKEN_ALIASES}

    possible_json = [text]
    possible_json.extend(
        line
        for line in text.splitlines()
        if line.lstrip().startswith(("{", "["))
    )
    for candidate in possible_json:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        collect_token_values(parsed, collected)

    text_patterns = {
        "input_tokens": [
            r"\binput[_ ]tokens?\s*[:=]\s*([0-9][0-9,]*)",
            r"\bprompt[_ ]tokens?\s*[:=]\s*([0-9][0-9,]*)",
        ],
        "output_tokens": [
            r"\boutput[_ ]tokens?\s*[:=]\s*([0-9][0-9,]*)",
            r"\bcompletion[_ ]tokens?\s*[:=]\s*([0-9][0-9,]*)",
        ],
        "reasoning_tokens": [
            r"\breasoning[_ ]tokens?\s*[:=]\s*([0-9][0-9,]*)",
        ],
        "total_tokens": [
            r"\btotal[_ ]tokens?\s*[:=]\s*([0-9][0-9,]*)",
        ],
    }
    for key, patterns in text_patterns.items():
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.I):
                collected[key].append(int(match.replace(",", "")))

    for key, values in collected.items():
        if values:
            result[key] = max(values)

    if (
        result["total_tokens"] is None
        and result["input_tokens"] is not None
        and result["output_tokens"] is not None
    ):
        result["total_tokens"] = (
            result["input_tokens"] + result["output_tokens"]
        )
    return result


def parse_llm_tokens(path: Path) -> dict[str, int | None]:
    empty = {key: None for key in TOKEN_ALIASES}
    if not path.exists():
        return empty

    text = path.read_text(encoding="utf-8", errors="replace")
    invocation_marker = re.compile(
        r"^===== LLM INVOCATION \d+:[^\n]*=====\s*$",
        re.M,
    )
    sections = invocation_marker.split(text)
    if len(sections) == 1:
        return parse_llm_tokens_text(text)

    parsed_sections = [
        parse_llm_tokens_text(section)
        for section in sections[1:]
    ]
    return {
        key: (
            sum(
                int(section[key])
                for section in parsed_sections
                if section[key] is not None
            )
            if any(section[key] is not None for section in parsed_sections)
            else None
        )
        for key in TOKEN_ALIASES
    }


def opencode_permission_rejected(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return bool(
        re.search(
            r"(?:permission requested:\s*external_directory|auto-rejecting|"
            r"user rejected permission|permission denied)",
            text,
            flags=re.I,
        )
    )


def pass_at_k(n: int, correct: int, k: int) -> float | None:
    if n <= 0 or k <= 0 or k > n:
        return None
    if n - correct < k:
        return 1.0
    failure_probability = 1.0
    for index in range(k):
        failure_probability *= (n - correct - index) / (n - index)
    return 1.0 - failure_probability


# ---------------------------------------------------------------------------
# Clang AST extraction
# ---------------------------------------------------------------------------


def location_file(location: Any) -> str | None:
    if not isinstance(location, dict):
        return None
    direct = location.get("file")
    if isinstance(direct, str):
        return direct
    for key in ("spellingLoc", "expansionLoc", "presumedLoc"):
        nested = location.get(key)
        if isinstance(nested, dict):
            nested_file = nested.get("file")
            if isinstance(nested_file, str):
                return nested_file
    return None


def location_line(location: Any) -> int | None:
    if not isinstance(location, dict):
        return None
    direct = location.get("line")
    if isinstance(direct, int):
        return direct
    for key in ("spellingLoc", "expansionLoc", "presumedLoc"):
        nested = location.get(key)
        if isinstance(nested, dict):
            nested_line = nested.get("line")
            if isinstance(nested_line, int):
                return nested_line
    return None


def clang_range(node: Mapping[str, Any]) -> tuple[Any, Any]:
    range_data = node.get("range")
    if not isinstance(range_data, dict):
        return None, None
    return range_data.get("begin"), range_data.get("end")


def same_source_path(candidate: str, source: Path) -> bool:
    try:
        return Path(candidate).resolve() == source.resolve()
    except OSError:
        return os.path.normpath(candidate) == os.path.normpath(str(source))


def clang_node_in_source(
    node: Mapping[str, Any],
    source: Path,
    total_lines: int,
    inherited: bool,
) -> bool:
    begin, end = clang_range(node)
    explicit_files = [
        value
        for value in (location_file(begin), location_file(end))
        if value
    ]
    if explicit_files:
        return any(same_source_path(value, source) for value in explicit_files)

    lines = [
        value
        for value in (location_line(begin), location_line(end))
        if value is not None
    ]
    if lines:
        return all(1 <= value <= total_lines for value in lines)
    return inherited


def clang_is_function_definition(node: Mapping[str, Any]) -> bool:
    if node.get("kind") != "FunctionDecl":
        return False
    if node.get("isThisDeclarationADefinition") is True:
        return True
    inner = node.get("inner")
    return isinstance(inner, list) and any(
        isinstance(child, dict) and child.get("kind") == "CompoundStmt"
        for child in inner
    )


def walk_clang(
    node: Any,
    *,
    source: Path,
    total_lines: int,
    counts: Counter[str],
    inherited_in_source: bool = False,
    current_function: str | None = None,
) -> None:
    if isinstance(node, list):
        for child in node:
            walk_clang(
                child,
                source=source,
                total_lines=total_lines,
                counts=counts,
                inherited_in_source=inherited_in_source,
                current_function=current_function,
            )
        return
    if not isinstance(node, dict):
        return

    in_source = clang_node_in_source(
        node,
        source,
        total_lines,
        inherited_in_source,
    )
    function_context = current_function
    if in_source and clang_is_function_definition(node):
        function_name = node.get("name")
        if isinstance(function_name, str):
            function_context = function_name

    kind = node.get("kind")
    if in_source and isinstance(kind, str):
        # Every node is counted once: function-scoped when inside a function,
        # otherwise file-scoped. This removes the duplicate weighting present
        # in the previous analyzer.
        scope = (
            f"function.{function_context}"
            if function_context
            else "file"
        )
        counts[f"{scope}.kind.{kind}"] += 1

        if kind in {
            "UnaryOperator",
            "BinaryOperator",
            "CompoundAssignOperator",
        }:
            opcode = node.get("opcode")
            if isinstance(opcode, str):
                counts[f"{scope}.operator.{kind}.{opcode}"] += 1

    inner = node.get("inner")
    if isinstance(inner, list):
        for child in inner:
            walk_clang(
                child,
                source=source,
                total_lines=total_lines,
                counts=counts,
                inherited_in_source=in_source,
                current_function=function_context,
            )


def parse_clang_ast(
    source: Path,
    output_path: Path | None,
    extra_args: Sequence[str],
) -> tuple[Counter[str], int | None, str | None]:
    executable = shutil.which("clang")
    if executable is None:
        return Counter(), None, "clang not found"

    command = [
        executable,
        "-std=c11",
        "-fsyntax-only",
        *extra_args,
        "-Xclang",
        "-ast-dump=json",
        str(source),
    ]
    result = run_command(command, timeout=300)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.stdout, encoding="utf-8")

    if result.returncode != 0:
        return (
            Counter(),
            None,
            result.stderr.strip() or "Clang AST command failed",
        )

    try:
        tree = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return Counter(), None, f"Invalid Clang JSON AST: {exc}"

    total_lines = len(
        source.read_text(encoding="utf-8", errors="replace").splitlines()
    )
    counts: Counter[str] = Counter()
    walk_clang(
        tree,
        source=source,
        total_lines=total_lines,
        counts=counts,
    )
    return counts, int(sum(counts.values())), None


# ---------------------------------------------------------------------------
# Tree-sitter C extraction and function detection
# ---------------------------------------------------------------------------


def tree_sitter_function_name(node: Any, data: bytes) -> str | None:
    declarator = node.child_by_field_name("declarator")
    if declarator is None:
        return None

    stack = [declarator]
    while stack:
        current = stack.pop()
        if current.type == "identifier":
            return data[current.start_byte : current.end_byte].decode(
                "utf-8", errors="replace"
            )
        stack.extend(reversed(current.children))
    return None


def tree_sitter_call_name(node: Any, data: bytes) -> str | None:
    function = node.child_by_field_name("function")
    if function is None:
        return None
    if function.type == "identifier":
        return data[function.start_byte : function.end_byte].decode(
            "utf-8", errors="replace"
        )
    return None


def parse_tree_sitter(
    source: Path,
) -> tuple[
    Counter[str],
    int | None,
    int | None,
    dict[str, FunctionInfo] | None,
    str | None,
]:
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_c
    except ImportError:
        return (
            Counter(),
            None,
            None,
            None,
            "tree-sitter/tree-sitter-c not installed",
        )

    try:
        language = Language(tree_sitter_c.language())
        try:
            parser = Parser(language)
        except TypeError:
            parser = Parser()
            parser.language = language
    except Exception as exc:
        return (
            Counter(),
            None,
            None,
            None,
            f"Tree-sitter initialization failed: {exc}",
        )

    data = source.read_bytes()
    tree = parser.parse(data)
    counts: Counter[str] = Counter()
    functions: dict[str, FunctionInfo] = {}
    function_calls: dict[str, set[str]] = {}
    leaf_tokens = 0
    node_count = 0

    def visit(node: Any, current_function: str | None = None) -> None:
        nonlocal leaf_tokens, node_count

        function_context = current_function
        if node.type == "function_definition":
            detected = tree_sitter_function_name(node, data)
            if detected:
                function_context = detected
                function_calls.setdefault(detected, set())
                source_slice = data[node.start_byte : node.end_byte]
                functions[detected] = FunctionInfo(
                    name=detected,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    source_hash=hashlib.sha256(source_slice).hexdigest(),
                    calls=(),
                )

        if node.type != "translation_unit":
            scope = (
                f"function.{function_context}"
                if function_context
                else "file"
            )
            counts[f"{scope}.kind.{node.type}"] += 1

            if node.type == "call_expression" and function_context:
                call_name = tree_sitter_call_name(node, data)
                if call_name:
                    counts[f"{scope}.call.{call_name}"] += 1
                    function_calls.setdefault(function_context, set()).add(
                        call_name
                    )

        node_count += 1
        children = list(node.children)
        if not children and node.type != "comment":
            leaf_tokens += 1

        for child in children:
            visit(child, function_context)

    visit(tree.root_node)

    for name, info in list(functions.items()):
        functions[name] = FunctionInfo(
            name=info.name,
            start_line=info.start_line,
            end_line=info.end_line,
            start_byte=info.start_byte,
            end_byte=info.end_byte,
            source_hash=info.source_hash,
            calls=tuple(sorted(function_calls.get(name, set()))),
        )

    return counts, leaf_tokens, node_count, functions, None


# ---------------------------------------------------------------------------
# GumTree
# ---------------------------------------------------------------------------

GUMTREE_ACTION_RE = re.compile(
    r"\b(insert-node|insert-tree|delete-node|delete-tree|"
    r"update-node|move-tree)\b",
    re.I,
)
GUMTREE_OLD_ACTION_RE = re.compile(
    r"^===\s*(insert|delete|update|move)\b",
    re.I,
)


def run_gumtree(
    baseline: Path,
    candidate: Path,
    output_path: Path | None,
    baseline_nodes: int | None,
    candidate_nodes: int | None,
) -> tuple[Counter[str], float | None, str | None]:
    executable = shutil.which("gumtree")
    if executable is None:
        return Counter(), None, "gumtree not found"

    result = run_command(
        [executable, "textdiff", str(baseline), str(candidate)],
        timeout=300,
    )
    combined = result.stdout
    if result.stderr:
        combined += "\n--- STDERR ---\n" + result.stderr
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(combined, encoding="utf-8")

    if result.returncode != 0:
        return (
            Counter(),
            None,
            result.stderr.strip()
            or f"GumTree exited with status {result.returncode}",
        )

    actions: Counter[str] = Counter()
    for line in result.stdout.splitlines():
        match = GUMTREE_ACTION_RE.search(line)
        if match:
            actions[f"action.{match.group(1).lower()}"] += 1
            continue
        old_match = GUMTREE_OLD_ACTION_RE.search(line.strip())
        if old_match:
            actions[f"action.{old_match.group(1).lower()}"] += 1

    total_actions = int(sum(actions.values()))
    normalized_distance = None
    if baseline_nodes is not None and candidate_nodes is not None:
        normalized_distance = total_actions / max(
            baseline_nodes, candidate_nodes, 1
        )

    if total_actions == 0 and baseline.read_bytes() != candidate.read_bytes():
        return (
            actions,
            normalized_distance,
            "GumTree succeeded but no edit actions were parsed; inspect gumtree.txt",
        )
    return actions, normalized_distance, None


# ---------------------------------------------------------------------------
# Source-level metric helpers
# ---------------------------------------------------------------------------


def analyze_source(
    source: Path,
    output_dir: Path | None,
    clang_extra_args: Sequence[str],
) -> ParsedSource:
    clang_counts, clang_nodes, clang_error = parse_clang_ast(
        source,
        output_dir / "clang-ast.json" if output_dir is not None else None,
        clang_extra_args,
    )
    (
        tree_sitter_counts,
        tree_sitter_tokens,
        tree_sitter_nodes,
        tree_sitter_functions,
        tree_sitter_error,
    ) = parse_tree_sitter(source)
    return ParsedSource(
        clang_counts=clang_counts,
        clang_node_count=clang_nodes,
        clang_error=clang_error,
        tree_sitter_counts=tree_sitter_counts,
        tree_sitter_leaf_tokens=tree_sitter_tokens,
        tree_sitter_node_count=tree_sitter_nodes,
        tree_sitter_functions=tree_sitter_functions,
        tree_sitter_error=tree_sitter_error,
    )


def function_change_metrics(
    baseline: dict[str, FunctionInfo] | None,
    candidate: dict[str, FunctionInfo] | None,
) -> dict[str, Any]:
    if baseline is None or candidate is None:
        return {
            "functions_edited_count": None,
            "functions_created_count": None,
            "functions_deleted_count": None,
            "functions_edited": None,
            "functions_created": None,
            "functions_deleted": None,
        }

    created = sorted(set(candidate) - set(baseline))
    deleted = sorted(set(baseline) - set(candidate))
    edited = sorted(
        name
        for name in set(candidate) & set(baseline)
        if candidate[name].source_hash != baseline[name].source_hash
    )
    return {
        "functions_edited_count": len(edited),
        "functions_created_count": len(created),
        "functions_deleted_count": len(deleted),
        "functions_edited": edited,
        "functions_created": created,
        "functions_deleted": deleted,
    }


def counter_delta(
    candidate: Mapping[str, int | float],
    baseline: Mapping[str, int | float],
) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in sorted(set(candidate) | set(baseline)):
        value = float(candidate.get(key, 0.0)) - float(
            baseline.get(key, 0.0)
        )
        if value != 0:
            result[key] = value
    return result


def split_signed_delta(
    values: Mapping[str, int | float],
    prefix: str,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in values.items():
        numeric = float(value)
        if numeric > 0:
            result[f"{prefix}.added.{key}"] = numeric
        elif numeric < 0:
            result[f"{prefix}.removed.{key}"] = -numeric
    return result


FUNCTION_FEATURE_RE = re.compile(r"^function\.([^.]+)\.(.+)$")


def created_function_mapping(
    baseline_functions: Mapping[str, FunctionInfo],
    candidate_functions: Mapping[str, FunctionInfo],
    parser_regex: re.Pattern[str],
    forced_strategy_functions: set[str],
) -> tuple[dict[str, str], dict[str, str]]:
    created_names = sorted(
        set(candidate_functions) - set(baseline_functions),
        key=lambda name: candidate_functions[name].start_byte,
    )
    architecture_mapping: dict[str, str] = {}
    strategy_mapping: dict[str, str] = {}
    parser_index = 0
    behavior_index = 0

    for name in created_names:
        parser_like = bool(parser_regex.search(name)) and (
            name not in forced_strategy_functions
        )
        if parser_like:
            parser_index += 1
            architecture_mapping[name] = f"created_parser_helper_{parser_index}"
        else:
            behavior_index += 1
            canonical = f"created_behavior_helper_{behavior_index}"
            architecture_mapping[name] = canonical
            strategy_mapping[name] = canonical
    return architecture_mapping, strategy_mapping


def canonicalize_function_keys(
    counts: Mapping[str, int | float],
    mapping: Mapping[str, str],
) -> Counter[str]:
    result: Counter[str] = Counter()
    for key, value in counts.items():
        match = FUNCTION_FEATURE_RE.match(key)
        if match:
            function_name, suffix = match.groups()
            function_name = mapping.get(function_name, function_name)
            result[f"function.{function_name}.{suffix}"] += value
        else:
            result[key] += value
    return result


def strategy_function_names(
    baseline_functions: Mapping[str, FunctionInfo],
    candidate_functions: Mapping[str, FunctionInfo],
    parser_regex: re.Pattern[str],
    forced_strategy_functions: set[str],
) -> tuple[set[str], set[str], set[str]]:
    baseline_behavior = {
        name
        for name in baseline_functions
        if name in forced_strategy_functions or not parser_regex.search(name)
    }
    created_behavior = {
        name
        for name in set(candidate_functions) - set(baseline_functions)
        if name in forced_strategy_functions or not parser_regex.search(name)
    }
    edited_behavior = {
        name
        for name in set(candidate_functions) & set(baseline_functions)
        if (
            name in forced_strategy_functions
            or not parser_regex.search(name)
        )
        and candidate_functions[name].source_hash
        != baseline_functions[name].source_hash
    }
    return baseline_behavior, created_behavior, edited_behavior


def filter_strategy_delta(
    values: Mapping[str, int | float],
    allowed_function_names: set[str],
    created_mapping: Mapping[str, str],
) -> dict[str, float]:
    result: dict[str, float] = {}
    allowed_canonical = set(allowed_function_names) | set(
        created_mapping.values()
    )

    for key, value in values.items():
        match = FUNCTION_FEATURE_RE.match(key)
        if not match:
            continue
        function_name, suffix = match.groups()
        canonical = created_mapping.get(function_name, function_name)
        if canonical in allowed_canonical:
            result[f"function.{canonical}.{suffix}"] = float(value)
    return result


# ---------------------------------------------------------------------------
# Feature matrices and distances
# ---------------------------------------------------------------------------


def normalize_rows(matrix: Any) -> Any:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.divide(
        matrix,
        norms,
        out=np.zeros_like(matrix),
        where=norms != 0,
    )


def build_feature_matrix(
    run_ids: Sequence[str],
    blocks_by_run: Mapping[str, Mapping[str, Mapping[str, float]]],
    block_order: Sequence[str],
) -> tuple[Any, list[str], dict[str, list[str]]]:
    parts: list[Any] = []
    feature_names: list[str] = []
    schema: dict[str, list[str]] = {}

    for block_name in block_order:
        names = sorted(
            {
                feature
                for run_id in run_ids
                for feature in blocks_by_run[run_id].get(block_name, {})
            }
        )
        schema[block_name] = names
        if not names:
            continue

        matrix = np.array(
            [
                [
                    float(
                        blocks_by_run[run_id]
                        .get(block_name, {})
                        .get(feature, 0.0)
                    )
                    for feature in names
                ]
                for run_id in run_ids
            ],
            dtype=float,
        )
        parts.append(normalize_rows(matrix))
        feature_names.extend(
            f"{block_name}:{feature}" for feature in names
        )

    if not parts:
        # A zero-column matrix still permits reliability analysis and clearly
        # communicates that structural tooling produced no features.
        return np.zeros((len(run_ids), 0), dtype=float), [], schema

    combined = np.concatenate(parts, axis=1)
    return normalize_rows(combined), feature_names, schema


def cosine_distance_matrix(matrix: Any) -> Any:
    n = len(matrix)
    if matrix.shape[1] == 0:
        return np.zeros((n, n), dtype=float)

    similarity = np.clip(matrix @ matrix.T, -1.0, 1.0)
    distance = 1.0 - similarity
    zero_rows = np.linalg.norm(matrix, axis=1) == 0

    for i in range(n):
        for j in range(n):
            if zero_rows[i] and zero_rows[j]:
                distance[i, j] = 0.0
            elif zero_rows[i] or zero_rows[j]:
                distance[i, j] = 1.0

    np.fill_diagonal(distance, 0.0)
    return np.clip(distance, 0.0, 2.0)


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def agglomerative_labels(distance: Any, threshold: float) -> Any:
    n = len(distance)
    if n == 0:
        return np.array([], dtype=int)
    if n == 1:
        return np.array([0], dtype=int)

    kwargs = {
        "n_clusters": None,
        "linkage": "average",
        "distance_threshold": threshold,
    }
    try:
        model = AgglomerativeClustering(
            metric="precomputed",
            **kwargs,
        )
    except TypeError:
        model = AgglomerativeClustering(
            affinity="precomputed",
            **kwargs,
        )
    return model.fit_predict(distance)


def stabilize_labels(labels: Sequence[int], run_ids: Sequence[str]) -> Any:
    members: dict[int, list[str]] = {}
    for label, run_id in zip(labels, run_ids):
        members.setdefault(int(label), []).append(run_id)

    ordered = sorted(
        members,
        key=lambda label: (-len(members[label]), min(members[label])),
    )
    remap = {old: new for new, old in enumerate(ordered)}
    return np.array([remap[int(label)] for label in labels], dtype=int)


def cluster_statistics(labels: Sequence[int]) -> dict[str, Any]:
    return family_statistics(labels)


def parse_threshold_grid(
    supplied: str | None,
    primary_threshold: float,
) -> list[float]:
    return deterministic_threshold_grid(primary_threshold, supplied)


def threshold_sensitivity(
    distance: Any,
    thresholds: Sequence[float],
    primary_threshold: float = 0.30,
) -> list[dict[str, Any]]:
    return family_threshold_sensitivity(distance, primary_threshold, thresholds)


def mean_pairwise_distance(distance: Any) -> float:
    if len(distance) < 2:
        return 0.0
    return float(np.mean(distance[np.triu_indices(len(distance), k=1)]))


def cluster_representatives(
    labels: Sequence[int],
    distance: Any,
    run_ids: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster_id in sorted(set(int(value) for value in labels)):
        indices = [
            index
            for index, label in enumerate(labels)
            if int(label) == cluster_id
        ]
        if len(indices) == 1:
            medoid_index = indices[0]
            mean_intra = 0.0
            maximum_intra = 0.0
        else:
            means = {
                index: float(
                    np.mean(
                        [
                            distance[index, other]
                            for other in indices
                            if other != index
                        ]
                    )
                )
                for index in indices
            }
            medoid_index = min(
                indices,
                key=lambda index: (means[index], run_ids[index]),
            )
            pair_values = [
                float(distance[left, right])
                for left, right in itertools.combinations(indices, 2)
            ]
            mean_intra = statistics.fmean(pair_values)
            maximum_intra = max(pair_values)

        rows.append(
            {
                "cluster_id": cluster_id,
                "cluster_size": len(indices),
                "medoid_run_id": run_ids[medoid_index],
                "mean_intra_cluster_distance": mean_intra,
                "maximum_intra_cluster_distance": maximum_intra,
                "members": ";".join(run_ids[index] for index in indices),
            }
        )
    return rows


def plot_dendrogram(
    distance: Any,
    run_ids: Sequence[str],
    threshold: float,
    output_path: Path,
    title: str,
    plt: Any,
    scipy_linkage: Any,
    scipy_dendrogram: Any,
    squareform: Any,
) -> None:
    if len(run_ids) < 2:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    condensed = squareform(distance, checks=False)
    linkage_matrix = scipy_linkage(condensed, method="average")
    plt.figure(figsize=(max(9, len(run_ids) * 0.13), 6))
    scipy_dendrogram(
        linkage_matrix,
        labels=list(run_ids),
        leaf_rotation=90,
        leaf_font_size=6 if len(run_ids) > 30 else 9,
    )
    plt.axhline(threshold, linestyle="--", label=f"threshold={threshold:.4f}")
    plt.ylabel("Cosine distance")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def analyze_population(
    *,
    space_name: str,
    population_name: str,
    run_ids: Sequence[str],
    all_run_ids: Sequence[str],
    full_distance: Any,
    full_feature_matrix: Any,
    threshold: float,
    supplied_thresholds: str | None,
    diagnostic_data_dir: Path | None,
    diagnostic_plot_dir: Path | None,
    plotting_helpers: tuple[Any, Any, Any, Any] | None,
    diversity_k_max: int | None,
    bootstrap_repetitions: int,
    bootstrap_seed: int,
) -> tuple[dict[str, Any], Any]:
    indices = [all_run_ids.index(run_id) for run_id in run_ids]
    distance = full_distance[np.ix_(indices, indices)]
    feature_matrix = full_feature_matrix[indices]

    labels = stabilize_labels(
        agglomerative_labels(distance, threshold),
        run_ids,
    )
    stats = cluster_statistics([int(value) for value in labels])
    if not run_ids:
        for key in ("raw_family_count", "raw_cluster_count"):
            stats[key] = None

    prefix = f"{space_name}_{population_name}"
    representative_rows = cluster_representatives(
        labels,
        distance,
        run_ids,
    )
    curve = da_curve([int(value) for value in labels])
    area = nauadc_summary(curve, diversity_k_max)
    vendi = compute_vendi_score(feature_matrix)
    bootstrap = bootstrap_diversity_ci(
        feature_matrix,
        threshold,
        bootstrap_repetitions if population_name == "passing_complete_runs" else 0,
        bootstrap_seed,
        diversity_k_max,
    )
    if diagnostic_data_dir is not None:
        threshold_grid = parse_threshold_grid(supplied_thresholds, threshold)
        sensitivity_rows = threshold_sensitivity(
            distance,
            threshold_grid,
            threshold,
        )
        write_csv(
            diagnostic_data_dir / f"threshold_sensitivity_{prefix}.csv",
            sensitivity_rows,
            [
                "threshold",
                "raw_family_count",
                "effective_family_count",
                "dominant_family_share",
                "singleton_rate",
                "silhouette",
                "adjusted_rand_vs_primary",
            ],
        )
        write_csv(
            diagnostic_data_dir / f"cluster_assignments_{prefix}.csv",
            [
                {
                    "run_id": run_id,
                    "cluster_id": int(label),
                    "space": space_name,
                    "population": population_name,
                }
                for run_id, label in zip(run_ids, labels)
            ],
            ["run_id", "cluster_id", "space", "population"],
        )
        write_csv(
            diagnostic_data_dir / f"cluster_representatives_{prefix}.csv",
            representative_rows,
            [
                "cluster_id",
                "cluster_size",
                "medoid_run_id",
                "mean_intra_cluster_distance",
                "maximum_intra_cluster_distance",
                "members",
            ],
        )
        if diagnostic_plot_dir is None or plotting_helpers is None:
            raise RuntimeError("Diagnostic plotting was not initialized.")
        plt, scipy_linkage, scipy_dendrogram, squareform = plotting_helpers
        plot_dendrogram(
            distance,
            run_ids,
            threshold,
            diagnostic_plot_dir / f"cluster_dendrogram_{prefix}.png",
            f"{space_name.title()} clustering - "
            f"{population_name.replace('_', ' ')}",
            plt,
            scipy_linkage,
            scipy_dendrogram,
            squareform,
        )

    return (
        {
            **stats,
            "run_count": len(run_ids),
            "distance": "cosine",
            "linkage": "average",
            "threshold_used": threshold,
            "measurement_available": bool(run_ids),
            "unavailable_reason": None if run_ids else "no successful candidates with complete measurement",
            "mean_pairwise_distance": mean_pairwise_distance(distance) if run_ids else None,
            "representatives": representative_rows,
            "da_curve": curve,
            **area,
            "vendi_score": vendi["score"],
            "vendi_diagnostic": vendi,
            "bootstrap_95_percent_ci": bootstrap,
        },
        labels,
    )


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    if args.diversity_k_max is not None and args.diversity_k_max < 1:
        raise SystemExit("--diversity-k-max must be positive")
    if args.bootstrap_repetitions < 0:
        raise SystemExit("--bootstrap-repetitions must be non-negative")
    global np, AgglomerativeClustering, silhouette_score
    np, AgglomerativeClustering, silhouette_score = require_python_packages()
    experiment = args.experiment.resolve()
    if not experiment.exists():
        raise SystemExit(f"Experiment directory not found: {experiment}")

    experiment_metadata_path = experiment / "experiment.json"
    sandbox_metadata = None if experiment_metadata_path.exists() else sandbox_run_metadata(experiment)
    if experiment_metadata_path.exists():
        experiment_format = "git_experiment"
        experiment_metadata = read_json(experiment_metadata_path)
        run_root = experiment
    elif sandbox_metadata is not None:
        experiment_format = "sandbox_run"
        run_metadata_path, experiment_metadata = sandbox_metadata
        run_root = run_metadata_path.parent
    else:
        raise SystemExit(
            f"Missing experiment.json and no enclosing sandbox run.json: {experiment}"
        )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else experiment / "analysis"
    )
    diagnostic_packages = (
        require_diagnostic_packages() if args.diagnostic_output else None
    )
    if args.clean_output and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    diagnostic_root = (
        output_dir / "diagnostics" if args.diagnostic_output else None
    )
    diagnostic_clustering_dir = (
        diagnostic_root / "clustering" if diagnostic_root else None
    )
    diagnostic_plot_dir = diagnostic_root / "plots" if diagnostic_root else None
    plotting_helpers = (
        (
            diagnostic_packages[0],
            diagnostic_packages[2],
            diagnostic_packages[3],
            diagnostic_packages[4],
        )
        if diagnostic_packages is not None
        else None
    )

    configured_source = args.source_path or experiment_metadata.get("source_path")
    if configured_source is None:
        raise SystemExit(
            "Sandbox metadata does not record source_path; pass --source-path PATH"
        )
    source_path = Path(str(configured_source))
    if source_path.is_absolute():
        raise SystemExit("source_path must be relative to the candidate workspace")
    if experiment_format == "git_experiment":
        baseline_source = (
            args.baseline_source.resolve()
            if args.baseline_source is not None
            else experiment / "baseline" / source_path
        )
        baseline_kind = "experiment_snapshot"
        attempts = sorted(
            path
            for path in experiment.glob("attempt-*")
            if path.is_dir() and (path / "metadata.json").exists()
        )
    else:
        baseline_source, baseline_kind = resolve_sandbox_baseline(
            experiment_metadata, source_path, args.baseline_source, output_dir
        )
        attempts = sandbox_attempts(experiment, run_root)
    if not baseline_source.exists():
        raise SystemExit(f"Baseline source not found: {baseline_source}")
    if not attempts:
        raise SystemExit("No candidate directories with metadata.json found.")

    attempt_temperatures = {
        read_json(attempt / "metadata.json").get("temperature") for attempt in attempts
    }
    attempt_temperatures.discard(None)
    if experiment_format == "sandbox_run" and len(attempt_temperatures) > 1:
        raise SystemExit(
            "Sandbox analysis must select one temperature condition; pass a temp-* directory, not the mixed run root"
        )
    if experiment_metadata.get("temperature") is None and len(attempt_temperatures) == 1:
        experiment_metadata["temperature"] = next(iter(attempt_temperatures))
    experiment_metadata["source_path"] = str(source_path)

    parser_regex = re.compile(args.strategy_exclude_regex, re.I)
    forced_strategy_functions = set(args.strategy_include_function)
    strategy_threshold = (
        args.strategy_threshold
        if args.strategy_threshold is not None
        else args.cluster_threshold
    )

    tool_paths = {
        "clang": shutil.which("clang"),
        "gumtree": shutil.which("gumtree"),
        "flawfinder": shutil.which("flawfinder"),
        "python": sys.executable,
    }
    if diagnostic_root is not None:
        write_json(diagnostic_root / "tool_paths.json", tool_paths)

    print(f"Experiment: {experiment}")
    print(f"Output:     {output_dir}")
    print(f"Runs:       {len(attempts)}")
    print(f"Architecture threshold: {args.cluster_threshold}")
    print(f"Strategy threshold:     {strategy_threshold}")
    for name, path in tool_paths.items():
        print(f"{name:11s} {path}")

    print("\nAnalyzing baseline...")
    baseline_dir = diagnostic_root / "baseline" if diagnostic_root else None
    baseline = analyze_source(
        baseline_source,
        baseline_dir,
        args.clang_extra_arg,
    )
    baseline_functions = baseline.tree_sitter_functions or {}
    if baseline_dir is not None:
        write_json(
            baseline_dir / "features.json",
            {
                "source": str(baseline_source),
                "clang_counts": dict(baseline.clang_counts),
                "clang_node_count": baseline.clang_node_count,
                "clang_error": baseline.clang_error,
                "tree_sitter_counts": dict(baseline.tree_sitter_counts),
                "tree_sitter_leaf_tokens": baseline.tree_sitter_leaf_tokens,
                "tree_sitter_node_count": baseline.tree_sitter_node_count,
                "tree_sitter_functions": {
                    name: asdict(info)
                    for name, info in baseline_functions.items()
                },
                "tree_sitter_error": baseline.tree_sitter_error,
            },
        )

    rows: list[dict[str, Any]] = []
    architecture_blocks: dict[str, dict[str, dict[str, float]]] = {}
    strategy_blocks: dict[str, dict[str, dict[str, float]]] = {}
    candidate_sources: dict[str, Path] = {}

    print("\nAnalyzing candidates...")
    for index, attempt in enumerate(attempts, start=1):
        raw_metadata = read_json(attempt / "metadata.json")
        if experiment_format == "sandbox_run":
            test_exit = raw_metadata.get("test_exit_code")
            public_success = test_exit == 0 and raw_metadata.get("opencode_exit_code") == 0
            raw_metadata.update(
                {
                    "run_id": str(attempt.relative_to(run_root)),
                    "build_exit_code": 0,
                    "base_test_exit_code": 0,
                    "feature_test_exit_code": test_exit,
                    "extra_test_exit_code": 0,
                    "initial_success": public_success,
                    "public_validation_success": public_success,
                    "repair_loops": 0,
                    "llm_invocations": 1,
                    "success_loop": 0 if public_success else None,
                    "initial_opencode_runtime_ms": raw_metadata.get("opencode_runtime_ms", 0),
                    "repair_opencode_runtime_ms": 0,
                    "total_opencode_runtime_ms": raw_metadata.get("opencode_runtime_ms", 0),
                }
            )
        metadata = normalize_repair_metadata(raw_metadata)
        run_id = str(metadata.get("run_id", attempt.name))
        run_output = (
            diagnostic_root / "runs" / attempt.name
            if diagnostic_root
            else None
        )

        candidate_source = attempt / ("candidate" if experiment_format == "git_experiment" else "workdir") / source_path
        candidate_missing = not candidate_source.exists()
        measured_source = candidate_source if not candidate_missing else baseline_source

        candidate = analyze_source(
            measured_source,
            run_output,
            args.clang_extra_arg,
        )
        candidate_functions = candidate.tree_sitter_functions or {}

        gumtree_actions, gumtree_distance, gumtree_error = run_gumtree(
            baseline_source,
            measured_source,
            run_output / "gumtree.txt" if run_output is not None else None,
            baseline.tree_sitter_node_count,
            candidate.tree_sitter_node_count,
        )
        function_metrics = function_change_metrics(
            baseline.tree_sitter_functions,
            candidate.tree_sitter_functions,
        )
        patch_metrics = (
            parse_change_metrics(attempt)
            if experiment_format == "git_experiment"
            else source_change_metrics(baseline_source, measured_source)
        )

        architecture_mapping, strategy_created_mapping = (
            created_function_mapping(
                baseline_functions,
                candidate_functions,
                parser_regex,
                forced_strategy_functions,
            )
        )

        candidate_clang_architecture = canonicalize_function_keys(
            candidate.clang_counts,
            architecture_mapping,
        )
        candidate_tree_architecture = canonicalize_function_keys(
            candidate.tree_sitter_counts,
            architecture_mapping,
        )
        architecture_clang_delta = counter_delta(
            candidate_clang_architecture,
            baseline.clang_counts,
        )
        architecture_tree_delta = counter_delta(
            candidate_tree_architecture,
            baseline.tree_sitter_counts,
        )

        (
            baseline_behavior,
            created_behavior,
            edited_behavior,
        ) = strategy_function_names(
            baseline_functions,
            candidate_functions,
            parser_regex,
            forced_strategy_functions,
        )

        raw_clang_delta = counter_delta(
            candidate.clang_counts,
            baseline.clang_counts,
        )
        raw_tree_delta = counter_delta(
            candidate.tree_sitter_counts,
            baseline.tree_sitter_counts,
        )
        strategy_clang_delta = filter_strategy_delta(
            raw_clang_delta,
            baseline_behavior,
            strategy_created_mapping,
        )
        strategy_tree_delta = filter_strategy_delta(
            raw_tree_delta,
            baseline_behavior,
            strategy_created_mapping,
        )

        architecture_blocks[run_id] = {
            "clang": split_signed_delta(
                architecture_clang_delta,
                "clang",
            )
            if candidate.clang_error is None
            and baseline.clang_error is None
            else {},
            "tree_sitter": split_signed_delta(
                architecture_tree_delta,
                "tree_sitter",
            )
            if candidate.tree_sitter_error is None
            and baseline.tree_sitter_error is None
            else {},
            "gumtree": {
                f"gumtree.{key}": float(value)
                for key, value in gumtree_actions.items()
            }
            if gumtree_error is None
            else {},
        }
        strategy_blocks[run_id] = {
            "clang": split_signed_delta(
                strategy_clang_delta,
                "clang",
            )
            if candidate.clang_error is None
            and baseline.clang_error is None
            else {},
            "tree_sitter": split_signed_delta(
                strategy_tree_delta,
                "tree_sitter",
            )
            if candidate.tree_sitter_error is None
            and baseline.tree_sitter_error is None
            else {},
        }

        if experiment_format == "git_experiment":
            base_test = parse_test_log(attempt / "base-tests.log")
            feature_test = parse_test_log(attempt / "feature-tests.log")
            extra_test = parse_test_log(attempt / "extra-tests.log")
        else:
            base_test = parse_test_log(Path("/nonexistent"))
            feature_test = parse_test_log(attempt / "test.log")
            extra_test = parse_test_log(Path("/nonexistent"))
        llm_tokens = parse_llm_tokens(attempt / "opencode.log")

        complete_architecture_measurement = all(
            [
                not candidate_missing,
                baseline.clang_error is None,
                baseline.tree_sitter_error is None,
                candidate.clang_error is None,
                candidate.tree_sitter_error is None,
                gumtree_error is None,
            ]
        )
        complete_strategy_measurement = all(
            [
                not candidate_missing,
                baseline.clang_error is None,
                baseline.tree_sitter_error is None,
                candidate.clang_error is None,
                candidate.tree_sitter_error is None,
            ]
        )

        row: dict[str, Any] = {
            **metadata,
            **patch_metrics,
            **function_metrics,
            "candidate_missing": candidate_missing,
            "candidate_sha256": file_sha256(measured_source) if not candidate_missing else None,
            "source_bytes": measured_source.stat().st_size if not candidate_missing else None,
            "source_tree_sitter_leaf_tokens": (
                candidate.tree_sitter_leaf_tokens
            ),
            "source_tree_sitter_node_count": (
                candidate.tree_sitter_node_count
            ),
            "source_clang_node_count": candidate.clang_node_count,
            "gumtree_action_count": (
                int(sum(gumtree_actions.values()))
                if gumtree_error is None
                else None
            ),
            "gumtree_normalized_edit_distance": gumtree_distance,
            "base_tests_run": base_test["tests_run"],
            "base_test_failures": base_test["failures"],
            "base_test_errors": base_test["errors"],
            "base_tests_passed": base_test["tests_passed"],
            "feature_tests_run": feature_test["tests_run"],
            "feature_test_failures": feature_test["failures"],
            "feature_test_errors": feature_test["errors"],
            "feature_tests_passed": feature_test["tests_passed"],
            "extra_tests_run": extra_test["tests_run"],
            "extra_test_failures": extra_test["failures"],
            "extra_test_errors": extra_test["errors"],
            "extra_tests_passed": extra_test["tests_passed"],
            "llm_input_tokens": llm_tokens["input_tokens"],
            "llm_output_tokens": llm_tokens["output_tokens"],
            "llm_reasoning_tokens": llm_tokens["reasoning_tokens"],
            "llm_cache_read_tokens": llm_tokens["cache_read_tokens"],
            "llm_total_tokens": llm_tokens["total_tokens"],
            "opencode_permission_rejected": opencode_permission_rejected(
                attempt / "opencode.log"
            ),
            "clang_available": candidate.clang_error is None,
            "tree_sitter_available": candidate.tree_sitter_error is None,
            "gumtree_available": gumtree_error is None,
            "complete_architecture_measurement": (
                complete_architecture_measurement
            ),
            "complete_strategy_measurement": complete_strategy_measurement,
            "clang_error": candidate.clang_error,
            "tree_sitter_error": candidate.tree_sitter_error,
            "gumtree_error": gumtree_error,
        }
        rows.append(row)
        if not candidate_missing:
            candidate_sources[run_id] = measured_source

        if run_output is not None:
            write_json(
                run_output / "features.json",
                {
                    "run_id": run_id,
                    "function_metrics": function_metrics,
                    "function_name_mapping": {
                        "architecture": architecture_mapping,
                        "strategy": strategy_created_mapping,
                    },
                    "strategy_function_sets": {
                        "baseline_behavior": sorted(baseline_behavior),
                        "created_behavior": sorted(created_behavior),
                        "edited_behavior": sorted(edited_behavior),
                    },
                    "architecture_clang_delta": architecture_clang_delta,
                    "architecture_tree_sitter_delta": architecture_tree_delta,
                    "strategy_clang_delta": strategy_clang_delta,
                    "strategy_tree_sitter_delta": strategy_tree_delta,
                    "gumtree_actions": dict(gumtree_actions),
                    "gumtree_normalized_edit_distance": gumtree_distance,
                    "architecture_blocks": architecture_blocks[run_id],
                    "strategy_blocks": strategy_blocks[run_id],
                    "candidate_functions": {
                        name: asdict(info)
                        for name, info in candidate_functions.items()
                    },
                    "tool_errors": {
                        "clang": candidate.clang_error,
                        "tree_sitter": candidate.tree_sitter_error,
                        "gumtree": gumtree_error,
                    },
                },
            )

        print(f"[{index:3d}/{len(attempts):3d}] {run_id}", flush=True)

    run_ids = [str(row["run_id"]) for row in rows]

    architecture_matrix, architecture_features, architecture_schema = (
        build_feature_matrix(
            run_ids,
            architecture_blocks,
            ("clang", "tree_sitter", "gumtree"),
        )
    )
    strategy_matrix, strategy_features, strategy_schema = build_feature_matrix(
        run_ids,
        strategy_blocks,
        ("clang", "tree_sitter"),
    )
    architecture_distance = cosine_distance_matrix(architecture_matrix)
    strategy_distance = cosine_distance_matrix(strategy_matrix)

    complete_architecture_ids = [
        str(row["run_id"])
        for row in rows
        if bool(row["complete_architecture_measurement"])
    ]
    complete_strategy_ids = [
        str(row["run_id"])
        for row in rows
        if bool(row["complete_strategy_measurement"])
    ]
    passing_ids = [
        str(row["run_id"])
        for row in rows
        if bool(row.get("overall_success"))
    ]
    passing_architecture_ids = [
        run_id for run_id in passing_ids if run_id in complete_architecture_ids
    ]
    passing_strategy_ids = [
        run_id for run_id in passing_ids if run_id in complete_strategy_ids
    ]

    population_ids = {
        "all_runs": run_ids,
        "complete_runs": complete_architecture_ids,
        "passing_runs": passing_ids,
        "passing_complete_runs": passing_architecture_ids,
    }
    strategy_population_ids = {
        "all_runs": run_ids,
        "complete_runs": complete_strategy_ids,
        "passing_runs": passing_ids,
        "passing_complete_runs": passing_strategy_ids,
    }

    architecture_summaries: dict[str, Any] = {}
    architecture_labels: dict[str, Any] = {}
    for population_name, ids in population_ids.items():
        summary, labels = analyze_population(
            space_name="architecture",
            population_name=population_name,
            run_ids=ids,
            all_run_ids=run_ids,
            full_distance=architecture_distance,
            full_feature_matrix=architecture_matrix,
            threshold=args.cluster_threshold,
            supplied_thresholds=args.thresholds,
            diagnostic_data_dir=diagnostic_clustering_dir,
            diagnostic_plot_dir=diagnostic_plot_dir,
            plotting_helpers=plotting_helpers,
            diversity_k_max=args.diversity_k_max,
            bootstrap_repetitions=args.bootstrap_repetitions,
            bootstrap_seed=args.bootstrap_seed,
        )
        architecture_summaries[population_name] = summary
        architecture_labels[population_name] = labels

    strategy_summaries: dict[str, Any] = {}
    strategy_labels: dict[str, Any] = {}
    for population_name, ids in strategy_population_ids.items():
        summary, labels = analyze_population(
            space_name="strategy",
            population_name=population_name,
            run_ids=ids,
            all_run_ids=run_ids,
            full_distance=strategy_distance,
            full_feature_matrix=strategy_matrix,
            threshold=strategy_threshold,
            supplied_thresholds=args.thresholds,
            diagnostic_data_dir=diagnostic_clustering_dir,
            diagnostic_plot_dir=diagnostic_plot_dir,
            plotting_helpers=plotting_helpers,
            diversity_k_max=args.diversity_k_max,
            bootstrap_repetitions=args.bootstrap_repetitions,
            bootstrap_seed=args.bootstrap_seed + 1,
        )
        strategy_summaries[population_name] = summary
        strategy_labels[population_name] = labels

    def label_map(ids: Sequence[str], labels: Sequence[int]) -> dict[str, int]:
        return {
            run_id: int(label)
            for run_id, label in zip(ids, labels)
        }

    architecture_all_map = label_map(
        population_ids["all_runs"],
        architecture_labels["all_runs"],
    )
    architecture_complete_map = label_map(
        population_ids["complete_runs"],
        architecture_labels["complete_runs"],
    )
    architecture_passing_map = label_map(
        population_ids["passing_runs"],
        architecture_labels["passing_runs"],
    )
    architecture_passing_complete_map = label_map(
        population_ids["passing_complete_runs"],
        architecture_labels["passing_complete_runs"],
    )
    strategy_all_map = label_map(
        strategy_population_ids["all_runs"],
        strategy_labels["all_runs"],
    )
    strategy_complete_map = label_map(
        strategy_population_ids["complete_runs"],
        strategy_labels["complete_runs"],
    )
    strategy_passing_map = label_map(
        strategy_population_ids["passing_runs"],
        strategy_labels["passing_runs"],
    )
    strategy_passing_complete_map = label_map(
        strategy_population_ids["passing_complete_runs"],
        strategy_labels["passing_complete_runs"],
    )

    architecture_primary_name = "passing_complete_runs"
    strategy_primary_name = "passing_complete_runs"
    architecture_primary_map = label_map(
        population_ids[architecture_primary_name],
        architecture_labels[architecture_primary_name],
    )
    strategy_primary_map = label_map(
        strategy_population_ids[strategy_primary_name],
        strategy_labels[strategy_primary_name],
    )

    def primary_cluster_details(
        population_summary: Mapping[str, Any],
    ) -> tuple[Mapping[int, int], dict[int, str]]:
        sizes = population_summary.get("cluster_sizes", {})
        representatives = population_summary.get("representatives", [])
        medoids = {
            int(representative["cluster_id"]): str(
                representative["medoid_run_id"]
            )
            for representative in representatives
        }
        return sizes, medoids

    architecture_sizes, architecture_medoids = primary_cluster_details(
        architecture_summaries[architecture_primary_name]
    )
    strategy_sizes, strategy_medoids = primary_cluster_details(
        strategy_summaries[strategy_primary_name]
    )

    diversity_dir = output_dir / "diversity"
    write_csv(
        diversity_dir / "architecture_clusters.csv",
        [
            {"run_id": run_id, "family_id": architecture_primary_map[run_id]}
            for run_id in passing_architecture_ids
        ],
        ["run_id", "family_id"],
    )
    write_csv(
        diversity_dir / "strategy_clusters.csv",
        [
            {"run_id": run_id, "family_id": strategy_primary_map[run_id]}
            for run_id in passing_strategy_ids
        ],
        ["run_id", "family_id"],
    )
    write_csv(
        diversity_dir / "architecture_da_curve.csv",
        architecture_summaries[architecture_primary_name]["da_curve"],
        ["k", "da_at_k"],
    )
    write_csv(
        diversity_dir / "strategy_da_curve.csv",
        strategy_summaries[strategy_primary_name]["da_curve"],
        ["k", "da_at_k"],
    )

    successful_candidate_rows = [row for row in rows if bool(row.get("overall_success"))]
    successful_hash_rows = [
        row
        for row in successful_candidate_rows
        if isinstance(row.get("candidate_sha256"), str)
    ]
    exact_repetition = exact_repetition_summary(
        [str(row["candidate_sha256"]) for row in successful_hash_rows],
        [str(row["run_id"]) for row in successful_hash_rows],
    )
    exact_repetition["successful_candidates"] = len(successful_candidate_rows)
    exact_repetition["hash_measurement_coverage"] = (
        len(successful_hash_rows) / len(successful_candidate_rows)
        if successful_candidate_rows
        else None
    )
    if len(successful_hash_rows) != len(successful_candidate_rows):
        exact_repetition["exact_unique_rate"] = None
        exact_repetition["exact_modal_share"] = None
        exact_repetition["unavailable_reason"] = "one or more successful candidates lacks a source hash"
    else:
        exact_repetition["unavailable_reason"] = None
    write_csv(
        diversity_dir / "exact_repetition.csv",
        [
            {**group, "members": ";".join(group["members"])}
            for group in exact_repetition["hash_groups"]
        ],
        ["sha256", "count", "members"],
    )
    diagnostics_dir = output_dir / "diagnostics"
    for space_name, population_ids_for_space, distance, threshold in (
        ("architecture", passing_architecture_ids, architecture_distance, args.cluster_threshold),
        ("strategy", passing_strategy_ids, strategy_distance, strategy_threshold),
    ):
        indices = [run_ids.index(run_id) for run_id in population_ids_for_space]
        primary_distance = distance[np.ix_(indices, indices)]
        sensitivity = family_threshold_sensitivity(
            primary_distance,
            threshold,
            deterministic_threshold_grid(threshold, args.thresholds),
        )
        write_csv(
            diagnostics_dir / f"{space_name}_threshold_sensitivity.csv",
            sensitivity,
            [
                "threshold", "raw_family_count", "effective_family_count",
                "dominant_family_share", "singleton_rate", "silhouette",
                "adjusted_rand_vs_primary",
            ],
        )

    uncertainty_rows = []
    for space_name, population in (
        ("architecture", architecture_summaries[architecture_primary_name]),
        ("strategy", strategy_summaries[strategy_primary_name]),
    ):
        for metric, interval in population["bootstrap_95_percent_ci"].items():
            if not isinstance(interval, Mapping):
                continue
            uncertainty_rows.append({"space": space_name, "metric": metric, **interval})
    write_csv(
        diagnostics_dir / "uncertainty.csv",
        uncertainty_rows,
        ["space", "metric", "lower", "upper", "replicates"],
    )
    security_summary: dict[str, Any] = {"status": "not_requested"}
    if args.security_diagnostics:
        security_rows = []
        flawfinder_rows = []
        for run_id in passing_ids:
            source = candidate_sources.get(run_id)
            if source is None:
                continue
            security_rows.append({"run_id": run_id, **security_profile(source.read_bytes())})
            flawfinder = flawfinder_crosscheck(source)
            flawfinder_rows.append(
                {
                    "run_id": run_id,
                    "status": flawfinder["status"],
                    "reason": flawfinder["reason"],
                    "hit_count": len(flawfinder["hits"]),
                }
            )
        write_csv(
            output_dir / "security" / "security_profiles.csv",
            security_rows,
            [
                "run_id", "unsafe_call_count", "bounded_risky_call_count",
                "heap_allocation_deallocation_call_count",
                "fixed_size_stack_buffer_count", "indexing_operation_count",
            ],
        )
        write_csv(
            output_dir / "security" / "flawfinder.csv",
            flawfinder_rows,
            ["run_id", "status", "reason", "hit_count"],
        )
        security_summary = {
            "status": "completed",
            "profiles": len(security_rows),
            "flawfinder_available_runs": sum(row["status"] == "available" for row in flawfinder_rows),
            "flawfinder_unavailable_runs": sum(row["status"] != "available" for row in flawfinder_rows),
        }

    for row in rows:
        run_id = str(row["run_id"])
        architecture_cluster = architecture_primary_map.get(run_id)
        strategy_cluster = strategy_primary_map.get(run_id)
        row["architecture_cluster_id"] = architecture_cluster
        row["strategy_cluster_id"] = strategy_cluster
        row["architecture_cluster_size"] = (
            architecture_sizes.get(architecture_cluster)
            if architecture_cluster is not None
            else None
        )
        row["strategy_cluster_size"] = (
            strategy_sizes.get(strategy_cluster)
            if strategy_cluster is not None
            else None
        )
        row["architecture_cluster_medoid"] = (
            run_id == architecture_medoids.get(architecture_cluster)
            if architecture_cluster is not None
            else None
        )
        row["strategy_cluster_medoid"] = (
            run_id == strategy_medoids.get(strategy_cluster)
            if strategy_cluster is not None
            else None
        )
        if args.diagnostic_output:
            row["architecture_cluster_all_runs"] = architecture_all_map.get(run_id)
            row["architecture_cluster_complete_runs"] = (
                architecture_complete_map.get(run_id)
            )
            row["architecture_cluster_passing_runs"] = (
                architecture_passing_map.get(run_id)
            )
            row["architecture_cluster_passing_complete_runs"] = (
                architecture_passing_complete_map.get(run_id)
            )
            row["strategy_cluster_all_runs"] = strategy_all_map.get(run_id)
            row["strategy_cluster_complete_runs"] = strategy_complete_map.get(
                run_id
            )
            row["strategy_cluster_passing_runs"] = strategy_passing_map.get(run_id)
            row["strategy_cluster_passing_complete_runs"] = (
                strategy_passing_complete_map.get(run_id)
            )

    flattened_rows = [flatten_dict(row) for row in rows]
    fields = sorted({key for row in flattened_rows for key in row})
    write_csv(output_dir / "per_run_metrics.csv", flattened_rows, fields)
    write_csv(output_dir / "runs.csv", flattened_rows, fields)

    if diagnostic_clustering_dir is not None:
        architecture_feature_rows = [
            {
                "run_id": run_id,
                **{
                    feature: float(value)
                    for feature, value in zip(
                        architecture_features,
                        architecture_matrix[index],
                    )
                },
            }
            for index, run_id in enumerate(run_ids)
        ]
        strategy_feature_rows = [
            {
                "run_id": run_id,
                **{
                    feature: float(value)
                    for feature, value in zip(
                        strategy_features,
                        strategy_matrix[index],
                    )
                },
            }
            for index, run_id in enumerate(run_ids)
        ]
        write_csv(
            diagnostic_clustering_dir / "architecture_feature_matrix.csv",
            architecture_feature_rows,
            ["run_id", *architecture_features],
        )
        write_csv(
            diagnostic_clustering_dir / "strategy_feature_matrix.csv",
            strategy_feature_rows,
            ["run_id", *strategy_features],
        )
        # The compatibility filename means the architecture feature matrix.
        write_csv(
            diagnostic_clustering_dir / "feature_matrix.csv",
            architecture_feature_rows,
            ["run_id", *architecture_features],
        )

        write_json(
            diagnostic_clustering_dir / "feature_schema.json",
            {
                "architecture": {
                    "blocks": architecture_schema,
                    "description": (
                        "Configured-source architecture: non-duplicated Clang AST "
                        "deltas, Tree-sitter C deltas, and GumTree actions."
                    ),
                },
                "strategy": {
                    "blocks": strategy_schema,
                    "description": (
                        "Implementation strategy: Clang and Tree-sitter deltas "
                        "from behavioral functions only; main and parser/usage "
                        "helpers are excluded by the configured regex."
                    ),
                    "excluded_function_regex": args.strategy_exclude_regex,
                    "forced_includes": sorted(forced_strategy_functions),
                },
                "normalization": (
                    "Each tool block is L2-normalized per run; concatenated "
                    "vectors are L2-normalized again."
                ),
                "signed_delta_encoding": (
                    "Positive and negative baseline deltas are split into "
                    "separate added/removed non-negative features."
                ),
                "created_function_canonicalization": (
                    "New function names are replaced by ordered parser-helper "
                    "or behavior-helper placeholders so arbitrary names do "
                    "not create artificial distance."
                ),
                "excluded_from_clustering": [
                    "lines and files edited",
                    "source token count",
                    "runtime",
                    "test outcomes",
                    "lexical, token-winnowing, APTED, and API-call distances",
                    "security profiles",
                    "LLM token usage",
                ],
            },
        )

        pairwise_rows: list[dict[str, Any]] = []
        successful_source_ids = [run_id for run_id in passing_ids if run_id in candidate_sources]
        run_index = {run_id: index for index, run_id in enumerate(run_ids)}
        for left, right in itertools.combinations(successful_source_ids, 2):
            left_index = run_index[left]
            right_index = run_index[right]
            validation = validation_distances(
                candidate_sources[left].read_bytes(),
                candidate_sources[right].read_bytes(),
            )
            pairwise_rows.append({
                "left_run_id": left,
                "right_run_id": right,
                **validation,
                "architecture_distance": (
                    float(architecture_distance[left_index, right_index])
                    if left in architecture_primary_map and right in architecture_primary_map
                    else None
                ),
                "strategy_distance": (
                    float(strategy_distance[left_index, right_index])
                    if left in strategy_primary_map and right in strategy_primary_map
                    else None
                ),
                "same_architecture_family": (
                    int(architecture_primary_map[left] == architecture_primary_map[right])
                    if left in architecture_primary_map and right in architecture_primary_map
                    else None
                ),
                "same_strategy_family": (
                    int(strategy_primary_map[left] == strategy_primary_map[right])
                    if left in strategy_primary_map and right in strategy_primary_map
                    else None
                ),
            })
        write_csv(
            diagnostic_root / "pairwise_validation.csv",
            pairwise_rows,
            [
                "left_run_id", "right_run_id", "lexical_distance",
                "token_winnowing_distance", "apted_distance",
                "api_callset_distance", "architecture_distance",
                "strategy_distance", "same_architecture_family",
                "same_strategy_family",
            ],
        )
        correlation_metrics = [
            "lexical_distance", "token_winnowing_distance", "apted_distance",
            "api_callset_distance", "architecture_distance", "strategy_distance",
        ]
        write_csv(
            diagnostic_root / "cross_representation_correlation.csv",
            pairwise_spearman_correlations(pairwise_rows, correlation_metrics),
            ["left_metric", "right_metric", "spearman_correlation", "supporting_pairs"],
        )

    n = len(rows)
    successful = sum(bool(row.get("overall_success")) for row in rows)
    configured_max_loops = experiment_metadata.get("max_loops")
    if not isinstance(configured_max_loops, int) or isinstance(
        configured_max_loops, bool
    ):
        configured_max_loops = None
    repair_summary = build_repair_summary(rows, configured_max_loops)
    runtime_seconds = [
        float(row["total_runtime_ms"]) / 1000.0
        for row in rows
        if row.get("total_runtime_ms") is not None
    ]
    gumtree_distances = [
        float(row["gumtree_normalized_edit_distance"])
        for row in rows
        if isinstance(
            row.get("gumtree_normalized_edit_distance"),
            (int, float),
        )
    ]
    stage_success_ratios: dict[str, float | None] = {}
    for key in (
        "opencode_exit_code",
        "build_exit_code",
        "base_test_exit_code",
        "feature_test_exit_code",
        "extra_test_exit_code",
    ):
        available = [
            row.get(key)
            for row in rows
            if row.get(key) is not None
        ]
        stage_success_ratios[key.removesuffix("_exit_code")] = (
            sum(value == 0 for value in available) / len(available)
            if available
            else None
        )

    summary = {
        "schema_version": 4,
        "analyzer_version": ANALYZER_VERSION,
        "experiment_format": experiment_format,
        "baseline_kind": baseline_kind,
        "source_path": str(source_path),
        "experiment": str(experiment),
        "output_directory": str(output_dir),
        "model": experiment_metadata.get("model"),
        "temperature": experiment_metadata.get("temperature"),
        "runs_analyzed": n,
        "successful_runs": successful,
        "architecture_population_n": len(passing_architecture_ids),
        "architecture_measurement_coverage": (
            len(passing_architecture_ids) / successful if successful else None
        ),
        "strategy_population_n": len(passing_strategy_ids),
        "strategy_measurement_coverage": (
            len(passing_strategy_ids) / successful if successful else None
        ),
        "success_ratio": successful / n if n else None,
        "diversity_k_max": args.diversity_k_max,
        "exact_generation_convergence": exact_repetition,
        "stage_success_ratios": stage_success_ratios,
        "repair": repair_summary,
        "uncertainty": {
            "wilson_95_percent": {
                "overall_success_rate": wilson_interval(successful, n),
                "initial_public_success_rate": wilson_interval(
                    repair_summary["initial_public_successes"], n
                ),
                "final_public_success_rate": wilson_interval(
                    repair_summary["final_public_successes"], n
                ),
                "repair_recovery_rate": wilson_interval(
                    repair_summary["recovered_initially_failed_runs"],
                    n - repair_summary["initial_public_successes"],
                ),
            },
            "diversity_bootstrap": {
                "architecture": architecture_summaries[architecture_primary_name]["bootstrap_95_percent_ci"],
                "strategy": strategy_summaries[strategy_primary_name]["bootstrap_95_percent_ci"],
            },
        },
        "pass_at_k": {
            f"pass@{k}": pass_at_k(n, successful, k)
            for k in (1, 5, 10, 20, 50, 100)
            if k <= n
        },
        "runtime_seconds": {
            "mean": statistics.fmean(runtime_seconds)
            if runtime_seconds
            else None,
            "median": statistics.median(runtime_seconds)
            if runtime_seconds
            else None,
            "minimum": min(runtime_seconds) if runtime_seconds else None,
            "maximum": max(runtime_seconds) if runtime_seconds else None,
            "total": sum(runtime_seconds) if runtime_seconds else None,
        },
        "gumtree": {
            "runs_with_measurement": len(gumtree_distances),
            "mean_normalized_baseline_edit_distance": (
                statistics.fmean(gumtree_distances)
                if gumtree_distances
                else None
            ),
        },
        "clustering": {
            "primary_population": {
                "architecture": "passing_complete_runs",
                "strategy": "passing_complete_runs",
            },
            "architecture": {
                "threshold_used": args.cluster_threshold,
                "populations": architecture_summaries,
            },
            "strategy": {
                "threshold_used": strategy_threshold,
                "excluded_function_regex": args.strategy_exclude_regex,
                "populations": strategy_summaries,
            },
            "note": (
                "Threshold sensitivity is a robustness analysis only. The "
                "configured primary thresholds are never optimized on the "
                "reported population."
            ),
        },
        "measurement_counts": {
            "clang": sum(bool(row["clang_available"]) for row in rows),
            "tree_sitter": sum(
                bool(row["tree_sitter_available"]) for row in rows
            ),
            "gumtree": sum(bool(row["gumtree_available"]) for row in rows),
            "complete_architecture": len(complete_architecture_ids),
            "complete_strategy": len(complete_strategy_ids),
        },
        "baseline_errors": {
            "clang": baseline.clang_error,
            "tree_sitter": baseline.tree_sitter_error,
        },
        "security_diagnostics": security_summary,
        "tool_paths": tool_paths,
    }
    for metric, interval in summary["uncertainty"]["wilson_95_percent"].items():
        uncertainty_rows.append(
            {
                "space": "reliability",
                "metric": metric,
                "lower": interval["lower"],
                "upper": interval["upper"],
                "replicates": interval["n"],
            }
        )
    write_csv(
        diagnostics_dir / "uncertainty.csv",
        uncertainty_rows,
        ["space", "metric", "lower", "upper", "replicates"],
    )
    write_json(output_dir / "summary.json", summary)

    paper_row = build_paper_metrics_row(
        experiment_metadata,
        summary,
        rows,
        issue_label=args.paper_issue_label,
        checkpoint_label=args.paper_checkpoint_label,
    )
    paper_descriptive_row = build_paper_descriptive_row(
        experiment_metadata,
        summary,
        rows,
        issue_label=args.paper_issue_label,
        checkpoint_label=args.paper_checkpoint_label,
    )
    paper_output_dir = output_dir
    write_json(paper_output_dir / "paper_metrics_row.json", paper_row)
    write_csv(
        paper_output_dir / "paper_metrics.csv",
        [paper_row],
        PAPER_METRICS_COLUMNS,
    )
    write_csv(
        paper_output_dir / "paper_descriptive_metrics.csv",
        [paper_descriptive_row],
        PAPER_DESCRIPTIVE_COLUMNS,
    )
    write_json(
        paper_output_dir / "paper_metrics_schema.json",
        paper_metrics_schema(),
    )
    if experiment_format == "git_experiment":
        rebuild_paper_metrics_aggregate(
            infer_repository_root(experiment, experiment_metadata)
        )

    print("\nAnalysis complete")
    print(f"Success: {successful}/{n} ({successful / n:.1%})")
    print(
        "Initial public success: "
        f"{repair_summary['initial_public_successes']}/{n} "
        f"({repair_summary['initial_public_success_rate']:.1%})"
    )
    print(
        "Final public success:   "
        f"{repair_summary['final_public_successes']}/{n} "
        f"({repair_summary['final_public_success_rate']:.1%})"
    )
    for curve_point in repair_summary["success_curve"]:
        print(
            f"Success by loop {curve_point['loop']}: "
            f"{curve_point['success_rate']:.1%}"
        )
    architecture_primary_name = "passing_complete_runs"
    strategy_primary_name = "passing_complete_runs"
    architecture_primary = architecture_summaries[architecture_primary_name]
    strategy_primary = strategy_summaries[strategy_primary_name]
    print(
        "Passing architecture: "
        f"{architecture_primary['raw_family_count']} raw, "
        f"{architecture_primary['effective_family_count']} effective, "
        f"dominant {architecture_primary['dominant_family_share']}"
    )
    print(
        "Passing strategy:     "
        f"{strategy_primary['raw_family_count']} raw, "
        f"{strategy_primary['effective_family_count']} effective, "
        f"dominant {strategy_primary['dominant_family_share']}"
    )
    print(f"Results: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
