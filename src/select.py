"""Function selection: eligibility, depth rule, ordering."""

from __future__ import annotations

import random
from typing import Any, Mapping

from src.model import CallGraph, CGFunction


def eligible(fn: CGFunction, include_unreachable: bool) -> bool:
    if fn.is_entry or not fn.is_local:
        return False
    if fn.depth is None:
        return include_unreachable
    return fn.depth >= 1


def matches_depth(fn: CGFunction, depth: int | None, rule: str) -> bool:
    if depth is None:
        return True  # default: every eligible function
    if fn.depth is None:
        return True  # unreachable functions only appear when explicitly included
    return {"eq": fn.depth == depth, "le": fn.depth <= depth, "ge": fn.depth >= depth}[rule]


def _depth_key(fn: CGFunction) -> float:
    return float("inf") if fn.depth is None else fn.depth


def order(functions: list[CGFunction], how: str, seed: int) -> list[CGFunction]:
    by_source = sorted(functions, key=lambda f: (f.file or "", f.def_line or 0, f.id))
    if how == "source":
        return by_source
    if how == "shallow_first":
        return sorted(by_source, key=_depth_key)
    if how == "deep_first":
        return sorted(by_source, key=lambda f: -_depth_key(f) if f.depth is not None else float("-inf"))
    if how == "random":
        shuffled = list(by_source)
        random.Random(seed).shuffle(shuffled)
        return shuffled
    raise ValueError(f"unknown order {how!r}")


class DepthSelector:
    def select(self, graph: CallGraph, config: Mapping[str, Any]) -> list[CGFunction]:
        depth_cfg = config["depth"]
        chosen = [
            fn
            for fn in graph.functions
            if eligible(fn, depth_cfg["include_unreachable"]) and matches_depth(fn, depth_cfg["depth"], depth_cfg["rule"])
        ]
        return order(chosen, depth_cfg["order"], depth_cfg["seed"])
