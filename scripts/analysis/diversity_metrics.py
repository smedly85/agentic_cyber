"""Pure statistical helpers for architecture and strategy diversity."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score, silhouette_score


def cluster_statistics(labels: Sequence[int]) -> dict[str, Any]:
    """Summarize an empirical family distribution without deduplicating it."""
    if len(labels) == 0:
        return {
            "raw_family_count": 0,
            "raw_cluster_count": 0,
            "family_sizes": {},
            "cluster_sizes": {},
            "entropy_nats": None,
            "entropy_bits": None,
            "effective_family_count": None,
            "effective_cluster_count": None,
            "dominant_family_share": None,
            "dominant_cluster_share": None,
            "singleton_rate": None,
        }

    sizes = Counter(int(label) for label in labels)
    total = len(labels)
    proportions = [size / total for size in sizes.values()]
    entropy_nats = -sum(p * math.log(p) for p in proportions)
    entropy_bits = -sum(p * math.log2(p) for p in proportions)
    family_sizes = dict(sorted(sizes.items()))
    effective = math.exp(entropy_nats)
    dominant = max(proportions)
    return {
        "raw_family_count": len(sizes),
        "raw_cluster_count": len(sizes),
        "family_sizes": family_sizes,
        "cluster_sizes": family_sizes,
        "entropy_nats": entropy_nats,
        "entropy_bits": entropy_bits,
        "effective_family_count": effective,
        "effective_cluster_count": effective,
        "dominant_family_share": dominant,
        "dominant_cluster_share": dominant,
        "singleton_rate": sum(size == 1 for size in sizes.values()) / total,
    }


def da_at_k(labels: Sequence[int], k: int) -> float:
    """Exact expected families discovered by a size-k sample without replacement."""
    n = len(labels)
    if n == 0 or k < 1 or k > n:
        raise ValueError(f"k must satisfy 1 <= k <= N (received k={k}, N={n})")
    denominator = math.comb(n, k)
    return sum(
        1.0
        - (math.comb(n - size, k) / denominator if n - size >= k else 0.0)
        for size in Counter(int(label) for label in labels).values()
    )


def da_curve(labels: Sequence[int]) -> list[dict[str, float | int]]:
    return [{"k": k, "da_at_k": da_at_k(labels, k)} for k in range(1, len(labels) + 1)]


def nauadc(values: Sequence[float], kmax: int | None = None) -> float | None:
    """Width-normalized trapezoidal area over DA@1,...,DA@Kmax."""
    if not values:
        return None
    selected_kmax = len(values) if kmax is None else kmax
    if selected_kmax < 1 or selected_kmax > len(values):
        raise ValueError("kmax must be within the available DA curve")
    selected = np.asarray(values[:selected_kmax], dtype=float)
    if selected_kmax == 1:
        return float(selected[0])
    return float(np.trapezoid(selected, dx=1.0) / (selected_kmax - 1))


def nauadc_summary(
    curve: Sequence[Mapping[str, Any]], requested_kmax: int | None
) -> dict[str, Any]:
    values = [float(point["da_at_k"]) for point in curve]
    full_kmax = len(values) if values else None
    result: dict[str, Any] = {
        "nauadc_full": nauadc(values),
        "nauadc_full_kmax": full_kmax,
        "requested_kmax": requested_kmax,
        "nauadc_at_kmax": None,
        "nauadc_at_kmax_reason": None,
    }
    if requested_kmax is None:
        result["nauadc_at_kmax_reason"] = "--diversity-k-max was not supplied"
    elif requested_kmax < 1:
        raise ValueError("--diversity-k-max must be positive")
    elif len(values) < requested_kmax:
        result["nauadc_at_kmax_reason"] = (
            f"population N={len(values)} is smaller than requested K={requested_kmax}"
        )
    else:
        result["nauadc_at_kmax"] = nauadc(values, requested_kmax)
    return result


def exact_repetition_summary(
    hashes: Sequence[str], run_ids: Sequence[str] | None = None
) -> dict[str, Any]:
    if run_ids is None:
        run_ids = [str(index) for index in range(len(hashes))]
    if len(run_ids) != len(hashes):
        raise ValueError("hashes and run_ids must have equal length")
    groups: dict[str, list[str]] = defaultdict(list)
    for digest, run_id in zip(hashes, run_ids):
        groups[str(digest)].append(str(run_id))
    n = len(hashes)
    return {
        "population_n": n,
        "distinct_hashes": len(groups),
        "exact_unique_rate": len(groups) / n if n else None,
        "exact_modal_share": max(map(len, groups.values())) / n if n else None,
        "hash_groups": [
            {"sha256": digest, "count": len(members), "members": members}
            for digest, members in sorted(groups.items())
        ],
    }


def primary_population(
    rows: Sequence[Mapping[str, Any]], complete_measurement_key: str
) -> dict[str, Any]:
    successful = [row for row in rows if bool(row.get("overall_success"))]
    included = [
        row for row in successful if bool(row.get(complete_measurement_key))
    ]
    return {
        "run_ids": [str(row["run_id"]) for row in included],
        "population_n": len(included),
        "successful_runs": len(successful),
        "measurement_coverage": len(included) / len(successful) if successful else None,
    }


def compute_vendi_score(matrix: Any, negative_tolerance: float = 1e-8) -> dict[str, Any]:
    features = np.asarray(matrix, dtype=float)
    if features.ndim != 2 or features.shape[0] == 0 or features.shape[1] == 0:
        return {"score": None, "reason": "empty structural representation"}
    if not np.isfinite(features).all():
        return {"score": None, "reason": "non-finite structural representation"}

    gram = features @ features.T
    gram = (gram + gram.T) / 2.0
    eigenvalues = np.linalg.eigvalsh(gram)
    minimum = float(eigenvalues.min(initial=0.0))
    if minimum < -negative_tolerance:
        return {
            "score": None,
            "reason": "Gram matrix has materially negative eigenvalues",
            "minimum_eigenvalue": minimum,
        }
    eigenvalues = np.clip(eigenvalues, 0.0, None)
    total = float(eigenvalues.sum())
    if total <= 0.0:
        return {"score": None, "reason": "zero-trace Gram matrix"}
    probabilities = eigenvalues / total
    positive = probabilities[probabilities > 0.0]
    score = math.exp(-float(np.sum(positive * np.log(positive))))
    return {"score": score, "reason": None, "minimum_eigenvalue": minimum}


def vendi_score(matrix: Any) -> float | None:
    return compute_vendi_score(matrix)["score"]


def agglomerative_labels(distance: Any, threshold: float) -> np.ndarray:
    matrix = np.asarray(distance, dtype=float)
    n = len(matrix)
    if n == 0:
        return np.array([], dtype=int)
    if n == 1:
        return np.array([0], dtype=int)
    kwargs = {"n_clusters": None, "linkage": "average", "distance_threshold": threshold}
    try:
        model = AgglomerativeClustering(metric="precomputed", **kwargs)
    except TypeError:  # scikit-learn < 1.2
        model = AgglomerativeClustering(affinity="precomputed", **kwargs)
    return model.fit_predict(matrix)


def deterministic_threshold_grid(
    primary_threshold: float, supplied: str | Sequence[float] | None = None
) -> list[float]:
    if supplied is not None:
        values = (
            [float(item.strip()) for item in supplied.split(",") if item.strip()]
            if isinstance(supplied, str)
            else [float(item) for item in supplied]
        )
        if any(value <= 0 for value in values):
            raise ValueError("Thresholds must be positive")
        return values
    offsets = (-0.10, -0.05, -0.025, 0.0, 0.025, 0.05, 0.10)
    return [round(primary_threshold + offset, 10) for offset in offsets if primary_threshold + offset > 0]


def threshold_sensitivity(
    distance: Any, primary_threshold: float, thresholds: Sequence[float]
) -> list[dict[str, Any]]:
    matrix = np.asarray(distance, dtype=float)
    primary = agglomerative_labels(matrix, primary_threshold)
    n = len(matrix)
    rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        labels = agglomerative_labels(matrix, float(threshold))
        stats = cluster_statistics(labels.tolist())
        family_count = stats["raw_family_count"]
        silhouette = None
        if 2 <= family_count < n:
            try:
                silhouette = float(silhouette_score(matrix, labels, metric="precomputed"))
            except ValueError:
                pass
        rows.append(
            {
                "threshold": float(threshold),
                "raw_family_count": family_count,
                "effective_family_count": stats["effective_family_count"],
                "dominant_family_share": stats["dominant_family_share"],
                "singleton_rate": stats["singleton_rate"],
                "silhouette": silhouette,
                "adjusted_rand_vs_primary": float(adjusted_rand_score(primary, labels)),
            }
        )
    return rows


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> dict[str, Any]:
    if total <= 0:
        return {"estimate": None, "lower": None, "upper": None, "n": total}
    if successes < 0 or successes > total:
        raise ValueError("successes must be within [0, total]")
    estimate = successes / total
    denominator = 1.0 + z * z / total
    center = (estimate + z * z / (2.0 * total)) / denominator
    radius = (
        z
        * math.sqrt(estimate * (1.0 - estimate) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return {
        "estimate": estimate,
        "lower": max(0.0, center - radius),
        "upper": min(1.0, center + radius),
        "n": total,
    }


def cosine_distance_matrix(matrix: Any) -> np.ndarray:
    features = np.asarray(matrix, dtype=float)
    if features.ndim != 2:
        raise ValueError("feature matrix must be two-dimensional")
    if features.shape[1] == 0:
        return np.zeros((len(features), len(features)), dtype=float)
    similarity = np.clip(features @ features.T, -1.0, 1.0)
    distance = 1.0 - similarity
    zero_rows = np.linalg.norm(features, axis=1) == 0
    for left in range(len(features)):
        for right in range(len(features)):
            if zero_rows[left] and zero_rows[right]:
                distance[left, right] = 0.0
            elif zero_rows[left] or zero_rows[right]:
                distance[left, right] = 1.0
    np.fill_diagonal(distance, 0.0)
    return np.clip(distance, 0.0, 2.0)


def bootstrap_diversity_ci(
    feature_matrix: Any,
    threshold: float,
    repetitions: int,
    seed: int,
    diversity_k_max: int | None = None,
) -> dict[str, Any]:
    """Bootstrap implementations, then reconstruct every replicate statistic."""
    features = np.asarray(feature_matrix, dtype=float)
    n = len(features)
    metric_names = (
        "effective_family_count",
        "dominant_family_share",
        "mean_pairwise_distance",
        "nauadc_at_kmax",
        "vendi_score",
    )
    if n == 0 or features.ndim != 2 or features.shape[1] == 0 or repetitions <= 0:
        return {name: None for name in metric_names} | {
            "repetitions": repetitions,
            "seed": seed,
            "sampling_unit": "implementation",
        }

    rng = np.random.default_rng(seed)
    values: dict[str, list[float]] = {name: [] for name in metric_names}
    for _ in range(repetitions):
        indices = rng.integers(0, n, size=n)
        sampled = features[indices]
        distance = cosine_distance_matrix(sampled)
        labels = agglomerative_labels(distance, threshold).tolist()
        stats = cluster_statistics(labels)
        values["effective_family_count"].append(stats["effective_family_count"])
        values["dominant_family_share"].append(stats["dominant_family_share"])
        pairwise = distance[np.triu_indices(n, k=1)]
        values["mean_pairwise_distance"].append(float(pairwise.mean()) if len(pairwise) else 0.0)
        if diversity_k_max is not None and diversity_k_max <= n:
            curve = [float(point["da_at_k"]) for point in da_curve(labels)]
            values["nauadc_at_kmax"].append(float(nauadc(curve, diversity_k_max)))
        vendi = vendi_score(sampled)
        if vendi is not None:
            values["vendi_score"].append(vendi)

    result: dict[str, Any] = {
        "repetitions": repetitions,
        "seed": seed,
        "sampling_unit": "implementation",
    }
    for name, samples in values.items():
        result[name] = (
            {
                "lower": float(np.percentile(samples, 2.5)),
                "upper": float(np.percentile(samples, 97.5)),
                "replicates": len(samples),
            }
            if samples
            else None
        )
    return result
