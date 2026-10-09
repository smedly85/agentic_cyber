"""Controlled validation of the Rust LLVM/SVF backend (rust_llvm_svf_v1).

Every program is compiled from source, linked, verified and analyzed in a
fresh directory, twice, under each configuration in pipeline.CONFIGURATIONS.
Observed graphs are compared with expectations that were preregistered in
expectations.json and the frozen calibration manifest before any run.  The
C halves of the 15 calibration pairs are rerun through the same helpers; under
the primary configuration they must reproduce the committed C results.

No historical specimen is touched here.

Run from the repository root under WSL/Linux:
    PYTHONPATH=. python3 -m security.semantic_callgraph.rust_llvm_svf_v1.validate \
        --output build/rust-llvm-svf-v1/validation
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import platform
import re
import subprocess
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from security.semantic_callgraph.rust_llvm_svf_v1 import pipeline as P

HERE = Path(__file__).resolve().parent
ROOT = P.ROOT
CALIBRATION = ROOT / "security/semantic_callgraph/cross_language_calibration"
PRIMARY = "P"


def read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def lf_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify_preregistration() -> dict[str, Any]:
    record = read(HERE / "preregistration.json")
    changed = [name for name, digest in record["files"].items() if lf_sha256(ROOT / name) != digest]
    if changed:
        raise SystemExit(f"STOP: preregistered inputs changed after preregistration: {changed}")
    return record


# ---------------------------------------------------------------- programs

def controlled_programs(expectations: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand expectations.json into concrete programs (one per cfg variant)."""
    programs = []
    for program in expectations["programs"]:
        crates = program["crates"]
        variants = program.get("variants") or [None]
        for variant in variants:
            built = []
            for crate in crates:
                cfg = list(crate.get("cfg", []))
                if crate.get("cfg_audit_case"):
                    cfg.append(f'audit_case="{variant["cfg_audit_case"]}"')
                built.append(P.Crate(crate["name"], crate["source"], crate["crate_type"], crate["edition"],
                                     tuple(crate.get("externs", [])), tuple(cfg)))
            identifier = program["id"] if variant is None else f'{program["id"]}/{variant["cfg_audit_case"]}'
            programs.append({
                "id": identifier,
                "kind": "controlled",
                "crates": built,
                "functions": program["functions"],
                "indirect_sites": variant["indirect_sites"] if variant else program.get("indirect_sites", []),
                "cases": [variant["case"]] if variant else program["cases"],
                "instance_counts": program.get("instance_counts", {}),
                "application_files": sorted({c["source"] for c in crates
                                             if not c["source"].startswith("build/")}),
            })
    return programs


def calibration_programs(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    programs = []
    for pair in manifest["pairs"]:
        programs.append({
            "id": f"calibration/{pair['pair_id']}/Rust", "kind": "calibration", "language": "Rust", "pair": pair,
            "crates": [P.Crate(f"calibration_{pair['pair_id']}", pair["rust_source"], "bin", "2021")],
            "application_files": [pair["rust_source"]],
        })
        programs.append({
            "id": f"calibration/{pair['pair_id']}/C", "kind": "calibration", "language": "C", "pair": pair,
            "application_files": [pair["c_source"]],
        })
    return programs


def build(program: Mapping[str, Any], out: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=False)
    log: list[dict[str, Any]] = []
    record: dict[str, Any] = {"commands": log}
    try:
        if program.get("language") == "C":
            config = manifest["semantic_extraction_configuration"]["C"]
            flags = [flag.replace("$REPO", str(ROOT)) for flag in config["flags"]]
            module = out / "fixture.bc"
            P.run([P.CLANG, *flags, ROOT / program["pair"]["c_source"], "-o", module],
                  cwd=ROOT, log=log, out=out, stage="clang")
            modules = [module]
        else:
            modules = P.compile_crates(program["crates"], out, log)
        linked, text = P.link_and_verify(modules, out, log)
        record.update({"status": "success", "linked": str(linked), "ir": str(text),
                       "modules": [{"path": m.relative_to(out).as_posix(), "sha256": P.sha256(m)} for m in modules],
                       "linked_sha256": P.sha256(linked)})
    except P.PipelineError as error:
        record.update({"status": "build_or_ir_unavailable", "error": str(error)})
    write(out / "build.json", {k: v for k, v in record.items() if k not in ("linked", "ir")})
    return record


# ---------------------------------------------------------------- matching

def label_index(raw: Mapping[str, Any], functions: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, list[str]], dict[str, str]]:
    by_label: dict[str, list[str]] = {}
    for label, spec in functions.items():
        by_label[label] = sorted(
            row["identity"] for row in raw["functions"]
            if row.get("source_file") == spec["file"]
            and (spec.get("line") is None or (row.get("definition") or {}).get("line") == spec["line"])
            and P.strip_generics(str(row.get("name", ""))) == spec["name"])
    label_of = {identity: label for label, identities in by_label.items() for identity in identities}
    return by_label, label_of


