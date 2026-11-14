"""Prepare or explicitly run S_node over the immutable historical C journal.

Planning is read-only. Evaluation always writes a new caller-selected artifact
and refuses to overwrite it. No extraction, compilation, lineage generation, or
historical A/S artifact mutation is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .analysis import ordered_distances as old
from .analysis.strategy_node import (ALGORITHM_VERSION, NodeLimits, compare,
                                     evaluate_architecture_mappings)

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "docs/checkpoint_diversity_measurements.json"
IMPLEMENTATION_PATHS = (ROOT / "scripts/analysis/strategy_node.py", Path(__file__).resolve())
HISTORICAL_LIMITS = NodeLimits(max_diagnostic_operations=0)


def sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


def _classification(pair: dict[str, Any]) -> str:
    comparison = pair["comparison"]
    architecture, strategy = comparison["architecture"], comparison["strategy"]
    if architecture.get("status") != "success":
        return "unavailable_prior_architecture"
    if not architecture.get("enumeration_complete"):
        return "unavailable_incomplete_architecture_optima"
    if strategy.get("status") == "success":
        mappings = strategy.get("evaluated_alignments", [])
        expected = comparison.get("alignment", {}).get("optimal_mapping_count")
        return "reuse_saved_alignments" if mappings and len(mappings) == expected else "invalid_saved_alignment_artifact"
    if strategy.get("reason") == "comparison_work_limit":
        return "recompute_architecture_alignments"
    return "unavailable_prior_alignment:" + str(strategy.get("reason", "unknown"))


def build_plan(journal_path: Path = JOURNAL, *, verify_hashes: bool = True) -> dict[str, Any]:
    journal_bytes = journal_path.read_bytes()
    journal = json.loads(journal_bytes)
    candidates, pairs = journal["candidates"], journal["pairs"]
    missing, mismatched, eligible = [], [], 0
    for candidate_id, candidate in candidates.items():
        if not candidate.get("comparison_eligible"):
            continue
        eligible += 1
        if verify_hashes:
            path = ROOT / candidate["representation_artifact"]
            if not path.is_file():
                missing.append(candidate_id)
            elif sha(path.read_bytes()) != candidate["representation_sha256"]:
                mismatched.append(candidate_id)
    counts = Counter(_classification(pair) for pair in pairs.values())
    return {"schema_version": 1, "study": "historical_snode_evaluation_plan_v1",
            "journal": str(journal_path.relative_to(ROOT)), "journal_sha256": sha(journal_bytes),
            "algorithm": ALGORITHM_VERSION,
            "implementation_sha256": {str(path.relative_to(ROOT)): sha(path.read_bytes())
                                      for path in IMPLEMENTATION_PATHS},
            "candidate_count": len(candidates),
            "pair_count": len(pairs), "eligible_representation_count": eligible,
            "representation_hash_check": {"missing": missing, "mismatched": mismatched},
            "pair_routes": dict(sorted(counts.items())),
            "policy": {"reuse": "saved complete scope-compatible A-optimal mappings when present",
                       "recompute": "rerun unchanged exact A objective only when old S exhausted its work budget",
                       "unavailable": "preserve absent/incomplete Architecture outcomes",
                       "representations": "reuse hash-verified saved Clang-adapter JSON; never re-extract"}}


def _representations(journal, pair):
    output = []
    for candidate_id in (pair["left"], pair["right"]):
        candidate = journal["candidates"][candidate_id]
        path = ROOT / candidate["representation_artifact"]
        data = path.read_bytes()
        if sha(data) != candidate["representation_sha256"]:
            raise ValueError("historical_representation_hash_mismatch:" + candidate_id)
        output.append(json.loads(data))
    return output


def evaluate_pair(journal: dict[str, Any], pair_key: str, *, limits: NodeLimits) -> dict[str, Any]:
    pair = journal["pairs"][pair_key]
    route = _classification(pair)
    base = {"left": pair["left"], "right": pair["right"], "route": route,
            "historical_architecture": pair["comparison"]["architecture"]}
    if route.startswith("unavailable_"):
        return {**base, "strategy_node": {"status": "unavailable", "distance": None,
                                           "reason": route}}
    if route == "invalid_saved_alignment_artifact":
        return {**base, "strategy_node": {"status": "unavailable", "distance": None,
                                           "reason": route}}
    left, right = _representations(journal, pair)
    saved = pair["comparison"]
    saved_scope = saved["scope"]
    if (saved_scope.get("exclude_regex") != old.DEFAULT_EXCLUDE
            or saved_scope.get("forced_includes") != []):
        return {**base, "strategy_node": {"status": "unavailable", "distance": None,
                                           "reason": "historical_scope_policy_mismatch"}}
    if route == "reuse_saved_alignments":
        mappings = [row["mapping"] for row in saved["strategy"]["evaluated_alignments"]]
        result = evaluate_architecture_mappings(
            left, right, mappings, saved_scope["left"], saved_scope["right"], limits=limits)
    else:
        result = compare(left, right, limits=limits, exclude_regex=old.DEFAULT_EXCLUDE, forced_includes=())
        if result.get("scope", {}).get("left") != saved_scope["left"] or result.get("scope", {}).get("right") != saved_scope["right"]:
            result["strategy_node"] = {"status": "unavailable", "distance": None,
                                       "reason": "recomputed_scope_mismatch"}
        historical_distance = saved["architecture"]["distance"]
        recomputed_distance = result.get("architecture", {}).get("distance")
        if recomputed_distance != historical_distance:
            result["strategy_node"] = {"status": "unavailable", "distance": None,
                                       "reason": "recomputed_architecture_distance_mismatch"}
    return {**base, "result": result}


def run(output: Path, max_pairs: int, *, journal_path: Path = JOURNAL,
        limits: NodeLimits = HISTORICAL_LIMITS) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("refusing_to_overwrite:" + str(output))
    journal_bytes = journal_path.read_bytes()
    journal = json.loads(journal_bytes)
    keys = sorted(journal["pairs"])
    if max_pairs <= 0 or max_pairs > len(keys):
        raise ValueError("max_pairs_must_be_between_1_and_historical_pair_count")
    artifact = {"schema_version": 1, "study": "historical_snode_evaluation_v1",
                "journal": str(journal_path.relative_to(ROOT)), "journal_sha256": sha(journal_bytes),
                "algorithm": ALGORITHM_VERSION,
                "implementation_sha256": {str(path.relative_to(ROOT)): sha(path.read_bytes())
                                          for path in IMPLEMENTATION_PATHS},
                "limits": vars(limits),
                "diagnostic_policy": "operation traces omitted from population artifact; per-function costs retained",
                "selection": {"order": "lexicographic historical pair key", "max_pairs": max_pairs},
                "pairs": {key: evaluate_pair(journal, key, limits=limits) for key in keys[:max_pairs]}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(stable_json(artifact))
    return artifact


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-pairs", type=int)
    args = parser.parse_args(argv)
    if args.run:
        if args.output is None or args.max_pairs is None:
            parser.error("--run requires --output and --max-pairs")
        print(stable_json(run(args.output, args.max_pairs)), end="")
    else:
        print(stable_json(build_plan()), end="")


if __name__ == "__main__":
    main()
