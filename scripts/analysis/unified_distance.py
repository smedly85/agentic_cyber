"""Exact-bounded experimental unified attributed-program-graph distance."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
import platform
import time
from typing import Any

from .unified_graph import BACKEND, SCHEMA_VERSION

ALGORITHM_VERSION = "unified-graph-distance-exact-constrained-search-v2"
CFG_EDGE_LABELS = {"cfg:unconditional", "cfg:true", "cfg:false", "cfg:default",
                   "cfg:normal", "cfg:exception", "cfg:indirect"}


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
    if graph.get("schema_version") != SCHEMA_VERSION or graph.get("backend") != BACKEND:
        raise InvalidGraph("unsupported_representation")
    if graph.get("language") != "c":
        raise InvalidGraph("unsupported_language")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise InvalidGraph("invalid_graph_shape")
    ids = [node.get("id") for node in nodes]
    if (len(ids) != len(set(ids))
            or any(not isinstance(identifier, str) or not identifier for identifier in ids)
            or any(node.get("kind") not in {"function", "block", "api"} for node in nodes)):
        raise InvalidGraph("invalid_nodes")
    known = set(ids)
    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        if (not isinstance(node.get("label"), str) or not isinstance(node.get("content"), list)
                or not all(isinstance(atom, str) for atom in node.get("content", []))):
            raise InvalidGraph("invalid_node_attributes")
        kind, label = node["kind"], node["label"]
        if kind == "block":
            if node.get("owner") not in known or by_id[node["owner"]].get("kind") != "function":
                raise InvalidGraph("invalid_block_owner")
            if not label.startswith("block:"):
                raise InvalidGraph("invalid_block_label")
        elif node.get("owner") is not None:
            raise InvalidGraph("invalid_nonblock_owner")
        elif kind == "api" and (not label.startswith("api:") or len(label) == 4):
            raise InvalidGraph("invalid_api_identity")
        elif kind == "function" and not (label == "function:helper" or label.startswith("function:entry:")):
            raise InvalidGraph("invalid_function_label")
    edge_ids = [edge.get("id") for edge in edges]
    if len(edge_ids) != len(set(edge_ids)):
        raise InvalidGraph("invalid_duplicate_edge_identity")
    for edge in edges:
        source, target, label = edge.get("source"), edge.get("target"), edge.get("label")
        if source not in known or target not in known or not isinstance(label, str):
            raise InvalidGraph("invalid_edges")
        sk, tk = by_id[source]["kind"], by_id[target]["kind"]
        if label in {"contains", "entry"}:
            if sk != "function" or tk != "block" or by_id[target].get("owner") != source:
                raise InvalidGraph("invalid_ownership_edge")
        elif label in CFG_EDGE_LABELS or (label.startswith("cfg:case:") and len(label) > len("cfg:case:")):
            if sk != "block" or tk != "block" or by_id[source].get("owner") != by_id[target].get("owner"):
                raise InvalidGraph("invalid_cfg_edge")
        elif label.startswith("cfg:"):
            raise InvalidGraph("unsupported_cfg_edge_label:" + label)
        elif label == "call":
            if sk != "block" or tk not in {"function", "api"}:
                raise InvalidGraph("invalid_call_edge")
        else:
            raise InvalidGraph("unsupported_edge_label:" + label)
    for function in (node for node in nodes if node["kind"] == "function"):
        owned = [node["id"] for node in nodes if node.get("owner") == function["id"]]
        entries = [edge for edge in edges if edge["source"] == function["id"] and edge["label"] == "entry"]
        contains_edges = [edge for edge in edges
                          if edge["source"] == function["id"] and edge["label"] == "contains"]
        contains = {edge["target"] for edge in contains_edges}
        if (not owned or len(entries) != 1 or len(contains_edges) != len(owned)
                or contains != set(owned) or entries[0]["target"] not in contains):
            raise InvalidGraph("invalid_function_block_inventory")


def _edit_sequence(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + int(a != b)))
        previous = current
    return previous[-1]


def _function_atom_records(graph: dict[str, Any], owner: str) -> list[dict[str, Any]]:
    """Canonical CFG traversal, independent of textual LLVM block order."""
    nodes = {node["id"]: node for node in graph["nodes"]}
    blocks = {identifier for identifier, node in nodes.items()
              if node["kind"] == "block" and node.get("owner") == owner}
    entry = next(edge["target"] for edge in graph["edges"]
                 if edge["source"] == owner and edge["label"] == "entry")
    adjacency: dict[str, list[tuple[str, str]]] = {identifier: [] for identifier in blocks}
    for edge in graph["edges"]:
        if edge["source"] in blocks and edge["target"] in blocks and edge["label"].startswith("cfg:"):
            adjacency[edge["source"]].append((edge["label"], edge["target"]))
    order, seen = [], set()
    def visit(identifier: str) -> None:
        if identifier in seen:
            return
        seen.add(identifier); order.append(identifier)
        edge_rank = {"cfg:true": 0, "cfg:unconditional": 1, "cfg:normal": 1,
                     "cfg:false": 2, "cfg:exception": 3, "cfg:default": 4}
        choices = sorted(adjacency[identifier],
                         key=lambda item: (edge_rank.get(item[0], 3 if item[0].startswith("cfg:case:") else 9),
                                           item[0], nodes[item[1]]["label"],
                                           tuple(nodes[item[1]]["content"]), item[1]))
        for _, target in choices:
            visit(target)
    visit(entry)
    unreachable = sorted(blocks - seen, key=lambda identifier: (
        nodes[identifier]["label"], tuple(nodes[identifier]["content"]),
        sorted(label for label, _ in adjacency[identifier]), identifier))
    for identifier in unreachable:
        visit(identifier)
    return [{"block": identifier, "index": index, "atom": atom}
            for identifier in order for index, atom in enumerate(nodes[identifier]["content"])]


def _sequence_correspondence(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    rows, columns = len(left), len(right)
    dp = [[0] * (columns + 1) for _ in range(rows + 1)]
    for i in range(rows + 1): dp[i][0] = i
    for j in range(columns + 1): dp[0][j] = j
    for i in range(1, rows + 1):
        for j in range(1, columns + 1):
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1,
                           dp[i - 1][j - 1] + int(left[i - 1]["atom"] != right[j - 1]["atom"]))
    operations, i, j = [], rows, columns
    while i or j:
        if i and j and dp[i][j] == dp[i - 1][j - 1] + int(left[i - 1]["atom"] != right[j - 1]["atom"]):
            status = "retained" if left[i - 1]["atom"] == right[j - 1]["atom"] else "substituted"
            operations.append({"status": status, "left": left[i - 1], "right": right[j - 1]})
            i -= 1; j -= 1
        elif i and dp[i][j] == dp[i - 1][j] + 1:
            operations.append({"status": "deleted", "left": left[i - 1], "right": None}); i -= 1
        else:
            operations.append({"status": "inserted", "left": None, "right": right[j - 1]}); j -= 1
    operations.reverse()
    return dp[rows][columns], operations


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
    def function_content(graph: dict[str, Any], owner: str) -> list[str]:
        return [record["atom"] for record in _function_atom_records(graph, owner)]
    function_mapping = {a: b for a, b in mapping.items() if ln[a]["kind"] == "function"}
    content_cost = sum(_edit_sequence(function_content(left, a), function_content(right, b))
                       for a, b in function_mapping.items())
    content_cost += sum(len(function_content(left, a)) for a, n in ln.items()
                        if n["kind"] == "function" and a not in function_mapping)
    used_functions = set(function_mapping.values())
    content_cost += sum(len(function_content(right, b)) for b, n in rn.items()
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


def correspondence_diagnostics(left: dict[str, Any], right: dict[str, Any],
                               mapping: dict[str, str]) -> dict[str, Any]:
    ln, rn = {n["id"]: n for n in left["nodes"]}, {n["id"]: n for n in right["nodes"]}
    used = set(mapping.values())
    matched_nodes = [{"left": a, "right": b, "left_label": ln[a]["label"],
                      "right_label": rn[b]["label"],
                      "status": "retained" if ln[a]["label"] == rn[b]["label"] else "substituted"}
                     for a, b in sorted(mapping.items())]
    function_scripts = []
    for a, b in sorted(mapping.items()):
        if ln[a]["kind"] != "function":
            continue
        cost, operations = _sequence_correspondence(_function_atom_records(left, a),
                                                    _function_atom_records(right, b))
        function_scripts.append({"left_function": a, "right_function": b, "cost": cost,
                                 "operations": operations})
    for a, node in sorted(ln.items()):
        if node["kind"] == "function" and a not in mapping:
            function_scripts.append({"left_function": a, "right_function": None,
                "cost": len(_function_atom_records(left, a)),
                "operations": [{"status": "deleted", "left": record, "right": None}
                               for record in _function_atom_records(left, a)]})
    for b, node in sorted(rn.items()):
        if node["kind"] == "function" and b not in used:
            function_scripts.append({"left_function": None, "right_function": b,
                "cost": len(_function_atom_records(right, b)),
                "operations": [{"status": "inserted", "left": None, "right": record}
                               for record in _function_atom_records(right, b)]})
    right_edges = Counter((e["source"], e["target"], e["label"]) for e in right["edges"])
    mapped_left = Counter((mapping[e["source"]], mapping[e["target"]], e["label"])
                          for e in left["edges"] if e["source"] in mapping and e["target"] in mapping)
    retained = mapped_left & right_edges
    def expand(counter: Counter) -> list[dict[str, Any]]:
        return [{"source": key[0], "target": key[1], "label": key[2], "count": count}
                for key, count in sorted(counter.items()) if count]
    left_original = Counter((e["source"], e["target"], e["label"]) for e in left["edges"])
    mapped_retained_left = Counter()
    remaining = Counter(retained)
    for edge in left["edges"]:
        if edge["source"] in mapping and edge["target"] in mapping:
            key = (mapping[edge["source"]], mapping[edge["target"]], edge["label"])
            if remaining[key]:
                mapped_retained_left[(edge["source"], edge["target"], edge["label"])] += 1
                remaining[key] -= 1
    return {
        "interpretation": "Optimal structural edit correspondence; not semantic equivalence or data-flow proof.",
        "nodes": {"matched": matched_nodes,
                  "deleted": [identifier for identifier in sorted(ln) if identifier not in mapping],
                  "inserted": [identifier for identifier in sorted(rn) if identifier not in used]},
        "edges": {"retained_after_relabeling": expand(retained),
                  "deleted": expand(left_original - mapped_retained_left),
                  "inserted": expand(right_edges - retained)},
        "local_content": function_scripts,
    }


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
                  mapping=best_mapping, correspondence=correspondence_diagnostics(left, right, best_mapping),
                  states=states, exact=complete)
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

