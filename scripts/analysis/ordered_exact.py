"""Bounded MILP optimization of the existing node/edge discrepancy objective.

The exhaustive matcher remains the oracle. This changes optimization only.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time

from . import ordered_distances as old
from .clang_ordered import validate, comparison_tree


@dataclass(frozen=True)
class ExactLimits:
    alignment_seconds: float = 45
    max_optima: int = 128
    strategy_seconds: float = 45
    max_work: int = 2000000
    max_events: int = 10000
    max_unordered_width: int = 10
    max_model_variables: int = 100000


class TimedBudget(old.Budget):
    def __init__(self, limits):
        super().__init__(old.Limits(max_work=limits.max_work, max_unordered_width=limits.max_unordered_width))
        self.deadline = time.monotonic() + limits.strategy_seconds

    def tick(self):
        super().tick()
        if time.monotonic() >= self.deadline:
            raise old.Unavailable("strategy_time_limit")


def scope(result, exclude, forced):
    pattern = re.compile(exclude, re.I)
    return {f["id"]: f["name"] == "main" or f["name"] in forced or not pattern.search(f["name"])
            for f in result["functions"]}


class Model:
    def __init__(self, left, right, max_variables=100000):
        import numpy as np
        self.np = np
        self.left, self.right = left, right
        if len(left["functions"]) * len(right["functions"]) > max_variables:
            raise old.Unavailable("alignment_model_size_limit")
        self.pairs = [(a["id"], b["id"]) for a in left["functions"] for b in right["functions"]
                      if (not a["entry_point"] and not b["entry_point"]) or (a["entry_point"] and b["entry_point"] and a["name"] == b["name"])]
        self.x = {pair: i for i, pair in enumerate(self.pairs)}
        self.weights = [1.] * len(self.pairs)
        self.rows, self.lower, self.upper = [], [], []
        self.lb = [0.] * len(self.pairs)
        self.ub = [1.] * len(self.pairs)
        for a in left["functions"]:
            self.add({i: 1 for (u, v), i in self.x.items() if u == a["id"]}, 0, 1)
            if a["entry_point"]:
                for (u, v), i in self.x.items():
                    if u == a["id"]:
                        self.lb[i] = 1
        for b in right["functions"]:
            self.add({i: 1 for (u, v), i in self.x.items() if v == b["id"]}, 0, 1)
        def edges(result):
            internal, external = set(), {}
            for c in result["call_sites"]:
                if c["target"]:
                    internal.add((c["function"], c["target"]))
                else:
                    external.setdefault(c["function"], set()).add(c["callee_name"])
            return internal, external
        li, le = edges(left)
        ri, re_ = edges(right)
        if len(self.weights) + len(li) * len(ri) > max_variables:
            raise old.Unavailable("alignment_model_size_limit")
        for (a, b), i in self.x.items():
            self.weights[i] += len(le.get(a, set()) & re_.get(b, set()))
        for a, c in sorted(li):
            for b, d in sorted(ri):
                if (a, b) not in self.x or (c, d) not in self.x:
                    continue
                i, j = self.x[a, b], self.x[c, d]
                if i == j:
                    self.weights[i] += 1
                    continue
                y = len(self.weights)
                self.weights.append(1.)
                self.lb.append(0.)
                self.ub.append(1.)
                self.add({y: 1, i: -1}, -math.inf, 0)
                self.add({y: 1, j: -1}, -math.inf, 0)
        la, ra = {c["callee_name"] for c in left["call_sites"] if not c["target"]}, {c["callee_name"] for c in right["call_sites"] if not c["target"]}
        self.constant = len(la & ra)
        lm, rm = old._label_maps(left, right, {})
        self.denominator = len(old._atoms(left, lm)) + len(old._atoms(right, rm))

    def add(self, row, lower, upper):
        self.rows.append(row)
        self.lower.append(lower)
        self.upper.append(upper)

    def solve(self, seconds):
        from scipy.optimize import milp, Bounds, LinearConstraint
        from scipy.sparse import lil_matrix
        if seconds <= 0:
            raise old.Unavailable("alignment_time_limit")
        matrix = lil_matrix((len(self.rows), len(self.weights)))
        for i, row in enumerate(self.rows):
            for j, value in row.items():
                matrix[i, j] = value
        return milp(-self.np.array(self.weights), integrality=self.np.ones(len(self.weights)),
                    bounds=Bounds(self.lb, self.ub),
                    constraints=LinearConstraint(matrix.tocsr(), self.lower, self.upper),
                    options={"time_limit": seconds, "mip_rel_gap": 0.0, "presolve": True})

    def mapping(self, solution):
        mapping = {a: b for (a, b), i in self.x.items() if solution.x[i] > .5}
        lm, rm = old._label_maps(self.left, self.right, mapping)
        shared = len(old._atoms(self.left, lm) & old._atoms(self.right, rm))
        return mapping, shared

    def exclude_mapping(self, mapping):
        chosen = {self.x[a, b] for a, b in mapping.items()}
        self.add({i: 1 if i in chosen else -1 for i in range(len(self.pairs))}, -math.inf, len(chosen) - 1)


def architecture(left, right, ls, rs, limits):
    start = time.monotonic()
    deadline = start + limits.alignment_seconds
    model = Model(left, right, limits.max_model_variables)
    # Empty atom sets are valid degenerate structures, without invoking a zero-variable MILP.
    if not model.weights:
        distance, mappings = old._align(left, right, old.Budget(old.Limits()))
        return {"status": "success", "distance": distance, "enumeration_complete": True,
                "incompatible_optimum_exists": False, "seconds": time.monotonic() - start}, mappings
    solution = model.solve(deadline - time.monotonic())
    if solution.x is None:
        # Without a feasible incumbent, do not invent a completed alignment.
        bound = getattr(solution, "mip_dual_bound", None)
        interval = None
        if bound is not None and math.isfinite(bound) and model.denominator:
            interval = [max(0., min(1., (model.denominator - 2 * (model.constant - bound)) / model.denominator)), 1.]
        return {"status": "bounded" if interval else "unavailable", "distance": None,
                "bounds": interval, "reason": "no_alignment_incumbent", "solver_message": solution.message}, []
    mapping, shared = model.mapping(solution)
    upper = (model.denominator - 2 * shared) / model.denominator if model.denominator else 0.
    bound = getattr(solution, "mip_dual_bound", None)
    lower = max(0., (model.denominator - 2 * (model.constant - bound)) / model.denominator) if bound is not None and math.isfinite(bound) and model.denominator else 0.
    if solution.status != 0:
        return {"status": "bounded", "distance": None, "bounds": [min(lower, upper), upper],
                "reason": "alignment_optimization_budget", "solver_message": solution.message}, []
    optimum = shared - model.constant
    if abs(-solution.fun - optimum) > 1e-6:
        raise old.Unavailable("solver_integer_objective_verification_failed")
    # Fix the original optimum, then enumerate only scope-compatible optima.
    model.add(dict(enumerate(model.weights)), optimum, optimum)
    incompatible = {i: 1 for (a, b), i in model.x.items() if ls[a] != rs[b]}
    incompatible_exists = False
    if incompatible:
        model.add(incompatible, 1, math.inf)
        if time.monotonic() < deadline:
            check = model.solve(deadline - time.monotonic())
            incompatible_exists = True if check.x is not None else False if check.status == 2 else None
        else:
            incompatible_exists = None
        model.rows.pop(); model.lower.pop(); model.upper.pop()
        for i in incompatible:
            model.ub[i] = 0
    mappings = []
    complete, reason = False, None
    while len(mappings) < limits.max_optima:
        if time.monotonic() >= deadline:
            reason = "optimal_alignment_enumeration_time_limit"
            break
        solution = model.solve(deadline - time.monotonic())
        if solution.status == 2:
            complete = True
            break
        if solution.status != 0 or solution.x is None:
            reason = "optimal_alignment_enumeration_solver_limit"
            break
        mapping, actual = model.mapping(solution)
        if actual != shared:
            raise old.Unavailable("optimal_alignment_verification_failed")
        mappings.append(mapping)
        model.exclude_mapping(mapping)
    if not complete and reason is None:
        reason = "optimal_alignment_count_limit"
    return {"status": "success", "distance": upper, "bounds": [upper, upper],
            "atom_discrepancy": model.denominator - 2 * shared, "atom_size_sum": model.denominator,
            "enumeration_complete": complete, "enumeration_reason": reason,
            "admissible_optima_found": len(mappings), "incompatible_optimum_exists": incompatible_exists,
            "seconds": time.monotonic() - start}, mappings


def compare(left, right, *, limits=ExactLimits(), exclude_regex=old.DEFAULT_EXCLUDE, forced_includes=()):
    start = time.monotonic()
    out = {"method": "existing_graph_atom_discrepancy_and_rooted_subtree_edit", "limits": vars(limits),
           "normalization": "unit edit cost / sum of representation sizes; no feature weights",
           "optimizer": "SciPy HiGHS MILP, mip_rel_gap=0; integer objective rechecked against graph atoms",
           "architecture": {"status": "unavailable", "distance": None},
           "strategy": {"status": "unavailable", "distance": None}}
    try:
        validate(left, limits.max_events); validate(right, limits.max_events)
        ls, rs = scope(left, exclude_regex, forced_includes), scope(right, exclude_regex, forced_includes)
        out["scope"] = {"left": ls, "right": rs, "exclude_regex": exclude_regex, "forced_includes": list(forced_includes),
                        "policy": "independent_candidate_names_main_and_forced_included; exclusion-boundary rename sensitivity"}
        out["architecture"], mappings = architecture(left, right, ls, rs, limits)
        if out["architecture"]["status"] != "success":
            raise old.Unavailable("architecture_not_certified_exact")
        if not out["architecture"]["enumeration_complete"]:
            raise old.Unavailable("architecture_optima_not_exhausted:" + out["architecture"]["enumeration_reason"])
        if not mappings:
            raise old.Unavailable("no_scope_compatible_architecture_optimum")
        out["alignment"] = old._alignment_diagnostics(left, right, mappings)
        out["alignment"]["population"] = "all scope-compatible architecture-optimal mappings; incompatible optima flagged separately"
        budget = TimedBudget(limits)
        lc, rc = ({c["id"]: c for c in r["call_sites"]} for r in (left, right))
        strategy_start = time.monotonic()
        values, evaluated = [], []
        for mapping in mappings:
            budget.tick()
            lm, rm = old._label_maps(left, right, mapping)
            lt = {f["id"]: comparison_tree(f, lc, lm) for f in left["functions"] if ls[f["id"]]}
            rt = {f["id"]: comparison_tree(f, rc, rm) for f in right["functions"] if rs[f["id"]]}
            denominator = sum(old._size(t) for t in lt.values()) + sum(old._size(t) for t in rt.values())
            paired = {a: b for a, b in mapping.items() if a in lt and b in rt}
            cost = sum(old._tree_distance(lt[a], rt[b], budget) for a, b in paired.items())
            cost += sum(old._size(t) for a, t in lt.items() if a not in paired)
            cost += sum(old._size(t) for b, t in rt.items() if b not in paired.values())
            values.append(cost / denominator if denominator else 0.)
            evaluated.append({"mapping": mapping, "subtree_edit_cost": cost, "tree_size_sum": denominator,
                              "strategy_distance": values[-1]})
        interval = [min(values), max(values)]
        out["strategy"] = {"status": "success", "distance": interval[0] if interval[0] == interval[1] else None,
                           "alignment_range": interval, "primary_eligible": False,
                           "reporting": "alignment_sensitive_range" if interval[0] != interval[1] else "alignment_invariant",
                           "work_units": budget.work, "seconds": time.monotonic() - strategy_start,
                           "evaluated_alignments": evaluated}
    except (old.Unavailable, ImportError) as exc:
        out["strategy"]["reason"] = str(exc)
        if out["architecture"]["status"] == "unavailable":
            out["architecture"]["reason"] = str(exc)
    out["seconds"] = time.monotonic() - start
    return out
