"""Phase 2.6: four-source, build-aware JSON AST feasibility probe, not a metric.

Reuses the unmodified production parse_clang_ast action with recorded flags.
No compiler recovery flags, binary builds, fingerprints, distances, or clustering.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys

from .analysis.ordered_callgraph import stable_json
from .analysis.ordered_distances import DEFAULT_EXCLUDE

ROOT = Path(__file__).resolve().parents[1]
SELECTION = {("mkdir", "002"): ("lineage-003", "lineage-009"),
             ("grep", "004"): ("lineage-001", "lineage-002")}
CONTROL = {"IfStmt", "ForStmt", "WhileStmt", "DoStmt", "SwitchStmt", "ConditionalOperator"}
TRANSFERS = {"ReturnStmt", "BreakStmt", "ContinueStmt", "GotoStmt", "LabelStmt"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def walk(node, path=(), controls=()):
    if not isinstance(node, dict):
        return
    kind = node.get("kind", "<empty>")
    yield node, path, controls
    nested = controls + (kind,) if kind in CONTROL else controls
    for index, child in enumerate(node.get("inner", [])):
        yield from walk(child, path + ((kind, index),), nested)


def recorded_flags(experiment):
    """Recognize only this audited simple command shape; never execute its shell."""
    tokens = shlex.split(experiment["build_command"])
    if tokens[:4] != ["mkdir", "-p", "build", "&&"]:
        raise ValueError("unsupported recorded build command shape")
    command = tokens[4:]
    if command[0] != "cc" or command[-2] != "-o":
        raise ValueError("unsupported recorded compiler/output clause")
    source = experiment["source_workdir_path"]
    if command[-3] != source:
        raise ValueError("recorded source does not match build command")
    flags = command[1:-3]
    # This deliberately narrow probe refuses flags requiring unknown relocation,
    # environment expansion, response files, link inputs, or extra translation units.
    allowed = {"-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2"}
    if set(flags) != allowed or len(flags) != len(allowed):
        raise ValueError("recorded flags outside the four-candidate audited context")
    return flags


def direct_reference(call):
    """Inspect only the callee operand. An argument reference cannot create an edge."""
    children = call.get("inner", [])
    callee = children[0] if children else {}
    while callee.get("kind") in {"ImplicitCastExpr", "ParenExpr"}:
        inner = callee.get("inner", [])
        if len(inner) != 1:
            return None
        callee = inner[0]
    ref = callee.get("referencedDecl", {})
    return ref if callee.get("kind") == "DeclRefExpr" and ref.get("kind") == "FunctionDecl" else None


def main_definitions(tree, source):
    """Top-level filename state, never the production line-number heuristic.

    Clang omits repeated filenames in successive top-level declaration locations.
    Keep explicit state; retain uncertainty if a source filename is never stated.
    """
    current_file = None
    definitions, origins = [], {}
    for node in tree.get("inner", []):
        loc = node.get("loc", {})
        actual = loc.get("expansionLoc", loc)
        if actual.get("file"):
            current_file = actual["file"]
        if node.get("id"):
            origins[node["id"]] = current_file
        if node.get("kind") == "FunctionDecl" and any(c.get("kind") == "CompoundStmt" for c in node.get("inner", [])):
            if current_file and Path(current_file).resolve() == source.resolve():
                definitions.append(node)
    return definitions, origins


def location_excerpt(node, data):
    result = {"raw_range": node.get("range"), "raw_location": node.get("loc")}
    begin = node.get("range", {}).get("begin", {})
    end = node.get("range", {}).get("end", {})
    if "expansionLoc" in begin:
        result["provenance_kind"] = "macro_spelling_and_expansion"
        location = begin["expansionLoc"]
        offset, length = location.get("offset"), location.get("tokLen")
        if isinstance(offset, int) and isinstance(length, int) and 0 <= offset < len(data):
            result["main_source_expansion_token"] = data[offset:offset + length].decode("utf-8", "replace")
        result["note"] = "Raw spelling/expansion locations are separate; omitted filenames are not invented. Expansion span may cover only the macro token."
    else:
        result["provenance_kind"] = "ordinary_source_range"
        start, stop = begin.get("offset"), end.get("offset")
        if isinstance(start, int) and isinstance(stop, int) and 0 <= start <= stop < len(data):
            result["main_source_excerpt"] = data[start:min(stop + end.get("tokLen", 0), start + 200)].decode("utf-8", "replace")
    return result


def summarize_ast(tree, source, data):
    definitions, origins = main_definitions(tree, source)
    index = {n["id"]: n for n, _, _ in walk(tree) if n.get("id")}

    def canonical(identifier):
        seen = set()
        while identifier in index and index[identifier].get("previousDecl") and identifier not in seen:
            seen.add(identifier)
            identifier = index[identifier]["previousDecl"]
        return identifier

    local = {canonical(f["id"]): f["name"] for f in definitions}
    functions, calls, casts, macros, references = [], [], [], [], []
    operators, kinds, edges = Counter(), Counter(), set()
    all_reference_counts = Counter()
    for function in definitions:
        body = next(c for c in function["inner"] if c.get("kind") == "CompoundStmt")
        rows = list(walk(body))
        functions.append({
            "name": function["name"], "compiler_local_id": function["id"],
            "location": function.get("loc"), "body_nodes": len(rows),
            "name_regex_hint_parser_usage": bool(re.search(DEFAULT_EXCLUDE, function["name"], re.I)),
            "body_statement_sequence": [{"slot": i, "kind": c.get("kind"), **location_excerpt(c, data)} for i, c in enumerate(body.get("inner", []))],
        })
        for node, path, controls in rows:
            kind = node.get("kind", "<empty>")
            kinds[kind] += 1
            if "opcode" in node:
                operators[kind + ":" + node["opcode"]] += 1
            if kind == "CallExpr":
                ref = direct_reference(node)
                target = ref.get("name") if ref else None
                declaration = index.get(ref.get("id"), {}) if ref else {}
                internal = bool(ref and canonical(ref["id"]) in local)
                call = {
                    "caller": function["name"], "callee": target,
                    "resolution": "internal_direct" if internal else "external_declared" if ref else "unresolved_indirect",
                    "callee_declaration_id": ref.get("id") if ref else None,
                    "callee_declaration_location": declaration.get("loc"),
                    "callee_declaration_file_context": origins.get(ref.get("id")) if ref else None,
                    "argument_count": max(0, len(node.get("inner", [])) - 1),
                    "arguments": [{"argument_slot": i, "kind": arg.get("kind"), "type": arg.get("type"), **location_excerpt(arg, data)} for i, arg in enumerate(node.get("inner", [])[1:])],
                    "path": path, "control_ancestors": controls, **location_excerpt(node, data),
                }
                calls.append(call)
                if ref:
                    edges.add((function["name"], target, call["resolution"]))
            if kind == "CStyleCastExpr" and "mode_t" in node.get("type", {}).get("qualType", ""):
                casts.append({"function": function["name"], "kind": kind, "type": node.get("type"),
                              "castKind": node.get("castKind"), "path": path, **location_excerpt(node, data)})
            if "expansionLoc" in node.get("range", {}).get("begin", {}):
                macros.append({"function": function["name"], "kind": kind, "opcode": node.get("opcode"),
                               "path": path, **location_excerpt(node, data)})
            if kind == "DeclRefExpr":
                ref = node.get("referencedDecl", {})
                identifier = ref.get("id")
                all_reference_counts[identifier] += 1
                references.append({"function": function["name"], "reference_kind": ref.get("kind"),
                                   "name": ref.get("name"), "declaration_id": identifier,
                                   "declaration_found_in_dump": identifier in index,
                                   "type": node.get("type"), "path": path})
    repeated = [dict(row, occurrences=all_reference_counts[row["declaration_id"]]) for row in references
                if row["reference_kind"] in {"VarDecl", "ParmVarDecl"} and all_reference_counts[row["declaration_id"]] > 1]
    unique_repeated = {row["declaration_id"]: row for row in repeated}
    return {
        "scope": "all_main_source_function_bodies; no parser exclusions",
        "definition_attribution": "top_level_loc_file_state; explicit candidate file match; no line-number inclusion heuristic",
        "function_count": len(functions), "function_body_nodes": sum(kinds.values()),
        "functions": functions, "call_count": len(calls), "call_resolutions": dict(Counter(c["resolution"] for c in calls)),
        "direct_edges": [list(e) for e in sorted(edges)], "calls": calls,
        "fprintf_calls": sum(c["callee"] == "fprintf" for c in calls),
        "mode_t_calls": sum(c["callee"] == "mode_t" for c in calls), "mode_t_casts": casts,
        "S_ISDIR_calls": sum(c["callee"] == "S_ISDIR" for c in calls),
        "macro_expansion_nodes": len(macros),
        "macro_expansion_token_counts": dict(Counter(m.get("main_source_expansion_token", "<unavailable>") for m in macros)),
        "S_ISDIR_expansion_examples": [m for m in macros if m.get("main_source_expansion_token") == "S_ISDIR"][:12],
        "other_macro_examples": [m for m in macros if m.get("main_source_expansion_token") != "S_ISDIR"][:8],
        "operators": dict(sorted(operators.items())), "node_kinds": dict(sorted(kinds.items())),
        "control_kinds": {k: kinds[k] for k in sorted(CONTROL) if kinds[k]},
        "transfer_kinds": {k: kinds[k] for k in sorted(TRANSFERS) if kinds[k]},
        "max_control_nesting": max((len(c["control_ancestors"]) for c in calls), default=0),
        "declaration_reference_count": len(references),
        "references_with_declaration_in_dump": sum(r["declaration_found_in_dump"] for r in references),
        "repeated_variable_binding_examples": list(unique_repeated.values())[:12],
        "scope_diagnostic": {"name_regex_hint_functions": [f["name"] for f in functions if f["name_regex_hint_parser_usage"]],
                             "hint_function_body_nodes": sum(f["body_nodes"] for f in functions if f["name_regex_hint_parser_usage"]),
                             "use": "Name-sensitive descriptive diagnostic only; no functions excluded"},
        "limitations": ["AST child order is not a universal execution-order guarantee", "Compiler IDs are dump-local, never cross-candidate features", "Active expanded code only; inactive preprocessor alternatives absent"],
    }


def probe(output, evidence_dir):
    # Import only the existing action; do not invoke analyzer main or change code.
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from scripts.analyze_experiment import parse_clang_ast
    finally:
        sys.path.pop(0)
    clang = shutil.which("clang")
    if clang is None:
        raise RuntimeError("clang unavailable; no fallback")
    version = subprocess.run([clang, "--version"], capture_output=True, text=True, check=True).stdout
    include_probe = subprocess.run([clang, "-std=c11", "-E", "-v", "-x", "c", "-"], input="", capture_output=True, text=True)
    audit_path = ROOT / "docs/ordered_diversity_phase25_feasibility.json"
    audit_bytes = audit_path.read_bytes()
    audit = json.loads(audit_bytes)
    selected = [c for group in audit["groups"] for c in group["candidates"]
                if c["lineage_id"] in SELECTION.get((group["utility"], group["checkpoint"]), ())]
    if len(selected) != 4:
        raise ValueError("The predetermined four audited candidates are not available")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "investigation": "ordered-diversity-phase2.6-feasibility-only",
        "compiler_path": clang, "compiler_version": version.strip(), "platform": platform.platform(),
        "include_search_probe": {"command": [clang, "-std=c11", "-E", "-v", "-x", "c", "-"],
                                 "returncode": include_probe.returncode, "stderr": include_probe.stderr},
        "environment_include_variables": {key: os.environ.get(key) for key in ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "SDKROOT")},
        "phase25_audit_sha256": sha(audit_bytes), "runner_sha256": sha(Path(__file__).read_bytes()),
        "production_analyzer_sha256": sha((ROOT / "scripts/analyze_experiment.py").read_bytes()),
        "build_context_limit": "Recorded flags preserved; historical cc version, target/sysroot and header image not recorded here. Local Clang/Linux is not certified original-environment reproduction.",
        "candidates": [],
    }
    for member in selected:
        source = ROOT / member["candidate_source"]
        before = source.read_bytes()
        if sha(before.replace(b"\r\n", b"\n")) != member["candidate_source_sha256"]:
            raise ValueError("candidate hash mismatch")
        experiment_path = source.parents[2] / "experiment.json"
        experiment_bytes = experiment_path.read_bytes()
        experiment = json.loads(experiment_bytes)
        flags = recorded_flags(experiment)
        # parse_clang_ast supplies precisely the recorded -std=c11 itself.
        extra = [f for f in flags if f != "-std=c11"]
        evidence = evidence_dir / f"{member['utility']}-{member['lineage_id']}-{member['checkpoint_id']}.ast.json"
        counts, count_total, error = parse_clang_ast(source, evidence, extra)
        raw = evidence.read_bytes() if evidence.exists() else b""
        row = {
            "candidate_id": member["candidate_id"], "utility": member["utility"],
            "checkpoint": member["checkpoint_id"], "functional_population_status": member["functional_population_status"],
            "phase25_extraction_status": member["extraction_status"],
            "source": member["candidate_source"], "source_sha256": sha(before),
            "manifest_lf_sha256": member["candidate_source_sha256"],
            "experiment": str(experiment_path.relative_to(ROOT)), "experiment_sha256": sha(experiment_bytes),
            "recorded_build_command": experiment["build_command"], "recorded_repository": experiment["repository"],
            "recorded_repository_commit": experiment.get("repository_commit"),
            "recorded_flags": flags,
            "ast_command": [clang, "-std=c11", "-fsyntax-only", *extra, "-Xclang", "-ast-dump=json", str(source)],
            "command_adaptations": ["cc replaced by installed clang", "-o binary output and mkdir shell prelude omitted for syntax-only extraction", "recorded source path relocated to unchanged candidate snapshot", "-std=c11 supplied once by existing parse_clang_ast"],
            "status": "compiler_or_ast_failure" if error else "success", "diagnostics": error,
            "raw_ast_artifact": str(evidence.relative_to(ROOT)), "raw_ast_bytes": len(raw), "raw_ast_sha256": sha(raw),
            "raw_ast_measurement_eligible": error is None,
            "existing_count_total_not_used_as_structural_measure": count_total,
            "source_unchanged": source.read_bytes() == before,
        }
        if error is None:
            row["structure_evidence"] = summarize_ast(json.loads(raw), source, before)
        else:
            row["structure_evidence"] = None  # Never use a failed compiler's partial AST.
        report["candidates"].append(row)
    report["coverage"] = {
        "attempted": len(selected), "compiler_ast_success": sum(r["status"] == "success" for r in report["candidates"]),
        "failures": sum(r["status"] != "success" for r in report["candidates"]),
        "source_files_unchanged": all(r["source_unchanged"] for r in report["candidates"]),
        "distances_computed": False,
    }
    output.write_text(stable_json(report), encoding="utf-8")
    for row in report["candidates"]:
        print(row["candidate_id"], row["status"], row["diagnostics"] or {
            k: row["structure_evidence"][k] for k in ("function_count", "call_count", "call_resolutions", "fprintf_calls", "mode_t_calls", "S_ISDIR_calls")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/ordered_diversity_phase26_feasibility.json")
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "build/ordered-diversity-phase26")
    args = parser.parse_args()
    probe(args.output, args.evidence_dir)


if __name__ == "__main__":
    main()
