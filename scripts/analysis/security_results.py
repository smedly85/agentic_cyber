"""Missing-aware aggregation of post-validation dynamic security results."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping


def load_security_result(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "security_evaluation_completed": False,
            "security_clean": None,
            "security_finding_count": 0,
            "unique_security_findings": [],
            "unique_crash_signatures": [],
            "time_to_first_security_finding_seconds": None,
            "security_results_available": False,
            "reachability_analysis_completed": False,
            "function_reachability": [],
            "reachable_function_count": None,
            "unreachable_function_count": None,
            "max_reachable_call_depth": None,
            "functions_by_call_depth": {},
            "structural_exposure_ranking": [],
            "reachability_report": None,
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raw = {}
    completed = raw.get("security_evaluation_completed") is True
    findings = raw.get("unique_security_findings") or []
    signatures = sorted({
        str(item.get("signature")) for item in findings
        if isinstance(item, Mapping) and item.get("signature")
    })
    function_reachability = raw.get("function_reachability")
    reachability_completed = isinstance(function_reachability, list)
    return {
        "security_evaluation_completed": completed,
        "security_clean": raw.get("security_clean") if completed else None,
        "security_finding_count": len(signatures),
        "unique_security_findings": signatures,
        "unique_crash_signatures": sorted(set(raw.get("unique_crash_signatures") or [])),
        "time_to_first_security_finding_seconds": raw.get(
            "time_to_first_security_finding_seconds"
        ),
        "security_results_available": True,
        "reachability_analysis_completed": reachability_completed,
        "function_reachability": function_reachability if reachability_completed else [],
        "reachable_function_count": raw.get("reachable_function_count") if reachability_completed else None,
        "unreachable_function_count": raw.get("unreachable_function_count") if reachability_completed else None,
        "max_reachable_call_depth": raw.get("max_reachable_call_depth") if reachability_completed else None,
        "functions_by_call_depth": raw.get("functions_by_call_depth") if reachability_completed else {},
        "structural_exposure_ranking": raw.get("structural_exposure_ranking") if reachability_completed else [],
        "reachability_report": raw.get("reachability_report") if reachability_completed else None,
    }


def aggregate_security_results(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    evaluated = [row for row in rows if row.get("security_evaluation_completed") is True]
    with_findings = [row for row in evaluated if int(row.get("security_finding_count") or 0) > 0]
    finding_signatures = {
        str(signature)
        for row in evaluated
        for signature in (row.get("unique_security_findings") or [])
    }
    crash_signatures = {
        str(signature)
        for row in evaluated
        for signature in (row.get("unique_crash_signatures") or [])
    }
    times = [
        float(row["time_to_first_security_finding_seconds"])
        for row in with_findings
        if isinstance(row.get("time_to_first_security_finding_seconds"), (int, float))
        and not isinstance(row.get("time_to_first_security_finding_seconds"), bool)
    ]
    reachability_rows = [
        row for row in rows if row.get("reachability_analysis_completed") is True
    ]
    reachable_counts = [
        int(row["reachable_function_count"])
        for row in reachability_rows
        if isinstance(row.get("reachable_function_count"), int)
        and not isinstance(row.get("reachable_function_count"), bool)
    ]
    maximum_depths = [
        int(row["max_reachable_call_depth"])
        for row in reachability_rows
        if isinstance(row.get("max_reachable_call_depth"), int)
        and not isinstance(row.get("max_reachable_call_depth"), bool)
    ]
    reachability_summary = {
        "reachability_evaluated_count": len(reachability_rows),
        "reachability_unevaluated_count": len(rows) - len(reachability_rows),
        "mean_reachable_function_count": statistics.fmean(reachable_counts) if reachable_counts else None,
        "mean_max_reachable_call_depth": statistics.fmean(maximum_depths) if maximum_depths else None,
        "missing_reachability_semantics": "not_characterized; never assigned an inferred depth",
    }
    return {
        "security_candidate_count": len(rows),
        "security_evaluated_count": len(evaluated),
        "security_unevaluated_count": len(rows) - len(evaluated),
        "security_clean_count": sum(row.get("security_clean") is True for row in evaluated),
        "security_finding_count": sum(int(row.get("security_finding_count") or 0) for row in evaluated),
        "lineages_with_security_findings": len(with_findings),
        "unique_security_findings": sorted(finding_signatures),
        "unique_security_finding_count": len(finding_signatures),
        "unique_crash_signatures": sorted(crash_signatures),
        "unique_crash_signature_count": len(crash_signatures),
        "mean_time_to_first_finding": statistics.fmean(times) if times else None,
        "reachability_analysis": reachability_summary,
        **reachability_summary,
        "missing_results_semantics": "not_evaluated; never interpreted as security_clean",
    }
