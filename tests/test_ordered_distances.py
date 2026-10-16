"""Construct sensitivity and explicit missingness, not functional equivalence."""
from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.analysis.ordered_callgraph import analyze_source_bytes
from scripts.analysis.ordered_distances import compare, DEFAULT_EXCLUDE, Limits
from scripts.analysis import ordered_distances
from scripts.ordered_diversity_pilot import run_pilot

FIXTURES = Path(__file__).parent / "fixtures/ordered_callgraph"


@lru_cache(None)
def source(name):
    return analyze_source_bytes((FIXTURES / name).read_bytes(), source_file=name)


def measure(a, b, reference=None, **kwargs):
    return compare(source(a), source(b), scope_reference=source(reference or a), **kwargs)


def distances(result):
    assert result["architecture"]["status"] == "success", result
    assert result["strategy"]["status"] == "success", result
    return result["architecture"]["distance"], result["strategy"]["distance"]


@pytest.mark.parametrize("a,b,a_positive,s_positive", [
    ("order_forward.c", "order_forward.c", False, False),
    ("order_forward.c", "formatted.c", False, False),
    ("renaming_original.c", "renaming_changed.c", False, False),
    ("rename_multi.c", "rename_multi_changed.c", False, False),
    ("order_forward.c", "order_reverse.c", False, True),
    ("branch_first.c", "branch_second.c", False, True),
    ("order_forward.c", "order_decomposed.c", True, True),
    ("order_forward.c", "order_repeated.c", False, True),
    ("unsequenced.c", "unsequenced_reverse.c", False, False),
    ("call_free.c", "call_free_changed.c", False, True),
    ("ambiguous.c", "ambiguous_renamed.c", False, False),
    ("empty.c", "empty.c", False, False),
])
def test_controlled_properties(a, b, a_positive, s_positive):
    result = measure(a, b)
    da, ds = distances(result)
    assert (da > 0) == a_positive
    assert (ds > 0) == s_positive
    assert result == measure(a, b)
    reverse = measure(b, a, reference=a)
    assert (da, ds) == distances(reverse)
    for value in (da, ds):
        assert math.isfinite(value) and 0 <= value <= 1
    assert distances(measure(a, a)) == (0, 0)


def test_match_not_declaration_order_and_scope_rename_transfer():
    result = measure("rename_multi.c", "rename_multi_changed.c")
    opts = result["alignment"]["left_match_options"]
    assert opts["f0:worker"] == ["f1:parser_name"]
    assert opts["f1:parse_args"] == ["f0:ordinary"]
    assert result["strategy"]["scope"]["right"] == {
        "f0:ordinary": False, "f1:parser_name": True, "f2:main": True,
    }


def test_fixed_scope_rename_cannot_change_distance_to_third_candidate():
    reference = source("rename_multi.c")
    changed = analyze_source_bytes((FIXTURES / "rename_multi.c").read_text().replace("{ write(); }", "{ write(); write(); }"))
    original = compare(reference, changed, scope_reference=reference)
    renamed = compare(source("rename_multi_changed.c"), changed, scope_reference=reference)
    assert distances(original) == distances(renamed)
    assert distances(original)[1] > 0


def test_exclusions_and_forced_includes_are_reference_bound():
    reference = source("rename_multi.c")
    changed = analyze_source_bytes((FIXTURES / "rename_multi_changed.c").read_text().replace("{ validate(); }", "{ validate(); validate(); }"))
    assert distances(compare(reference, changed, scope_reference=reference)) == (0, 0)
    forced = compare(reference, changed, scope_reference=reference, forced_includes=["parse_args"])
    assert distances(forced)[1] > 0
    assert forced["strategy"]["scope"]["right"]["f0:ordinary"]
    assert compare(reference, changed, scope_reference=reference, forced_includes=["missing"])["strategy"]["reason"] == "forced_include_missing_from_reference"


