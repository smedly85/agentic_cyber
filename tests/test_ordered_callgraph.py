"""Phase-1 construct checks: tiny syntax fixtures, no compiler/model workloads."""
import builtins
import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import pytest

from scripts.analysis import diversity_validation as parser_utils
from scripts.analysis import ordered_callgraph as oc

FIXTURES = Path(__file__).parent / "fixtures" / "ordered_callgraph"
SCHEMA = json.loads(Path(oc.__file__).with_suffix(".schema.json").read_text())


def extract(name):
    path = FIXTURES / name
    result = oc.analyze_source_bytes(path.read_bytes(), source_file=path.name)
    jsonschema.Draft202012Validator(SCHEMA).validate(result)
    return result


def walk(event):
    yield event
    for child in event["children"]:
        yield from walk(child)


def events(result):
    return [event for f in result["functions"] for event in walk(f["structure"])]


def names(result):
    return [call["callee_name"] for call in result["call_sites"]]


def ancestors(result, call):
    def search(event, path):
        if event["id"] == call["event"]:
            return path
        for child in event["children"]:
            found = search(child, path + [(event["kind"], child["role"])])
            if found is not None:
                return found
        return None
    return next(path for f in result["functions"]
                if (path := search(f["structure"], [])) is not None)


def test_a_identical_structure_and_deterministic_json():
    left = extract("order_forward.c")
    right = extract("order_forward.c")
    assert left["status"] == "success"
    assert oc.normalized_structure(left) == oc.normalized_structure(right)
    assert oc.stable_json(left) == oc.stable_json(right)
    command = [sys.executable, "-m", "scripts.analysis.ordered_callgraph", str(FIXTURES / "order_forward.c")]
    first = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    second = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    assert first == second


def test_b_order_and_actual_existing_count_representation(monkeypatch):
    # Invoke the actual existing count extractor, rather than reconstructing it.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from scripts.analyze_experiment import parse_tree_sitter
    forward = parse_tree_sitter(FIXTURES / "order_forward.c")
    reverse = parse_tree_sitter(FIXTURES / "order_reverse.c")
    assert forward[-1] is reverse[-1] is None
    assert forward[0] == reverse[0]  # all node-kind AND call-count features
    left, right = extract("order_forward.c"), extract("order_reverse.c")
    assert names(left) == ["validate", "transform", "write"]
    assert names(right) == ["write", "transform", "validate"]
    assert oc.normalized_structure(left) != oc.normalized_structure(right)
    body = next(e for e in events(left) if e["kind"] == "compound_statement")
    assert body["ordering"] == "source_statement_sequence"
    assert [e["call_site"] for e in walk(body) if "call_site" in e] == ["c0", "c1", "c2"]


def test_c_repeated_calls_remain_distinct():
    result = extract("repeated.c")
    assert names(result) == ["validate", "validate", "write"]
    assert len({c["id"] for c in result["call_sites"]}) == 3
    assert len({c["event"] for c in result["call_sites"]}) == 3
    assert len(result["direct_edges"]) == 3


def test_d_branch_context():
    left, right = extract("branch_first.c"), extract("branch_second.c")
    assert names(left) == names(right) == ["transform", "write"]
    for result, conditional_name in [(left, "transform"), (right, "write")]:
        for call in result["call_sites"]:
            in_branch = ("if_statement", "consequence") in ancestors(result, call)
            assert in_branch == (call["callee_name"] == conditional_name)
    assert oc.normalized_structure(left) != oc.normalized_structure(right)


def test_e_formatting_and_comments():
    left, right = extract("order_forward.c"), extract("formatted.c")
    assert left["functions"][0]["location"] != right["functions"][0]["location"]
    assert oc.normalized_structure(left) == oc.normalized_structure(right)
    empty = oc.analyze_source_bytes("void f(void) {}")
    comments = oc.analyze_source_bytes("void f ( void ) { /* only a comment */ }")
    assert oc.normalized_structure(empty) == oc.normalized_structure(comments)


def test_f_unsequenced_arguments():
    result = extract("unsequenced.c")
    assert names(result) == ["combine", "first", "second"]  # source traversal only
    outer = next(e for e in events(result) if e.get("call_site") == "c0")
    assert outer["ordering"] == "callee_and_arguments_before_invocation_no_sibling_order"
    arguments = next(c for c in outer["children"] if c["role"] == "arguments")
    assert arguments["ordering"] == "unsequenced_arguments"
    assert [c["call_site"] for c in arguments["children"]] == ["c1", "c2"]


@pytest.mark.parametrize("fixture,status", [("malformed.c", "malformed_input"), ("unsupported.rs", "unsupported_language")])
def test_g_bad_input(fixture, status):
    result = extract(fixture)
    assert result["status"] == status
    assert not result["functions"] and not result["call_sites"]
    with pytest.raises(ValueError):
        oc.normalized_structure(result)


