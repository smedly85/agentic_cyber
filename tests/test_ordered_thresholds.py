"""Reporting tests only; the established extraction and distance code is unchanged."""
import math

import pytest

from scripts.analysis.ordered_thresholds import GRID, analyze_population, matrices, cluster_scenario
from scripts.ordered_diversity_threshold_study import select_populations


def candidate(name, **kwargs):
    return {"candidate_id": name, "formal_run_id": "run", "utility": "mkdir", "checkpoint_id": "002",
            "candidate_source_sha256": "same-source", "functional_population_status": "public_checkpoint_stage_success", **kwargs}


def pair(left, right, distance, interval=None):
    return {"left": left, "right": right, "comparison": {
        "architecture": {"status": "success", "distance": distance},
        "strategy": {"status": "success", "distance": None, "alignment_range": interval or [distance, distance]}}}


def test_monotonicity_statistics_and_silhouette():
    matrix = [[0, .1, .8, .8], [.1, 0, .8, .8], [.8, .8, 0, .1], [.8, .8, .1, 0]]
    result = cluster_scenario(matrix, ["a", "b", "c", "d"])
    counts = [row["raw_family_count"] for row in result["rows"]]
    assert all(a >= b for a, b in zip(counts, counts[1:]))
    row = result["rows"][1]
    assert row["raw_family_count"] == 2
    assert row["effective_family_count"] == pytest.approx(2)
    assert row["dominant_family_share"] == .5
    assert row["singleton_rate"] == 0
    assert row["changed_candidate_count"] == 4
    assert row["changed_copair_count"] == 2
    assert row["silhouette"] == pytest.approx(.875)
    assert result["rows"][0]["silhouette"] is None
    assert result["rows"][-1]["silhouette"] is None
    assert result["stable_grid_ranges"][1]["first_grid_threshold"] == .1
    assert result["stable_grid_ranges"][1]["last_grid_threshold"] == .75
    assert result["merge_heights"] == pytest.approx([.1, .1, .8])


def test_candidate_indexing_and_deterministic_repeat_with_input_reordering():
    candidates = [candidate("c"), candidate("a"), candidate("b")]
    pairs = [pair("c", "a", .6), pair("b", "a", .2), pair("c", "b", .4)]
    first = analyze_population(candidates, pairs)
    assert first == analyze_population(list(reversed(candidates)), list(reversed(pairs)))
    assert first["matrices"]["candidate_order"] == ["a", "b", "c"]
    assert first["matrices"]["architecture"] == [[0, .2, .6], [.2, 0, .4], [.6, .4, 0]]
    assert first["matrices"]["architecture_summary"]["mean"] == pytest.approx(.4)


def test_incomplete_matrix_is_not_imputed_or_reduced():
    candidates = [candidate(x) for x in "abc"]
    pairs = [pair("a", "b", .2), pair("b", "c", .4)]
    result = analyze_population(candidates, pairs)
    summary = result["matrices"]["architecture_summary"]
    assert summary["estimate_scope"] == "available_pairs_descriptive_only"
    assert summary["available_pairs"] == 2 and summary["total_pairs"] == 3
    assert summary["mean"] == pytest.approx(.3)
    assert result["matrices"]["architecture"][0][2] is None
    assert all(s["status"] == "unavailable" for s in result["scenarios"].values())
    assert len(result["scenarios"]["architecture_exact"]["rows"]) == len(GRID) == 19


def test_certified_bounds_even_singleton_are_not_exact_values():
    p = pair("a", "b", .2)
    p["comparison"]["architecture"] = {"status": "bounded", "distance": None, "bounds": [.2, .2]}
    result = analyze_population([candidate("a"), candidate("b")], [p])
    assert result["matrices"]["architecture_summary"]["available_pairs"] == 0
    assert result["scenarios"]["architecture_exact"]["status"] == "unavailable"
    assert result["scenarios"]["strategy_lower_endpoint"]["status"] == "success"


def test_strategy_intervals_remain_separate_endpoint_scenarios():
    result = analyze_population([candidate("a"), candidate("b")], [pair("a", "b", .2, [.1, .9])])
    summary = result["matrices"]["strategy_summary"]
    assert summary["mean_interval"] == [.1, .9]
    assert summary["alignment_sensitive_pairs"] == 1 and summary["singleton_pairs"] == 0
    assert result["matrices"]["strategy_lower"] == [[0, .1], [.1, 0]]
    assert result["matrices"]["strategy_upper"] == [[0, .9], [.9, 0]]
    at_reference = next(r for r in result["endpoint_sensitivity"] if r["threshold"] == .3)
    assert at_reference == {"threshold": .3, "same_partition": False, "lower_family_count": 1, "upper_family_count": 2}


def test_duplicate_observations_keep_identity_weight_and_zero_identity_diagonal():
    candidates = [candidate(x) for x in "abc"]
    result = analyze_population(candidates, [pair("a", "b", 0, [0, .1]), pair("a", "c", .8), pair("b", "c", .8)])
    assert result["matrices"]["candidate_order"] == ["a", "b", "c"]
    assert all(result["matrices"]["strategy_upper"][i][i] == 0 for i in range(3))
    assert result["matrices"]["strategy_upper"][0][1] == .1
    row = result["scenarios"]["architecture_exact"]["rows"][0]
    assert row["dominant_family_share"] == pytest.approx(2 / 3)
    assert row["singleton_rate"] == pytest.approx(1 / 3)
    assert row["effective_family_count"] == pytest.approx(math.exp(-(2 / 3 * math.log(2 / 3) + 1 / 3 * math.log(1 / 3))))


@pytest.mark.parametrize("field,value", [("formal_run_id", "other"), ("utility", "grep"), ("checkpoint_id", "004")])
def test_no_cross_population_matrices(field, value):
    with pytest.raises(ValueError, match="cross_population"):
        matrices([candidate("a"), candidate("b", **{field: value})], [pair("a", "b", .1)])


def test_pair_identity_checks():
    candidates = [candidate("a"), candidate("b")]
    with pytest.raises(ValueError, match="outside_population"):
        matrices(candidates, [pair("a", "elsewhere", .1)])
    with pytest.raises(ValueError, match="duplicate_pair"):
        matrices(candidates, [pair("a", "b", .1), pair("b", "a", .1)])
    with pytest.raises(ValueError, match="duplicate_candidate_identity"):
        matrices([candidate("a"), candidate("a")], [])
    with pytest.raises(ValueError, match="self_or_duplicate_pair"):
        matrices(candidates, [pair("a", "a", .1)])


def test_manifest_selection_keeps_all_seventeen_and_separates_populations():
    rows = [candidate(f"mkdir{i}") for i in range(7)]
    rows += [candidate(f"grep{i}", utility="grep", checkpoint_id="004", formal_run_id="grep-run") for i in range(10)]
    selected = select_populations({"candidates": rows})
    assert [len(g["manifest_members"]) for g in selected] == [7, 10]
    rows[-1]["formal_run_id"] = "different-run"
    with pytest.raises(ValueError, match="formal_run_mismatch"):
        select_populations({"candidates": rows})


def test_invalid_interval_or_nonfinite_scalar_rejected():
    candidates = [candidate("a"), candidate("b")]
    with pytest.raises(ValueError, match="invalid_strategy_interval"):
        matrices(candidates, [pair("a", "b", .2, [.9, .1])])
    with pytest.raises(ValueError, match="invalid_distance"):
        matrices(candidates, [pair("a", "b", float("nan"))])
