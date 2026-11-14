"""Experimental node-splicing Strategy comparator over accepted A optima.

This module is separate from the accepted rooted-subtree Strategy result.  It
reuses the Clang comparison trees, scope, Architecture objective, and complete
A-optimal function-alignment policy without modifying historical outputs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import time
from typing import Any

from . import ordered_distances as old
from .clang_ordered import comparison_tree, validate
from .ordered_exact import architecture as milp_architecture, scope

ALGORITHM_VERSION = "strategy-node-splicing-constrained-unordered-v2"


@dataclass(frozen=True)
class NodeLimits:
    alignment_seconds: float = 45
    max_optima: int = 128
    strategy_seconds: float = 45
    max_work: int = 2_000_000
    max_events: int = 10_000
    max_unordered_width: int = 10
    max_model_variables: int = 100_000
    max_exhaustive_alignments: int = 20_000
    max_diagnostic_operations: int = 5_000


class NodeBudget:
    def __init__(self, limits: NodeLimits):
        self.limits = limits
        self.work = 0
        self.deadline = time.monotonic() + limits.strategy_seconds

    def tick(self) -> None:
        self.work += 1
        if self.work > self.limits.max_work:
            raise old.Unavailable("strategy_node_work_limit")
        if time.monotonic() >= self.deadline:
            raise old.Unavailable("strategy_node_time_limit")


def _label(tree) -> Any:
    return tree[0]


def _unordered(tree) -> bool:
    return bool(tree[1])


def _children(tree):
    return tree[2]


def _slot_compatible(left, right) -> bool:
    return _label(left)[-1] == _label(right)[-1]


def _unordered_compatible(left, right) -> bool:
    # The accepted recurrence permits root substitution whenever both roots
    # carry unordered-child semantics.  Preserve that policy exactly; slot
    # constraints below still govern child pairing.
    return _unordered(left) and _unordered(right)


def _without_frontier_slot(tree):
    current = _label(tree)
    return (current[:-1] + (None,), _unordered(tree), _children(tree))


def node_tree_edit(left, right, budget: NodeBudget) -> dict[str, Any]:
    """Exact ordered node edit with constrained exact unordered frontiers.

    Ordinary node insertion/deletion costs one and splices children into the
    parent's ordered forest.  When two explicit unordered containers align,
    their immediate child trees use exact assignment subject to the existing
    slot labels. A unary unordered container may be inserted or deleted for unit
    cost because splicing its only child cannot reorder siblings; the child's
    container-local slot is removed with that frontier. Other unmatched
    unordered-rooted subtrees cost their full tree because splicing a multi-child
    argument/initializer/evaluation frontier would change the accepted role
    semantics. This is an exact result for that documented frontier-preserving
    edit model, not unrestricted unordered tree edit distance.
    """
    choices: dict[tuple[tuple, tuple], tuple[str, Any]] = {}
    assignments: dict[tuple[tuple, tuple], tuple[tuple[int | None, int | None], ...]] = {}
    infinity = 10 ** 12

    @lru_cache(maxsize=None)
    def unordered_cost(left_children: tuple, right_children: tuple) -> int:
        budget.tick()
        if max(len(left_children), len(right_children)) > budget.limits.max_unordered_width:
            raise old.Unavailable("strategy_node_unordered_group_width_limit")
        assignment_choice: dict[tuple[int, int], tuple[str, int | None]] = {}
        @lru_cache(maxsize=None)
        def assign(index: int, mask: int) -> int:
            budget.tick()
            if index == len(left_children):
                return sum(old._size(right_children[j]) for j in range(len(right_children))
                           if not mask & (1 << j))
            candidates = [(old._size(left_children[index]) + assign(index + 1, mask), 1, "delete", None)]
            for j, child in enumerate(right_children):
                if not mask & (1 << j) and _slot_compatible(left_children[index], child):
                    candidates.append((forest((_without_frontier_slot(left_children[index]),),
                                              (_without_frontier_slot(child),))
                                       + assign(index + 1, mask | (1 << j)), 0, "match", j))
            cost, _, action, target = min(candidates, key=lambda item: (item[0], item[1], item[3] or -1))
            assignment_choice[(index, mask)] = (action, target)
            return cost
        cost = assign(0, 0)
        pairs, index, mask = [], 0, 0
        while index < len(left_children):
            action, target = assignment_choice[(index, mask)]
            if action == "match":
                pairs.append((index, target)); mask |= 1 << target
            else:
                pairs.append((index, None))
            index += 1
        pairs.extend((None, j) for j in range(len(right_children)) if not mask & (1 << j))
        assignments[(left_children, right_children)] = tuple(pairs)
        return cost

    @lru_cache(maxsize=None)
    def forest(left_forest: tuple, right_forest: tuple) -> int:
        budget.tick()
        if not left_forest:
            cost = sum(old._size(tree) for tree in right_forest)
            choices[(left_forest, right_forest)] = ("insert_forest", None)
            return cost
        if not right_forest:
            cost = sum(old._size(tree) for tree in left_forest)
            choices[(left_forest, right_forest)] = ("delete_forest", None)
            return cost
        a, b = left_forest[0], right_forest[0]
        rest_a, rest_b = left_forest[1:], right_forest[1:]
        candidates = []
        if not _unordered(a):
            candidates.append((1 + forest(_children(a) + rest_a, right_forest), 1, "delete"))
        else:
            candidates.append((old._size(a) + forest(rest_a, right_forest), 3, "delete_unordered"))
            if len(_children(a)) == 1:
                candidates.append((1 + forest((_without_frontier_slot(_children(a)[0]),) + rest_a,
                                               right_forest), 1, "delete_unary_unordered"))
        if not _unordered(b):
            candidates.append((1 + forest(left_forest, _children(b) + rest_b), 2, "insert"))
        else:
            candidates.append((old._size(b) + forest(left_forest, rest_b), 4, "insert_unordered"))
            if len(_children(b)) == 1:
                candidates.append((1 + forest(left_forest,
                                               (_without_frontier_slot(_children(b)[0]),) + rest_b),
                                   2, "insert_unary_unordered"))
        if _unordered(a) == _unordered(b):
            if _unordered(a):
                if _unordered_compatible(a, b):
                    candidates.append((int(_label(a) != _label(b))
                                       + unordered_cost(_children(a), _children(b))
                                       + forest(rest_a, rest_b), 0, "unordered_match"))
            else:
                candidates.append((int(_label(a) != _label(b))
                                   + forest(_children(a), _children(b))
                                   + forest(rest_a, rest_b), 0, "match"))
        if not candidates:
            choices[(left_forest, right_forest)] = ("unsupported", None)
            return infinity
        cost, _, action = min(candidates, key=lambda item: (item[0], item[1]))
        choices[(left_forest, right_forest)] = (action, None)
        return cost

    cost = forest((left,), (right,))
    if cost >= infinity:
        raise old.Unavailable("strategy_node_unordered_container_mismatch")

    operations: list[dict[str, Any]] = []
    def whole(tree, status: str) -> None:
        operations.append({"status": status, "label": _label(tree)})
        for child in _children(tree):
            whole(child, status)
    def trace(left_forest: tuple, right_forest: tuple) -> None:
        if not left_forest:
            for tree in right_forest: whole(tree, "inserted")
            return
        if not right_forest:
            for tree in left_forest: whole(tree, "deleted")
            return
        action, _ = choices[(left_forest, right_forest)]
        a, b = left_forest[0], right_forest[0]
        rest_a, rest_b = left_forest[1:], right_forest[1:]
        if action == "delete":
            operations.append({"status": "deleted", "label": _label(a)})
            trace(_children(a) + rest_a, right_forest)
        elif action == "insert":
            operations.append({"status": "inserted", "label": _label(b)})
            trace(left_forest, _children(b) + rest_b)
        elif action == "delete_unordered":
            whole(a, "deleted"); trace(rest_a, right_forest)
        elif action == "insert_unordered":
            whole(b, "inserted"); trace(left_forest, rest_b)
        elif action == "delete_unary_unordered":
            operations.append({"status": "deleted", "label": _label(a),
                               "unary_unordered_splice": True})
            trace((_without_frontier_slot(_children(a)[0]),) + rest_a, right_forest)
        elif action == "insert_unary_unordered":
            operations.append({"status": "inserted", "label": _label(b),
                               "unary_unordered_splice": True})
            trace(left_forest, (_without_frontier_slot(_children(b)[0]),) + rest_b)
        elif action == "match":
            operations.append({"status": "retained" if _label(a) == _label(b) else "substituted",
                               "left_label": _label(a), "right_label": _label(b)})
            trace(_children(a), _children(b)); trace(rest_a, rest_b)
        elif action == "unordered_match":
            operations.append({"status": "retained" if _label(a) == _label(b) else "substituted",
                               "left_label": _label(a), "right_label": _label(b),
                               "unordered_frontier": True})
            for i, j in assignments[(_children(a), _children(b))]:
                if i is None: whole(_children(b)[j], "inserted")
                elif j is None: whole(_children(a)[i], "deleted")
                else: trace((_without_frontier_slot(_children(a)[i]),),
                            (_without_frontier_slot(_children(b)[j]),))
            trace(rest_a, rest_b)
        else:
            raise old.Unavailable("strategy_node_trace_unavailable")
    trace((left,), (right,))
    return {"cost": cost, "operations": operations}


def _architecture(left, right, left_scope, right_scope, limits: NodeLimits):
    left_helpers = sum(not function["entry_point"] for function in left["functions"])
    right_helpers = sum(not function["entry_point"] for function in right["functions"])
    search_size = old.alignment_search_size(left_helpers, right_helpers)
    if search_size <= limits.max_exhaustive_alignments:
        budget = old.Budget(old.Limits(max_alignments=limits.max_exhaustive_alignments,
                                      max_work=max(limits.max_work, search_size + 1)))
        distance, all_optima = old._align(left, right, budget)
        compatible = [mapping for mapping in all_optima
                      if all(left_scope[a] == right_scope[b] for a, b in mapping.items())]
        witness = all_optima[0]
        left_labels, right_labels = old._label_maps(left, right, witness)
        left_atoms, right_atoms = old._atoms(left, left_labels), old._atoms(right, right_labels)
        return ({"status": "success", "distance": distance, "bounds": [distance, distance],
                 "atom_discrepancy": len(left_atoms ^ right_atoms),
                 "atom_size_sum": len(left_atoms) + len(right_atoms),
                 "enumeration_complete": True, "admissible_optima_found": len(compatible),
                 "incompatible_optimum_exists": len(compatible) != len(all_optima),
                 "optimizer": "existing_exhaustive_architecture_oracle",
                 "search_size": search_size}, compatible)
    return milp_architecture(left, right, left_scope, right_scope, limits)


def _strategy_from_mappings(left, right, mappings, left_scope, right_scope,
                            limits: NodeLimits) -> dict[str, Any]:
    calls_left = {call["id"]: call for call in left["call_sites"]}
    calls_right = {call["id"]: call for call in right["call_sites"]}
    budget = NodeBudget(limits)
    evaluated, values = [], []
    for mapping in mappings:
        left_labels, right_labels = old._label_maps(left, right, mapping)
        left_trees = {f["id"]: comparison_tree(f, calls_left, left_labels)
                      for f in left["functions"] if left_scope[f["id"]]}
        right_trees = {f["id"]: comparison_tree(f, calls_right, right_labels)
                       for f in right["functions"] if right_scope[f["id"]]}
        denominator = (sum(old._size(tree) for tree in left_trees.values())
                       + sum(old._size(tree) for tree in right_trees.values()))
        paired = {a: b for a, b in mapping.items() if a in left_trees and b in right_trees}
        cost, function_edits = 0, []
        for a, b in sorted(paired.items()):
            edit = node_tree_edit(left_trees[a], right_trees[b], budget)
            cost += edit["cost"]
            operations = edit["operations"]
            function_edits.append({"left": a, "right": b, "cost": edit["cost"],
                "operation_count": len(operations),
                "operations": operations[:limits.max_diagnostic_operations],
                "operations_complete": len(operations) <= limits.max_diagnostic_operations})
        for a, tree in left_trees.items():
            if a not in paired:
                size = old._size(tree); cost += size
                function_edits.append({"left": a, "right": None, "cost": size, "unmatched_tree": True})
        used = set(paired.values())
        for b, tree in right_trees.items():
            if b not in used:
                size = old._size(tree); cost += size
                function_edits.append({"left": None, "right": b, "cost": size, "unmatched_tree": True})
        value = cost / denominator if denominator else 0.0
        values.append(value)
        evaluated.append({"mapping": mapping, "node_edit_cost": cost,
                          "tree_size_sum": denominator, "strategy_node_distance": value,
                          "function_edits": function_edits})
    interval = [min(values), max(values)]
    return {"status": "success",
        "distance": interval[0] if interval[0] == interval[1] else None,
        "alignment_range": interval,
        "reporting": "alignment_invariant" if interval[0] == interval[1] else "alignment_sensitive_range",
        "exact": True, "work_units": budget.work, "evaluated_alignments": evaluated,
        "unordered_policy": "exact slot-constrained assignment at compatible unordered frontiers; unary unordered containers may splice their sole child; unmatched multi-child unordered subtrees cost full size"}


def evaluate_architecture_mappings(left, right, mappings, left_scope, right_scope,
                                   *, limits: NodeLimits = NodeLimits()) -> dict[str, Any]:
    """Evaluate S_node over a caller-verified complete A-optimal mapping set.

    This entry point deliberately does not certify Architecture optimality. It is
    for provenance-checked historical artifacts that already contain the exact,
    complete A-optimal mappings and scope decisions.
    """
    started = time.monotonic()
    output = {"method": ALGORITHM_VERSION, "limits": asdict(limits),
              "mapping_source": "caller-verified complete Architecture-optimal artifact",
              "strategy_node": {"status": "unavailable", "distance": None},
              "normalization": "unit node edit cost / sum of selected comparison-tree node counts"}
    try:
        validate(left, limits.max_events); validate(right, limits.max_events)
        left_functions = {function["id"]: function for function in left["functions"]}
        right_functions = {function["id"]: function for function in right["functions"]}
        if set(left_scope) != set(left_functions) or set(right_scope) != set(right_functions):
            raise old.Unavailable("strategy_node_invalid_saved_scope")
        mappings = [dict(mapping) for mapping in mappings]
        if not mappings:
            raise old.Unavailable("strategy_node_missing_saved_alignments")
        signatures = set()
        for mapping in mappings:
            if (not set(mapping) <= set(left_functions) or not set(mapping.values()) <= set(right_functions)
                    or len(set(mapping.values())) != len(mapping)):
                raise old.Unavailable("strategy_node_invalid_saved_alignment")
            for a, b in mapping.items():
                lf, rf = left_functions[a], right_functions[b]
                if (lf["entry_point"] != rf["entry_point"]
                        or (lf["entry_point"] and lf["name"] != rf["name"])
                        or bool(left_scope[a]) != bool(right_scope[b])):
                    raise old.Unavailable("strategy_node_incompatible_saved_alignment")
            signature = tuple(sorted(mapping.items()))
            if signature in signatures:
                raise old.Unavailable("strategy_node_duplicate_saved_alignment")
            signatures.add(signature)
        output["scope"] = {"left": left_scope, "right": right_scope}
        output["alignment"] = old._alignment_diagnostics(left, right, mappings)
        output["alignment"]["population"] = "caller-verified complete scope-compatible Architecture-optimal mappings"
        output["strategy_node"] = _strategy_from_mappings(
            left, right, mappings, left_scope, right_scope, limits)
    except (old.Unavailable, ImportError) as exc:
        output["strategy_node"]["reason"] = str(exc)
    output["seconds"] = time.monotonic() - started
    return output


def compare(left, right, *, limits: NodeLimits = NodeLimits(),
            exclude_regex: str = old.DEFAULT_EXCLUDE, forced_includes=()) -> dict[str, Any]:
    started = time.monotonic()
    output = {"method": ALGORITHM_VERSION, "limits": asdict(limits),
              "architecture": {"status": "unavailable", "distance": None},
              "strategy_node": {"status": "unavailable", "distance": None},
              "normalization": "unit node edit cost / sum of selected comparison-tree node counts"}
    try:
        validate(left, limits.max_events); validate(right, limits.max_events)
        left_scope, right_scope = scope(left, exclude_regex, forced_includes), scope(right, exclude_regex, forced_includes)
        output["scope"] = {"left": left_scope, "right": right_scope, "exclude_regex": exclude_regex,
                           "forced_includes": list(forced_includes),
                           "policy": "unchanged independent candidate scope from ordered_exact"}
        output["architecture"], mappings = _architecture(left, right, left_scope, right_scope, limits)
        if output["architecture"]["status"] != "success":
            raise old.Unavailable("architecture_not_certified_exact")
        if not output["architecture"].get("enumeration_complete"):
            raise old.Unavailable("architecture_optima_not_exhausted")
        if not mappings:
            raise old.Unavailable("no_scope_compatible_architecture_optimum")
        output["alignment"] = old._alignment_diagnostics(left, right, mappings)
        output["alignment"]["population"] = "all scope-compatible Architecture-optimal mappings"
        output["strategy_node"] = _strategy_from_mappings(
            left, right, mappings, left_scope, right_scope, limits)
    except (old.Unavailable, ImportError) as exc:
        output["strategy_node"]["reason"] = str(exc)
        if output["architecture"]["status"] == "unavailable":
            output["architecture"]["reason"] = str(exc)
    output["seconds"] = time.monotonic() - started
    return output

