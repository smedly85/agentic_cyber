"""Tests of the bounded Phase-2.6 evidence probe, not diversity metrics."""
from pathlib import Path

import pytest

from scripts.ordered_diversity_clang_probe import (
    direct_reference, location_excerpt, main_definitions, recorded_flags,
    summarize_ast, walk,
)


def experiment(flags="-std=c11 -Wall -Wextra -Werror -pedantic -O2"):
    return {"build_command": f"mkdir -p build && cc {flags} src/a.c -o build/a",
            "source_workdir_path": "src/a.c"}


def test_exact_recorded_flags():
    assert recorded_flags(experiment()) == ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2"]


@pytest.mark.parametrize("flags", ["-std=c11", "-std=c11 -Wall -Wextra -Werror -pedantic -O2 -D_DEFAULT_SOURCE"])
def test_no_missing_or_recovery_flags(flags):
    with pytest.raises(ValueError):
        recorded_flags(experiment(flags))


def ref(identifier, name, kind="FunctionDecl"):
    return {"kind": "DeclRefExpr", "referencedDecl": {"id": identifier, "kind": kind, "name": name}}


def test_direct_callee_only():
    call = {"inner": [{"kind": "ImplicitCastExpr", "inner": [ref("f", "f")]}, ref("g", "g")]}
    assert direct_reference(call)["id"] == "f"
    call["inner"][0] = ref("p", "pointer", "VarDecl")
    assert direct_reference(call) is None


def test_source_attribution_uses_filename_not_small_line_number():
    source = Path("/example/main.c")
    def function(identifier, loc):
        return {"id": identifier, "kind": "FunctionDecl", "loc": loc, "inner": [{"kind": "CompoundStmt"}]}
    tree = {"inner": [function("h", {"file": "/include/header.h", "line": 1}),
                      function("a", {"file": str(source), "line": 10}),
                      function("b", {"line": 20})]}
    definitions, _ = main_definitions(tree, source)
    assert [f["id"] for f in definitions] == ["a", "b"]


def test_macro_provenance_keeps_spelling_and_expansion_separate():
    begin = {"spellingLoc": {"file": "/include/stat.h", "offset": 300},
             "expansionLoc": {"offset": 0, "tokLen": 7}}
    result = location_excerpt({"range": {"begin": begin, "end": begin}}, b"S_ISDIR(x)")
    assert result["main_source_expansion_token"] == "S_ISDIR"
    assert result["raw_range"]["begin"] == begin
    assert "main_source_excerpt" not in result


def test_paths_retain_positions_and_control_context():
    tree = {"kind": "IfStmt", "inner": [{"kind": "CallExpr"}, {"kind": "CompoundStmt"}]}
    rows = list(walk(tree))
    assert rows[1][1:] == ((("IfStmt", 0),), ("IfStmt",))
    assert rows[2][1] == (("IfStmt", 1),)


def test_redeclarations_argument_slots_and_indirect_missingness():
    source = Path("/example/main.c")
    tree = {"inner": [
        {"kind": "FunctionDecl", "id": "prototype", "name": "helper", "loc": {"file": str(source)}},
        {"kind": "FunctionDecl", "id": "definition", "previousDecl": "prototype", "name": "helper",
         "inner": [{"kind": "CompoundStmt"}]},
        {"kind": "FunctionDecl", "id": "main", "name": "main", "inner": [{"kind": "CompoundStmt", "inner": [
            {"kind": "CallExpr", "inner": [ref("prototype", "helper"), {"kind": "IntegerLiteral", "value": "1"}, {"kind": "IntegerLiteral", "value": "2"}]},
            {"kind": "CallExpr", "inner": [ref("p", "pointer", "VarDecl")]},
        ]}]},
    ]}
    result = summarize_ast(tree, source, b"")
    assert result["call_resolutions"] == {"internal_direct": 1, "unresolved_indirect": 1}
    assert result["direct_edges"] == [["main", "helper", "internal_direct"]]
    assert [a["argument_slot"] for a in result["calls"][0]["arguments"]] == [0, 1]
    assert result["function_count"] == 2
