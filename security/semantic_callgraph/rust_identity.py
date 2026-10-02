"""Debug-backed Rust identities and explicit entry provenance; no call extraction."""
from __future__ import annotations
from collections import defaultdict, deque
import re


def strip_generic_arguments(name: str) -> str:
    """Remove balanced generic argument groups, never split at the first '<'.

    Impl/type identity is retained in the debug scope chain and declaration line.
    Malformed/unbalanced debug names are not silently normalized.
    """
    output = []
    depth = 0
    for index, char in enumerate(name):
        if char == "<":
            depth += 1
        elif char == ">" and depth and (index == 0 or name[index - 1] != "-"):
            depth -= 1
        elif depth == 0:
            output.append(char)
    if depth:
        raise ValueError("unbalanced Rust generic debug name")
    return "".join(output)


def source_key(row):
    scope = row.get("debug_scope_chain")
    file = row.get("source_file")
    line = row.get("definition", {}).get("line")
    if row.get("language") != "Rust" or not scope or not file or not line or not row.get("source_mapping_eligible"):
        raise ValueError("source_identity_ambiguous: incomplete Rust debug provenance")
    normalized_scope = tuple(strip_generic_arguments(part) for part in scope)
    return (normalized_scope[0], file, normalized_scope, line, strip_generic_arguments(row["name"]))


def group_instances(functions):
    groups = defaultdict(list)
    for row in functions:
        if row.get("language") == "Rust" and row.get("source_mapping_eligible"):
            groups[source_key(row)].append(row)
    return {key: sorted(rows, key=lambda row: row["llvm_symbol"])
            for key, rows in sorted(groups.items())}


def select_instances(functions, *, crate, source_file, scope_chain, source_line, source_name):
    key = (crate, source_file, tuple(scope_chain), source_line, source_name)
    rows = group_instances(functions).get(key, [])
    if not rows:
        raise ValueError("source_identity_not_found")
    return rows  # Every legitimate LLVM instance, not the first reachable match.


def declaration_line(source: str, name: str, *, occurrence_line=None):
    """Locate declarations only. Caller must supply a reviewed scope/line if ambiguous."""
    lines = [n for n, line in enumerate(source.splitlines(), 1)
             if re.search(r"\bfn\s+" + re.escape(name) + r"\b", line)]
    if occurrence_line is not None:
        if occurrence_line not in lines:
            raise ValueError("configured declaration does not exist")
        return occurrence_line
    if len(lines) != 1:
        raise ValueError("source_identity_ambiguous: multiple declarations")
    return lines[0]


def configure_entry(graph, authored_instances, native_identity, mechanical_identities):
    """Validate an explicitly reviewed mechanical startup chain in SVF edges.

    Mechanical classification must come from a separate LLVM/body review; this
    function never classifies a wrapper as mechanical from its name alone.
    """
    targets = {r["identity"] for r in authored_instances}
    allowed = set(mechanical_identities)
    outgoing = defaultdict(list)
    for edge in graph["call_edges"]:
        outgoing[edge["caller"]].append(edge)
    pending = deque([(native_identity, [])])
    seen = set()
    paths = []
    while pending:
        node, path = pending.popleft()
        if node in seen:
            continue
        seen.add(node)
        if node in targets:
            paths.append(path)
            continue
        if node not in allowed:
            raise ValueError("unreviewed substantive startup function")
        edges = outgoing[node]
        if len(edges) != 1 or edges[0]["edge_type"] != "direct":
            raise ValueError("startup is not a verified mechanical direct chain")
        pending.append((edges[0]["callee"], path + [edges[0]]))
    if len(paths) != 1:
        raise ValueError("source_identity_ambiguous: no unique authored startup target")
    return {"configured_source_instances": sorted(targets), "native_wrapper": native_identity,
            "excluded_startup_edges": len(paths[0]), "startup_path": paths[0],
            "projection": "scientific_entry_selection_only_no_graph_edges_removed"}


def verify_mechanical_body(ir, llvm_symbol, expected_callee):
    """Conservative LLVM body check, NOT scientific call-edge construction.

    Only argument/debug spills and one direct forwarding call followed by its
    return qualify. Anything else needs human review, including unwind logic.
    """
    pattern = r'^define [^\n]*@(?:"' + re.escape(llvm_symbol) + r'"|' + re.escape(llvm_symbol) + r')\([^\n]*\{\n(.*?)^\}'
    matches = re.findall(pattern, ir, re.M | re.S)
    if len(matches) != 1:
        raise ValueError("wrapper LLVM body absent/ambiguous")
    calls = []
    return_value = None
    spill_slots = set()
    for raw in matches[0].splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#dbg_")) or line.endswith(":"):
            continue
        allocation = re.match(r'(%[^ ]+) = alloca\b', line)
        if allocation:
            spill_slots.add(allocation[1])
            continue
        if re.match(r'store\b|%[^ ]+ = load\b', line):
            addresses = re.findall(r', ptr ([%@][^ ,]+)', line)
            if len(addresses) != 1 or addresses[0] not in spill_slots:
                raise ValueError("wrapper memory access is not a local argument/debug spill")
            continue
        call = re.match(r'(%[^ ]+) = (?:tail )?call [^@]*@(?:"([^\"]+)"|([^ (]+))\(', line)
        if call:
            calls.append((call[1], call[2] or call[3]))
            continue
        ret = re.match(r'ret [^ ]+ (%[^ ,]+)', line)
        if ret:
            return_value = ret[1]
            continue
        raise ValueError("wrapper has substantive/unreviewed LLVM operation: " + line)
    if len(calls) != 1 or calls[0] != (return_value, expected_callee):
        raise ValueError("wrapper does not directly return the sole callee result")
    return {"llvm_symbol": llvm_symbol, "callee": expected_callee,
            "classification": "mechanical_argument_forwarder", "body_verified": True}
