"""Exploratory reporting over existing A/S results; no new distance definitions."""
from __future__ import annotations

from collections import Counter
import itertools
import math

GRID = tuple(i / 100 for i in range(5, 100, 5))


def population_key(candidate):
    return candidate["formal_run_id"], candidate["utility"], candidate["checkpoint_id"]


def scalar(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid_distance")
    return float(value)


def matrices(candidates, pairs):
    """Identity-indexed matrices; missing edges stay None, even for duplicate sources."""
    if not candidates or len({population_key(c) for c in candidates}) != 1:
        raise ValueError("empty_or_cross_population_input")
    ids = sorted(c["candidate_id"] for c in candidates)
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate_candidate_identity")
    index = {identifier: i for i, identifier in enumerate(ids)}
    n = len(ids)
    a, lo, hi = ([[0. if i == j else None for j in range(n)] for i in range(n)] for _ in range(3))
    seen = set()
    for pair in pairs:
        left, right = pair["left"], pair["right"]
        if left not in index or right not in index:
            raise ValueError("pair_outside_population")
        key = tuple(sorted((left, right)))
        if left == right or key in seen:
            raise ValueError("self_or_duplicate_pair")
        seen.add(key)
        i, j = index[left], index[right]
        comparison = pair["comparison"]
        architecture, strategy = comparison["architecture"], comparison["strategy"]
        if architecture["status"] == "success":
            a[i][j] = a[j][i] = scalar(architecture["distance"])
        # A solver bound, including a singleton bound, is not an exact scalar result.
        if strategy["status"] == "success":
            interval = strategy["alignment_range"]
            if len(interval) != 2 or scalar(interval[0]) > scalar(interval[1]):
                raise ValueError("invalid_strategy_interval")
            lo[i][j] = lo[j][i] = scalar(interval[0])
            hi[i][j] = hi[j][i] = scalar(interval[1])
    def describe(matrix, upper=None):
        positions = list(itertools.combinations(range(n), 2))
        values = [matrix[i][j] for i, j in positions if matrix[i][j] is not None]
        complete = len(values) == len(positions)
        result = {"complete": complete, "available_pairs": len(values), "total_pairs": len(positions),
                  "coverage": len(values) / len(positions) if positions else None,
                  "estimate_scope": "full_population" if complete else "available_pairs_descriptive_only",
                  "mean": sum(values) / len(values) if values else None}
        if upper is not None:
            highs = [upper[i][j] for i, j in positions if matrix[i][j] is not None]
            result["mean_interval"] = [result.pop("mean"), sum(highs) / len(highs) if highs else None]
            result["singleton_pairs"] = sum(matrix[i][j] == upper[i][j] for i, j in positions if matrix[i][j] is not None)
            result["alignment_sensitive_pairs"] = len(values) - result["singleton_pairs"]
        return result
    return {"candidate_order": ids, "architecture": a, "strategy_lower": lo, "strategy_upper": hi,
            "architecture_summary": describe(a), "strategy_summary": describe(lo, hi),
            "diagonal_policy": "zero by candidate identity; no self-comparison or claim about self-alignment extrema"}


def partition(labels):
    groups = {}
    for i, label in enumerate(labels):
        groups.setdefault(int(label), []).append(i)
    return sorted(groups.values(), key=lambda group: group[0])


def silhouette(matrix, groups):
    n, k = len(matrix), len(groups)
    if not 1 < k < n:
        return None, "requires_2_to_n_minus_1_families"
    values = []
    for group in groups:
        for i in group:
            if len(group) == 1:
                values.append(0.)
                continue
            a = sum(matrix[i][j] for j in group if i != j) / (len(group) - 1)
            b = min(sum(matrix[i][j] for j in other) / len(other) for other in groups if other is not group)
            values.append((b - a) / max(a, b) if max(a, b) else 0.)
    return sum(values) / n, None


def statistics(matrix, groups, previous=None):
    n = len(matrix)
    shares = [len(group) / n for group in groups]
    score, reason = silhouette(matrix, groups)
    result = {"raw_family_count": len(groups), "effective_family_count": math.exp(-sum(p * math.log(p) for p in shares)),
              "dominant_family_share": max(shares), "singleton_rate": sum(len(g) == 1 for g in groups) / n,
              "silhouette": score, "silhouette_reason": reason}
    def neighborhoods(collection):
        return {i: frozenset(group) for group in collection for i in group}
    now = neighborhoods(groups)
    if previous is None:
        result.update(changed_candidate_count=None, changed_copair_count=None, changed_copair_rate=None)
    else:
        old = neighborhoods(previous)
        changes = sum((old[i] == old[j]) != (now[i] == now[j]) for i, j in itertools.combinations(range(n), 2))
        result.update(changed_candidate_count=sum(old[i] != now[i] for i in range(n)), changed_copair_count=changes,
                      changed_copair_rate=changes / math.comb(n, 2) if n > 1 else 0.)
    return result


def cluster_scenario(matrix, candidate_order, grid=GRID):
    if any(value is None for row in matrix for value in row):
        return {"status": "unavailable", "reason": "incomplete_full_population_matrix",
                "rows": [{"threshold": t, "status": "unavailable", "reason": "incomplete_full_population_matrix"} for t in grid]}
    import numpy as np
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform
    n = len(matrix)
    z = linkage(squareform(np.array(matrix), checks=True), method="average", optimal_ordering=False) if n > 1 else []
    def cut(t):
        return partition(fcluster(z, t=t, criterion="distance")) if n > 1 else [[0]]
    rows, stable = [], []
    previous = None
    for threshold in grid:
        groups = cut(threshold)
        row = {"threshold": threshold, "status": "success", "legacy_reference_only": threshold == .30,
               "families": [[candidate_order[i] for i in group] for group in groups],
               **statistics(matrix, groups, previous)}
        rows.append(row)
        if previous == groups:
            stable[-1]["last_grid_threshold"] = threshold
        else:
            stable.append({"first_grid_threshold": threshold, "last_grid_threshold": threshold,
                           "raw_family_count": len(groups), "families": row["families"]})
        previous = groups
    heights = [float(r[2]) for r in z]
    boundaries = sorted({0., 1., *heights})
    continuous = [{"lower_inclusive": a, "upper_exclusive": b,
                   "raw_family_count": len(cut(a))} for a, b in zip(boundaries, boundaries[1:]) if a < b]
    return {"status": "success", "rows": rows, "merge_heights": heights,
            "linkage": [list(map(float, r)) for r in z], "stable_grid_ranges": stable,
            "continuous_partition_stability": continuous, "at_one_family_count": len(cut(1.)),
            "cut_policy": "merge height <= threshold; candidate IDs sorted before deterministic linkage tie handling"}


def analyze_population(candidates, pairs):
    matrix = matrices(candidates, pairs)
    scenarios = {name: cluster_scenario(matrix[key], matrix["candidate_order"])
                 for name, key in (("architecture_exact", "architecture"), ("strategy_lower_endpoint", "strategy_lower"), ("strategy_upper_endpoint", "strategy_upper"))}
    uncertainty = []
    lower, upper = scenarios["strategy_lower_endpoint"], scenarios["strategy_upper_endpoint"]
    if lower["status"] == upper["status"] == "success":
        uncertainty = [{"threshold": a["threshold"], "same_partition": a["families"] == b["families"],
                        "lower_family_count": a["raw_family_count"], "upper_family_count": b["raw_family_count"]}
                       for a, b in zip(lower["rows"], upper["rows"])]
    return {"matrices": matrix, "scenarios": scenarios, "endpoint_sensitivity": uncertainty,
            "strategy_reporting": "Exploratory endpoint scenarios only; no definitive families when any pair is alignment-sensitive. Endpoint agreement does not establish all admissible partitions are invariant."}
