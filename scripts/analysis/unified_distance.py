"""Exact-bounded experimental unified attributed-program-graph distance."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
import platform
import time
from typing import Any

from .unified_graph import SCHEMA_VERSION

ALGORITHM_VERSION = "unified-graph-distance-exact-constrained-search-v1"


@dataclass(frozen=True)
class Limits:
    max_states: int = 2_000_000
    seconds: float = 45.0
    max_nodes: int = 80


class InvalidGraph(ValueError):
    pass


def _validate(graph: dict[str, Any]) -> None:
    if graph.get("status") != "success":
        raise InvalidGraph("representation_unavailable:" + str(graph.get("reason", graph.get("status"))))
    if graph.get("schema_version") != SCHEMA_VERSION or graph.get("backend") != "llvm-ir-cfg-v1":
        raise InvalidGraph("unsupported_representation")
    if graph.get("language") != "c":
        raise InvalidGraph("unsupported_language")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise InvalidGraph("invalid_graph_shape")
    ids = [node.get("id") for node in nodes]
    if len(ids) != len(set(ids)) or any(node.get("kind") not in {"function", "block", "api"} for node in nodes):
        raise InvalidGraph("invalid_nodes")
    known = set(ids)
    for node in nodes:
        if not isinstance(node.get("label"), str) or not isinstance(node.get("content"), list):
            raise InvalidGraph("invalid_node_attributes")
        if node.get("kind") == "block" and node.get("owner") not in known:
            raise InvalidGraph("invalid_block_owner")
    if any(edge.get("source") not in known or edge.get("target") not in known or not isinstance(edge.get("label"), str)
           for edge in edges):
        raise InvalidGraph("invalid_edges")


def _edit_sequence(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + int(a != b)))
        previous = current
    return previous[-1]


def representation_size(graph: dict[str, Any]) -> int:
    return len(graph["nodes"]) + len(graph["edges"]) + sum(len(n["content"]) for n in graph["nodes"])


def _compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["kind"] != right["kind"]:
        return False
    if left["kind"] == "function":
        le, re = left["label"].startswith("function:entry:"), right["label"].startswith("function:entry:")
        return le == re and (not le or left["label"] == right["label"])
    return True


def edit_components(left: dict[str, Any], right: dict[str, Any], mapping: dict[str, str]) -> dict[str, int]:
    ln, rn = {n["id"]: n for n in left["nodes"]}, {n["id"]: n for n in right["nodes"]}
    node_cost = len(ln) + len(rn) - 2 * len(mapping)
    node_cost += sum(ln[a]["label"] != rn[b]["label"] for a, b in mapping.items())
    # Compare local atoms in function order, independently of basic-block
    # alignment.  A parent insertion may split a block; unchanged instructions
    # can therefore remain corresponding while the new blocks/CFG edges still
    # incur their own costs.
    def function_content(nodes: dict[str, dict[str, Any]], owner: str) -> list[str]:
        return [atom for node in sorted(nodes.values(), key=lambda n: (n.get("audit", {}).get("block_index", -1), n["id"]))
                if node["kind"] == "block" and node.get("owner") == owner
                for atom in node["content"]]
    function_mapping = {a: b for a, b in mapping.items() if ln[a]["kind"] == "function"}
    content_cost = sum(_edit_sequence(function_content(ln, a), function_content(rn, b))
                       for a, b in function_mapping.items())
    content_cost += sum(len(function_content(ln, a)) for a, n in ln.items()
                        if n["kind"] == "function" and a not in function_mapping)
    used_functions = set(function_mapping.values())
    content_cost += sum(len(function_content(rn, b)) for b, n in rn.items()
                        if n["kind"] == "function" and b not in used_functions)
    right_edges = Counter((e["source"], e["target"], e["label"]) for e in right["edges"])
    mapped_edges = Counter((mapping[e["source"]], mapping[e["target"]], e["label"])
                           for e in left["edges"] if e["source"] in mapping and e["target"] in mapping)
    common = sum((mapped_edges & right_edges).values())
    edge_cost = len(left["edges"]) + len(right["edges"]) - 2 * common
    return {"node": int(node_cost), "edge": int(edge_cost), "content": int(content_cost)}


def _ordered_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    order = {"function": 0, "api": 1, "block": 2}
    return sorted(graph["nodes"], key=lambda n: (order[n["kind"]], n["id"]))


def _greedy(left: dict[str, Any], right: dict[str, Any]) -> dict[str, str]:
    mapping, used = {}, set()
    right_nodes = _ordered_nodes(right)
    for node in _ordered_nodes(left):
        candidates = [r for r in right_nodes if r["id"] not in used and _compatible(node, r)]
        if node["kind"] == "block":
            owner = mapping.get(node["owner"])
            candidates = [r for r in candidates if r.get("owner") == owner]
        if candidates:
            best = min(candidates, key=lambda r: (node["label"] != r["label"],
                                                   _edit_sequence(node["content"], r["content"]), r["id"]))
            mapping[node["id"]] = best["id"]; used.add(best["id"])
    return mapping


def compare(left: dict[str, Any], right: dict[str, Any], *, limits: Limits = Limits()) -> dict[str, Any]:
    started = time.monotonic()
    output = {"algorithm_version": ALGORITHM_VERSION, "status": "unavailable", "distance": None,
              "normalization": "(|V|+|E|+local_atoms)_left + (same)_right",
              "primitive_costs": {"node_insert": 1, "node_delete": 1, "node_label_substitute": 1,
                                  "directed_labeled_edge_insert": 1, "directed_labeled_edge_delete": 1,
                                  "local_atom_insert": 1, "local_atom_delete": 1, "local_atom_substitute": 1},
              "limits": asdict(limits),
              "provenance": {"python": platform.python_version(), "implementation_sha256": {
                  name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                  for name in ("unified_distance.py", "unified_graph.py", "unified_graph.schema.json")}}}
    try:
        _validate(left); _validate(right)
    except InvalidGraph as exc:
        output["reason"] = str(exc); output["seconds"] = time.monotonic() - started; return output
    if max(len(left["nodes"]), len(right["nodes"])) > limits.max_nodes:
        output.update(status="bounded", bounds=[0.0, 1.0], reason="node_limit_before_search")
        output["seconds"] = time.monotonic() - started
        return output
    denominator = representation_size(left) + representation_size(right)
    if denominator == 0:
        output.update(status="success", distance=0.0, bounds=[0.0, 0.0], cost=0,
                      components={"node": 0, "edge": 0, "content": 0}, mapping={}, exact=True)
        output["seconds"] = time.monotonic() - started
        return output
    lnodes, rnodes = _ordered_nodes(left), _ordered_nodes(right)
    right_by_id = {n["id"]: n for n in rnodes}
    incumbent = _greedy(left, right)
    best_components = edit_components(left, right, incumbent)
    best_cost = sum(best_components.values()); best_mapping = dict(incumbent)
    states, deadline, complete = 0, time.monotonic() + limits.seconds, True

    def search(index: int, mapping: dict[str, str], used: set[str]) -> None:
        nonlocal states, complete, best_cost, best_mapping, best_components
        states += 1
        if states > limits.max_states or time.monotonic() >= deadline:
            complete = False; return
        if index == len(lnodes):
            components = edit_components(left, right, mapping); cost = sum(components.values())
            if cost < best_cost or (cost == best_cost and sorted(mapping.items()) < sorted(best_mapping.items())):
                best_cost, best_mapping, best_components = cost, dict(mapping), components
            return
        node = lnodes[index]
        # An entry function is an anchor and may not be left unmatched.
        required = (node["kind"] == "function" and node["label"].startswith("function:entry:")
                    and any(_compatible(node, candidate) for candidate in rnodes))
        if not required:
            search(index + 1, mapping, used)
            if not complete:
                return
        candidates = [r for r in rnodes if r["id"] not in used and _compatible(node, r)]
        if node["kind"] == "block":
            owner = mapping.get(node["owner"])
            candidates = [r for r in candidates if owner is not None and r.get("owner") == owner]
        candidates.sort(key=lambda r: (node["label"] != r["label"],
                                       _edit_sequence(node["content"], r["content"]), r["id"]))
        for candidate in candidates:
            mapping[node["id"]] = candidate["id"]; used.add(candidate["id"])
            search(index + 1, mapping, used)
            used.remove(candidate["id"]); mapping.pop(node["id"])
            if not complete:
                return

    search(0, {}, set())
    distance = best_cost / denominator
    output.update(cost=best_cost, normalization_value=denominator, components=best_components,
                  mapping=best_mapping, states=states, exact=complete)
    if complete:
        output.update(status="success", distance=distance, bounds=[distance, distance])
    else:
        output.update(status="bounded", distance=None, bounds=[0.0, distance], reason="alignment_limit")
    output["seconds"] = time.monotonic() - started
    return output


def brute_force_reference(left: dict[str, Any], right: dict[str, Any], *, max_states: int = 200_000) -> dict[str, Any]:
    """Independent tiny-graph oracle with a separate exhaustive product recurrence."""
    _validate(left); _validate(right)
    lnodes, rnodes = _ordered_nodes(left), _ordered_nodes(right)
    candidates = [[None, *[r["id"] for r in rnodes if _compatible(node, r)]] for node in lnodes]
    best, best_map, states = None, None, 0
    def visit(i: int, chosen: list[str | None]) -> None:
        nonlocal best, best_map, states
        states += 1
        if states > max_states:
            raise RuntimeError("oracle_state_limit")
        if i == len(lnodes):
            values = [v for v in chosen if v is not None]
            if len(values) != len(set(values)):
                return
            mapping = {lnodes[j]["id"]: v for j, v in enumerate(chosen) if v is not None}
            for j, node in enumerate(lnodes):
                if (node["kind"] == "function" and node["label"].startswith("function:entry:")
                        and any(_compatible(node, candidate) for candidate in rnodes)
                        and node["id"] not in mapping):
                    return
                if node["kind"] == "block" and node["id"] in mapping:
                    if mapping.get(node["owner"]) != right_by[mapping[node["id"]]].get("owner"):
                        return
            cost = sum(edit_components(left, right, mapping).values())
            if best is None or cost < best:
                best, best_map = cost, mapping
            return
        for value in candidates[i]:
            visit(i + 1, [*chosen, value])
    right_by = {n["id"]: n for n in rnodes}
    visit(0, [])
    denominator = representation_size(left) + representation_size(right)
    return {"cost": best, "distance": best / denominator if denominator else 0.0,
            "mapping": best_map, "states": states, "exact": True}