@pytest.mark.parametrize("missing", ["tree_sitter", "tree_sitter_c"])
def test_g_missing_dependencies(monkeypatch, missing):
    monkeypatch.setattr(parser_utils, "_PARSER", None)
    monkeypatch.setattr(parser_utils, "_PARSE_CACHE", {})
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == missing:
            raise ModuleNotFoundError(name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", unavailable)
    result = extract("order_forward.c")
    assert result["status"] == "dependency_unavailable"
    assert not result["functions"]


def test_renaming_fixture_reserved_for_phase_two():
    left, right = extract("renaming_original.c"), extract("renaming_changed.c")
    assert left["direct_edges"][0]["target"] == "f0:helper"
    assert right["direct_edges"][0]["target"] == "f0:renamed"
    assert [f["entry_point"] for f in left["functions"]] == [False, True]
    assert oc.normalized_structure(left) != oc.normalized_structure(right)


def test_nested_control_loops_switch_and_expression_branches():
    result = extract("nested_control.c")
    assert result["status"] == "success"
    rows = events(result)
    policies = {e["kind"]: e["ordering"] for e in rows}
    assert policies["for_statement"] == "initializer_condition_body_update_repeat"
    assert policies["while_statement"] == "condition_body_repeat"
    assert policies["do_statement"] == "body_condition_repeat"
    assert policies["switch_statement"] == "condition_then_label_dispatch"
    assert policies["case_statement"] == "label_with_possible_fallthrough"
    assert policies["conditional_expression"] == "condition_then_exclusive_branch"
    assert policies["binary_expression"] == "left_then_conditional_right"
    transform = next(c for c in result["call_sites"] if c["callee_name"] == "transform")
    context = ancestors(result, transform)
    assert ("for_statement", "body") in context
    assert ("if_statement", "consequence") in context
    assert ("while_statement", "body") in context
    condition_calls = [c for c in result["call_sites"] if ("if_statement", "condition") in ancestors(result, c)]
    assert [c["callee_name"] for c in condition_calls] == ["check", "first"]
    assert any(("if_statement", "alternative") in ancestors(result, c) for c in result["call_sites"])


def test_indirect_external_unknown_no_fabricated_edges():
    result = extract("indirect.c")
    assert [c["resolution"] for c in result["call_sites"]] == [
        "unresolved_indirect", "unresolved_indirect", "unresolved_indirect",
        "external_declared", "unresolved_name",
    ]
    assert result["unresolved_calls"] == ["c0", "c1", "c2", "c4"]
    assert len(result["direct_edges"]) == 1
    assert result["direct_edges"][0]["target"] is None


@pytest.mark.parametrize("source,status", [
    (b"\xff", "invalid_encoding"),
    ("#define GO() f()\nvoid g(void){ GO(); }", "unsupported_input"),
    ("#if FLAG\nvoid f(void){}\n#endif", "unsupported_input"),
    ("void f(void){} void f(void){}", "unsupported_input"),
    ("int f(void); void run(void){sizeof(f());}", "unsupported_input"),
    ("int f(void); int n = sizeof((f()));", "unsupported_input"),
    ("void outer(void) { void inner(void) {} inner(); }", "unsupported_input"),
])
def test_additional_explicit_failure_statuses(source, status):
    result = oc.analyze_source_bytes(source)
    jsonschema.validate(result, SCHEMA)
    assert result["status"] == status


def test_parser_failure(monkeypatch):
    def broken(source):
        raise RuntimeError("unavailable parser ABI")
    monkeypatch.setattr(oc, "parse_source", broken)
    result = extract("order_forward.c")
    assert result["status"] == "parser_failure"


def test_c_expression_policies_and_unevaluated_calls():
    result = oc.analyze_source_bytes("int f(void); int g(void); void run(void) { f()+g(); (f(),g()); sizeof((f())); }")
    assert result["status"] == "success"
    policies = {e["kind"]: e["ordering"] for e in events(result)}
    assert policies["binary_expression"] == "unsequenced_operands"
    assert policies["comma_expression"] == "left_before_right"
    assert policies["sizeof_expression"] == "unevaluated_or_vla_dependent"
    assert len(result["call_sites"]) == 5  # syntactic occurrences, not executed calls


def test_schema_and_referential_integrity_for_all_success_fixtures():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    for path in sorted(FIXTURES.glob("*.c")):
        result = extract(path.name)
        if result["status"] != "success":
            continue
        function_ids = {f["id"] for f in result["functions"]}
        by_event = {e["id"]: e for e in events(result)}
        for call in result["call_sites"]:
            assert call["function"] in function_ids
            assert by_event[call["event"]]["call_site"] == call["id"]
            assert call["target"] is None or call["target"] in function_ids
            location = call["location"]
            assert location["start_byte"] < location["end_byte"]
        assert len(by_event) == len(events(result))


def test_cli_io_failure(tmp_path):
    completed = subprocess.run([sys.executable, "-m", "scripts.analysis.ordered_callgraph", str(tmp_path / "missing.c")], capture_output=True, text=True)
    assert completed.returncode == 1
    result = json.loads(completed.stdout)
    jsonschema.validate(result, SCHEMA)
    assert result["status"] == "io_error"
