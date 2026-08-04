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

from sklearn.metrics import adjusted_rand_score


def behavioral_fingerprint_hash(failing_cases: Sequence[tuple[str, str]]) -> str:
    """Canonical SHA-256 over the (case name, verdict) pairs a candidate failed.

    Order-independent by construction: the pairs are sorted before hashing, so
    two candidates that failed the same cases with the same verdicts collide
    regardless of the order the runner's thread pool happened to report them in.

    The pairs are the *failures only*, which is what `runner.py --json-report`
    enumerates individually. That is sufficient to identify the full pass/fail
    vector precisely because the case set is a deterministic function of the
    condition being measured -- same suite files, same cumulative flag list,
    same corpus -- so every candidate under comparison is judged on an identical
    set of cases and any case absent from the failure list passed. The
    orchestrator verifies that premise rather than assuming it, and records the
    result as `case_count_stable`.

    The verdict is part of the material, not just the case name: a candidate
    that times out on a case has not behaved the same way as one that produced
    wrong output on it, and collapsing the two would understate divergence.
    """
    normalized = sorted(
        [str(name), str(verdict)] for name, verdict in failing_cases
    )
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
