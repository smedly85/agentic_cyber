"""Phase 2.5 feasibility and known construct limitations; no candidate builds."""
import hashlib
from copy import deepcopy
import math
from pathlib import Path

import pytest

from scripts.analysis.ordered_callgraph import analyze_source_bytes
from scripts.analysis.ordered_distances import (
    _tree, alignment_search_size, compare, reference_sensitivity,
)
from scripts.ordered_diversity_feasibility import audit_group, syntax_census

FIXTURES = Path(__file__).parent / "fixtures/ordered_callgraph"


def fixture(name):
    return analyze_source_bytes((FIXTURES / name).read_bytes(), source_file=name)


def walk(tree):
    yield tree
    for child in tree[2]:
        yield from walk(child)


@pytest.mark.parametrize("left,right,kind", [
    ("unsequenced.c", "unsequenced_reverse.c", "argument_list"),
    ("initializer_slots.c", "initializer_slots_swapped.c", "initializer_list"),
])
def test_data_slots_are_preserved_without_execution_order(left, right, kind):
    a, b = fixture(left), fixture(right)
    result = compare(a, b, scope_reference=a)
    assert result["architecture"]["distance"] == 0
    assert result["strategy"]["distance"] > 0
    assert compare(b, a, scope_reference=a)["strategy"]["distance"] == result["strategy"]["distance"]
    calls = {c["id"]: c for c in a["call_sites"]}
    tree = _tree(a["functions"][0], calls, {})
    group = next(t for t in walk(tree) if t[0][0] == kind and len(t[2]) == 2)
    assert group[1] is True  # No left-before-right evaluation assertion.
    assert [child[0][-1] for child in group[2]] == [(kind, 0), (kind, 1)]
    assert [child[0][5] for child in group[2]] == ["api:first", "api:second"]


def test_initializer_designators_and_nested_slots():
    a = analyze_source_bytes("int main(void) {struct {int x,y;} s={.x=1,.y=2}; return 0;}")
    b = analyze_source_bytes("int main(void) {struct {int x,y;} s={.y=1,.x=2}; return 0;}")
    assert compare(a, b, scope_reference=a)["strategy"]["distance"] > 0
    c = analyze_source_bytes("int main(void){int a[2][2]={{1,2},{3,4}};return 0;}")
    d = analyze_source_bytes("int main(void){int a[2][2]={{2,1},{3,4}};return 0;}")
    assert compare(c, d, scope_reference=c)["strategy"]["distance"] > 0
    e = analyze_source_bytes("int main(void){int a[4]={[1]=2};return 0;}")
    f = analyze_source_bytes("int main(void){int a[4]={[2]=2};return 0;}")
    assert compare(e, f, scope_reference=e)["strategy"]["distance"] > 0


@pytest.mark.parametrize("left,right,detected", [
    ("identifiers.c", "identifiers_changed.c", False),
    ("predicate.c", "predicate_operator.c", True),
    ("predicate.c", "predicate_binding.c", False),
    ("renaming_original.c", "renaming_changed.c", False),
    ("rename_multi.c", "rename_multi_changed.c", False),
    ("control_break.c", "control_continue.c", True),
])
def test_detected_and_missed_constructs_are_explicit(left, right, detected):
    a, b = fixture(left), fixture(right)
    result = compare(a, b, scope_reference=a)
    assert result["architecture"]["distance"] == 0
    assert result["strategy"]["status"] == "success"
    assert (result["strategy"]["distance"] > 0) is detected


def test_header_external_declarations_are_not_invented():
    header, declared = fixture("header_call.c"), fixture("declared_call.c")
    assert header["status"] == declared["status"] == "success"
    assert header["call_sites"][0]["resolution"] == "unresolved_name"
    assert declared["call_sites"][0]["resolution"] == "external_declared"
    assert compare(header, header, scope_reference=header)["architecture"]["distance"] is None
    assert compare(declared, declared, scope_reference=declared)["architecture"]["distance"] == 0


def test_reference_choice_changes_scope_and_measured_strategy():
    a, b = fixture("scope_worker.c"), fixture("scope_worker_changed.c")
    result = reference_sensitivity(a, b, {
        "behavior": a, "parser_name": fixture("scope_parser.c"), "empty": fixture("empty.c"),
    })
    assert result["outcome_sensitive"] and result["membership_sensitive"]
    refs = result["references"]
    assert refs["behavior"]["strategy"]["distance"] > 0
    assert refs["parser_name"]["strategy"]["distance"] == 0
    assert refs["empty"]["strategy"]["distance"] is None
    unknown = refs["empty"]["strategy"]
    assert unknown["reason"] == "scope_unmatched_functions"
    assert unknown["details"]["unresolved_scope"]["f0:worker"]["possibilities"] == [None]