def test_default_scope_snapshot_matches_existing_policy(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from scripts.analyze_experiment import DEFAULT_STRATEGY_EXCLUDE_REGEX
    assert DEFAULT_EXCLUDE == DEFAULT_STRATEGY_EXCLUDE_REGEX
    main = source("call_free.c")
    result = compare(main, main, scope_reference=main, exclude_regex=".*")
    assert result["strategy"]["scope"]["left"]["f0:main"]


def test_ambiguity_report_not_hidden_by_tie_breaking():
    result = measure("ambiguous.c", "ambiguous_renamed.c")
    assert result["alignment"]["ambiguous"]
    assert result["alignment"]["optimal_mapping_count"] == 2
    assert result["strategy"]["alignment_range"][0] == 0
    assert result["strategy"]["alignment_range"][1] > 0
    assert result["alignment"]["strategy_minimizers"]["optimal_mapping_count"] == 1


def test_scope_ambiguity_is_unavailable():
    reference = analyze_source_bytes("void parse(void){} void worker(void){} int main(void){parse();worker();}")
    renamed = analyze_source_bytes("void x(void){} void y(void){} int main(void){x();y();}")
    result = compare(reference, renamed, scope_reference=reference)
    assert result["architecture"]["distance"] == 0
    assert result["strategy"]["distance"] is None
    assert result["strategy"]["reason"] == "scope_alignment_ambiguous"


def test_added_removed_and_empty_graphs():
    original = analyze_source_bytes("int main(void){return 0;}")
    extra = analyze_source_bytes("int main(void){return 0;} void extra(void){}")
    result = compare(original, extra, scope_reference=original)
    assert all(v > 0 for v in distances(result))
    assert result["alignment"]["definitely_added"] == ["f1:extra"]
    reverse = compare(extra, original, scope_reference=original)
    assert result["alignment"]["definitely_added"] == reverse["alignment"]["definitely_removed"]
    empty = source("empty.c")
    assert distances(compare(empty, original, scope_reference=original)) == (1, 1)


def test_unmatched_candidates_included_without_name_classification():
    ref = analyze_source_bytes("int main(void){return 0;}")
    a = analyze_source_bytes("int main(void){return 0;} void parse(void){}")
    b = analyze_source_bytes("int main(void){return 0;} void arbitrary(void){}")
    assert distances(compare(ref, a, scope_reference=ref)) == distances(compare(ref, b, scope_reference=ref))
    assert distances(compare(a, b, scope_reference=ref)) == (0, 0)


@pytest.mark.parametrize("name", ["malformed.c", "unsupported.rs", "indirect.c"])
def test_unavailable_not_zero(name):
    result = measure(name, name)
    for metric in ("architecture", "strategy"):
        assert result[metric]["status"] == "unavailable"
        assert result[metric]["distance"] is None
    if name == "indirect.c":
        assert result["architecture"]["reason"] == "unresolved_call_targets"
        assert result["coverage"]["left"]["unresolved_calls"] == 4


def test_missing_reference_only_blocks_strategy():
    result = compare(source("order_forward.c"), source("order_forward.c"))
    assert result["architecture"]["distance"] == 0
    assert result["strategy"]["reason"] == "fixed_scope_reference_required"


@pytest.mark.parametrize("limits,reason", [
    (Limits(max_alignments=1), "alignment_search_limit"),
    (Limits(max_events=1), "event_limit"),
    (Limits(max_work=0), "comparison_work_limit"),
])
def test_bounded_comparison_is_fail_closed(limits, reason):
    result = measure("rename_multi.c", "rename_multi_changed.c", limits=limits)
    assert result["architecture"]["distance"] is None
    assert result["architecture"]["reason"] == reason


def test_unordered_assignment_limit_keeps_architecture_result():
    result = measure("unsequenced.c", "unsequenced_reverse.c", limits=Limits(max_unordered_width=1))
    assert result["architecture"]["distance"] == 0
    assert result["strategy"]["distance"] is None
    assert result["strategy"]["reason"] == "unordered_group_width_limit"


def test_incomplete_or_corrupt_success_artifacts_are_not_empty_graphs():
    good = source("order_forward.c")
    for key in ("functions", "call_sites", "backend"):
        bad = deepcopy(good)
        del bad[key]
        assert compare(bad, good, scope_reference=good)["architecture"]["distance"] is None
    bad = deepcopy(good)
    bad["direct_edges"] = []
    assert compare(bad, good)["architecture"]["reason"] == "inconsistent_call_inventory"


def test_external_api_identity_and_entry_identity():
    a = analyze_source_bytes("void puts(void); int main(void){puts();}")
    b = analyze_source_bytes("void write(void); int main(void){write();}")
    assert all(d > 0 for d in distances(compare(a, b, scope_reference=a)))
    other = analyze_source_bytes("int start(void){return 0;}", entry_points=("start",))
    assert compare(a, other)["architecture"]["reason"] == "entry_point_policy_mismatch"


@pytest.mark.parametrize("left,right", [
    ("int main(void){while(1){break;}}", "int main(void){while(1){continue;}}"),
    ("int main(void){int x=0; return x;}", "int main(void){int x=0; x++; return x;}"),
    ("int main(void){if(1){return 0;}}", "int main(void){while(1){return 0;}}"),
    ("int main(void){goto done;done:return 0;}", "int main(void){return 0;done:return 0;}"),
])
def test_call_free_and_control_transfer_information(left, right):
    a, b = analyze_source_bytes(left), analyze_source_bytes(right)
    da, ds = distances(compare(a, b, scope_reference=a))
    assert da == 0 and ds > 0


def test_literal_operand_roles_not_confused_with_execution_order():
    a = analyze_source_bytes("int main(void){return 1-2;}")
    b = analyze_source_bytes("int main(void){return 2-1;}")
    assert distances(compare(a, b, scope_reference=a))[1] > 0


def test_topology_change_with_same_number_of_functions():
    chain = analyze_source_bytes("void second(void){} void first(void){second();} int main(void){first();}")
    star = analyze_source_bytes("void second(void){} void first(void){} int main(void){first();second();}")
    result = compare(chain, star, scope_reference=chain)
    assert distances(result)[0] > 0
    assert distances(compare(star, chain, scope_reference=chain)) == distances(result)


def test_architecture_triangle_inequality_is_not_claimed():
    prefix = "void a(void); void b(void); int main(void){"
    a, union, b = [analyze_source_bytes(prefix + body + "}") for body in ("a();", "a();b();", "b();")]
    distance = lambda x, y: compare(x, y)["architecture"]["distance"]
    assert distance(a, b) == pytest.approx(2 / 3)
    assert distance(a, union) == distance(union, b) == 0.25
    assert distance(a, b) > distance(a, union) + distance(union, b)


def test_timeout_is_explicit_not_a_zero_distance(monkeypatch):
    def timed_out(*args):
        raise TimeoutError("test comparison interrupted")
    monkeypatch.setattr(ordered_distances, "_tree_distance", timed_out)
    result = measure("order_forward.c", "order_reverse.c")
    assert result["architecture"]["distance"] == 0
    assert result["strategy"]["distance"] is None
    assert result["strategy"]["reason"] == "comparison_failure:TimeoutError"


def test_manifest_rejects_language_pooling(tmp_path):
    manifest = json.loads((FIXTURES / "pilot_manifest.json").read_text())
    manifest["groups"][0]["language"] = "Rust"
    (tmp_path / "pilot_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="only C"):
        run_pilot(tmp_path)


def test_pilot_separate_matrices_missingness_and_determinism():
    pilot = run_pilot()
    assert pilot == run_pilot()
    for group in pilot["groups"]:
        assert group["language"] == "C"
        for key in ("architecture_distances", "strategy_distances", "raw_count_cosine_distances"):
            matrix = group[key]
            for i, row in enumerate(matrix):
                for j, value in enumerate(row):
                    assert value == matrix[j][i]
                    assert value is None or (math.isfinite(value) and 0 <= value <= 1)
    order = pilot["groups"][0]
    assert order["raw_count_cosine_distances"][0][2] == 0
    assert order["strategy_distances"][0][2] > 0
    unresolved = next(g for g in pilot["groups"] if g["utility"] == "synthetic-unresolved")
    assert unresolved["architecture_distances"] == [[None]]
    assert pilot["negative_extractions"]["unsupported.rs"]["extraction_status"] == "unsupported_language"


def test_cli_repeatability_across_processes(tmp_path):
    paths = [tmp_path / "first.json", tmp_path / "second.json"]
    for path in paths:
        subprocess.run([sys.executable, "-m", "scripts.ordered_diversity_pilot", "--output", str(path)], check=True)
    assert paths[0].read_bytes() == paths[1].read_bytes()
    assert json.loads(paths[0].read_text())["provenance"]["representation_version"] == "ordered-diversity-experimental-v2"
