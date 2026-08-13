#!/usr/bin/env python3
"""Aggregate a lineage run produced by scripts/run_lineage_experiment.sh.

The experimental unit is a LINEAGE: one independent walk through every
checkpoint of a utility, where each stage inherits only the source the previous
stage of that same lineage produced.

Four questions are reported separately, because they need different populations
and different baselines and must not be blended:

  A. END-TO-END RELIABILITY, over every lineage STARTED. Completion rate,
     stopping checkpoint, infrastructure attrition, repair usage per checkpoint.

  B. FINAL-POPULATION DIVERSITY, over the successful completed finals only.
     Delegated wholesale to `scripts/analyze_experiment.py` by materializing the
     population as a view it already knows how to read.

  C. PER-STAGE MAINTENANCE CHANGE, for each successful transition inside a
     lineage: checkpoint N's candidate against checkpoint N-1's source. This is
     the only correct baseline for "how much did this maintenance task change",
     and it is computed here because the pairing is per attempt.

  D. TOTAL LINEAGE CHANGE, the final source against that same lineage's own
     checkpoint 000 source. Labelled as total change across the trajectory, not
     as a single maintenance step.

There is no natural shared source baseline for a final population: each lineage
generated its own checkpoint 000 independently, so no lineage's source is a
meaningful predecessor of another's final. The view therefore uses the empty
translation unit -- the same baseline a `--source-mode new` experiment already
uses -- which is correct for the structural and clustering metrics (every member
shares one constant baseline, and the comparisons among finals are pairwise) and
meaningless for the churn metrics (difference from nothing is program size, not
maintenance effort). Those churn metrics are therefore reported as UNSUPPORTED
in the final view, by name, and are answered properly by C and D instead. See
`BASELINE_DEPENDENT_METRICS`.

Reliability and diversity deliberately use different denominators, and both are
always reported:

    lineages started                 = every lineage the run attempted
    successful final implementations = those that passed every checkpoint

A lineage that stopped is retained and counted. It is never replaced with
another attempt to keep the number of finals round, and the completion rate is
never computed over the survivors.

Usage:
  python3 scripts/analyze_lineages.py --lineage-root runs/lineages/sort/MODEL/temp-0
  python3 scripts/analyze_lineages.py --lineage-root DIR --checkpoint-diversity
  python3 scripts/analyze_lineages.py --lineage-root DIR --skip-diversity
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Reused, never reimplemented: the interval formula lives with the other
# diversity statistics. It is imported on first use rather than at module
# import, because scripts/analysis/diversity_metrics.py pulls in NumPy and
# scikit-learn -- a machine that can still aggregate lineage outcomes without
# the clustering stack should get its counts and an explicit note, not an
# ImportError.
_WILSON: dict[str, Any] = {"function": None, "unavailable_reason": None}


def wilson(successes: int, total: int) -> dict[str, Any] | None:
    if _WILSON["function"] is None and _WILSON["unavailable_reason"] is None:
        try:
            from analysis.diversity_metrics import wilson_interval
        except ImportError as error:
            _WILSON["unavailable_reason"] = (
                f"scripts/analysis/diversity_metrics.py is unimportable "
                f"({error}); install scripts/analysis-requirements.txt for "
                "confidence intervals"
            )
        else:
            _WILSON["function"] = wilson_interval
    function = _WILSON["function"]
    return function(successes, total) if function else None


# Copied into a population view alongside metadata.json and candidate/. These
# are the small per-attempt artifacts analyze_experiment.py knows how to read;
# opencode.log is deliberately not copied, because a view exists to compare
# sources and the session transcript stays with the stage run that produced it.
#
# diff-numstat / untracked-files / changed-files are deliberately NOT copied:
# they record the stage's churn against its own seed, and dropping them into a
# view whose baseline is the empty translation unit would let a baseline-
# dependent number look consistent when it is not. Per-stage churn is reported
# by this script instead, against the right baseline. See
# BASELINE_DEPENDENT_METRICS.
VIEW_ATTEMPT_FILES = (
    "build.log",
    "base-tests.log",
    "feature-tests.log",
    "extra-tests.log",
)

# Metrics in a population view's report that are computed against the view's
# baseline. For a final population that baseline is the empty translation unit,
# so each of these measures the whole program rather than a maintenance step and
# must not be read as change. They are named here, echoed into the report, and
# answered properly by the per-stage (C) and total-lineage (D) sections.
#
# NOT listed, because they remain valid: the architecture and strategy
# clustering, the family/Vendi/discovery/repetition summaries, and the pairwise
# distances. Those compare members with each other; every member shares the one
# constant baseline, so it cancels.
BASELINE_DEPENDENT_METRICS = (
    "lines_added",
    "lines_deleted",
    "lines_edited",
    "files_edited",
    "tracked_files_edited",
    "untracked_files_created",
    "functions_edited_count",
    "functions_created_count",
    "functions_deleted_count",
    "gumtree_edit_actions",
    "gumtree_normalized_edit_distance",
)

# Reused, never reimplemented: the churn and function-change formulas live in
# the canonical analyzer. Imported on first use because that module pulls in
# NumPy and scikit-learn at import time.
_ANALYZER: dict[str, Any] = {"module": None, "unavailable_reason": None}


def experiment_analyzer():
    """`scripts.analyze_experiment`, or None with a recorded reason."""
    if _ANALYZER["module"] is None and _ANALYZER["unavailable_reason"] is None:
        try:
            import analyze_experiment
        except ImportError as error:
            _ANALYZER["unavailable_reason"] = (
                f"scripts/analyze_experiment.py is unimportable ({error}); "
                "install scripts/analysis-requirements.txt for change metrics"
            )
        else:
            _ANALYZER["module"] = analyze_experiment
    return _ANALYZER["module"]


class LineageError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"analyze_lineages: {message}")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LineageError(f"cannot read {path}: {error}") from error


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})


# ---------------------------------------------------------------------------
# Locating a stage's files
# ---------------------------------------------------------------------------


def lineage_directory(record: Mapping[str, Any]) -> Path:
    """Where this lineage actually lives, as `load_run` resolved it.

    `load_run` is the only thing that knows the root the caller asked for, so a
    record that did not come through it cannot be located on disk and must say
    so rather than fall back to a recorded string.
    """
    directory = record.get("_dir")
    if not isinstance(directory, Path):
        raise LineageError(
            f"lineage {record.get('lineage_id')!r} was not loaded through "
            "load_run(), so its location under --lineage-root is unknown"
        )
    return directory


def resolve_stage_paths(
    lineage_dir: Path, stage: Mapping[str, Any]
) -> dict[str, Path]:
    """Where one stage's files are NOW, derived from the root being analyzed.

    A stage record stores `stage_dir`, `attempt_dir`, `candidate` and
    `test_bundle_dir` as absolute paths baked in when the run was generated.
    Those are provenance -- what happened, on the machine it happened on -- and
    they are wrong as filesystem locations the moment the run is copied to
    another host or the run directory is renamed, both of which have already
    happened to runs in this repository. Opening them directly made an analysis
    fail on a run whose files were all present and intact.

    So every location is rebuilt here from `--lineage-root` (which `load_run`
    resolved into `_dir`), the stage's own `checkpoint_id`, and the layout
    `run_lineage_experiment.sh` writes:

        <lineage_dir>/<checkpoint_id>/temp-<slug>/attempt-NNN/candidate/<basename>
        <lineage_dir>/<checkpoint_id>/test-bundle

    The temperature slug and attempt number are found by globbing rather than by
    editing the recorded string, because the recorded string is exactly what
    cannot be trusted. A stage that does not resolve to exactly one attempt
    directory is an error: picking one of several would silently attribute a
    measurement to whichever the filesystem happened to list first.
    """
    checkpoint_id = stage.get("checkpoint_id")
    if checkpoint_id is None:
        raise LineageError(
            f"a stage of {lineage_dir.name} has no checkpoint_id, so its files "
            "cannot be located under the lineage root"
        )
    stage_dir = lineage_dir / str(checkpoint_id)
    attempts = sorted(
        path for path in stage_dir.glob("temp-*/attempt-*") if path.is_dir()
    )
    if not attempts:
        raise LineageError(
            f"no temp-*/attempt-* directory under {stage_dir}; the stage's "
            "files are not present under --lineage-root"
        )
    if len(attempts) > 1:
        raise LineageError(
            f"{len(attempts)} temp-*/attempt-* directories under {stage_dir} "
            f"({', '.join(path.name for path in attempts)}); a stage must have "
            "exactly one, and guessing which one produced the recorded "
            "candidate would be a fabricated measurement"
        )
    attempt_dir = attempts[0]

    basename = stage.get("candidate_source_basename")
    if not basename:
        raise LineageError(
            f"stage {checkpoint_id} of {lineage_dir.name} records no "
            "candidate_source_basename, so its candidate cannot be named"
        )
    return {
        "stage_dir": stage_dir,
        "attempt_dir": attempt_dir,
        "test_bundle_dir": stage_dir / "test-bundle",
        "candidate": attempt_dir / "candidate" / str(basename),
    }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


# A lineage that started but whose record never reached a terminal state. The
# controller marks a record `completed` or `stopped`; anything else at analysis
# time means the controller itself died, so the lineage is counted as started
# and reported under its own reason rather than as an implementation failure.
INTERRUPTED_STATE = "controller_interrupted"


def incomplete_record(directory: Path, reason: str) -> dict[str, Any]:
    """A minimal record for a lineage whose own record is absent or unusable."""
    return {
        "lineage_id": directory.name,
        "state": INTERRUPTED_STATE,
        "incomplete_reason": reason,
        "end_to_end_success": False,
        "failure_stage": None,
        "failure_reason": reason,
        "stages": [],
        "_dir": directory,
    }


def classify(record: Mapping[str, Any]) -> str:
    """completed | stopped | controller_interrupted, from the record's state.

    Older records predate the `state` field; for those the terminal flags still
    decide, so a finished run analyzed with a newer analyzer is unaffected.
    """
    state = record.get("state")
    if state in {"completed", "stopped", INTERRUPTED_STATE}:
        return INTERRUPTED_STATE if state == INTERRUPTED_STATE else state
    if state == "running":
        return INTERRUPTED_STATE
    if record.get("end_to_end_success"):
        return "completed"
    if record.get("finished_at") or record.get("failure_stage"):
        return "stopped"
    return INTERRUPTED_STATE


def is_successful(record: Mapping[str, Any]) -> bool:
    """A final implementation must come from a lineage that actually completed.

    Both conditions are required: an interrupted record must never contribute a
    final, even if a stale `end_to_end_success` said otherwise.
    """
    return bool(record.get("end_to_end_success")) and classify(record) == "completed"


def load_run(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    if not root.is_dir():
        raise LineageError(f"lineage root not found: {root}")

    run_metadata_path = root / "lineages.json"
    run_metadata = read_json(run_metadata_path) if run_metadata_path.is_file() else {}

    lineages = []
    for directory in sorted(root.glob("lineage-*")):
        record_path = directory / "lineage.json"
        if not record_path.is_file():
            # The controller writes this record before checkpoint 000 begins, so
            # its absence means the lineage died before the first transition --
            # or predates that guarantee. Either way the lineage was STARTED,
            # and dropping it here would shrink the reliability denominator in
            # the one direction that flatters the result.
            lineages.append(incomplete_record(directory, "missing_record"))
            continue
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            # Reported, never silently excluded: a record we cannot parse is a
            # lineage whose outcome is unknown, not a lineage that did not run.
            record = incomplete_record(directory, "malformed_record")
            record["record_error"] = str(error)
        else:
            if not isinstance(record, dict):
                record = incomplete_record(directory, "malformed_record")
                record["record_error"] = "lineage.json is not a JSON object"
        record["_dir"] = directory
        record.setdefault("lineage_id", directory.name)
        lineages.append(record)

    # Planned is not started. lineages.json is written ONCE, before any lineage
    # begins, and lists every id the invocation intends to run -- so treating it
    # as evidence of a start would report ten lineages for a run interrupted
    # after three. A lineage counts as started only when the controller left
    # durable proof: the directory and lineage.json that lineage_state.py init
    # creates immediately before checkpoint 000.
    #
    # Planned-but-never-started ids are reported separately and stay out of the
    # reliability denominator entirely.
    planned = run_metadata.get("planned_lineage_ids")
    if not isinstance(planned, list):
        planned = run_metadata.get("lineage_ids")   # pre-rename runs
    started_ids = {record.get("lineage_id") for record in lineages}
    never_started = (
        sorted(set(planned) - started_ids) if isinstance(planned, list) else []
    )

    if not lineages:
        # A run the controller refused on environment grounds legitimately has
        # no lineages: the platform preflight stops before any is initialized.
        # That is a valid, fully-described outcome, not a broken directory.
        if run_metadata.get("run_status") == "platform_incompatible":
            return run_metadata, [], []
        raise LineageError(f"no lineage-* directories under {root}")

    fingerprints = {record.get("config_fingerprint") for record in lineages
                    if record.get("config_fingerprint") is not None}
    if len(fingerprints) > 1:
        raise LineageError(
            "lineages under this root were produced under different stage "
            f"configurations ({sorted(str(f) for f in fingerprints)}); analyze "
            "them separately rather than pooling them"
        )
    # Only meaningful when at least one lineage actually recorded a
    # fingerprint. A run whose lineages were all interrupted before their first
    # transition has none to compare, and must still be analyzable -- otherwise
    # the very lineages this counting change exists to preserve would abort the
    # analysis instead.
    if (run_metadata and fingerprints
            and run_metadata.get("config_fingerprint") not in fingerprints):
        raise LineageError(
            "lineages.json records a different configuration fingerprint than "
            "the lineages themselves; the run directory has been mixed"
        )

    return run_metadata, lineages, never_started


def checkpoint_order(
    run_metadata: dict[str, Any], lineages: list[dict[str, Any]]
) -> list[str]:
    declared = run_metadata.get("checkpoints")
    if isinstance(declared, list) and declared:
        return [str(entry["id"]) for entry in declared]
    # Fall back to the longest walk observed, which is the full sequence unless
    # every lineage stopped early.
    order: list[str] = []
    for record in lineages:
        for stage in record.get("stages", []):
            identifier = str(stage.get("checkpoint_id"))
            if identifier not in order:
                order.append(identifier)
    return order


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def numeric(values: list[Any]) -> list[float]:
    return [float(value) for value in values
            if isinstance(value, (int, float)) and not isinstance(value, bool)]


def summarize(values: list[Any]) -> dict[str, Any]:
    numbers = numeric(values)
    if not numbers:
        return {"n": 0, "total": None, "mean": None, "median": None, "max": None}
    return {
        "n": len(numbers),
        "total": sum(numbers),
        "mean": statistics.fmean(numbers),
        "median": statistics.median(numbers),
        "max": max(numbers),
    }


def build_reliability(
    lineages: list[dict[str, Any]], order: list[str],
    never_started: list[str] | None = None,
) -> dict[str, Any]:
    started = len(lineages)
    completed = [record for record in lineages if is_successful(record)]
    interrupted = [record for record in lineages
                   if classify(record) == INTERRUPTED_STATE]

    failure_stages: dict[str, int] = {}
    failure_reasons: dict[str, int] = {}
    for record in lineages:
        if is_successful(record):
            continue
        stage = str(record.get("failure_stage")
                    or record.get("current_checkpoint") or "unknown")
        reason = str(record.get("failure_reason") or "unknown")
        failure_stages[stage] = failure_stages.get(stage, 0) + 1
        failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

    return {
        # Only lineages the controller actually began. Planned ids with no
        # directory are reported below and deliberately excluded.
        "lineages_started": started,
        "lineages_planned_not_started": len(never_started or []),
        "planned_not_started_lineage_ids": list(never_started or []),
        "lineages_completed": len(completed),
        "successful_final_implementations": len(completed),
        # Denominator is every lineage started, interruptions included. A
        # lineage is never dropped or replaced to keep the population round.
        "end_to_end_completion_rate": len(completed) / started if started else None,
        "end_to_end_completion_interval": wilson(len(completed), started),
        "completed_lineage_ids": [record["lineage_id"] for record in completed],
        "stopped_lineage_ids": [
            record["lineage_id"] for record in lineages
            if classify(record) == "stopped"
        ],
        "controller_interrupted_lineage_ids": [
            record["lineage_id"] for record in interrupted
        ],
        "controller_interrupted": len(interrupted),
        # Named separately so an unreadable record is visible as such rather
        # than looking like an ordinary validation failure.
        "incomplete_record_reasons": dict(sorted(
            (reason, sum(1 for record in interrupted
                         if record.get("incomplete_reason") == reason))
            for reason in {str(record.get("incomplete_reason"))
                           for record in interrupted
                           if record.get("incomplete_reason")}
        )),
        # Keyed by checkpoint so a reader never has to guess whether a missing
        # entry means "no failures there" or "never reached".
        "failure_stage_counts": {
            checkpoint: failure_stages.get(checkpoint, 0) for checkpoint in order
        },
        "failure_stage_counts_other": {
            stage: count for stage, count in sorted(failure_stages.items())
            if stage not in set(order)
        },
        "failure_reason_counts": dict(sorted(failure_reasons.items())),
    }


def build_checkpoint_rows(
    lineages: list[dict[str, Any]], order: list[str]
) -> list[dict[str, Any]]:
    by_checkpoint: dict[str, list[dict[str, Any]]] = {
        checkpoint: [] for checkpoint in order
    }
    for record in lineages:
        for stage in record.get("stages", []):
            by_checkpoint.setdefault(str(stage.get("checkpoint_id")), []).append(stage)

    rows = []
    for checkpoint in order:
        stages = by_checkpoint.get(checkpoint, [])
        successes = [stage for stage in stages if stage.get("success")]
        rows.append(
            {
                "checkpoint_id": checkpoint,
                "checkpoint_name": stages[0].get("checkpoint_name") if stages else None,
                "source_mode": stages[0].get("source_mode") if stages else None,
                "implemented_flags": (
                    " ".join(stages[0].get("implemented_flags", [])) if stages else ""
                ),
                # A lineage only reaches a checkpoint if every earlier one
                # passed, so "reached" shrinks down the ladder by construction.
                "lineages_reached": len(stages),
                "lineages_passed": len(successes),
                "pass_rate_given_reached": (
                    len(successes) / len(stages) if stages else None
                ),
                "pass_interval_given_reached": wilson(len(successes), len(stages)),
                "initial_success": sum(
                    1 for stage in stages if stage.get("initial_success")
                ),
                "passed_after_repair": sum(
                    1 for stage in successes if not stage.get("initial_success")
                ),
                "repair_loops": summarize(
                    [stage.get("repair_loops") for stage in stages]
                ),
                "llm_invocations": summarize(
                    [stage.get("llm_invocations") for stage in stages]
                ),
                "loop_limit_reached": sum(
                    1 for stage in stages if stage.get("loop_limit_reached")
                ),
                # Kept distinct from implementation failure, using the
                # single-stage runner's own metadata vocabulary.
                "infrastructure_failures": sum(
                    1 for stage in stages if stage.get("infrastructure_failure")
                ),
                "agent_execution_failures": sum(
                    1 for stage in stages if stage.get("agent_execution_failure")
                ),
                "stop_reasons": dict(
                    sorted(
                        (reason, sum(1 for stage in stages
                                     if stage.get("stop_reason") == reason))
                        for reason in {
                            str(stage.get("stop_reason")) for stage in stages
                            if stage.get("stop_reason")
                        }
                    )
                ),
            }
        )
    return rows


def build_stage_rows(lineages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in lineages:
        for stage in record.get("stages", []):
            rows.append(
                {
                    "lineage_id": record.get("lineage_id"),
                    "end_to_end_success": is_successful(record),
                    "lineage_state": classify(record),
                    "checkpoint_id": stage.get("checkpoint_id"),
                    "checkpoint_name": stage.get("checkpoint_name"),
                    "source_mode": stage.get("source_mode"),
                    "implemented_flags": " ".join(stage.get("implemented_flags", [])),
                    "success": stage.get("success"),
                    "failure_reason": stage.get("failure_reason"),
                    "initial_success": stage.get("initial_success"),
                    "repair_loops": stage.get("repair_loops"),
                    "llm_invocations": stage.get("llm_invocations"),
                    "success_loop": stage.get("success_loop"),
                    "stop_reason": stage.get("stop_reason"),
                    "loop_limit_reached": stage.get("loop_limit_reached"),
                    "infrastructure_failure": stage.get("infrastructure_failure"),
                    "agent_execution_failure": stage.get("agent_execution_failure"),
                    "build_exit_code": stage.get("build_exit_code"),
                    "feature_test_exit_code": stage.get("feature_test_exit_code"),
                    # Provenance: which candidate seeded this stage, and what
                    # this stage produced for the next one.
                    "seed": stage.get("seed"),
                    "seed_sha256": stage.get("seed_sha256"),
                    "candidate": stage.get("candidate"),
                    "candidate_sha256": stage.get("candidate_sha256"),
                    "total_opencode_runtime_ms": stage.get("total_opencode_runtime_ms"),
                }
            )
    return rows


# ---------------------------------------------------------------------------
# C. Per-stage maintenance change, and D. total lineage change
# ---------------------------------------------------------------------------


def change_between(before: Path, after: Path) -> dict[str, Any]:
    """Reuse the canonical churn and function-change measures for one pair.

    Both are taken verbatim from `scripts/analyze_experiment.py`, so a per-stage
    number here is defined exactly as the same number is in a single-stage
    report -- only the baseline differs, and that is the whole point.

    Structural measures degrade rather than fail: when Tree-sitter is not
    installed the function counts come back None with a recorded reason, which
    is honest, where substituting zero would not be.
    """
    analyzer = experiment_analyzer()
    if analyzer is None:
        return {"available": False,
                "unavailable_reason": _ANALYZER["unavailable_reason"]}
    if not before.is_file() or not after.is_file():
        return {"available": False,
                "unavailable_reason": "a source in this pair is missing"}

    metrics: dict[str, Any] = {"available": True}
    metrics.update(analyzer.source_change_metrics(before, after))
    metrics.pop("changed_paths", None)

    before_parsed = analyzer.analyze_source(before, None, [])
    after_parsed = analyzer.analyze_source(after, None, [])
    metrics.update(
        analyzer.function_change_metrics(
            before_parsed.tree_sitter_functions, after_parsed.tree_sitter_functions
        )
    )
    metrics["tree_sitter_error"] = (
        before_parsed.tree_sitter_error or after_parsed.tree_sitter_error
    )
    # Code scope: the size of the thing being maintained, on both sides.
    metrics["tree_sitter_nodes_before"] = before_parsed.tree_sitter_node_count
    metrics["tree_sitter_nodes_after"] = after_parsed.tree_sitter_node_count

    actions, distance, error = analyzer.run_gumtree(
        before, after, None,
        before_parsed.tree_sitter_node_count, after_parsed.tree_sitter_node_count,
    )
    metrics["gumtree_edit_actions"] = None if error else int(sum(actions.values()))
    metrics["gumtree_normalized_edit_distance"] = distance
    metrics["gumtree_error"] = error
    return metrics


def stage_source(lineage_dir: Path, stage: Mapping[str, Any]) -> Path | None:
    """The candidate this stage produced, located under the root being analyzed.

    The recorded `candidate` field decides only WHETHER a candidate exists: the
    controller writes null there for a stage that produced none. Where it is is
    resolved locally; see `resolve_stage_paths`.
    """
    if not stage.get("candidate"):
        return None
    return resolve_stage_paths(lineage_dir, stage)["candidate"]


def build_transitions(lineages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """C: one row per successful transition, N-1's source vs N's candidate.

    The pairing is what makes this correct and what a population-shaped
    analyzer cannot express: every row has its own baseline, namely the exact
    file that stage was seeded with.
    """
    rows: list[dict[str, Any]] = []
    for record in lineages:
        lineage_dir = lineage_directory(record)
        previous: dict[str, Any] | None = None
        for stage in record.get("stages", []):
            if not stage.get("success"):
                break
            after = stage_source(lineage_dir, stage)
            if previous is not None and after is not None:
                before = stage_source(lineage_dir, previous)
                row = {
                    "lineage_id": record.get("lineage_id"),
                    "from_checkpoint": previous.get("checkpoint_id"),
                    "to_checkpoint": stage.get("checkpoint_id"),
                    "to_checkpoint_name": stage.get("checkpoint_name"),
                    "added_flags": sorted(
                        set(stage.get("implemented_flags", []))
                        - set(previous.get("implemented_flags", []))
                    ),
                    "baseline_source": str(before) if before else None,
                    "candidate_source": str(after),
                    # Effort, alongside change: both are per stage.
                    "repair_loops": stage.get("repair_loops"),
                    "llm_invocations": stage.get("llm_invocations"),
                    "initial_success": stage.get("initial_success"),
                    "total_opencode_runtime_ms": stage.get("total_opencode_runtime_ms"),
                    "total_runtime_ms": stage.get("total_runtime_ms"),
                }
                row.update(
                    {f"change_{k}": v
                     for k, v in change_between(before, after).items()}
                    if before else {"change_available": False,
                                    "change_unavailable_reason": "no seed source"}
                )
                rows.append(row)
            previous = stage
    return rows


def build_total_change(lineages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """D: the final source against that lineage's OWN checkpoint 000 source.

    Same-lineage only. Comparing a final against another lineage's 000 would
    measure the difference between two independent programs, not a trajectory.
    """
    rows: list[dict[str, Any]] = []
    for record in lineages:
        if not is_successful(record):
            continue
        stages = record.get("stages", [])
        if len(stages) < 2:
            continue
        lineage_dir = lineage_directory(record)
        first = stage_source(lineage_dir, stages[0])
        last = stage_source(lineage_dir, stages[-1])
        if first is None or last is None:
            continue
        row = {
            "lineage_id": record.get("lineage_id"),
            "from_checkpoint": stages[0].get("checkpoint_id"),
            "to_checkpoint": stages[-1].get("checkpoint_id"),
            "checkpoints_traversed": len(stages),
            "baseline_source": str(first),
            "final_source": str(last),
            "total_repair_loops": sum(
                stage.get("repair_loops") or 0 for stage in stages
            ),
            "total_llm_invocations": sum(
                stage.get("llm_invocations") or 0 for stage in stages
            ),
        }
        row.update({f"change_{k}": v for k, v in change_between(first, last).items()})
        rows.append(row)
    return rows


def check_seed_provenance(lineages: list[dict[str, Any]]) -> list[str]:
    """Every stage after the first must have been seeded by the immediately
    preceding stage of the SAME lineage. The controller enforces this while
    running; re-checking it from the recorded hashes means a pooled or hand-
    edited result set cannot pass silently."""
    problems = []
    for record in lineages:
        previous: dict[str, Any] | None = None
        for stage in record.get("stages", []):
            if previous is None:
                if stage.get("source_mode") != "new":
                    problems.append(
                        f"{record.get('lineage_id')}: first stage "
                        f"{stage.get('checkpoint_id')} is not source-mode new"
                    )
            else:
                if stage.get("seed_sha256") != previous.get("candidate_sha256"):
                    problems.append(
                        f"{record.get('lineage_id')}: stage "
                        f"{stage.get('checkpoint_id')} was not seeded by "
                        f"{previous.get('checkpoint_id')}'s candidate"
                    )
            previous = stage
    return problems


# ---------------------------------------------------------------------------
# Population views
# ---------------------------------------------------------------------------


def population_members(
    lineages: list[dict[str, Any]], checkpoint: str | None
) -> list[tuple[str, Path, dict[str, Any]]]:
    """(lineage_id, lineage_dir, stage) triples for one population.

    The lineage's own directory travels with the member because a stage's files
    are located from it, never from the paths the stage recorded at generation
    time; see `resolve_stage_paths`.

    checkpoint=None selects the FINAL population: the last stage of every
    lineage that completed every checkpoint. Otherwise it selects every lineage
    that passed that checkpoint, whether or not the lineage later stopped.
    """
    members = []
    for record in lineages:
        stages = record.get("stages", [])
        if checkpoint is None:
            if not is_successful(record) or not stages:
                continue
            members.append(
                (record["lineage_id"], lineage_directory(record), stages[-1])
            )
            continue
        for stage in stages:
            if str(stage.get("checkpoint_id")) == checkpoint and stage.get("success"):
                members.append(
                    (record["lineage_id"], lineage_directory(record), stage)
                )
                break
    return members


def agreed_value(values: set[str], key: str, label: str) -> str | None:
    """The one value a population's members share for `key`, or None.

    Every member of a materialized population is the same checkpoint of the
    same condition by construction, so a population has exactly one of these.
    That is verified rather than assumed: picking one of several would describe
    the view with a configuration it does not have, and a reader of the view's
    report would have no way to see it. Refused the same way `load_run` refuses
    to pool lineages recorded under different `config_fingerprint` values.

    Absent is not disagreement. `values` is collected from the members that
    recorded something, so a run that recorded nothing yields None and the key
    is written as null -- which keeps such a run analyzable for diversity,
    where making it fatal would break analyses that work today.
    """
    if len(values) > 1:
        raise LineageError(
            f"members of population {label!r} disagree on {key} "
            f"({sorted(values)}); every member of a population is the same "
            "checkpoint under the same condition, so choosing one of them "
            "would describe the view with a configuration it does not have"
        )
    return next(iter(values), None)


# Where `scripts/measure_execution_consistency.py` writes its results, relative
# to the population view it was pointed at. That tool's output lands INSIDE the
# view, which is the same tree `materialize_view` clears before rebuilding.
EXECUTION_CONSISTENCY_OUTPUT = ("analysis", "execution_consistency")


def check_execution_consistency_loss(
    view_dir: Path, label: str, allow_loss: bool
) -> None:
    """Refuse to rebuild a population view over an existing behavioral measurement.

    `materialize_view` clears `view_dir` before rewriting it, and
    `scripts/measure_execution_consistency.py` writes into
    `<view_dir>/analysis/execution_consistency/`. So re-running this script --
    for any reason, including one that has nothing to do with the population in
    question -- used to delete a completed behavioral measurement without ever
    saying so. That is not hypothetical: it destroyed a real, fully measured
    population in this repository, which had to be recovered from an earlier
    commit.

    Losing one is not a small cost. Reproducing it rebuilds and re-judges every
    candidate in the population, and per
    `docs/execution_consistency_methodology.md` a rebuild is not portable: a
    candidate that used an extension its original compiler provided will not
    build elsewhere, so the measurement may not be reproducible on the machine
    now doing the analysis at all.

    Deletion is therefore refused rather than performed silently -- and refused
    rather than worked around, because quietly preserving the old directory
    would leave a behavioral measurement sitting beside a population that may no
    longer be the one it described. `allow_loss` is the deliberate escape hatch
    for the case where the lineage data really did change.

    A population with no such directory -- one being materialized for the first
    time, or one nobody has measured -- is untouched by any of this, and the
    ordinary rebuild proceeds exactly as before.
    """
    measurement = view_dir.joinpath(*EXECUTION_CONSISTENCY_OUTPUT)
    if allow_loss or not measurement.exists():
        return
    raise LineageError(
        f"refusing to rebuild the population view {view_dir}: "
        f"{measurement} already holds an execution-consistency measurement for "
        f"the {label!r} population, and rebuilding the view would delete it. "
        "That measurement rebuilds and re-judges every candidate and is not "
        "reproducible on a different host family, so it is never discarded "
        "silently. Move or copy that directory aside to keep it, or pass "
        "--allow-execution-consistency-loss to discard it deliberately -- which "
        "is the right choice when the underlying lineage data changed and the "
        "old measurement no longer describes this population."
    )


def materialize_view(
    view_dir: Path,
    members: list[tuple[str, Path, dict[str, Any]]],
    run_metadata: dict[str, Any],
    label: str,
    *,
    allow_execution_consistency_loss: bool = False,
) -> Path:
    """Write a population as an experiment directory analyze_experiment.py can
    read: experiment.json, an empty baseline, and one attempt per member.

    The baseline is the empty translation unit, and that is a deliberate,
    recorded choice rather than a convenience. Each member is a whole program
    produced by an independent lineage; the lineages share no seed, so no
    member's source is a meaningful predecessor of another's. Picking one
    lineage's 000, one lineage's final, or an arbitrary candidate would invent a
    common ancestor that does not exist.

    The consequence is written into the view's own metadata: every clustering
    and pairwise metric stays valid, because all members share one constant
    baseline that cancels out of a member-to-member comparison, while every
    churn metric measures the program's size rather than a maintenance step.
    Those are listed by name in `baseline_dependent_metrics_unsupported` so a
    reader of the view's report cannot mistake them for change.

    The view must be a valid input to EVERY downstream analysis, not only the
    diversity analyzer it was first written for. `feature_test_command` and
    `build_command` are therefore carried across as well: they are what
    `scripts/measure_execution_consistency.py` reads to recover the
    checkpoint's cumulative flag scope and to rebuild each candidate, and a
    view without them crashed that tool on a population it is documented to
    accept. Both are recorded per checkpoint rather than per run, and every
    member of a population is the same checkpoint, so each has exactly one
    value here; see `agreed_value`.

    Rebuilding clears `view_dir` first, which would take an
    execution-consistency measurement written into it with everything else;
    `check_execution_consistency_loss` refuses that rather than letting it
    happen quietly.
    """
    check_execution_consistency_loss(
        view_dir, label, allow_execution_consistency_loss
    )
    if view_dir.exists():
        shutil.rmtree(view_dir)
    source_basename = run_metadata.get("source_basename") or (
        members[0][2].get("candidate_source_basename") if members else "source.c"
    )
    (view_dir / "baseline").mkdir(parents=True, exist_ok=True)
    (view_dir / "baseline" / source_basename).write_bytes(b"")

    index = []
    # Collected across every member and checked for agreement below, never
    # sampled from the first member. See `agreed_value`.
    feature_test_commands: set[str] = set()
    build_commands: set[str] = set()
    for number, (lineage_id, lineage_dir, stage) in enumerate(members, start=1):
        # Resolved from the lineage root, never from the stage's recorded
        # absolute paths: those were written on the generating machine and are
        # stale on any other one, or after the run directory is renamed.
        located = resolve_stage_paths(lineage_dir, stage)
        attempt_source = located["attempt_dir"]

        # The judge call is on the stage record; the build command is not, and
        # lives in the per-checkpoint experiment.json the stage run wrote
        # alongside its attempt. Located from the same resolved attempt
        # directory as everything else, so there is one way to find a stage's
        # files rather than two that can disagree. A checkpoint that recorded
        # no experiment.json contributes nothing rather than failing: this
        # function is on the diversity path, which does not need either value.
        recorded_judge = stage.get("feature_test_command")
        if recorded_judge is not None:
            feature_test_commands.add(str(recorded_judge))
        stage_experiment = attempt_source.parent / "experiment.json"
        if stage_experiment.is_file():
            recorded_build = read_json(stage_experiment).get("build_command")
            if recorded_build is not None:
                build_commands.add(str(recorded_build))

        attempt_target = view_dir / f"attempt-{number:03d}"
        (attempt_target / "candidate").mkdir(parents=True, exist_ok=True)

        metadata = read_json(attempt_source / "metadata.json")
        # Keep the stage's own metadata intact and add the lineage coordinates,
        # so a row in the view's report can always be traced back.
        metadata.update(
            {
                "run_id": f"attempt-{number:03d}",
                "attempt_number": number,
                "lineage_id": lineage_id,
                "lineage_checkpoint_id": stage.get("checkpoint_id"),
                "lineage_stage_dir": stage.get("stage_dir"),
                "source_path": source_basename,
            }
        )
        write_json(attempt_target / "metadata.json", metadata)

        candidate = located["candidate"]
        if not candidate.is_file():
            raise LineageError(f"candidate is missing: {candidate}")
        shutil.copy2(candidate, attempt_target / "candidate" / source_basename)
        for name in VIEW_ATTEMPT_FILES:
            origin = attempt_source / name
            if origin.is_file():
                shutil.copy2(origin, attempt_target / name)
        (attempt_target / "COMPLETE").write_text("", encoding="utf-8")

        index.append(
            {
                "attempt": f"attempt-{number:03d}",
                "lineage_id": lineage_id,
                "checkpoint_id": stage.get("checkpoint_id"),
                "candidate": stage.get("candidate"),
                "candidate_sha256": stage.get("candidate_sha256"),
            }
        )

    feature_test_command = agreed_value(
        feature_test_commands, "feature_test_command", label
    )
    build_command = agreed_value(build_commands, "build_command", label)

    write_json(
        view_dir / "experiment.json",
        {
            "schema_version": 2,
            "experiment_format": "lineage_population_view",
            "population": label,
            # Points at the view, not the checkout: analyze_experiment.py
            # rebuilds a repository-level paper aggregate under
            # <repository>/runs/experiments, and a lineage analysis must not
            # rewrite the results of unrelated experiments.
            "repository": str(view_dir),
            "repository_commit": run_metadata.get("repository_commit"),
            "utility": run_metadata.get("utility"),
            "model": run_metadata.get("model"),
            "temperature": run_metadata.get("temperature"),
            "agent": run_metadata.get("agent"),
            "max_loops": run_metadata.get("max_loops"),
            "source_path": source_basename,
            "source_workdir_path": run_metadata.get("source_path"),
            "source_mode": "new",
            "baseline_source_kind": "empty_new_source",
            # Carried from the checkpoint the population was drawn from, and
            # deliberately NOT synthesized: measure_execution_consistency.py
            # recovers the checkpoint's cumulative flag scope from the first
            # and rebuilds each candidate with the second, so a wrong value
            # would be a wrong measurement rather than a missing one.
            "feature_test_command": feature_test_command,
            "build_command": build_command,
            "requested_runs": len(members),
            "config_fingerprint": run_metadata.get("config_fingerprint"),
            "baseline_rationale": (
                "Lineages share no seed, so this population has no common "
                "prior source. The empty translation unit is used so that every "
                "member has the same constant baseline; clustering and pairwise "
                "metrics are unaffected, churn metrics are not maintenance "
                "change."
            ),
            "baseline_dependent_metrics_unsupported": list(
                BASELINE_DEPENDENT_METRICS
            ),
            "baseline_dependent_metrics_reported_by": (
                "lineage_transitions.csv (per stage) and "
                "lineage_total_change.csv (per lineage)"
            ),
        },
    )
    write_json(view_dir / "members.json", index)
    return view_dir


def run_analyzer(
    view_dir: Path, args: argparse.Namespace
) -> dict[str, Any]:
    command = [
        args.python,
        str(args.analyzer),
        "--experiment", str(view_dir),
        "--clean-output",
    ]
    if args.cluster_threshold is not None:
        command += ["--cluster-threshold", str(args.cluster_threshold)]
    if args.strategy_threshold is not None:
        command += ["--strategy-threshold", str(args.strategy_threshold)]
    if args.diversity_k_max is not None:
        command += ["--diversity-k-max", str(args.diversity_k_max)]

    print(f"\n=== diversity: {view_dir.name} ===")
    completed = subprocess.run(command, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "analysis_dir": str(view_dir / "analysis"),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_summary(report: dict[str, Any]) -> str:
    reliability = report["reliability"]
    lines = [
        f"# Lineage analysis: {report['utility']}",
        "",
        f"* Root: `{report['lineage_root']}`",
        f"* Model: `{report['model']}`  Temperature: {report['temperature']}",
        f"* Checkpoints: {' -> '.join(report['checkpoints'])}",
        f"* Configuration fingerprint: `{report['config_fingerprint']}`",
        "",
        "## Reliability",
        "",
        "The denominator is every lineage started. A lineage that stopped is "
        "retained and counted; it is never replaced to keep the number of "
        "finals round.",
        "",
        f"* **lineages started = {reliability['lineages_started']}**",
        f"* **successful final implementations = "
        f"{reliability['successful_final_implementations']}**",
    ]
    if reliability.get("lineages_planned_not_started"):
        # Reported for transparency, deliberately NOT in the denominator: these
        # lineages were declared by the run manifest but never begun.
        lines.append(
            f"* planned but never started = "
            f"{reliability['lineages_planned_not_started']} "
            "— excluded from the denominator"
        )
    if reliability.get("controller_interrupted"):
        # Counted in the denominator, never mistaken for an implementation
        # failure and never silently dropped.
        detail = ", ".join(
            f"{reason} × {count}"
            for reason, count in reliability["incomplete_record_reasons"].items()
        )
        lines.append(
            f"* controller-interrupted lineages = "
            f"{reliability['controller_interrupted']}"
            + (f" ({detail})" if detail else "")
            + " — started and counted; outcome unknown"
        )
    rate = reliability["end_to_end_completion_rate"]
    interval = reliability["end_to_end_completion_interval"]
    if rate is not None and interval:
        lines.append(
            f"* end-to-end completion rate = {rate:.3f} "
            f"(95% Wilson {interval['lower']:.3f}–{interval['upper']:.3f})"
        )
    elif rate is not None:
        lines.append(f"* end-to-end completion rate = {rate:.3f}")
        lines.append(
            f"* confidence interval unavailable: "
            f"{report['confidence_interval_unavailable_reason']}"
        )
    lines += ["", "### Where lineages stopped", ""]
    stopped = sum(reliability["failure_stage_counts"].values()) + sum(
        reliability["failure_stage_counts_other"].values()
    )
    if not stopped:
        lines.append("Every lineage completed every checkpoint.")
    else:
        lines += ["| checkpoint | lineages stopped here |", "|---|---|"]
        for checkpoint, count in reliability["failure_stage_counts"].items():
            lines.append(f"| {checkpoint} | {count} |")
        for checkpoint, count in reliability["failure_stage_counts_other"].items():
            lines.append(f"| {checkpoint} (unrecognized) | {count} |")
        lines += ["", "Reasons: " + ", ".join(
            f"{reason} × {count}"
            for reason, count in reliability["failure_reason_counts"].items()
        )]

    lines += [
        "",
        "## Per-checkpoint behavior",
        "",
        "| checkpoint | flags | reached | passed | first try | after repair | "
        "mean repair loops | infra fail | agent fail |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report["checkpoints_detail"]:
        mean_loops = row["repair_loops"]["mean"]
        lines.append(
            f"| {row['checkpoint_id']} {row['checkpoint_name'] or ''} "
            f"| `{row['implemented_flags'] or '(none)'}` "
            f"| {row['lineages_reached']} | {row['lineages_passed']} "
            f"| {row['initial_success']} | {row['passed_after_repair']} "
            f"| {'—' if mean_loops is None else f'{mean_loops:.2f}'} "
            f"| {row['infrastructure_failures']} "
            f"| {row['agent_execution_failures']} |"
        )

    lines += ["", "## Diversity (final population)", ""]
    if not report["populations"]:
        lines.append("Diversity analysis was not run.")
    else:
        # A population with fewer than two members is skipped before any
        # analyzer runs, so it has no report directory and no analyzer exit
        # status. Those fields stay None, and rendering them produced
        # "report under `None` (analyzer exit None)" -- Python placeholders
        # printed as if they were findings. Diversity over one implementation
        # is undefined, not failed: there is no pair to compare.
        analyzed = [
            population for population in report["populations"]
            if not population.get("skipped")
        ]
        for population in report["populations"]:
            members = population["members"]
            if population.get("skipped"):
                lines.append(
                    f"* **{population['label']}** — {members} successful "
                    f"implementation{'' if members == 1 else 's'} from "
                    f"{reliability['lineages_started']} lineages started. "
                    "Diversity was not computed: it needs at least 2 "
                    "successful implementations."
                )
                continue
            lines.append(
                f"* **{population['label']}** — {members} "
                f"implementation(s) from {reliability['lineages_started']} "
                f"lineages started; report under "
                f"`{population['analysis_dir']}`"
                + ("" if population["returncode"] == 0
                   else f" (analyzer exit {population['returncode']})")
            )
        # The paragraphs below explain how to read a view's report. With every
        # population skipped there is no view and no report, so they would be
        # describing something that was never written. The Change section still
        # follows either way.
        if analyzed:
            baseline = report["final_population_baseline"]
            lines += [
                "",
                "Final diversity compares only completed lineages. The number "
                "of lineages started is stated above and is not replaced by "
                "the number of finals.",
                "",
                f"**Baseline.** {baseline['why']}, so the view uses "
                f"`{baseline['kind']}`. Clustering, family, Vendi, discovery, "
                "repetition and pairwise-distance metrics are unaffected by "
                "that choice. These metrics in the view's report are **not** "
                "maintenance change and must not be read as such:",
                "",
            ]
            lines += [f"* `{name}`" for name in baseline["unsupported_metrics"]]
            lines.append("")
            lines.append(baseline["unsupported_reason"].capitalize() + ".")

    lines += ["", "## Change", ""]
    per_stage = report["per_stage_change"]
    total = report["total_lineage_change"]
    if per_stage["unavailable_reason"]:
        lines.append(f"Change measures unavailable: {per_stage['unavailable_reason']}")
    else:
        lines += [
            f"* **Per stage** ({per_stage['transitions']} successful "
            f"transitions) — baseline: {per_stage['baseline']}. "
            f"See `{per_stage['rows']}`.",
            f"* **Total per lineage** ({total['lineages']} completed) — "
            f"baseline: {total['baseline']}. {total['label'].capitalize()}. "
            f"See `{total['rows']}`.",
        ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lineage-root", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path,
                        help="Default: <lineage-root>/analysis")
    parser.add_argument("--checkpoint-diversity", action="store_true",
                        help="Also analyze the successful implementations at "
                             "each intermediate checkpoint")
    parser.add_argument("--skip-diversity", action="store_true",
                        help="Aggregate reliability only; build no views and "
                             "run no clustering")
    parser.add_argument("--skip-change", action="store_true",
                        help="Skip the per-stage and total-lineage change "
                             "measures, which reparse every retained source")
    parser.add_argument("--allow-execution-consistency-loss", action="store_true",
                        help="Rebuild a population view even when it holds an "
                             "execution-consistency measurement that the "
                             "rebuild will delete. Without this, such a "
                             "population is refused rather than overwritten")
    parser.add_argument("--cluster-threshold", type=float, default=None)
    parser.add_argument("--strategy-threshold", type=float, default=None)
    parser.add_argument("--diversity-k-max", type=int, default=None)
    parser.add_argument("--analyzer", type=Path,
                        default=REPO_ROOT / "scripts" / "analyze_experiment.py")
    parser.add_argument("--python", default=sys.executable)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.checkpoint_diversity and args.skip_diversity:
        raise LineageError(
            "--checkpoint-diversity and --skip-diversity are mutually exclusive"
        )

    root = args.lineage_root.resolve()
    output_dir = (args.output_dir or root / "analysis").resolve()
    run_metadata, lineages, never_started = load_run(root)

    # Run-level environment eligibility is answered before anything else, and
    # answers a different question from reliability. No lineage started, so
    # there is no denominator: reliability is NOT APPLICABLE, which is not the
    # same as 0.0 and must never be rendered as one.
    if run_metadata.get("run_status") == "platform_incompatible":
        report = {
            "schema_version": SCHEMA_VERSION,
            "lineage_root": str(root),
            "utility": run_metadata.get("utility"),
            "model": run_metadata.get("model"),
            "run_status": "platform_incompatible",
            "required_platform": run_metadata.get("required_platform"),
            "host_platform": run_metadata.get("host_platform"),
            "lineages_started": 0,
            "reliability": None,
            "reliability_applicable": False,
            "reliability_unavailable_reason": (
                "no lineage was started: this host does not satisfy the "
                "suite's platform contract, so there is no denominator over "
                "which to estimate reliability"
            ),
            "populations": [],
        }
        write_json(output_dir / "lineage_report.json", report)
        summary = (
            f"# Lineage analysis: {report['utility']}\n\n"
            f"* Root: `{root}`\n"
            f"* **Run status: platform_incompatible**\n"
            f"* Requires `{report['required_platform']}`; "
            f"this host is `{report['host_platform']}`\n\n"
            "## Reliability\n\n"
            "**Not applicable.** No lineage started, so there is no "
            "denominator. This is a run-level environment incompatibility, not "
            "a model result: it is not a validation failure, not an "
            "infrastructure failure inside a lineage, not a controller "
            "interruption, and not an unsuccessful generated implementation.\n"
        )
        (output_dir / "summary.md").write_text(summary, encoding="utf-8")
        print(summary)
        return 0
    order = checkpoint_order(run_metadata, lineages)

    reliability = build_reliability(lineages, order, never_started)
    checkpoints_detail = build_checkpoint_rows(lineages, order)
    stage_rows = build_stage_rows(lineages)
    provenance_problems = check_seed_provenance(lineages)
    transitions = [] if args.skip_change else build_transitions(lineages)
    total_change = [] if args.skip_change else build_total_change(lineages)

    populations: list[dict[str, Any]] = []
    if not args.skip_diversity:
        wanted: list[tuple[str, str | None]] = [("final", None)]
        if args.checkpoint_diversity:
            wanted += [(f"checkpoint-{checkpoint}", checkpoint)
                       for checkpoint in order]
        for label, checkpoint in wanted:
            members = population_members(lineages, checkpoint)
            entry: dict[str, Any] = {
                "label": label,
                "checkpoint_id": checkpoint,
                "members": len(members),
                "lineage_ids": [lineage_id for lineage_id, _, _ in members],
                "analysis_dir": None,
                "returncode": None,
            }
            if len(members) < 2:
                entry["skipped"] = (
                    "fewer than two successful implementations; diversity is "
                    "undefined for this population"
                )
                print(f"skipping {label}: {entry['skipped']}", file=sys.stderr)
                populations.append(entry)
                continue
            view = materialize_view(
                output_dir / "populations" / label, members, run_metadata, label,
                allow_execution_consistency_loss=(
                    args.allow_execution_consistency_loss
                ),
            )
            entry.update(run_analyzer(view, args))
            entry["view_dir"] = str(view)
            populations.append(entry)

    report = {
        "schema_version": SCHEMA_VERSION,
        "lineage_root": str(root),
        "utility": run_metadata.get("utility"),
        "model": run_metadata.get("model"),
        "temperature": run_metadata.get("temperature"),
        "agent": run_metadata.get("agent"),
        "max_loops": run_metadata.get("max_loops"),
        "config_fingerprint": (
            run_metadata.get("config_fingerprint")
            or lineages[0].get("config_fingerprint")
        ),
        "checkpoints": order,
        "reliability": reliability,
        "confidence_interval_unavailable_reason": _WILSON["unavailable_reason"],
        "checkpoints_detail": checkpoints_detail,
        # Change is reported against the baseline each measurement actually
        # has, never against the final population's placeholder baseline.
        "per_stage_change": {
            "baseline": "the source the stage was seeded with, i.e. checkpoint "
                        "N-1's candidate in the same lineage",
            "transitions": len(transitions),
            "rows": "lineage_transitions.csv",
            "unavailable_reason": _ANALYZER["unavailable_reason"],
        },
        "total_lineage_change": {
            "baseline": "that same lineage's checkpoint 000 source",
            "label": "total change across the maintenance trajectory, not a "
                     "single maintenance step",
            "lineages": len(total_change),
            "rows": "lineage_total_change.csv",
            "unavailable_reason": _ANALYZER["unavailable_reason"],
        },
        "final_population_baseline": {
            "kind": "empty_new_source",
            "why": "lineages share no seed, so the final population has no "
                   "common prior source; a shared constant baseline keeps the "
                   "clustering and pairwise metrics valid",
            "unsupported_metrics": list(BASELINE_DEPENDENT_METRICS),
            "unsupported_reason": "measured against an empty baseline these "
                                  "describe program size, not maintenance "
                                  "change; use per_stage_change instead",
        },
        "seed_provenance_problems": provenance_problems,
        "populations": populations,
    }

    write_json(output_dir / "lineage_report.json", report)
    write_csv(
        output_dir / "lineage_stages.csv",
        stage_rows,
        [
            "lineage_id", "end_to_end_success", "checkpoint_id", "checkpoint_name",
            "source_mode", "implemented_flags", "success", "failure_reason",
            "initial_success", "repair_loops", "llm_invocations", "success_loop",
            "stop_reason", "loop_limit_reached", "infrastructure_failure",
            "agent_execution_failure", "build_exit_code", "feature_test_exit_code",
            # A stage can now succeed, or be repaired, after a session that ran
            # out of time. These keep that visible per stage rather than only in
            # the attempt metadata underneath it.
            "opencode_exit_code", "initial_session_completed",
            "candidate_available_after_timeout", "repair_eligible",
            "repair_eligibility_reason",
            "seed", "seed_sha256", "candidate", "candidate_sha256",
            "total_opencode_runtime_ms",
        ],
    )
    if transitions:
        write_csv(
            output_dir / "lineage_transitions.csv",
            transitions,
            sorted({key for row in transitions for key in row}),
        )
    if total_change:
        write_csv(
            output_dir / "lineage_total_change.csv",
            total_change,
            sorted({key for row in total_change for key in row}),
        )
    summary = render_summary(report)
    (output_dir / "summary.md").write_text(summary, encoding="utf-8")

    print()
    print(summary)
    if provenance_problems:
        print("seed provenance problems:", file=sys.stderr)
        for problem in provenance_problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LineageError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