def test_empty_reference_does_not_infer_parser_or_behavior_classification():
    empty = fixture("empty.c")
    for name in ("scope_worker.c", "scope_parser.c"):
        a = fixture(name)
        result = compare(a, a, scope_reference=empty)
        assert result["architecture"]["distance"] == 0
        assert result["strategy"]["reason"] == "scope_unmatched_functions"
        assert result["strategy"]["distance"] is None


def test_conflicting_scope_correspondences_remain_ambiguous():
    a, b = fixture("scope_ambiguous.c"), fixture("scope_ambiguous_renamed.c")
    result = compare(a, b, scope_reference=a)
    assert result["architecture"]["distance"] == 0
    assert result["strategy"]["reason"] == "scope_alignment_ambiguous"
    assert set(result["strategy"]["details"]["unresolved_scope"]["f0:parse_args"]["possibilities"]) == {False, True}


def test_ambiguous_range_cannot_masquerade_as_formal_scalar():
    a, b = fixture("ambiguous.c"), fixture("ambiguous_renamed.c")
    result = compare(a, b, scope_reference=a)
    strategy = result["strategy"]
    assert strategy["alignment_range"][0] == 0 < strategy["alignment_range"][1]
    assert strategy["reporting_status"] == "alignment_sensitive"
    assert strategy["primary_eligible"] is False
    assert strategy["distance_interpretation"] == "optimistic_minimum_not_formal_primary"
    assert compare(b, a, scope_reference=a)["strategy"]["alignment_range"] == strategy["alignment_range"]


def test_partial_injection_capacity_exact_boundary():
    assert alignment_search_size(6, 6) == 13327
    assert alignment_search_size(7, 7) == 130922
    for n in range(8):
        for m in range(8):
            expected = sum(math.comb(n, k) * math.comb(m, k) * math.factorial(k) for k in range(min(n, m) + 1))
            assert alignment_search_size(n, m) == alignment_search_size(m, n) == expected


def test_failed_extraction_census_is_not_recovered_measurement():
    data = b"#define FLAG 1\nint main(void){return FLAG;}"
    extraction = analyze_source_bytes(data)
    census = syntax_census(data)
    assert extraction["status"] == "unsupported_input"
    assert extraction["functions"] == []
    assert census["function_definitions"] == 1
    assert census["named_function_events"] > 0
    assert census["preprocessor_kinds"]["preproc_def"] == 1
    assert "not_a_successful_extraction" in census["purpose"]


def test_feasibility_audit_verifies_membership_hashes_and_missingness(tmp_path):
    good = b'int puts(const char *s);\nint main(void){return puts("ok");}\n'
    blocked = b'#define FLAG 1\nint main(void){return FLAG;}\n'
    members = []
    for index, data in enumerate((good, blocked)):
        name = f"candidate{index}.c"
        (tmp_path / name).write_bytes(data.replace(b"\n", b"\r\n"))
        members.append({"utility": "fixture", "checkpoint_id": "001", "formal_run_id": "fixture-run",
                        "candidate_id": str(index), "functional_population_status": "public_checkpoint_stage_success",
                        "candidate_source": name, "candidate_source_sha256": hashlib.sha256(data).hexdigest()})
    population = {"candidates": members}
    report = audit_group(tmp_path, population, "fixture", "001")
    assert report["summary"]["extraction_statuses"] == {"success": 1, "unsupported_input": 1}
    assert report["summary"]["architecture_available"] == report["summary"]["strategy_available"] == 0
    assert report["candidates"][1]["unresolved_call_count"] is None
    assert report["candidates"][1]["function_count"] is None
    assert report["candidates"][1]["syntax_census"]["function_definitions"] == 1
    assert all(row["source_verification"] == "only_CRLF_to_LF_normalization_matches_manifest" for row in report["candidates"])
    (tmp_path / "candidate0.c").write_bytes(b"int different(void){}")
    with pytest.raises(ValueError, match="hash mismatch"):
        audit_group(tmp_path, population, "fixture", "001")


def test_feasibility_rejects_cross_run_pooling(tmp_path):
    rows = [{"utility": "x", "checkpoint_id": "001", "candidate_id": str(i), "formal_run_id": str(i)} for i in range(2)]
    with pytest.raises(ValueError, match="Different formal runs"):
        audit_group(tmp_path, {"candidates": rows}, "x", "001")


def test_coverage_does_not_turn_corrupt_structure_into_empty_success():
    good = fixture("declared_call.c")
    broken = deepcopy(good)
    del broken["functions"][0]["structure"]
    result = compare(broken, good, scope_reference=good)
    assert result["coverage"]["left"]["event_count"] is None
    assert result["architecture"]["distance"] is None
    assert result["strategy"]["distance"] is None
