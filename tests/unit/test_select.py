from __future__ import annotations

import pytest

from src.config import load_config
from src.model import CallGraph, CGFunction
from src.select import DepthSelector, order


def fn(name, depth, line=1, entry=False, local=True, file="a.c"):
    return CGFunction(id=f"{file}::{name}", name=name, file=file, def_line=line, depth=depth, is_entry=entry, is_local=local)


GRAPH = CallGraph(
    "test",
    "a.c::main",
    [
        fn("main", 0, 1, entry=True),
        fn("a", 1, 10),
        fn("b", 2, 20),
        fn("c", 3, 30),
        fn("d", 2, 5),
        fn("dead", None, 40),
        fn("libc_thing", 1, local=False),
    ],
    [],
)


def ids(functions):
    return [f.name for f in functions]


def select(**cli):
    cfg = load_config(None, None, {f"depth.{k}": v for k, v in cli.items()}, environ={})
    return ids(DepthSelector().select(GRAPH, cfg))


def test_default_selects_every_eligible_reachable_function_shallow_first():
    assert select() == ["a", "d", "b", "c"]


@pytest.mark.parametrize("rule,expected", [("eq", ["d", "b"]), ("le", ["a", "d", "b"]), ("ge", ["d", "b", "c"])])
def test_depth_rules(rule, expected):
    assert select(depth=2, rule=rule) == expected


def test_unreachable_only_when_included():
    assert "dead" not in select()
    assert select(include_unreachable=True)[-1] == "dead"
    assert "dead" in select(include_unreachable=True, depth=1, rule="eq")


def test_orders():
    assert select(order="deep_first") == ["c", "d", "b", "a"]
    assert select(order="source") == ["d", "a", "b", "c"]
    first = select(order="random", seed=7)
    assert sorted(first) == ["a", "b", "c", "d"] and first == select(order="random", seed=7)


def test_entry_and_external_never_selected():
    chosen = select(include_unreachable=True)
    assert "main" not in chosen and "libc_thing" not in chosen


def test_order_rejects_unknown():
    with pytest.raises(ValueError):
        order([], "sideways", 0)
