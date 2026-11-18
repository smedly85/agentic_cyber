from __future__ import annotations

import pytest

from src.callgraph.common import CallGraphError
from src.callgraph.mir import normalize_mir
from src.callgraph.rupta import normalize_rupta
from src.callgraph.rust_common import strip_trailing_generics
from src.callgraph.svf import normalize_svf


def svf_fn(identity, name, file, line, depth, **extra):
    return {"identity": identity, "name": name, "definition": {"file": file, "line": line}, "raw_call_depth": depth, **extra}


def test_svf_normalization_merges_header_duplicates_with_min_depth():
    graph = {
        "analysis_status": "success",
        "functions": [
            svf_fn("main.c::main", "main", "main.c", 3, 0),
            svf_fn("util.h::helper#llvm=helper", "helper", "util.h", 1, 4),
            svf_fn("util.h::helper#llvm=helper.1", "helper", "util.h", 1, 2, address_taken=True),
        ],
        "call_edges": [{"caller": "main.c::main", "callee": "util.h::helper#llvm=helper.1"}],
    }
    cg = normalize_svf(graph)
    by_id = {f.id: f for f in cg.functions}
    assert by_id["util.h::helper"].depth == 2
    assert by_id["util.h::helper"].attributes["address_taken"] is True
    assert len(by_id["util.h::helper"].instances) == 2
    assert cg.entry == "main.c::main"
    assert cg.edges == [("main.c::main", "util.h::helper")]


def test_svf_failure_is_reported():
    with pytest.raises(CallGraphError):
        normalize_svf({"analysis_status": "analysis_failure", "failures": ["x"], "functions": []})


@pytest.mark.parametrize(
    "name,expected",
    [
        ("apply<Negate>", "apply"),
        ("{impl#0}::transform", "{impl#0}::transform"),
        ("f<Vec<u8>, Option<i32>>", "f"),
        ("a::b", "a::b"),
    ],
)
def test_strip_trailing_generics(name, expected):
    assert strip_trailing_generics(name) == expected


ITEMS = [
    {"key": "::main", "name": "main", "file": "src/main.rs", "line": 30, "parent_kind": "module"},
    {"key": "::apply", "name": "apply", "file": "src/main.rs", "line": 10, "parent_kind": "module"},
    {"key": "::{impl#0}::go", "name": "<A as T>::go", "file": "src/main.rs", "line": 5, "parent_kind": "trait_impl"},
]


def test_rupta_collapses_generic_instances():
    graph = {
        "functions": [
            {"identity": "toy::main", "raw_call_depth": 0},
            {"identity": "toy::apply<A>", "raw_call_depth": 1},
            {"identity": "toy::apply<B>", "raw_call_depth": 3},
            {"identity": "toy::{impl#0}::go", "raw_call_depth": 2},
            {"identity": "core::iter::all<x>", "raw_call_depth": 2},
        ],
        "call_edges": [{"caller": "toy::main", "callee": "toy::apply<A>"}],
    }
    cg = normalize_rupta(graph, ITEMS, "toy")
    by = {f.name: f for f in cg.functions}
    assert by["apply"].depth == 1 and len(by["apply"].instances) == 2
    assert by["<A as T>::go"].depth == 2
    assert by["main"].is_entry
    assert cg.edges == [("src/main.rs::main", "src/main.rs::apply")]


def test_mir_maps_by_span_and_skips_closures_and_foreign_crates():
    def node(ident, line, depth, crate="toy", sid=None):
        return {
            "identity": ident,
            "crate": crate,
            "compiler_generated": False,
            "source_identity": sid or ident,
            "definition": {"source_span": f"/work/project/src/main.rs:{line}:1: {line}:9"},
            "raw_call_depth": depth,
        }

    graph = {
        "functions": [
            node("m", 30, 0),
            node("a1", 10, 2),
            node("a2", 10, 1),
            node("c", 10, 3, sid="x::apply::{closure#0}"),
            node("std", 10, 1, crate="core"),
        ],
        "call_edges": [],
    }
    cg = normalize_mir(graph, ITEMS, "toy")
    by = {f.name: f for f in cg.functions}
    assert by["apply"].depth == 1 and set(by["apply"].instances) == {"a1", "a2"}
    assert by["<A as T>::go"].depth is None
