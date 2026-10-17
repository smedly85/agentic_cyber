"""Compiler-to-existing-objective integration and exact-optimizer oracle tests."""
import json
from pathlib import Path
import random
import shutil
import subprocess

import pytest

from scripts.analysis.clang_ordered import adapt, BACKEND, comparison_tree
from scripts.analysis.ordered_exact import compare, architecture, ExactLimits
from scripts.analysis import ordered_distances as old


@pytest.fixture
def extract(tmp_path):
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("Clang unavailable")
    def run(body):
        source = tmp_path / "candidate.c"
        source.write_text(body)
        process = subprocess.run([clang, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2",
                                  "-D_POSIX_C_SOURCE=200809L", "-fsyntax-only", "-Xclang", "-ast-dump=json", str(source)], capture_output=True, text=True)
        result = adapt(process.stdout, process.returncode, source)
        assert result["status"] == "success", process.stderr
        return result
    return run


PREFIX = "void a(void); void b(void); int first(void); int second(void); void combine(int,int);\n"


@pytest.mark.parametrize("first,second,a_zero,s_zero", [
    ("a(); b();", "a(); b();", True, True),
    ("a(); b();", "b(); a();", True, False),
    ("a(); b();", "a(); a(); b();", True, False),
    ("if(first()) {a();} b();", "a(); if(first()) {b();}", True, False),
    ("combine(first(),second());", "combine(second(),first());", True, False),
    ("int x=1; int y=2; combine(x+x,y);", "int renamed=1; int other=2; combine(renamed+renamed,other);", True, True),
    ("int x=1; int y=2; combine(x+x,y);", "int x=1; int y=2; combine(x+y,y);", True, False),
])
def test_compiler_to_distances(extract, first, second, a_zero, s_zero):
    left = extract(PREFIX + "int main(void){" + first + "return 0;}")
    right = extract(PREFIX + "int main(void){" + second + "return 0;}")
    result = compare(left, right)
    assert result["architecture"]["status"] == "success"
    assert (result["architecture"]["distance"] == 0) == a_zero
    assert result["strategy"]["status"] == "success", result
    assert (result["strategy"]["alignment_range"][0] == 0) == s_zero
    reverse = compare(right, left)
    assert reverse["architecture"]["distance"] == result["architecture"]["distance"]
    assert reverse["strategy"]["alignment_range"] == result["strategy"]["alignment_range"]


def test_helper_rename_and_exhaustive_subtree_oracle(extract):
    left = extract("void a(void); void worker(void){a();} int main(void){worker();return 0;}")
    right = extract("void a(void); void renamed(void){a();} int main(void){renamed();return 0;}")
    result = compare(left, right)
    budget = old.Budget(old.Limits())
    distance, mappings = old._align(left, right, budget)
    ls, rs = ({f["id"]: True for f in r["functions"]} for r in (left, right))
    _, interval, _ = old._strategy(left, right, mappings, ls, rs, budget)
    assert result["architecture"]["distance"] == distance == 0
    assert result["strategy"]["alignment_range"] == interval == [0, 0]


def test_decomposition(extract):
    left = extract("void a(void); int main(void){a();return 0;}")
    right = extract("void a(void); void worker(void){a();} int main(void){worker();return 0;}")
    result = compare(left, right)
    assert result["architecture"]["distance"] > 0
    assert result["strategy"]["status"] == "success"


def test_scope_boundary_and_forced_include(extract):
    left = extract("void work(void){} int main(void){work();return 0;}")
    right = extract("void parse(void){} int main(void){parse();return 0;}")
    result = compare(left, right)
    assert result["architecture"]["distance"] == 0
    assert result["architecture"]["incompatible_optimum_exists"] is True
    assert result["strategy"]["reason"] == "no_scope_compatible_architecture_optimum"
    assert compare(left, right, forced_includes=("parse",))["strategy"]["alignment_range"] == [0, 0]


def test_implicit_nodes_and_unordered_argument_slots(extract):
    result = extract(PREFIX + "int main(void){int x=1; combine(x,second());return 0;}")
    tree = comparison_tree(result["functions"][0], {c["id"]: c for c in result["call_sites"]}, {"f0": "main"})
    def descendants(t):
        yield t
        for child in t[2]:
            yield from descendants(child)
    nodes = list(descendants(tree))
    assert any(n[0][0] == "ImplicitCastExpr" for n in nodes)
    group = next(n for n in nodes if n[0][0] == "argument_list" and len(n[2]) == 2)
    assert group[1] is True
    assert [n[0][-1] for n in group[2]] == [("argument_list", 0), ("argument_list", 1)]


