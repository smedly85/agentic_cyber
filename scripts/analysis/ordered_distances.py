"""Experimental Phase-2 graph and nested-syntax distances. No primary metrics.

Exact bounded comparisons for tiny C construct fixtures. No security imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from importlib.metadata import PackageNotFoundError, version
import itertools
import json
import math
import platform
from pathlib import Path
import re
from typing import Any

from .ordered_callgraph import BACKEND, normalized_structure, stable_json

VERSION = "ordered-diversity-experimental-v2.5"
# Snapshot of the existing configured default; tested against the primary analyzer.
DEFAULT_EXCLUDE = (
    r"^(?:.*(?:parse|parser|argument|arguments|argv|option|options|"
    r"usage|help|flag|error|report|diagnostic).*)$"
)
UNORDERED = {
    "unsequenced_arguments", "unsequenced_operands",
    "indeterminately_sequenced_initializers",
    "callee_and_arguments_before_invocation_no_sibling_order",
}


@dataclass(frozen=True)
class Limits:
    max_alignments: int = 20000
    max_events: int = 2000
    max_work: int = 1000000
    max_unordered_width: int = 10


class Unavailable(ValueError):
    def __init__(self, reason, details=None):
        super().__init__(reason)
        self.details = details


class Budget:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.work = 0

    def tick(self):
        self.work += 1
        if self.work > self.limits.max_work:
            raise Unavailable("comparison_work_limit")


def provenance() -> dict[str, Any]:
    packages = {}
    for name in ("tree-sitter", "tree-sitter-c", "jsonschema"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {
        "representation_version": VERSION, "extractor_schema_version": 1,
        "backend": BACKEND, "python": platform.python_version(), "packages": packages,
        "package_provenance_scope": "Current environment; pilot extracts in-process, imported v1 artifacts have no attested parser version",
        "implementation_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("ordered_callgraph.py", "ordered_callgraph.schema.json", "ordered_distances.py")
        },
        "architecture_method": "exact_partial_injection_graph_atom_difference",
        "strategy_method": "rooted_subtree_edit_ordered_dp_unordered_assignment",
        "normalization": "edit_cost_divided_by_sum_of_representation_sizes",
        "alignment": "entry_anchored_architecture_optima_then_strategy_minimum",
        "identifier_policy": "internal_calls_aligned_ordinary_identifiers_erased_designators_and_literals_retained",
        "scope_policy": "fixed_reference_transfer_unmatched_helpers_unknown",
        "position_policy": "argument_and_initializer_slots_separate_from_evaluation_order",
        "ambiguity_policy": "report_full_range_minimum_exploratory_only",
    }


def _walk(event):
    yield event
    for child in event["children"]:
        yield from _walk(child)


def coverage(result):
    calls = result.get("call_sites", [])
    resolved = sum(c.get("resolution") in {"internal_direct", "external_declared"} for c in calls)
    try:
        event_count = sum(1 for f in result.get("functions", []) for _ in _walk(f["structure"]))
    except (KeyError, TypeError, RecursionError):
        # Coverage must not bypass the fail-closed validator on corrupt artifacts.
        event_count = None
    return {
        "extraction_status": result.get("status", "missing"),
        "function_count": len(result.get("functions", [])), "call_count": len(calls),
        "event_count": event_count,
        "resolved_calls": resolved, "unresolved_calls": len(calls) - resolved,
        "resolution_fraction": resolved / len(calls) if calls else None,
    }


def _validate(result, limits):
    if result.get("status") != "success":
        raise Unavailable("extraction_unavailable:" + str(result.get("status")))
    if result.get("schema_version") != 1 or result.get("backend") != BACKEND:
        raise Unavailable("unsupported_representation")
    if not str(result.get("source_file", "")).lower().endswith(".c"):
        raise Unavailable("unsupported_language")
    # Validate the artifact contract, then cross references; no fabricated defaults.
    import jsonschema
    schema = json.loads(Path(__file__).with_name("ordered_callgraph.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(result)
    functions = {f["id"]: f for f in result["functions"]}
    events = [e for f in functions.values() for e in _walk(f["structure"])]
    if len(events) > limits.max_events:
        raise Unavailable("event_limit")
    event_map = {e["id"]: e for e in events}
    calls = {c["id"]: c for c in result["call_sites"]}
    if len(functions) != len(result["functions"]) or len(event_map) != len(events) or len(calls) != len(result["call_sites"]):
        raise Unavailable("invalid_duplicate_identity")
    if {e.get("call_site") for e in events if "call_site" in e} != set(calls):
        raise Unavailable("invalid_call_event_coverage")
    owners = {e["id"]: f["id"] for f in functions.values() for e in _walk(f["structure"])}
    if any(f["entry_point"] != (f["name"] in result["entry_points"]) for f in functions.values()):
        raise Unavailable("invalid_entry_point_flags")
    for c in calls.values():
        if c["function"] not in functions or event_map.get(c["event"], {}).get("call_site") != c["id"] or owners.get(c["event"]) != c["function"]:
            raise Unavailable("invalid_call_reference")
        if c["resolution"] == "internal_direct" and c["target"] not in functions:
            raise Unavailable("invalid_target_reference")
        if c["resolution"] == "external_declared" and (c["target"] is not None or not c["callee_name"]):
            raise Unavailable("invalid_external_reference")
    expected_edges = [{"caller": c["function"], "target": c["target"], "callee_name": c["callee_name"], "call_site": c["id"]}
                      for c in calls.values() if c["resolution"] in {"internal_direct", "external_declared"}]
    if result["direct_edges"] != expected_edges or set(result["unresolved_calls"]) != {c["id"] for c in calls.values() if c["resolution"].startswith("unresolved")}:
        raise Unavailable("inconsistent_call_inventory")
    if any(c["resolution"].startswith("unresolved") for c in calls.values()):
        raise Unavailable("unresolved_call_targets")


def _atoms(result, labels):
    """Unit node/edge atoms, with no call multiplicity or source coordinates."""
    atoms = {("node", labels[f["id"]]) for f in result["functions"]}
    for c in result["call_sites"]:
        target = labels[c["target"]] if c["target"] else "api:" + c["callee_name"]
        if c["target"] is None:
            atoms.add(("node", target))
        atoms.add(("edge", labels[c["function"]], target))
    return atoms


def _label_maps(left, right, mapping):
    # Candidate IDs only assign temporary symbols. Every injection is considered;
    # their names/order can neither change the minimum nor resolve a scientific tie.
    lm = {f["id"]: "left:" + f["id"] for f in left["functions"]}
    rm = {f["id"]: "right:" + f["id"] for f in right["functions"]}
    for a, b in mapping.items():
        rm[b] = lm[a]
    return lm, rm


def alignment_search_size(left_helpers: int, right_helpers: int) -> int:
    """Exact number of partial injections; diagnostic only, not graph analysis."""
    return sum(math.comb(left_helpers, k) * math.perm(right_helpers, k)
               for k in range(min(left_helpers, right_helpers) + 1))


def _align(left, right, budget):
    lf, rf = left["functions"], right["functions"]
    le = {f["name"]: f["id"] for f in lf if f["entry_point"]}
    re_ = {f["name"]: f["id"] for f in rf if f["entry_point"]}
    anchors = {le[n]: re_[n] for n in le.keys() & re_.keys()}
    lh = [f["id"] for f in lf if not f["entry_point"]]
    rh = [f["id"] for f in rf if not f["entry_point"]]
    count = alignment_search_size(len(lh), len(rh))
    if count > budget.limits.max_alignments:
        raise Unavailable("alignment_search_limit")
    best, optima, denominator = None, [], 0
    for k in range(min(len(lh), len(rh)) + 1):
        for subset in itertools.combinations(lh, k):
            for targets in itertools.permutations(rh, k):
                budget.tick()
                mapping = {**anchors, **dict(zip(subset, targets))}
                lm, rm = _label_maps(left, right, mapping)
                a, b = _atoms(left, lm), _atoms(right, rm)
                cost = len(a ^ b)
                denominator = len(a) + len(b)
                if best is None or cost < best:
                    best, optima = cost, [mapping]
                elif cost == best:
                    optima.append(mapping)
    return best / denominator if denominator else 0.0, optima


def _alignment_diagnostics(left, right, mappings):
    left_options = {
        f["id"]: sorted({m.get(f["id"]) for m in mappings}, key=lambda x: (x is None, x or ""))
        for f in left["functions"]
    }
    right_options = {
        f["id"]: sorted({next((a for a, b in m.items() if b == f["id"]), None) for m in mappings}, key=lambda x: (x is None, x or ""))
        for f in right["functions"]
    }
    return {
        "optimal_mapping_count": len(mappings), "ambiguous": len(mappings) > 1,
        "left_match_options": left_options, "right_match_options": right_options,
        "definitely_removed": [k for k, v in left_options.items() if v == [None]],
        "definitely_added": [k for k, v in right_options.items() if v == [None]],
        "note": "Edit correspondences, not assertions of semantic homology; null means unmatched.",
    }


def _scope(reference, candidate, exclude, forced, budget):
    _, mappings = _align(reference, candidate, budget)
    pattern = re.compile(exclude, re.I)
    reference_scope = {
        f["id"]: f["entry_point"] or f["name"] == "main" or f["name"] in forced or not pattern.search(f["name"])
        for f in reference["functions"]
    }
    decisions, unresolved = {}, {}
    for f in candidate["functions"]:
        if f["entry_point"] or f["name"] == "main":
            decisions[f["id"]] = True
            continue
        possibilities = set()
        for mapping in mappings:
            inverse = {b: a for a, b in mapping.items()}
            # An unmatched helper has no reference-bound classification. Candidate
            # naming cannot fill this gap without breaking rename invariance.
            possibilities.add(bool(reference_scope[inverse[f["id"]]]) if f["id"] in inverse else None)
        if len(possibilities) != 1 or None in possibilities:
            unresolved[f["id"]] = {
                "possibilities": sorted(possibilities, key=lambda p: (p is None, bool(p))),
                "candidate_regex_would_include": not bool(pattern.search(f["name"])),
            }
        else:
            decisions[f["id"]] = possibilities.pop()
    if unresolved:
        reason = "scope_unmatched_functions" if all(v["possibilities"] == [None] for v in unresolved.values()) else "scope_alignment_ambiguous"
        raise Unavailable(reason, {"unresolved_scope": unresolved, "known_scope": decisions})
    return decisions


def _tree(function, calls, labels):
    """Body-only syntax, with explicit unordered groups. Tuples are hashable."""
    def convert(event, slot=None, designator=False):
        kind = event["kind"]
        designator = designator or kind in {"field_designator", "subscript_designator"}
        token = event.get("token", "")
        if kind in {"identifier", "field_identifier", "type_identifier"} and not designator:
            token = "IDENTIFIER"
        call = calls.get(event.get("call_site"))
        call_label = ""
        if call:
            call_label = labels[call["target"]] if call["target"] else "api:" + call["callee_name"]
        label = (kind, event["role"], event["ordering"], event.get("operator", ""), token, call_label, slot)
        children = tuple(
            convert(c, (kind, index) if kind in {"argument_list", "initializer_list"} else None, designator)
            for index, c in enumerate(event["children"])
            if not (call and c["role"] == "function")
        )
        return label, event["ordering"] in UNORDERED, children
    body = next(c for c in function["structure"]["children"] if c["role"] == "body")
    return convert(body)


@lru_cache(maxsize=8192)
def _size(tree):
    return 1 + sum(_size(c) for c in tree[2])


def _tree_distance(left, right, budget):
    @lru_cache(maxsize=None)
    def edit(a, b):
        budget.tick()
        if a == b:
            return 0
        x, y = a[2], b[2]
        if a[1] and b[1]:
            if max(len(x), len(y)) > budget.limits.max_unordered_width:
                raise Unavailable("unordered_group_width_limit")
            @lru_cache(maxsize=None)
            def assign(i, mask):
                budget.tick()
                if i == len(x):
                    return sum(_size(y[j]) for j in range(len(y)) if not mask & (1 << j))
                choices = [_size(x[i]) + assign(i + 1, mask)]
                choices.extend(edit(x[i], y[j]) + assign(i + 1, mask | (1 << j))
                               for j in range(len(y)) if not mask & (1 << j)
                               and x[i][0][-1] == y[j][0][-1])
                return min(choices)
            cost = assign(0, 0)
        else:
            previous = [0]
            for c in y:
                previous.append(previous[-1] + _size(c))
            for ca in x:
                current = [previous[0] + _size(ca)]
                for j, cb in enumerate(y):
                    budget.tick()
                    current.append(min(previous[j + 1] + _size(ca),
                                       current[j] + _size(cb), previous[j] + edit(ca, cb)))
                previous = current
            cost = previous[-1]
        return min(_size(a) + _size(b), int(a[0] != b[0] or a[1] != b[1]) + cost)
    return edit(left, right)


def _strategy(left, right, mappings, ls, rs, budget):
    values = []
    lc = {c["id"]: c for c in left["call_sites"]}
    rc = {c["id"]: c for c in right["call_sites"]}
    for mapping in mappings:
        budget.tick()
        lm, rm = _label_maps(left, right, mapping)
        lt = {f["id"]: _tree(f, lc, lm) for f in left["functions"] if ls[f["id"]]}
        rt = {f["id"]: _tree(f, rc, rm) for f in right["functions"] if rs[f["id"]]}
        total = sum(map(_size, lt.values())) + sum(map(_size, rt.values()))
        paired = {a: b for a, b in mapping.items() if a in lt and b in rt}
        cost = sum(_tree_distance(lt[a], rt[b], budget) for a, b in paired.items())
        cost += sum(_size(t) for a, t in lt.items() if a not in paired)
        cost += sum(_size(t) for b, t in rt.items() if b not in paired.values())
        values.append(cost / total if total else 0.0)
    best = min(values)
    winners = [mapping for mapping, value in zip(mappings, values) if value == best]
    return best, [best, max(values)], winners


def compare(left: dict, right: dict, *, scope_reference: dict | None = None,
            exclude_regex: str = DEFAULT_EXCLUDE, forced_includes=(),
            limits: Limits = Limits()) -> dict[str, Any]:
    """Compare within ONE C utility/checkpoint contract supplied by the caller.

    A fixed scope reference is mandatory for S, optional for A. A search limit is
    unavailable, never a partially optimized or default-zero distance.
    """
    output = {
        "provenance": provenance(), "coverage": {"left": coverage(left), "right": coverage(right)},
        "limits": vars(limits),
        "architecture": {"status": "unavailable", "distance": None},
        "strategy": {"status": "unavailable", "distance": None},
        "alignment": None,
    }
    budget = Budget(limits)
    try:
        _validate(left, limits)
        _validate(right, limits)
        if sorted(left["entry_points"]) != sorted(right["entry_points"]):
            raise Unavailable("entry_point_policy_mismatch")
        distance, mappings = _align(left, right, budget)
        output["architecture"] = {"status": "success", "distance": distance}
        output["alignment"] = _alignment_diagnostics(left, right, mappings)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, Unavailable) else "invalid_input_or_dependency:" + type(exc).__name__
        for metric in ("architecture", "strategy"):
            output[metric]["reason"] = reason
        return output
    try:
        if scope_reference is None:
            raise Unavailable("fixed_scope_reference_required")
        _validate(scope_reference, limits)
        if sorted(scope_reference["entry_points"]) != sorted(left["entry_points"]):
            raise Unavailable("scope_entry_point_policy_mismatch")
        forced = set(forced_includes)
        if forced - {f["name"] for f in scope_reference["functions"]}:
            raise Unavailable("forced_include_missing_from_reference")
        ls = _scope(scope_reference, left, exclude_regex, forced, budget)
        rs = _scope(scope_reference, right, exclude_regex, forced, budget)
        distance, interval, winners = _strategy(left, right, mappings, ls, rs, budget)
        output["strategy"] = {
            "status": "success", "distance": distance, "alignment_range": interval,
            "reporting_status": "alignment_sensitive" if interval[1] > interval[0] else "alignment_invariant",
            "distance_interpretation": "optimistic_minimum_not_formal_primary",
            "primary_eligible": False,
            "scope": {"left": ls, "right": rs, "exclude_regex": exclude_regex,
                      "forced_reference_names": sorted(forced),
                      "reference_sha256": hashlib.sha256(stable_json(normalized_structure(scope_reference)).encode()).hexdigest()},
        }
        output["alignment"]["strategy_minimizers"] = _alignment_diagnostics(left, right, winners)
    except Exception as exc:
        output["strategy"]["reason"] = str(exc) if isinstance(exc, Unavailable) else "comparison_failure:" + type(exc).__name__
        if isinstance(exc, Unavailable) and exc.details:
            output["strategy"]["details"] = exc.details
    output["work_units"] = budget.work
    return output


def reference_sensitivity(left, right, references: dict[str, dict], **kwargs):
    """Audit every specified reference; never select the most favorable result."""
    rows = {name: compare(left, right, scope_reference=ref, **kwargs)
            for name, ref in sorted(references.items())}
    outcomes = {(row["strategy"]["status"], row["strategy"].get("distance"),
                 tuple(row["strategy"].get("alignment_range", [])), row["strategy"].get("reason"))
                for row in rows.values()}
    scopes = {json.dumps({side: row["strategy"].get("scope", {}).get(side) for side in ("left", "right")}, sort_keys=True)
              for row in rows.values()}
    return {"references": rows, "outcome_sensitive": len(outcomes) > 1,
            "membership_sensitive": len(scopes) > 1,
            "policy": "No reference-independent scope inferred; do not pool these alternatives"}
