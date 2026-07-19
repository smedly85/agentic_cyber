#!/usr/bin/env python3
"""Analyze repeated OpenCode maintenance runs.

This is the unified analyzer used by ``run_llm_experiment.sh``.  It keeps the
original command-line contract (especially ``--cluster-threshold``), while
providing two distinct structural analyses:

1. Whole-patch architecture clustering
   Uses non-duplicated Clang AST deltas, Tree-sitter C deltas, and GumTree edit
   actions.  Parser organization, helper creation, comparator changes, and
   other patch-wide structural decisions may all affect these clusters.

2. Algorithmic-strategy clustering
   Uses only baseline-relative Clang and Tree-sitter features from behavioral
   functions.  ``main`` and parser/usage helpers are excluded by default so
   argument-parsing structure does not dominate the strategy result.

Traditional patch size, Lizard metrics, tests, runtime, and Levenshtein scores
are reported separately and do not determine either structural clustering.

Default output directory: ``<experiment>/analysis``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


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


ANALYZER_VERSION = "3.0.0"

PAPER_METRICS_COLUMNS = [
    "Issue",
    "Checkpoint",
    "Model",
    "Temp",
    "N Runs",
    "Successful Runs",
    "Success Rate",
    "Pass@1",
    "Pass@5",
    "Pass@10",
    "Pass@20",
    "Mean Runtime (s)",
    "Median Runtime (s)",
    "Mean LLM Total Tokens",
    "Mean Lines Edited",
    "Mean Files Edited",
    "Mean Source Tokens",
    "Mean Functions Edited",
    "Mean Functions Created",
    "Mean Functions Deleted",
    "Mean AST Edit Distance",
    "Raw Arch. Clusters",
    "Effective Arch. Clusters",
    "Dominant Arch. Cluster Share",
    "Arch. Singleton Rate",
    "Raw Strategy Clusters",
    "Effective Strategy Clusters",
    "Dominant Strategy Cluster Share",
    "Strategy Singleton Rate",
    "Dominant Cluster Share",
]

PAPER_ALL_RUN_COLUMNS = [
    "All-Run Mean Lines Edited",
    "All-Run Mean Files Edited",
    "All-Run Mean Source Tokens",
    "All-Run Mean Functions Edited",
    "All-Run Mean Functions Created",
    "All-Run Mean Functions Deleted",
    "All-Run Mean AST Edit Distance",
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
    lizard_metrics: dict[str, float] | None
    lizard_error: str | None


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
        "--output-dir",
        type=Path,
        help="Default: <experiment>/analysis",
    )
    parser.add_argument(
        "--cluster-threshold",
        type=float,
        default=0.30,
        help=(
            "Whole-patch architecture cosine-distance cut. This preserves the "
            "argument used by run_llm_experiment.sh. Default: 0.30"
        ),
    )
    parser.add_argument(
        "--strategy-threshold",
        type=float,
        default=None,
        help=(
            "Algorithmic-strategy cosine-distance cut. Defaults to the value "
            "of --cluster-threshold."
        ),
    )
    parser.add_argument(
        "--thresholds",
        default=None,
        help=(
            "Optional comma-separated thresholds for sensitivity tables in "
            "--diagnostic-output mode. When omitted, each population "
            "receives a data-derived grid."
        ),
    )
    parser.add_argument(
        "--discovery-repetitions",
        type=int,
        default=2000,
        help=(
            "Random permutations used for discovery curves in "
            "--diagnostic-output mode. Default: 2000"
        ),
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
    for name in ("passing_complete_runs", "passing_runs"):
        population = populations.get(name)
        if not isinstance(population, Mapping):
            continue
        run_count = population.get("run_count")
        if (
            isinstance(run_count, (int, float))
            and not isinstance(run_count, bool)
            and run_count > 0
        ):
            return name, population

    return "passing_runs", {}


def build_paper_metrics_row(
    experiment_metadata: Mapping[str, Any],
    summary: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    issue_label: str | None = None,
    checkpoint_label: str | None = None,
) -> dict[str, Any]:
    passing_rows = [row for row in rows if bool(row.get("overall_success"))]
    passing_complete_rows = [
        row
        for row in passing_rows
        if bool(row.get("complete_architecture_measurement"))
    ]
    patch_rows = passing_complete_rows or passing_rows

    clustering = summary.get("clustering")
    if not isinstance(clustering, Mapping):
        clustering = {}
    architecture = clustering.get("architecture")
    strategy = clustering.get("strategy")
    architecture_populations = (
        architecture.get("populations", {})
        if isinstance(architecture, Mapping)
        else {}
    )
    strategy_populations = (
        strategy.get("populations", {})
        if isinstance(strategy, Mapping)
        else {}
    )
    _, architecture_primary = select_primary_cluster_population(
        architecture_populations
        if isinstance(architecture_populations, Mapping)
        else {}
    )
    _, strategy_primary = select_primary_cluster_population(
        strategy_populations
        if isinstance(strategy_populations, Mapping)
        else {}
    )

    pass_at_k_values = summary.get("pass_at_k")
    if not isinstance(pass_at_k_values, Mapping):
        pass_at_k_values = {}
    runtime = summary.get("runtime_seconds")
    if not isinstance(runtime, Mapping):
        runtime = {}
    llm_usage = summary.get("llm_token_usage")
    if not isinstance(llm_usage, Mapping):
        llm_usage = {}

    patch_fields = {
        "Mean Lines Edited": "lines_edited",
        "Mean Files Edited": "files_edited",
        "Mean Source Tokens": "source_tree_sitter_leaf_tokens",
        "Mean Functions Edited": "functions_edited_count",
        "Mean Functions Created": "functions_created_count",
        "Mean Functions Deleted": "functions_deleted_count",
        "Mean AST Edit Distance": "gumtree_normalized_edit_distance",
    }
    all_run_names = {
        paper_name: f"All-Run {paper_name}"
        for paper_name in patch_fields
    }

    paper_row: dict[str, Any] = {
        "Issue": infer_paper_issue(experiment_metadata, issue_label),
        "Checkpoint": infer_paper_checkpoint(
            experiment_metadata,
            checkpoint_label,
        ),
        "Model": experiment_metadata.get("model", summary.get("model")),
        "Temp": experiment_metadata.get(
            "temperature",
            summary.get("temperature"),
        ),
        "N Runs": summary.get("runs_analyzed", len(rows)),
        "Successful Runs": summary.get(
            "successful_runs",
            len(passing_rows),
        ),
        "Success Rate": summary.get("success_ratio"),
        "Pass@1": pass_at_k_values.get("pass@1"),
        "Pass@5": pass_at_k_values.get("pass@5"),
        "Pass@10": pass_at_k_values.get("pass@10"),
        "Pass@20": pass_at_k_values.get("pass@20"),
        "Mean Runtime (s)": runtime.get("mean"),
        "Median Runtime (s)": runtime.get("median"),
        "Mean LLM Total Tokens": llm_usage.get("mean_total_tokens"),
    }
    for paper_name, row_name in patch_fields.items():
        paper_row[paper_name] = safe_numeric_mean(
            row.get(row_name) for row in patch_rows
        )
        paper_row[all_run_names[paper_name]] = safe_numeric_mean(
            row.get(row_name) for row in rows
        )

    architecture_fields = {
        "Raw Arch. Clusters": "raw_cluster_count",
        "Effective Arch. Clusters": "effective_cluster_count",
        "Dominant Arch. Cluster Share": "dominant_cluster_share",
        "Arch. Singleton Rate": "singleton_rate",
    }
    strategy_fields = {
        "Raw Strategy Clusters": "raw_cluster_count",
        "Effective Strategy Clusters": "effective_cluster_count",
        "Dominant Strategy Cluster Share": "dominant_cluster_share",
        "Strategy Singleton Rate": "singleton_rate",
    }
    for paper_name, summary_name in architecture_fields.items():
        paper_row[paper_name] = architecture_primary.get(summary_name)
    for paper_name, summary_name in strategy_fields.items():
        paper_row[paper_name] = strategy_primary.get(summary_name)
    paper_row["Dominant Cluster Share"] = paper_row[
        "Dominant Arch. Cluster Share"
    ]
    return paper_row


def paper_metrics_schema() -> dict[str, Any]:
    all_attempted = "all attempted runs, including failed runs"
    successful_complete = (
        "passing_complete_runs when nonempty; otherwise passing_runs"
    )
    parsed_token_runs = (
        "all attempted runs with parsed LLM total-token measurements"
    )
    columns = {
        "Issue": {
            "description": "Utility, function, or algorithm under study.",
            "direction": "not applicable (identity)",
            "population": "experiment metadata or generic source-path inference",
        },
        "Checkpoint": {
            "description": "Prompt checkpoint or issue identifier.",
            "direction": "not applicable (identity)",
            "population": "experiment metadata or prompt filename inference",
        },
        "Model": {
            "description": "Model identifier recorded for the experiment.",
            "direction": "not applicable (identity)",
            "population": "experiment metadata",
        },
        "Temp": {
            "description": "Sampling temperature recorded for the experiment.",
            "direction": "higher means higher configured sampling temperature",
            "population": "experiment metadata",
        },
        "N Runs": {
            "description": "Number of attempted runs analyzed.",
            "direction": "higher means more attempted runs",
            "population": all_attempted,
        },
        "Successful Runs": {
            "description": "Number of attempted runs that passed all stages.",
            "direction": "higher means more successful runs",
            "population": all_attempted,
        },
        "Success Rate": {
            "description": "Fraction of attempted runs that passed all stages.",
            "direction": "higher means greater correctness success",
            "population": all_attempted,
        },
        "Pass@1": {
            "description": "Unbiased probability of at least one success in 1 sample.",
            "direction": "higher means greater probability of success",
            "population": all_attempted,
        },
        "Pass@5": {
            "description": "Unbiased probability of at least one success in 5 samples.",
            "direction": "higher means greater probability of success",
            "population": all_attempted,
        },
        "Pass@10": {
            "description": "Unbiased probability of at least one success in 10 samples.",
            "direction": "higher means greater probability of success",
            "population": all_attempted,
        },
        "Pass@20": {
            "description": "Unbiased probability of at least one success in 20 samples.",
            "direction": "higher means greater probability of success",
            "population": all_attempted,
        },
        "Mean Runtime (s)": {
            "description": "Arithmetic mean total attempt runtime in seconds.",
            "direction": "higher means more runtime cost",
            "population": all_attempted,
        },
        "Median Runtime (s)": {
            "description": "Median total attempt runtime in seconds.",
            "direction": "higher means more runtime cost",
            "population": all_attempted,
        },
        "Mean LLM Total Tokens": {
            "description": "Mean parsed model total-token usage; not source tokens.",
            "direction": "higher means more model-token cost",
            "population": parsed_token_runs,
        },
    }

    patch_descriptions = {
        "Mean Lines Edited": "Mean added plus deleted lines.",
        "Mean Files Edited": "Mean number of changed tracked or untracked files.",
        "Mean Source Tokens": "Mean Tree-sitter source-code leaf-token count.",
        "Mean Functions Edited": "Mean number of existing functions edited.",
        "Mean Functions Created": "Mean number of functions created.",
        "Mean Functions Deleted": "Mean number of functions deleted.",
        "Mean AST Edit Distance": (
            "Mean normalized GumTree baseline-to-candidate edit distance over "
            "runs with a valid measurement."
        ),
    }
    for name, description in patch_descriptions.items():
        columns[name] = {
            "description": description,
            "direction": "higher means greater patch magnitude",
            "population": successful_complete,
        }
        columns[f"All-Run {name}"] = {
            "description": f"All-run version of {name}.",
            "direction": "higher means greater patch magnitude",
            "population": all_attempted,
        }

    columns.update(
        {
            "Raw Arch. Clusters": {
                "description": "Number of observed architecture clusters.",
                "direction": "higher means more observed architecture diversity",
                "population": successful_complete,
            },
            "Effective Arch. Clusters": {
                "description": "Exponentiated Shannon entropy of architecture cluster sizes.",
                "direction": "higher means more size-adjusted architecture diversity",
                "population": successful_complete,
            },
            "Dominant Arch. Cluster Share": {
                "description": "Fraction of successful patches in the largest architecture cluster.",
                "direction": "higher means more architecture concentration",
                "population": successful_complete,
            },
            "Arch. Singleton Rate": {
                "description": "Fraction of successful patches in singleton architecture clusters.",
                "direction": "higher means more one-off architecture patches",
                "population": successful_complete,
            },
            "Raw Strategy Clusters": {
                "description": "Number of observed strategy clusters.",
                "direction": "higher means more observed strategy diversity",
                "population": successful_complete,
            },
            "Effective Strategy Clusters": {
                "description": "Exponentiated Shannon entropy of strategy cluster sizes.",
                "direction": "higher means more size-adjusted strategy diversity",
                "population": successful_complete,
            },
            "Dominant Strategy Cluster Share": {
                "description": "Fraction of successful patches in the largest strategy cluster.",
                "direction": "higher means more strategy concentration",
                "population": successful_complete,
            },
            "Strategy Singleton Rate": {
                "description": "Fraction of successful patches in singleton strategy clusters.",
                "direction": "higher means more one-off strategy patches",
                "population": successful_complete,
            },
            "Dominant Cluster Share": {
                "description": "Compatibility alias of Dominant Arch. Cluster Share.",
                "direction": "higher means more architecture concentration",
                "population": successful_complete,
            },
        }
    )
    return {
        "schema_version": 1,
        "compact_csv_columns": PAPER_METRICS_COLUMNS,
        "json_only_columns": PAPER_ALL_RUN_COLUMNS,
        "columns": columns,
        "notes": {
            "effective_clusters": (
                "Effective cluster counts account for unequal cluster sizes "
                "using exp(Shannon entropy)."
            ),
            "dominant_share": (
                "Dominant share is the fraction of successful patches in the "
                "largest cluster."
            ),
            "structural_clustering_inputs": (
                "Structural clustering does not use runtime, tests, patch "
                "size, or Levenshtein ratio as clustering inputs."
            ),
            "missing_values": (
                "Unavailable measurements are null in JSON and blank in CSV; "
                "observed zero values remain zero."
            ),
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
                column in row for column in PAPER_METRICS_COLUMNS
            ):
                continue
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


def parse_llm_tokens(path: Path) -> dict[str, int | None]:
    result: dict[str, int | None] = {
        "input_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "cache_read_tokens": None,
        "total_tokens": None,
    }
    if not path.exists():
        return result

    text = path.read_text(encoding="utf-8", errors="replace")
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
# Lizard, GumTree, and Difftastic
# ---------------------------------------------------------------------------


def lizard_metrics(
    source: Path,
    output_path: Path | None,
) -> tuple[dict[str, float] | None, str | None]:
    executable = shutil.which("lizard")
    if executable is None:
        return None, "lizard not found"

    result = run_command([executable, "--csv", str(source)], timeout=180)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        return None, result.stderr.strip() or "Lizard failed"

    metrics = {
        "function_count": 0.0,
        "total_nloc": 0.0,
        "total_cyclomatic_complexity": 0.0,
        "total_token_count": 0.0,
        "max_cyclomatic_complexity": 0.0,
        "max_function_length": 0.0,
    }
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) < 8:
            continue
        try:
            nloc = float(row[0])
            complexity = float(row[1])
            token_count = float(row[2])
            function_length = float(row[4])
        except ValueError:
            continue

        metrics["function_count"] += 1
        metrics["total_nloc"] += nloc
        metrics["total_cyclomatic_complexity"] += complexity
        metrics["total_token_count"] += token_count
        metrics["max_cyclomatic_complexity"] = max(
            metrics["max_cyclomatic_complexity"], complexity
        )
        metrics["max_function_length"] = max(
            metrics["max_function_length"], function_length
        )
    return metrics, None


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


def run_difftastic(
    baseline: Path,
    candidate: Path,
    output_path: Path | None,
) -> str | None:
    executable = shutil.which("difft") or shutil.which("difftastic")
    if executable is None:
        return "difftastic not found"

    result = run_command(
        [executable, str(baseline), str(candidate)],
        timeout=180,
    )
    combined = result.stdout
    if result.stderr:
        combined += "\n--- STDERR ---\n" + result.stderr
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(combined, encoding="utf-8")

    if result.returncode not in {0, 1}:
        return (
            result.stderr.strip()
            or f"Difftastic exited with status {result.returncode}"
        )
    return None


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
    candidate_lizard, lizard_error = lizard_metrics(
        source,
        output_dir / "lizard.csv" if output_dir is not None else None,
    )
    return ParsedSource(
        clang_counts=clang_counts,
        clang_node_count=clang_nodes,
        clang_error=clang_error,
        tree_sitter_counts=tree_sitter_counts,
        tree_sitter_leaf_tokens=tree_sitter_tokens,
        tree_sitter_node_count=tree_sitter_nodes,
        tree_sitter_functions=tree_sitter_functions,
        tree_sitter_error=tree_sitter_error,
        lizard_metrics=candidate_lizard,
        lizard_error=lizard_error,
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


def lizard_delta(
    candidate: dict[str, float] | None,
    baseline: dict[str, float] | None,
) -> dict[str, float | None]:
    keys = {
        "function_count",
        "total_nloc",
        "total_cyclomatic_complexity",
        "total_token_count",
        "max_cyclomatic_complexity",
        "max_function_length",
    }
    if candidate is None or baseline is None:
        return {f"{key}_delta": None for key in sorted(keys)}
    return {
        f"{key}_delta": candidate.get(key, 0.0)
        - baseline.get(key, 0.0)
        for key in sorted(keys)
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


def strategy_motifs(
    *,
    function_metrics: Mapping[str, Any],
    baseline_functions: Mapping[str, FunctionInfo],
    candidate_functions: Mapping[str, FunctionInfo],
    created_behavior: set[str],
    edited_behavior: set[str],
    strategy_tree_delta: Mapping[str, float],
    file_tree_delta: Mapping[str, float],
) -> dict[str, int | float]:
    edited_names = set(function_metrics.get("functions_edited") or [])
    created_names = set(function_metrics.get("functions_created") or [])

    def name_matches(names: Iterable[str], expression: str) -> int:
        pattern = re.compile(expression, re.I)
        return int(any(pattern.search(name) for name in names))

    def added_suffix(*suffixes: str) -> float:
        total = 0.0
        for key, value in strategy_tree_delta.items():
            if value > 0 and any(key.endswith(suffix) for suffix in suffixes):
                total += float(value)
        return total

    call_names: set[str] = set()
    for name in set(edited_behavior) | set(created_behavior):
        info = candidate_functions.get(name)
        if info:
            call_names.update(info.calls)

    global_declaration_delta = sum(
        value
        for key, value in file_tree_delta.items()
        if value > 0 and key.endswith(".kind.declaration")
    )

    return {
        "created_behavior_helpers": len(created_behavior),
        "edited_behavior_functions": len(edited_behavior),
        "edited_comparator_named_function": name_matches(
            edited_names, r"(?:compare|comparator|cmp)"
        ),
        "created_comparator_named_helper": name_matches(
            created_names, r"(?:compare|comparator|cmp)"
        ),
        "edited_sort_named_function": name_matches(edited_names, r"sort"),
        "created_sort_named_helper": name_matches(created_names, r"sort"),
        "edited_output_named_function": name_matches(
            edited_names, r"(?:write|output|print|emit)"
        ),
        "created_output_named_helper": name_matches(
            created_names, r"(?:write|output|print|emit)"
        ),
        "added_conditional_expressions": added_suffix(
            ".kind.conditional_expression"
        ),
        "added_if_statements": added_suffix(".kind.if_statement"),
        "added_loops": added_suffix(
            ".kind.for_statement",
            ".kind.while_statement",
            ".kind.do_statement",
        ),
        "added_unary_expressions": added_suffix(
            ".kind.unary_expression"
        ),
        "added_return_statements": added_suffix(
            ".kind.return_statement"
        ),
        "added_assignments": added_suffix(
            ".kind.assignment_expression"
        ),
        "added_global_declarations": global_declaration_delta,
        "calls_qsort": int("qsort" in call_names),
        "calls_memcmp": int("memcmp" in call_names),
        "calls_strcmp": int("strcmp" in call_names),
        "calls_rand": int("rand" in call_names),
        "calls_srand": int("srand" in call_names),
    }


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
    if not labels:
        return {
            "raw_cluster_count": 0,
            "cluster_sizes": {},
            "entropy_nats": None,
            "entropy_bits": None,
            "effective_cluster_count": None,
            "dominant_cluster_share": None,
            "singleton_rate": None,
        }

    sizes = Counter(int(label) for label in labels)
    total = len(labels)
    proportions = [size / total for size in sizes.values()]
    entropy_nats = -sum(p * math.log(p) for p in proportions)
    entropy_bits = -sum(p * math.log2(p) for p in proportions)
    return {
        "raw_cluster_count": len(sizes),
        "cluster_sizes": dict(sorted(sizes.items())),
        "entropy_nats": entropy_nats,
        "entropy_bits": entropy_bits,
        "effective_cluster_count": math.exp(entropy_nats),
        "dominant_cluster_share": max(proportions),
        "singleton_rate": sum(size == 1 for size in sizes.values()) / total,
    }


def parse_threshold_grid(
    supplied: str | None,
    distance: Any,
) -> list[float]:
    if supplied:
        values = sorted(
            {
                float(item.strip())
                for item in supplied.split(",")
                if item.strip()
            }
        )
        if any(value <= 0 for value in values):
            raise ValueError("Thresholds must be positive.")
        return values

    if len(distance) < 2:
        return [0.30]

    condensed = distance[np.triu_indices(len(distance), k=1)]
    positive = condensed[condensed > 1e-12]
    if len(positive) == 0:
        return [0.001]

    quantiles = np.quantile(
        positive,
        [
            0.01,
            0.025,
            0.05,
            0.075,
            0.10,
            0.15,
            0.20,
            0.25,
            0.35,
            0.50,
            0.65,
            0.75,
            0.85,
            0.90,
            0.95,
        ],
    )
    regular = np.linspace(
        max(float(positive.min()), 1e-6),
        float(positive.max()),
        20,
    )
    return sorted(
        {
            round(float(value), 8)
            for value in np.concatenate([quantiles, regular])
            if value > 0
        }
    )


def threshold_sensitivity(
    distance: Any,
    thresholds: Sequence[float],
) -> tuple[list[dict[str, Any]], float | None]:
    rows: list[dict[str, Any]] = []
    n = len(distance)

    for threshold in thresholds:
        labels = stabilize_labels(
            agglomerative_labels(distance, threshold),
            [str(index) for index in range(n)],
        )
        stats = cluster_statistics([int(value) for value in labels])
        cluster_count = stats["raw_cluster_count"]

        silhouette: float | None = None
        if 2 <= cluster_count < n:
            try:
                silhouette = float(
                    silhouette_score(
                        distance,
                        labels,
                        metric="precomputed",
                    )
                )
            except ValueError:
                silhouette = None

        rows.append(
            {
                "threshold": float(threshold),
                "cluster_count": cluster_count,
                "effective_cluster_count": stats[
                    "effective_cluster_count"
                ],
                "dominant_cluster_share": stats[
                    "dominant_cluster_share"
                ],
                "singleton_rate": stats["singleton_rate"],
                "silhouette": silhouette,
            }
        )

    eligible = [
        row
        for row in rows
        if row["silhouette"] is not None
        and 2 <= int(row["cluster_count"]) <= max(2, min(20, n - 1))
    ]
    if not eligible:
        return rows, None

    selected = max(
        eligible,
        key=lambda row: (
            float(row["silhouette"]),
            -float(row["singleton_rate"]),
            -float(row["threshold"]),
        ),
    )
    return rows, float(selected["threshold"])


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


def discovery_curve(
    labels: Sequence[int],
    repetitions: int,
    seed: int = 20260717,
) -> list[dict[str, Any]]:
    if not labels:
        return []

    observed: list[int] = []
    seen: set[int] = set()
    for label in labels:
        seen.add(int(label))
        observed.append(len(seen))

    rng = random.Random(seed)
    original = [int(label) for label in labels]
    curves: list[list[int]] = []
    for _ in range(repetitions):
        shuffled = original[:]
        rng.shuffle(shuffled)
        current_seen: set[int] = set()
        curve: list[int] = []
        for label in shuffled:
            current_seen.add(label)
            curve.append(len(current_seen))
        curves.append(curve)

    rows: list[dict[str, Any]] = []
    for index in range(len(original)):
        values = [curve[index] for curve in curves]
        rows.append(
            {
                "runs_sampled": index + 1,
                "observed_clusters": observed[index],
                "randomized_mean_clusters": statistics.fmean(values),
                "randomized_2_5_percentile": float(
                    np.percentile(values, 2.5)
                ),
                "randomized_97_5_percentile": float(
                    np.percentile(values, 97.5)
                ),
            }
        )
    return rows


def plot_discovery_curve(
    rows: Sequence[Mapping[str, Any]],
    output_path: Path,
    title: str,
    plt: Any,
) -> None:
    if not rows:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    x = [int(row["runs_sampled"]) for row in rows]
    observed = [float(row["observed_clusters"]) for row in rows]
    randomized_mean = [
        float(row["randomized_mean_clusters"]) for row in rows
    ]
    lower = [
        float(row["randomized_2_5_percentile"]) for row in rows
    ]
    upper = [
        float(row["randomized_97_5_percentile"]) for row in rows
    ]

    plt.figure(figsize=(8, 5))
    plt.plot(x, observed, label="Observed run order")
    plt.plot(x, randomized_mean, linestyle="--", label="Randomized mean")
    plt.fill_between(x, lower, upper, alpha=0.2, label="95% interval")
    plt.xlabel("Runs sampled")
    plt.ylabel("Clusters discovered")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


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
    threshold: float,
    supplied_thresholds: str | None,
    diagnostic_data_dir: Path | None,
    diagnostic_plot_dir: Path | None,
    plotting_helpers: tuple[Any, Any, Any, Any] | None,
    discovery_repetitions: int,
) -> tuple[dict[str, Any], Any]:
    indices = [all_run_ids.index(run_id) for run_id in run_ids]
    distance = full_distance[np.ix_(indices, indices)]

    labels = stabilize_labels(
        agglomerative_labels(distance, threshold),
        run_ids,
    )
    stats = cluster_statistics([int(value) for value in labels])

    prefix = f"{space_name}_{population_name}"
    representative_rows = cluster_representatives(
        labels,
        distance,
        run_ids,
    )
    diagnostic_recommendation = None
    if diagnostic_data_dir is not None:
        threshold_grid = parse_threshold_grid(supplied_thresholds, distance)
        sensitivity_rows, diagnostic_recommendation = threshold_sensitivity(
            distance,
            threshold_grid,
        )
        write_csv(
            diagnostic_data_dir / f"threshold_sensitivity_{prefix}.csv",
            sensitivity_rows,
            [
                "threshold",
                "cluster_count",
                "effective_cluster_count",
                "dominant_cluster_share",
                "singleton_rate",
                "silhouette",
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
        discovery_rows = discovery_curve(
            [int(value) for value in labels],
            repetitions=discovery_repetitions,
        )
        write_csv(
            diagnostic_data_dir / f"cluster_discovery_{prefix}.csv",
            discovery_rows,
            [
                "runs_sampled",
                "observed_clusters",
                "randomized_mean_clusters",
                "randomized_2_5_percentile",
                "randomized_97_5_percentile",
            ],
        )
        if diagnostic_plot_dir is None or plotting_helpers is None:
            raise RuntimeError("Diagnostic plotting was not initialized.")
        plt, scipy_linkage, scipy_dendrogram, squareform = plotting_helpers
        plot_discovery_curve(
            discovery_rows,
            diagnostic_plot_dir / f"cluster_discovery_{prefix}.png",
            f"{space_name.title()} cluster discovery - "
            f"{population_name.replace('_', ' ')}",
            plt,
        )
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
            "diagnostic_silhouette_recommendation": (
                diagnostic_recommendation
            ),
            "mean_pairwise_distance": mean_pairwise_distance(distance),
            "representatives": representative_rows,
        },
        labels,
    )


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    global np, AgglomerativeClustering, silhouette_score
    np, AgglomerativeClustering, silhouette_score = require_python_packages()
    experiment = args.experiment.resolve()
    if not experiment.exists():
        raise SystemExit(f"Experiment directory not found: {experiment}")

    experiment_metadata_path = experiment / "experiment.json"
    if not experiment_metadata_path.exists():
        raise SystemExit(f"Missing experiment.json: {experiment_metadata_path}")

    experiment_metadata = read_json(experiment_metadata_path)
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

    source_path = Path(experiment_metadata["source_path"])
    baseline_source = experiment / "baseline" / source_path
    if not baseline_source.exists():
        raise SystemExit(f"Baseline source not found: {baseline_source}")

    attempts = sorted(
        path
        for path in experiment.glob("attempt-*")
        if path.is_dir() and (path / "metadata.json").exists()
    )
    if not attempts:
        raise SystemExit("No attempt-* directories with metadata.json found.")

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
        "difftastic": shutil.which("difft")
        or shutil.which("difftastic"),
        "lizard": shutil.which("lizard"),
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
                "lizard_metrics": baseline.lizard_metrics,
                "lizard_error": baseline.lizard_error,
            },
        )

    rows: list[dict[str, Any]] = []
    architecture_blocks: dict[str, dict[str, dict[str, float]]] = {}
    strategy_blocks: dict[str, dict[str, dict[str, float]]] = {}
    source_texts: dict[str, str] = {}
    strategy_motif_rows: list[dict[str, Any]] = []

    print("\nAnalyzing candidates...")
    for index, attempt in enumerate(attempts, start=1):
        metadata = read_json(attempt / "metadata.json")
        run_id = str(metadata.get("run_id", attempt.name))
        run_output = (
            diagnostic_root / "runs" / attempt.name
            if diagnostic_root
            else None
        )

        candidate_source = attempt / "candidate" / source_path
        candidate_missing = not candidate_source.exists()
        if candidate_missing:
            candidate_source = baseline_source

        candidate = analyze_source(
            candidate_source,
            run_output,
            args.clang_extra_arg,
        )
        candidate_functions = candidate.tree_sitter_functions or {}

        gumtree_actions, gumtree_distance, gumtree_error = run_gumtree(
            baseline_source,
            candidate_source,
            run_output / "gumtree.txt" if run_output is not None else None,
            baseline.tree_sitter_node_count,
            candidate.tree_sitter_node_count,
        )
        # Difftastic is diagnostic-only; GumTree supplies structural metrics.
        if args.diagnostic_output:
            difftastic_error = run_difftastic(
                baseline_source,
                candidate_source,
                (
                    run_output / "difftastic.txt"
                    if run_output is not None
                    else None
                ),
            )
            difftastic_available: bool | None = difftastic_error is None
        else:
            difftastic_error = None
            difftastic_available = None

        function_metrics = function_change_metrics(
            baseline.tree_sitter_functions,
            candidate.tree_sitter_functions,
        )
        patch_metrics = parse_change_metrics(attempt)

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

        file_tree_delta = {
            key: value
            for key, value in architecture_tree_delta.items()
            if key.startswith("file.")
        }
        motifs = strategy_motifs(
            function_metrics=function_metrics,
            baseline_functions=baseline_functions,
            candidate_functions=candidate_functions,
            created_behavior=created_behavior,
            edited_behavior=edited_behavior,
            strategy_tree_delta=strategy_tree_delta,
            file_tree_delta=file_tree_delta,
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

        base_test = parse_test_log(attempt / "base-tests.log")
        feature_test = parse_test_log(attempt / "feature-tests.log")
        extra_test = parse_test_log(attempt / "extra-tests.log")
        llm_tokens = parse_llm_tokens(attempt / "opencode.log")

        candidate_lizard = candidate.lizard_metrics
        candidate_lizard_fields = {
            f"lizard_{key}": value
            for key, value in (candidate_lizard or {}).items()
        }
        if candidate_lizard is None:
            for key in (
                "function_count",
                "total_nloc",
                "total_cyclomatic_complexity",
                "total_token_count",
                "max_cyclomatic_complexity",
                "max_function_length",
            ):
                candidate_lizard_fields[f"lizard_{key}"] = None

        complete_architecture_measurement = all(
            [
                candidate.clang_error is None,
                candidate.tree_sitter_error is None,
                gumtree_error is None,
            ]
        )
        complete_strategy_measurement = all(
            [
                candidate.clang_error is None,
                candidate.tree_sitter_error is None,
            ]
        )

        row: dict[str, Any] = {
            **metadata,
            **patch_metrics,
            **function_metrics,
            "candidate_missing": candidate_missing,
            "candidate_sha256": file_sha256(candidate_source),
            "source_bytes": candidate_source.stat().st_size,
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
            "difftastic_requested": args.diagnostic_output,
            "difftastic_available": difftastic_available,
            "lizard_available": candidate.lizard_error is None,
            "complete_architecture_measurement": (
                complete_architecture_measurement
            ),
            "complete_strategy_measurement": complete_strategy_measurement,
            "clang_error": candidate.clang_error,
            "tree_sitter_error": candidate.tree_sitter_error,
            "gumtree_error": gumtree_error,
            "difftastic_error": difftastic_error,
            "lizard_error": candidate.lizard_error,
            **candidate_lizard_fields,
            **lizard_delta(
                candidate.lizard_metrics,
                baseline.lizard_metrics,
            ),
            **motifs,
        }
        rows.append(row)
        if args.diagnostic_output:
            source_texts[run_id] = candidate_source.read_text(
                encoding="utf-8", errors="replace"
            )
        strategy_motif_rows.append({"run_id": run_id, **motifs})

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
                    "strategy_motifs": motifs,
                    "candidate_functions": {
                        name: asdict(info)
                        for name, info in candidate_functions.items()
                    },
                    "tool_errors": {
                        "clang": candidate.clang_error,
                        "tree_sitter": candidate.tree_sitter_error,
                        "gumtree": gumtree_error,
                        "difftastic": difftastic_error,
                        "lizard": candidate.lizard_error,
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
            threshold=args.cluster_threshold,
            supplied_thresholds=args.thresholds,
            diagnostic_data_dir=diagnostic_clustering_dir,
            diagnostic_plot_dir=diagnostic_plot_dir,
            plotting_helpers=plotting_helpers,
            discovery_repetitions=args.discovery_repetitions,
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
            threshold=strategy_threshold,
            supplied_thresholds=args.thresholds,
            diagnostic_data_dir=diagnostic_clustering_dir,
            diagnostic_plot_dir=diagnostic_plot_dir,
            plotting_helpers=plotting_helpers,
            discovery_repetitions=args.discovery_repetitions,
        )
        strategy_summaries[population_name] = summary
        strategy_labels[population_name] = labels

    if diagnostic_clustering_dir is not None and diagnostic_plot_dir is not None:
        compatibility_files = [
            (
                diagnostic_clustering_dir,
                "threshold_sensitivity_architecture_all_runs.csv",
                "threshold_sensitivity_all_runs.csv",
            ),
            (
                diagnostic_clustering_dir,
                "threshold_sensitivity_architecture_passing_runs.csv",
                "threshold_sensitivity_passing_runs.csv",
            ),
            (
                diagnostic_clustering_dir,
                "cluster_assignments_architecture_all_runs.csv",
                "cluster_assignments_all_runs.csv",
            ),
            (
                diagnostic_clustering_dir,
                "cluster_assignments_architecture_passing_runs.csv",
                "cluster_assignments_passing_runs.csv",
            ),
            (
                diagnostic_clustering_dir,
                "cluster_discovery_architecture_all_runs.csv",
                "cluster_discovery_curve.csv",
            ),
            (
                diagnostic_plot_dir,
                "cluster_discovery_architecture_all_runs.png",
                "cluster_discovery_curve.png",
            ),
            (
                diagnostic_plot_dir,
                "cluster_dendrogram_architecture_all_runs.png",
                "cluster_dendrogram.png",
            ),
        ]
        for directory, source_name, destination_name in compatibility_files:
            source_file = directory / source_name
            if source_file.exists():
                shutil.copyfile(source_file, directory / destination_name)

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

    architecture_primary_name = (
        "passing_complete_runs"
        if passing_architecture_ids
        else "passing_runs"
    )
    strategy_primary_name = (
        "passing_complete_runs" if passing_strategy_ids else "passing_runs"
    )
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

        motif_fields = sorted(
            {key for row in strategy_motif_rows for key in row}
        )
        write_csv(
            diagnostic_clustering_dir / "strategy_motifs.csv",
            strategy_motif_rows,
            motif_fields,
        )

        write_json(
            diagnostic_clustering_dir / "feature_schema.json",
            {
                "architecture": {
                    "blocks": architecture_schema,
                    "description": (
                        "Whole-patch architecture: non-duplicated Clang AST "
                        "deltas, Tree-sitter C deltas, and GumTree actions."
                    ),
                },
                "strategy": {
                    "blocks": strategy_schema,
                    "description": (
                        "Algorithmic strategy: Clang and Tree-sitter deltas "
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
                    "Lizard metrics",
                    "runtime",
                    "test outcomes",
                    "Levenshtein ratio",
                    "LLM token usage",
                ],
            },
        )

        if diagnostic_packages is None:
            raise RuntimeError("Diagnostic packages were not initialized.")
        levenshtein_ratio = diagnostic_packages[1]
        pairwise_rows: list[dict[str, Any]] = []
        for left_index, right_index in itertools.combinations(
            range(len(run_ids)), 2
        ):
            left = run_ids[left_index]
            right = run_ids[right_index]
            pairwise_rows.append(
                {
                    "run_a": left,
                    "run_b": right,
                    "architecture_cosine_similarity": (
                        1.0
                        - float(
                            architecture_distance[left_index, right_index]
                        )
                    ),
                    "architecture_cosine_distance": float(
                        architecture_distance[left_index, right_index]
                    ),
                    "strategy_cosine_similarity": (
                        1.0 - float(strategy_distance[left_index, right_index])
                    ),
                    "strategy_cosine_distance": float(
                        strategy_distance[left_index, right_index]
                    ),
                    "levenshtein_ratio": (
                        levenshtein_ratio(
                            source_texts[left], source_texts[right]
                        )
                        / 100.0
                    ),
                    "same_architecture_all_cluster": int(
                        architecture_all_map[left]
                        == architecture_all_map[right]
                    ),
                    "same_strategy_all_cluster": int(
                        strategy_all_map[left] == strategy_all_map[right]
                    ),
                    "both_successful": int(
                        left in passing_ids and right in passing_ids
                    ),
                    "same_architecture_passing_cluster": (
                        int(
                            architecture_passing_map[left]
                            == architecture_passing_map[right]
                        )
                        if left in architecture_passing_map
                        and right in architecture_passing_map
                        else None
                    ),
                    "same_strategy_passing_cluster": (
                        int(
                            strategy_passing_map[left]
                            == strategy_passing_map[right]
                        )
                        if left in strategy_passing_map
                        and right in strategy_passing_map
                        else None
                    ),
                }
            )
        write_csv(
            diagnostic_clustering_dir / "pairwise_similarity.csv",
            pairwise_rows,
            [
                "run_a",
                "run_b",
                "architecture_cosine_similarity",
                "architecture_cosine_distance",
                "strategy_cosine_similarity",
                "strategy_cosine_distance",
                "levenshtein_ratio",
                "same_architecture_all_cluster",
                "same_strategy_all_cluster",
                "both_successful",
                "same_architecture_passing_cluster",
                "same_strategy_passing_cluster",
            ],
        )

    n = len(rows)
    successful = sum(bool(row.get("overall_success")) for row in rows)
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
    llm_total_tokens = [
        int(row["llm_total_tokens"])
        for row in rows
        if isinstance(row.get("llm_total_tokens"), int)
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
        "schema_version": 3,
        "analyzer_version": ANALYZER_VERSION,
        "experiment": str(experiment),
        "output_directory": str(output_dir),
        "model": experiment_metadata.get("model"),
        "temperature": experiment_metadata.get("temperature"),
        "runs_analyzed": n,
        "successful_runs": successful,
        "success_ratio": successful / n if n else None,
        "stage_success_ratios": stage_success_ratios,
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
        "llm_token_usage": {
            "runs_with_measurement": len(llm_total_tokens),
            "mean_total_tokens": (
                statistics.fmean(llm_total_tokens)
                if llm_total_tokens
                else None
            ),
            "note": (
                "Best-effort extraction from OpenCode logs. Source-code "
                "tokens are reported separately."
            ),
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
                "architecture": (
                    "passing_complete_runs"
                    if passing_architecture_ids
                    else "passing_runs"
                ),
                "strategy": (
                    "passing_complete_runs"
                    if passing_strategy_ids
                    else "passing_runs"
                ),
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
                "Threshold-sensitivity tables are diagnostic. Freeze both "
                "thresholds on a calibration set before final cross-model or "
                "cross-temperature comparisons."
            ),
        },
        "measurement_counts": {
            "clang": sum(bool(row["clang_available"]) for row in rows),
            "tree_sitter": sum(
                bool(row["tree_sitter_available"]) for row in rows
            ),
            "gumtree": sum(bool(row["gumtree_available"]) for row in rows),
            "difftastic": sum(
                bool(row["difftastic_available"]) for row in rows
            ),
            "lizard": sum(bool(row["lizard_available"]) for row in rows),
            "complete_architecture": len(complete_architecture_ids),
            "complete_strategy": len(complete_strategy_ids),
            "llm_token_usage": len(llm_total_tokens),
        },
        "baseline_errors": {
            "clang": baseline.clang_error,
            "tree_sitter": baseline.tree_sitter_error,
            "lizard": baseline.lizard_error,
        },
        "tool_paths": tool_paths,
    }
    write_json(output_dir / "summary.json", summary)

    paper_row = build_paper_metrics_row(
        experiment_metadata,
        summary,
        rows,
        issue_label=args.paper_issue_label,
        checkpoint_label=args.paper_checkpoint_label,
    )
    paper_output_dir = experiment / "analysis"
    write_json(paper_output_dir / "paper_metrics_row.json", paper_row)
    write_csv(
        paper_output_dir / "paper_metrics_row.csv",
        [paper_row],
        PAPER_METRICS_COLUMNS,
    )
    write_json(
        paper_output_dir / "paper_metrics_schema.json",
        paper_metrics_schema(),
    )
    rebuild_paper_metrics_aggregate(
        infer_repository_root(experiment, experiment_metadata)
    )

    print("\nAnalysis complete")
    print(f"Success: {successful}/{n} ({successful / n:.1%})")
    architecture_primary_name = (
        "passing_complete_runs"
        if passing_architecture_ids
        else "passing_runs"
    )
    strategy_primary_name = (
        "passing_complete_runs"
        if passing_strategy_ids
        else "passing_runs"
    )
    architecture_primary = architecture_summaries[architecture_primary_name]
    strategy_primary = strategy_summaries[strategy_primary_name]
    print(
        "Passing architecture: "
        f"{architecture_primary['raw_cluster_count']} raw, "
        f"{architecture_primary['effective_cluster_count']} effective, "
        f"dominant {architecture_primary['dominant_cluster_share']}"
    )
    print(
        "Passing strategy:     "
        f"{strategy_primary['raw_cluster_count']} raw, "
        f"{strategy_primary['effective_cluster_count']} effective, "
        f"dominant {strategy_primary['dominant_cluster_share']}"
    )
    print(f"Results: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