def test_missingness_and_budgets(extract):
    good = extract("int main(void){return 0;}")
    failed = adapt('{"kind":"TranslationUnitDecl"}', 1, Path("bad.c"))
    assert compare(failed, good)["architecture"]["distance"] is None
    result = compare(good, good, limits=ExactLimits(max_optima=0))
    assert result["architecture"]["distance"] == 0
    assert result["strategy"]["distance"] is None
    assert "optima_not_exhausted" in result["strategy"]["reason"]
    result = compare(good, good, limits=ExactLimits(alignment_seconds=0))
    assert result["architecture"]["status"] == "unavailable"
    result = compare(good, good, limits=ExactLimits(max_model_variables=0))
    assert result["architecture"]["reason"] == "alignment_model_size_limit"
    indirect = extract("int main(void){int (*p)(void)=0;return p();}")
    assert compare(indirect, indirect)["architecture"]["reason"] == "unresolved_call_targets"
    result = compare(good, good, limits=ExactLimits(max_work=0))
    assert result["architecture"]["distance"] == 0
    assert result["strategy"]["reason"] == "comparison_work_limit"


def test_callback_reference_rename_without_fabricated_call_edge(extract):
    left = extract("void api(int (*p)(void)); int worker(void){return 1;} int main(void){api(worker);return 0;}")
    right = extract("void api(int (*p)(void)); int renamed(void){return 1;} int main(void){api(renamed);return 0;}")
    assert len(left["call_sites"]) == 1
    assert compare(left, right)["strategy"]["alignment_range"] == [0, 0]


def test_alignment_ambiguity_range_is_not_optimistic_scalar(extract):
    left = extract("void a(void);void b(void);void one(void){a();b();}void two(void){b();a();}int main(void){one();two();return 0;}")
    result = compare(left, left)
    assert result["architecture"]["distance"] == 0
    assert result["alignment"]["ambiguous"]
    assert result["strategy"]["alignment_range"][0] == 0
    assert result["strategy"]["alignment_range"][1] > 0
    assert result["strategy"]["distance"] is None


def test_bounded_milp_keeps_certified_interval(monkeypatch):
    from types import SimpleNamespace
    from scripts.analysis.ordered_exact import Model
    left = {"functions": [{"id": "0", "name": "main", "entry_point": True}], "call_sites": []}
    monkeypatch.setattr(Model, "solve", lambda self, seconds: SimpleNamespace(
        x=[1.], status=1, mip_dual_bound=-1., message="time limit", fun=-1.))
    actual, mappings = architecture(left, left, {"0": True}, {"0": True}, ExactLimits())
    assert actual["status"] == "bounded"
    assert actual["distance"] is None
    assert actual["bounds"] == [0, 0]
    assert mappings == []


def test_non_inner_initializer_expressions_cannot_be_silently_lost():
    source = Path("/example/main.c")
    ast = {"kind": "TranslationUnitDecl", "inner": [{"kind": "FunctionDecl", "id": "f", "name": "main",
        "loc": {"file": str(source)}, "inner": [{"kind": "CompoundStmt", "inner": [
            {"kind": "InitListExpr", "array_filler": [{"kind": "CallExpr"}]}]}]}]}
    result = adapt(json.dumps(ast), 0, source)
    assert result["status"] == "unsupported_clang_form"
    assert result["functions"] == []
    assert compare(result, result)["strategy"]["distance"] is None


def graph(rng, size):
    functions = [{"id": str(i), "name": "main" if i == 0 else "helper" + str(i), "entry_point": i == 0} for i in range(size)]
    calls = []
    for a in range(size):
        for b in range(size + 1):
            if rng.random() < .4:
                calls.append({"function": str(a), "target": str(b) if b < size else None, "callee_name": "api" if b == size else "helper"})
    return {"functions": functions, "call_sites": calls}


@pytest.mark.parametrize("seed", range(8))
def test_milp_same_exact_objective_and_all_optima_as_exhaustive(seed):
    rng = random.Random(seed)
    left, right = graph(rng, 3), graph(rng, 3)
    expected, mappings = old._align(left, right, old.Budget(old.Limits()))
    ls, rs = ({f["id"]: True for f in r["functions"]} for r in (left, right))
    actual, found = architecture(left, right, ls, rs, ExactLimits())
    assert actual["distance"] == expected
    assert actual["enumeration_complete"]
    assert {tuple(sorted(m.items())) for m in found} == {tuple(sorted(m.items())) for m in mappings}