def calibration_index(raw: Mapping[str, Any], functions: Mapping[str, Mapping[str, Any]], language: str) -> tuple[dict[str, list[str]], dict[str, str]]:
    by_key: dict[str, list[str]] = {}
    for key, spec in functions.items():
        span = spec["source_span"]
        base = spec["function_name"].split("::")[-1] if language == "Rust" else spec["function_name"]

        def name_ok(name: str) -> bool:
            if language == "Rust" and base == "closure":
                return name.startswith("{closure#")
            return P.strip_generics(name) == base

        by_key[key] = sorted(
            row["identity"] for row in raw["functions"]
            if row.get("source_file") == spec["source_file"]
            and span["start_line"] <= ((row.get("definition") or {}).get("line") or 0) <= span["end_line"]
            and name_ok(str(row.get("name", ""))))
    label_of = {identity: key for key, identities in by_key.items() for identity in identities}
    return by_key, label_of


def site_rows(raw: Mapping[str, Any], callers: Iterable[str], line: int | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    callers = set(callers)
    def at(row: Mapping[str, Any]) -> bool:
        return row.get("caller") in callers and (line is None or (row.get("callsite") or {}).get("line") == line)
    resolved = [e for e in raw["call_edges"] if e["edge_type"] == "indirect_resolved" and at(e)]
    unresolved = [u for u in raw["unresolved_indirect_callsites"] if at(u)]
    # Amendment A-2: only meaningful for a specific source line.
    direct = [e for e in raw["call_edges"] if e["edge_type"] == "direct" and at(e)] if line is not None else []
    return resolved, unresolved, direct


def adjudicate(expected: Iterable[str], resolved: list[dict[str, Any]], unresolved: list[dict[str, Any]],
               label_of: Mapping[str, str], *, expect_unresolved: bool = False,
               direct: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    actual = sorted({label_of.get(edge["callee"], edge["callee"]) for edge in resolved})
    expected = sorted(set(expected))
    direct = list(direct)
    if not resolved and not unresolved and direct and not expect_unresolved:
        # Amendment A-2: rustc emitted a direct LLVM call at this source site
        # (the fn-pointer value was a compile-time constant).  The target set
        # is the direct callee set; it is reported separately from SVF
        # indirect resolution and never counted as a pointer-analysis success.
        lowered = sorted({label_of.get(edge["callee"], edge["callee"]) for edge in direct})
        exact_set = lowered == expected
        return {"expected": expected, "actual": lowered, "missing": sorted(set(expected) - set(lowered)),
                "unexpected": sorted(set(lowered) - set(expected)), "unresolved_rows": 0,
                "status": "lowered_to_direct_call_exact" if exact_set else "lowered_to_direct_call_mismatch",
                "passed": exact_set, "strict_preregistered_passed": False,
                "callsites": sorted({json.dumps(e.get("callsite"), sort_keys=True) for e in direct})}
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    if expect_unresolved:
        status = "exact_unresolved" if not resolved and unresolved else (
            "invented_targets" if resolved else "site_not_found")
    elif not resolved and not unresolved:
        status = "site_not_found"
    elif not missing and not unexpected and not unresolved:
        status = "exact"
    elif missing and not unexpected:
        status = "missing_targets"
    elif unexpected and not missing:
        status = "unexpected_targets"
    else:
        status = "missing_and_unexpected_targets"
    passed = status in ("exact", "exact_unresolved")
    return {"expected": expected, "actual": actual, "missing": missing, "unexpected": unexpected,
            "unresolved_rows": len(unresolved), "status": status,
            "passed": passed, "strict_preregistered_passed": passed,
            "callsites": sorted({json.dumps(e.get("callsite"), sort_keys=True) for e in resolved + unresolved})}


def all_indirect_sites(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    sites: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in raw["call_edges"]:
        if edge["edge_type"] != "indirect_resolved":
            continue
        key = (edge["caller"], json.dumps(edge.get("callsite"), sort_keys=True))
        sites.setdefault(key, {"caller": edge["caller"], "callsite": edge.get("callsite"), "targets": set(), "status": "resolved"})
        sites[key]["targets"].add(edge["callee"])
    for row in raw["unresolved_indirect_callsites"]:
        key = (row["caller"], json.dumps(row.get("callsite"), sort_keys=True))
        sites.setdefault(key, {"caller": row["caller"], "callsite": row.get("callsite"), "targets": set(), "status": "unresolved"})
    return [{**value, "targets": sorted(value["targets"])} for _, value in sorted(sites.items())]


# ---------------------------------------------------------------- evaluation

def evaluate_controlled(program: Mapping[str, Any], raw: Mapping[str, Any], ir_text: str, provenance: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    failures: list[str] = []
    files = set(program["application_files"])
    by_label, label_of = label_index(raw, program["functions"])
    rows = {row["identity"]: row for row in raw["functions"]}
    # Amendment A-1: rustc codegens only items reachable from the crate's
    # roots, so a cfg variant need not contain every function in the shared
    # table.  A label is required only when this variant's sites or cases use
    # it outside an `unreachable` list (an absent function is unreachable).
    referenced = referenced_labels(program)
    missing_labels = sorted(label for label, ids in by_label.items() if not ids and label in referenced)
    failures += [f"function_not_found:{label}" for label in missing_labels]
    absent_unreferenced = sorted(label for label, ids in by_label.items() if not ids and label not in referenced)
    for label, count in program.get("instance_counts", {}).items():
        if len(by_label[label]) != count:
            failures.append(f"instance_count:{label}:{len(by_label[label])}!={count}")
    inventory = P.definition_inventory(ir_text, raw)
    if inventory["debug_inventory_status"] != "all_debug_definitions_exported":
        failures.append("debug_definitions_dropped")
    sites = []
    adjudicated_keys = set()
    for site in program["indirect_sites"]:
        caller = site["caller"]
        if isinstance(caller, str):
            callers = by_label[caller]
        else:
            callers = [r["identity"] for r in raw["functions"] if r.get("source_file") == caller["file"]
                       and P.strip_generics(str(r.get("name", ""))) == caller["name"]]
        resolved, unresolved, direct = site_rows(raw, callers, site.get("line"))
        result = adjudicate(site["expected"], resolved, unresolved, label_of,
                            expect_unresolved=site.get("expect_unresolved", False), direct=direct)
        result.update({"id": site["id"], "mandatory": bool(site.get("mandatory")), "caller": caller, "line": site.get("line")})
        sites.append(result)
        for row in resolved + unresolved:
            adjudicated_keys.add((row["caller"], json.dumps(row.get("callsite"), sort_keys=True)))
        if not result["passed"]:
            failures.append(f"site:{site['id']}:{result['status']}")
    cases = []
    graphs = {}
    for case in program["cases"]:
        outcome = evaluate_case(case, raw, by_label, label_of, rows, files, provenance)
        graphs[case["id"]] = outcome.pop("graph", None)
        cases.append(outcome)
        failures += [f"case:{case['id']}:{reason}" for reason in outcome["failures"]]
    unadjudicated = [s for s in all_indirect_sites(raw)
                     if (s["caller"], json.dumps(s.get("callsite"), sort_keys=True)) not in adjudicated_keys]
    origins = Counter(P.origin(row, files) for row in raw["functions"])
    result = {
        "program": program["id"], "status": "pass" if not failures else "fail", "failures": failures,
        "sites": sites, "cases": cases, "inventory": inventory, "function_origins": dict(sorted(origins.items())),
        "labels": by_label, "absent_unreferenced_labels": absent_unreferenced,
        "unadjudicated_indirect_sites": unadjudicated,
        "edge_counts": dict(Counter(e["edge_type"] for e in raw["call_edges"])),
        "unresolved_indirect_callsites": len(raw["unresolved_indirect_callsites"]),
        "external_calls": len(raw["external_calls"]),
    }
    return result, graphs


def referenced_labels(program: Mapping[str, Any]) -> set[str]:
    labels: set[str] = set(program.get("instance_counts", {}))
    for site in program["indirect_sites"]:
        if isinstance(site["caller"], str):
            labels.add(site["caller"])
        labels.update(site["expected"])
    for case in program["cases"]:
        labels.add(case["entry"])
        for target in case.get("targets", []):
            labels.add(target["function"])
            labels.update(target["application_path"])
        for pair in case.get("required_edges", []):
            labels.update(pair)
        labels.update(case.get("reachable_instance_counts", {}))
        labels.update(row["caller"] for row in case.get("external_calls", []))
        labels.update(case.get("no_internal_out_edges", []))
        labels.update(row["caller"] for row in case.get("unresolved_sites", []))
    return labels


def path_labels(graph_row: Mapping[str, Any], label_of: Mapping[str, str]) -> list[str] | None:
    path = (graph_row.get("shortest_call_path") or {}).get("function_identities")
    if path is None:
        return None
    return [label_of.get(identity, identity) for identity in path]


def evaluate_case(case: Mapping[str, Any], raw: Mapping[str, Any], by_label: Mapping[str, list[str]],
                  label_of: Mapping[str, str], rows: Mapping[str, Any], files: set[str],
                  provenance: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    entries = by_label.get(case["entry"], [])
    if len(entries) != 1:
        return {"id": case["id"], "entry": case["entry"], "failures": [f"entry_not_unique:{entries}"],
                "mandatory": bool(case.get("mandatory")), "passed": False, "targets": []}
    graph = P.finalize(raw, entries[0], provenance)
    nodes = {row["identity"]: row for row in graph["functions"]}
    targets = []
    for spec in case.get("targets", []):
        instances = by_label.get(spec["function"], [])
        reachable = [nodes[i] for i in instances if nodes[i]["reachable_from_entry"]]
        best = min(reachable, key=lambda r: (r["raw_call_depth"], r["identity"])) if reachable else None
        depth = best["raw_call_depth"] if best else None
        labels = path_labels(best, label_of) if best else None
        row = {"function": spec["function"], "rule": spec["rule"], "expected_depth": spec.get("depth"),
               "observed_depth": depth, "expected_application_path": spec["application_path"],
               "observed_path": labels,
               "instances": [{"identity": i, "depth": nodes[i]["raw_call_depth"]} for i in instances]}
        if best is None:
            row["status"] = "unreachable"
        elif spec["rule"] == "exact":
            row["status"] = "exact" if depth == spec["depth"] and labels == spec["application_path"] else "mismatch"
        else:
            path = best["shortest_call_path"]["function_identities"]
            application = [label_of.get(i, i) for i in path if P.origin(rows[i], files) == "application"]
            other = sorted({P.origin(rows[i], files) for i in path if P.origin(rows[i], files) != "application"})
            row.update({"observed_application_subsequence": application, "intermediate_origins": other})
            ok = application == spec["application_path"] and set(other) <= {
                "rust_std_compiled_generic", "dependency", "compiler_generated"}
            row["status"] = "subsequence_match" if ok else "mismatch"
        if row["status"] not in ("exact", "subsequence_match"):
            failures.append(f"target:{spec['function']}:{row['status']}:{depth}:{labels}")
        targets.append(row)
    unreachable = []
    for label in case.get("unreachable", []):
        reached = [i for i in by_label.get(label, []) if nodes[i]["reachable_from_entry"]]
        unreachable.append({"function": label, "reached_instances": reached,
                            "depths": [nodes[i]["raw_call_depth"] for i in reached]})
        if reached:
            failures.append(f"unexpectedly_reachable:{label}:{[nodes[i]['raw_call_depth'] for i in reached]}")
    for caller, callee in case.get("required_edges", []):
        if not any(e["caller"] in by_label[caller] and e["callee"] in by_label[callee] for e in graph["call_edges"]):
            failures.append(f"missing_required_edge:{caller}->{callee}")
    for label, count in case.get("reachable_instance_counts", {}).items():
        reached = sum(nodes[i]["reachable_from_entry"] for i in by_label[label])
        if reached != count:
            failures.append(f"reachable_instances:{label}:{reached}!={count}")
    for row in case.get("external_calls", []):
        if not any(x["caller"] in by_label[row["caller"]] and x.get("callee_name") == row["callee_name"]
                   for x in graph["external_calls"]):
            failures.append(f"missing_external_call:{row['caller']}->{row['callee_name']}")
    for label in case.get("no_internal_out_edges", []):
        out = [e for e in graph["call_edges"] if e["caller"] in by_label[label]]
        if out:
            failures.append(f"invented_internal_edges:{label}:{[e['callee'] for e in out]}")
    for row in case.get("unresolved_sites", []):
        if not any(u["caller"] in by_label[row["caller"]] and (u.get("callsite") or {}).get("line") == row["line"]
                   for u in graph["unresolved_indirect_callsites"]):
            failures.append(f"missing_unresolved_site:{row['caller']}:{row['line']}")
    reachable_rows = [r for r in graph["functions"] if r["reachable_from_entry"]]
    return {"id": case["id"], "entry": case["entry"], "mandatory": bool(case.get("mandatory")),
            "targets": targets, "unreachable": unreachable, "failures": failures, "passed": not failures,
            "reachable_functions": len(reachable_rows),
            "maximum_finite_shortest_path_depth": max(r["raw_call_depth"] for r in reachable_rows),
            "graph": graph}


def evaluate_calibration(program: Mapping[str, Any], raw: Mapping[str, Any], ir_text: str,
                         provenance: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    pair, language = program["pair"], program["language"]
    prefix = "c" if language == "C" else "rust"
    functions = pair[f"{prefix}_functions"]
    by_key, label_of = calibration_index(raw, functions, language)
    rows = {row["identity"]: row for row in raw["functions"]}
    failures = [f"function_not_found:{k}" for k, ids in by_key.items() if not ids]
    entry_spec = pair[f"{prefix}_entry_identity"]
    entries = by_key.get(entry_spec["function_name"], [])
    if len(entries) != 1:
        return {"program": program["id"], "status": "fail", "failures": failures + [f"entry_not_unique:{entries}"]}, {}
    graph = P.finalize(raw, entries[0], provenance)
    nodes = {row["identity"]: row for row in graph["functions"]}
    in_scope = {row[language] for row in pair["application_correspondence"] if row["inside_entry_scope"]}
    expected_edges = {(e["caller"], e["callee"]) for e in pair[f"expected_{prefix}_edges"]}
    sites = []
    adjudicated_keys = set()
    for site in pair[f"expected_{prefix}_indirect_targets"]:
        resolved, unresolved, direct = site_rows(raw, by_key[site["owner"]], site["source_identity"]["line"])
        adjudicated_keys |= {(r["caller"], json.dumps(r.get("callsite"), sort_keys=True)) for r in resolved + unresolved}
        result = adjudicate(site["expected_targets"], resolved, unresolved, label_of, direct=direct)
        result.update({"id": site["callsite_id"], "owner": site["owner"]})
        sites.append(result)
        expected_edges |= {(site["owner"], target) for target in site["expected_targets"]}
        if not result["passed"]:
            failures.append(f"site:{site['callsite_id']}:{result['status']}")
    actual_edges = set()
    for edge in graph["call_edges"]:
        caller, callee = label_of.get(edge["caller"]), label_of.get(edge["callee"])
        if caller in in_scope and callee in in_scope and nodes[edge["caller"]]["reachable_from_entry"]:
            actual_edges.add((caller, callee))
    missing = sorted(expected_edges - actual_edges)
    extra = sorted(actual_edges - expected_edges)
    failures += [f"missing_application_relation:{a}->{b}" for a, b in missing]
    failures += [f"unexpected_application_relation:{a}->{b}" for a, b in extra]
    depths = []
    for target in pair[f"{prefix}_target_identity"]:
        key = target["function_name"]
        reachable = [nodes[i] for i in by_key.get(key, []) if nodes[i]["reachable_from_entry"]]
        best = min(reachable, key=lambda r: (r["raw_call_depth"], r["identity"])) if reachable else None
        instances = by_key.get(key, [])
        depths.append({"function": key, "depth": best["raw_call_depth"] if best else None,
                       "instance": best["identity"] if best else (instances[0] if len(instances) == 1 else None),
                       "path": best["shortest_call_path"]["function_identities"] if best else None})
    reachable_rows = [r for r in graph["functions"] if r["reachable_from_entry"]]
    files = set(program["application_files"])
    result = {
        "program": program["id"], "pair": pair["pair_id"], "language": language,
        "status": "pass" if not failures else "fail", "failures": failures, "sites": sites,
        "measured_application_relations": sorted(map(list, actual_edges)),
        "expected_application_relations": sorted(map(list, expected_edges)),
        "target_depths": depths,
        "external_calls": sorted((x["caller"], x.get("callee_name"), json.dumps(x.get("callsite"), sort_keys=True))
                                 for x in graph["external_calls"]),
        "reachable_functions": len(reachable_rows),
        "maximum_finite_shortest_path_depth": max(r["raw_call_depth"] for r in reachable_rows),
        "reachable_origins": dict(Counter(P.origin(rows[r["identity"]], files) for r in reachable_rows)),
        "inventory": P.definition_inventory(ir_text, raw),
        "unadjudicated_indirect_sites": [s for s in all_indirect_sites(raw)
                                         if (s["caller"], json.dumps(s.get("callsite"), sort_keys=True)) not in adjudicated_keys],
    }
    return result, {"entry": graph}


def c_regression(result: Mapping[str, Any], committed: Mapping[str, Any]) -> dict[str, Any]:
    """Compare a primary-configuration C calibration result with committed results."""
    mine_paths = sorted((d["instance"], d["depth"], tuple(d["path"] or ())) for d in result["target_depths"])
    theirs_paths = sorted((p["instance"], p["raw_depth"], tuple(p["shortest_path"]["function_identities"] or ()))
                          if p.get("shortest_path") else (p["instance"], p["raw_depth"], ())
                          for p in committed["paths"])
    mine_sites = sorted((s["id"], tuple(s["actual"])) for s in result["sites"])
    theirs_sites = sorted((s["callsite_id"], tuple(sorted(s["actual"]))) for s in committed["indirect_sites"])
    committed_external = sorted((x["caller"], x.get("callee_name"), json.dumps(x.get("callsite"), sort_keys=True))
                                for x in committed["external_boundaries"])
    checks = {
        "external_calls": sorted(map(tuple, result["external_calls"])) == committed_external,
        "application_relations": sorted(map(tuple, result["measured_application_relations"])) ==
                                 sorted(map(tuple, committed["measured_application_relations"])),
        "paths_and_depths": mine_paths == theirs_paths,
        "indirect_target_sets": mine_sites == theirs_sites,
    }
    return {"pair": result["pair"], "identical": all(checks.values()), "checks": checks,
            "observed_paths": mine_paths, "committed_paths": theirs_paths}


# ---------------------------------------------------------------- IR census

GEP_I8 = re.compile(r"getelementptr (?:inbounds )?(?:nuw )?(?:nusw )?i8, ptr [^,]+, i(?:64|32) (-?\d+|%[\w.\"$-]+)")
GEP_TYPED = re.compile(r"getelementptr (?:inbounds )?(?:nuw )?(?:nusw )?(%[\w.\"$-]+|\{|<\{|\[)")
ALLOCA_BYTES = re.compile(r"= alloca \[\d+ x i8\]")
ALLOCA = re.compile(r"= alloca ")


def ir_census(text: str) -> dict[str, int]:
    constant = variable = zero = 0
    for match in GEP_I8.finditer(text):
        index = match.group(1)
        if index.startswith("%"):
            variable += 1
        elif int(index) == 0:
            zero += 1
        else:
            constant += 1
    allocas = len(ALLOCA.findall(text))
    byte_allocas = len(ALLOCA_BYTES.findall(text))
    return {"gep_i8_constant_nonzero_offset": constant, "gep_i8_zero_offset": zero, "gep_i8_variable_offset": variable,
            "gep_typed_aggregate_or_array": len(GEP_TYPED.findall(text)),
            "alloca_byte_array": byte_allocas, "alloca_typed": allocas - byte_allocas,
            "defined_functions": sum(1 for line in text.splitlines() if line.startswith("define "))}


# ---------------------------------------------------------------- orchestration

def toolchain_record() -> dict[str, Any]:
    def text(argv: list[Any]) -> str:
        result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, check=False)
        return (result.stdout + result.stderr).strip()
    canonical_lib = P.CANONICAL_HELPER.parent.parent / "lib"
    def hashes(directory: Path, helper: Path) -> dict[str, str | None]:
        names = ["libSvfCore.so.3.4", "libSvfLLVM.so.3.4", "extapi.bc"]
        row = {name: (P.sha256(directory / name) if (directory / name).is_file() else None) for name in names}
        row["semantic-callgraph-svf"] = P.sha256(helper) if helper.is_file() else None
        return row
    return {
        "recorded_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "host": platform.platform(),
        "rustc": text([P.RUSTC, "-vV"]), "rustc_sha256": P.sha256(P.RUSTC),
        "clang": text([P.CLANG, "--version"]).splitlines()[0],
        "llvm_link": text([P.LLVM_BIN / "llvm-link", "--version"]),
        "opt": text([P.LLVM_BIN / "opt", "--version"]).splitlines()[:2],
        "rustc_codegen_flags": list(P.RUSTC_CODEGEN), "remap": P.scientific(P.remap_flags(), ROOT / "build/rust-llvm-svf-v1"),
        "canonical_svf": {"commit": text(["git", "-C", ROOT / "build/semantic-toolchain/SVF", "rev-parse", "HEAD"]),
                          "hashes": hashes(canonical_lib, P.CANONICAL_HELPER)},
        "configuration_instruments": {
            name: hashes(Path(config["helper"]).parent.parent / "lib", Path(config["helper"]))
            for name, config in P.CONFIGURATIONS.items()},
        "sensitivity_patches": {p.name: P.sha256(p) for p in sorted((HERE / "sensitivity_svf").glob("*.patch"))},
        "configurations": {k: {"helper": P.scientific([v["helper"]], ROOT)[0], "options": list(v["options"]), "role": v["role"]}
                           for k, v in P.CONFIGURATIONS.items()},
    }


def analyze(program: Mapping[str, Any], built: Mapping[str, Any], configuration: str, out: Path) -> dict[str, Any]:
    directory = out / "analysis" / configuration
    directory.mkdir(parents=True, exist_ok=False)
    if built["status"] != "success":
        return {"program": program["id"], "configuration": configuration, "status": "fail",
                "failures": ["build_or_ir_unavailable"], "error": built.get("error")}
    try:
        raw, _ = P.run_helper(configuration, Path(built["linked"]), directory)
        # Tokenize against the program directory so provenance (and hence the
        # finalized-graph hash) does not depend on which run produced it.
        argv = P.scientific([P.CONFIGURATIONS[configuration]["helper"], *P.CONFIGURATIONS[configuration]["options"],
                             built["linked"]], out)
    except P.PipelineError as error:
        return {"program": program["id"], "configuration": configuration, "status": "fail",
                "failures": ["analysis_failure"], "error": str(error)}
    provenance = {"configuration": configuration, "svf_command": argv, "linked_bitcode_sha256": built["linked_sha256"],
                  "build_commands": built["commands"], "program": program["id"]}
    ir_text = Path(built["ir"]).read_text()
    try:
        if program["kind"] == "controlled":
            result, graphs = evaluate_controlled(program, raw, ir_text, provenance)
        else:
            result, graphs = evaluate_calibration(program, raw, ir_text, provenance)
    except Exception as error:  # evaluation defects must stay visible, never pass
        result, graphs = {"program": program["id"], "status": "fail", "failures": ["evaluation_error"],
                          "error": traceback.format_exc()}, {}
    result["configuration"] = configuration
    result["raw_sha256"] = P.sha256(directory / "raw.json")
    graph_hashes = {}
    for name, graph in graphs.items():
        if graph is None:
            continue
        path = directory / "graphs" / f"{name}.json"
        write(path, graph)
        graph_hashes[name] = P.sha256(path)
    result["graph_sha256"] = graph_hashes
    write(directory / "evaluation.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--configurations", default=",".join(P.CONFIGURATIONS))
    args = parser.parse_args()
    output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
    if output.exists():
        raise SystemExit(f"refusing to reuse {output}; choose a fresh output directory")
    configurations = args.configurations.split(",")
    preregistration = verify_preregistration()
    expectations = read(HERE / "expectations.json")
    manifest = read(CALIBRATION / "fixture_manifest.json")
    committed = {row["pair_id"]: row for row in read(CALIBRATION / "pair_results.json")["pairs"]}
    programs = controlled_programs(expectations) + calibration_programs(manifest)
    write(output / "toolchain_before.json", toolchain_record())
    results: dict[str, Any] = {}
    census: dict[str, Any] = {}
    for run_index in range(1, args.runs + 1):
        run_dir = output / f"run-{run_index}"
        for program in programs:
            out = run_dir / program["id"]
            built = build(program, out, manifest)
            if run_index == 1 and built["status"] == "success":
                census[program["id"]] = ir_census(Path(built["ir"]).read_text())
            for configuration in configurations:
                row = analyze(program, built, configuration, out)
                results[f"run-{run_index}|{configuration}|{program['id']}"] = row
                print(f"run-{run_index} {configuration:8} {program['id']:45} {row['status']}", flush=True)
    write(output / "toolchain_after.json", toolchain_record())
    determinism = {}
    for key, row in results.items():
        run, configuration, program_id = key.split("|")
        if run != "run-1":
            continue
        other = results.get(f"run-2|{configuration}|{program_id}")
        if other is None:
            continue
        determinism[f"{configuration}|{program_id}"] = (
            row.get("raw_sha256") == other.get("raw_sha256") and row.get("graph_sha256") == other.get("graph_sha256")
            and row.get("status") == other.get("status") and row.get("failures") == other.get("failures"))
    regression = {}
    for program in programs:
        if program.get("language") == "C":
            row = results.get(f"run-1|{PRIMARY}|{program['id']}")
            if row and "target_depths" in row:
                regression[program["pair"]["pair_id"]] = c_regression(row, committed[program["pair"]["pair_id"]]["C"])
            else:
                regression[program["pair"]["pair_id"]] = {"identical": False, "error": (row or {}).get("failures")}
    # Does any other instrument change C at all?  Byte-compare helper output
    # with the primary configuration's output for the same compiled module.
    c_patch_effect = {}
    for program in programs:
        if program.get("language") != "C":
            continue
        for configuration in configurations:
            if configuration == PRIMARY:
                continue
            for run_index in range(1, args.runs + 1):
                left = results.get(f"run-{run_index}|{PRIMARY}|{program['id']}", {}).get("raw_sha256")
                right = results.get(f"run-{run_index}|{configuration}|{program['id']}", {}).get("raw_sha256")
                if left and right:
                    c_patch_effect[f"{configuration}|run-{run_index}|{program['pair']['pair_id']}"] = left == right
    write(output / "results.json", {"preregistration": preregistration, "results": results, "ir_census": census,
                                    "c_raw_identical_primary_vs_sensitivity": c_patch_effect,
                                    "determinism": determinism, "c_regression": regression,
                                    "configurations": configurations, "runs": args.runs})
    print("results written to", output / "results.json")


if __name__ == "__main__":
    main()
