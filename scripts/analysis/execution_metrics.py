"""Pure statistical helpers for behavioral and execution consistency.

The companion of `diversity_metrics`, for the second measurement dimension
rather than the third. `diversity_metrics` summarizes *structure*: how varied
the configured source of successful candidates is, relative to a baseline.
Nothing here reads source at all. These helpers summarize *observed execution*:
what a rebuilt candidate actually did when the suite's own runner judged it.

No subprocess, no filesystem, no clustering. `scripts/measure_execution_consistency.py`
performs the rebuild/judge orchestration and hands the resulting verdicts here,
exactly as `analyze_experiment.py` hands feature matrices to `diversity_metrics`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

BEHAVIORAL_PROFILE_DOMAIN = "agentic-cyber.behavioral-verdict-profile.v2"


def behavioral_fingerprint_hash(
    corpus_identity: str,
    case_results: Sequence[Mapping[str, Any]],
) -> str:
    """Hash a complete verdict trace together with its behavioral corpus."""
    normalized = sorted(
        (
            {"case_id": str(result["case_id"]),
             "verdict": str(result["verdict"])}
            for result in case_results
        ),
        key=lambda result: result["case_id"],
    )
    payload = json.dumps(
        {
            "domain": BEHAVIORAL_PROFILE_DOMAIN,
            "corpus_identity": str(corpus_identity),
            "results": normalized,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pairwise_verdict_disagreement(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
) -> float:
    """Fraction of compatible executed cases whose verdicts differ."""
    left_trace = [
        (str(result["case_id"]), str(result["verdict"])) for result in left
    ]
    right_trace = [
        (str(result["case_id"]), str(result["verdict"])) for result in right
    ]
    left_ids = [case_id for case_id, _ in left_trace]
    right_ids = [case_id for case_id, _ in right_trace]
    if left_ids != right_ids:
        raise ValueError("behavioral traces use different ordered case IDs")
    if not left_trace:
        raise ValueError("behavioral disagreement is undefined for an empty corpus")
    return sum(
        left_verdict != right_verdict
        for (_, left_verdict), (_, right_verdict) in zip(left_trace, right_trace)
    ) / len(left_trace)


def structural_behavior_agreement(
    run_ids: Sequence[str],
    behavioral_group_by_run: Mapping[str, Any],
    structural_label_by_run: Mapping[str, Any],
) -> dict[str, Any]:
    """Chance-adjusted agreement between behavioral and structural partitions.

    Both arguments are partitions of the same runs by different criteria: one
    groups runs that behaved identically under execution, the other is the
    architecture- or strategy-family assignment `analyze_experiment.py` already
    computed from source structure. The adjusted Rand index (Hubert and Arabie,
    1985) asks whether they cut the population the same way.

    Near 1, structural family membership predicts behavioral identity. Near 0,
    it does not -- structurally distinct candidates converged on the same
    observed behavior, or structurally similar ones diverged. Neither direction
    is a defect; the number is evidence about how much the structural diversity
    result says about behavior, which is a claim the diversity measurement
    itself does not make.

    Only runs present in both mappings contribute, so a run outside the
    architecture or strategy population simply does not enter that comparison.
    `run_ids` fixes the order, keeping the result deterministic. ARI is
    undefined for fewer than two runs and is reported as null there rather than
    as a number.
    """
    from sklearn.metrics import adjusted_rand_score

    shared = [
        run_id
        for run_id in run_ids
        if run_id in behavioral_group_by_run and run_id in structural_label_by_run
    ]
    if len(shared) < 2:
        return {"population_n": len(shared), "adjusted_rand_index": None}
    behavioral = [str(behavioral_group_by_run[run_id]) for run_id in shared]
    structural = [str(structural_label_by_run[run_id]) for run_id in shared]
    return {
        "population_n": len(shared),
        "adjusted_rand_index": float(adjusted_rand_score(behavioral, structural)),
    }
