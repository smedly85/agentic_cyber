"""Phase 2.7 bounded extraction audit. No metrics or source mutations."""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .ordered_diversity_clang_probe import (
    ROOT, main_definitions, recorded_flags, sha, stable_json, summarize_ast, walk,
)

PROFILE = "c11-posix2008-v1"
ADDITIONS = ["-D_POSIX_C_SOURCE=200809L"]
ENV_REMOVE = ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH",
              "SDKROOT", "MACOSX_DEPLOYMENT_TARGET", "CCC_OVERRIDE_OPTIONS")


def canonical_ids(value):
    """Audit equality only: replace dump-local pointer IDs, retaining aliasing.

    This is NOT function/name normalization or a diversity fingerprint. All
    remaining values, child ordering, coordinates and compiler nodes are retained.
    """
    ids = {}

    def visit(item, key=None):
        if isinstance(item, dict):
            return {k: visit(v, k) for k, v in sorted(item.items())}
        if isinstance(item, list):
            return [visit(v, key) for v in item]
        if isinstance(item, str) and key != "value" and re.fullmatch(r"0x[0-9a-fA-F]+", item):
            if item == "0x0":
                return "null-pointer-id"
            return ids.setdefault(item, f"dump-id-{len(ids)}")
        return item
    return visit(value)


def accept_ast(returncode, stdout):
    if returncode != 0:
        return None, "compiler_failure"
    try:
        tree = json.loads(stdout)
    except (ValueError, TypeError):
        return None, "invalid_json"
    if not isinstance(tree, dict) or tree.get("kind") != "TranslationUnitDecl":
        return None, "invalid_ast_root"
    return tree, "success"


def execute(command, env):
    try:
        r = subprocess.run(command, capture_output=True, env=env, timeout=120)
        return {"command": command, "returncode": r.returncode,
                "stdout": r.stdout.decode("utf-8", "replace"),
                "stderr": r.stderr.decode("utf-8", "replace")}
    except subprocess.TimeoutExpired:
        return {"command": command, "returncode": None, "stdout": "", "stderr": "timeout after 120 seconds"}


def extract(command, env, artifact):
    result = execute(command, env)
    artifact.write_text(result["stdout"], encoding="utf-8")
    tree, status = accept_ast(result["returncode"], result.pop("stdout"))
    result.update(status=status, raw_ast_artifact=str(artifact.relative_to(ROOT)),
                  raw_ast_sha256=sha(artifact.read_bytes()),
                  measurement_eligible=tree is not None)
    if tree is not None:
        result["id_normalized_ast_sha256"] = sha(stable_json(canonical_ids(tree)).encode())
    return result, tree


def attribution(tree, source, data):
    definitions, origins = main_definitions(tree, source)
    selected = {n["id"] for n in definitions}
    rows = []
    for node in tree.get("inner", []):
        if node.get("kind") != "FunctionDecl":
            continue
        body = any(c.get("kind") == "CompoundStmt" for c in node.get("inner", []))
        if body:
            loc = node.get("loc", {}).get("expansionLoc", node.get("loc", {}))
            offset = loc.get("offset", -1)
            token = data[offset:offset + loc.get("tokLen", 0)].decode("utf-8", "replace") if offset >= 0 else None
            rows.append({"name": node.get("name"), "origin": origins.get(node.get("id")),
                         "selected": node.get("id") in selected,
                         "source_name_token_matches": token == node.get("name") if node.get("id") in selected else None})
    return {"definitions": rows,
            "excluded_header_declarations": sum(n.get("kind") == "FunctionDecl" and n.get("id") not in selected for n in tree.get("inner", [])),
            "candidate_name_offsets_verified": all(r["source_name_token_matches"] for r in rows if r["selected"])}


def body_audit(tree, source):
    definitions, _ = main_definitions(tree, source)
    nodes = [n for f in definitions for c in f.get("inner", []) if c.get("kind") == "CompoundStmt" for n, _, _ in walk(c)]
    return {"implicit_flag_nodes": sum(bool(n.get("isImplicit")) for n in nodes),
            "implicit_kind_counts": dict(Counter(n["kind"] for n in nodes if n.get("kind", "").startswith("Implicit"))),
            "explicit_cast_nodes": sum(n.get("kind") == "CStyleCastExpr" for n in nodes),
            "note": "Compiler nodes are retained, not erased. ImplicitCastExpr is identified by kind even without isImplicit; absence of either marker is not proof of source authorship."}


def preprocessing(clang, flags, source, env, prefix):
    result = execute([clang, *flags, "-E", "-dD", str(source)], env)
    expanded = result.pop("stdout")
    prefix.with_suffix(".i").write_text(expanded, encoding="utf-8")
    result["preprocessed_sha256"] = sha(expanded.encode())
    result["artifact"] = str(prefix.with_suffix(".i").relative_to(ROOT))
    files = set()
    for match in re.finditer(r'^# \d+ ("(?:[^"\\]|\\.)*")', expanded, re.M):
        name = json.loads(match[1])
        if not name.startswith("<") and Path(name).is_file():
            files.add(name)
    result["input_files"] = [{"path": name, "sha256": sha(Path(name).read_bytes())} for name in sorted(files)]
    macros = execute([clang, *flags, "-E", "-dM", str(source)], env)
    result["macro_dump"] = macros
    return result


def macro_changes(before, after):
    def entries(text):
        return {line.split(None, 2)[1]: line for line in text.splitlines() if line.startswith("#define ")}
    left, right = entries(before), entries(after)
    return {key: {"before": left.get(key), "after": right.get(key)}
            for key in sorted(left.keys() | right.keys()) if left.get(key) != right.get(key)}


def run():
    old_path = ROOT / "docs/ordered_diversity_phase26_feasibility.json"
    old = json.loads(old_path.read_bytes())
    directory = ROOT / "build/ordered-diversity-phase27"
    directory.mkdir(parents=True, exist_ok=True)
    clang = shutil.which("clang")
    if not clang:
        raise RuntimeError("clang unavailable; no fallback")
    env = dict(os.environ)
    removed = {k: env.pop(k, None) for k in ENV_REMOVE}
    env["LC_ALL"] = "C"
    version = execute([clang, "--version"], env)
    report = {"schema_version": 1, "phase": "2.7", "profile": PROFILE,
              "analysis_only_additions": ADDITIONS, "compiler": version,
              "compiler_binary_sha256": sha(Path(clang).resolve().read_bytes()),
              "runner_sha256": sha(Path(__file__).read_bytes()),
              "phase26_helper_sha256": sha((ROOT / "scripts/ordered_diversity_clang_probe.py").read_bytes()),
              "phase26_report_sha256": sha(old_path.read_bytes()),
              "removed_environment": removed, "LC_ALL": "C", "candidates": []}
    for prior in old["candidates"]:
        source = ROOT / prior["source"]
        data = source.read_bytes()
        if sha(data) != prior["source_sha256"]:
            raise ValueError("source bytes differ from Phase 2.6")
        experiment_path = ROOT / prior["experiment"]
        experiment = json.loads(experiment_path.read_bytes())
        attempt = source.parent.parent
        metadata_path = attempt / "metadata.json"
        metadata = json.loads(metadata_path.read_bytes())
        success = next(r for r in metadata["loops"] if r["loop"] == metadata["success_loop"])
        if sha(data.replace(b"\r\n", b"\n")) != success["source_sha256"]:
            raise ValueError("historical successful-loop source hash mismatch")
        flags = recorded_flags(experiment)
        profile_flags = flags + ADDITIONS
        stem = prior["candidate_id"].replace("/", "_")
        row = {"candidate_id": prior["candidate_id"], "utility": prior["utility"], "checkpoint": prior["checkpoint"],
               "source": prior["source"], "source_sha256": sha(data), "historical_lf_sha256": success["source_sha256"],
               "compiler_version": version["stdout"], "analysis_profile": PROFILE, "analysis_flags": profile_flags,
               "historical": {"experiment": prior["experiment"], "recorded_build_command": experiment["build_command"],
                              "recorded_repository": experiment["repository"], "recorded_commit": experiment["repository_commit"],
                              "successful_loop": success, "final_outcomes": {k: metadata.get(k) for k in ("build_exit_code", "feature_test_exit_code", "extra_test_exit_code", "overall_success", "public_validation_success")},
                              "records": {}}, "attempts": []}
        for p in [experiment_path, metadata_path, attempt / "build.log", attempt / "feature-tests.log", attempt / "extra-tests.log"]:
            row["historical"]["records"][str(p.relative_to(ROOT))] = {"sha256": sha(p.read_bytes()), "tail": p.read_text()[-600:] if p.suffix == ".log" else None}
        security_record = attempt / "security_results.json"
        if security_record.is_file():
            security = json.loads(security_record.read_bytes())
            configuration = security.get("configuration", {})
            row["historical"]["adjacent_security_compiler_provenance"] = {
                "record": str(security_record.relative_to(ROOT)), "sha256": sha(security_record.read_bytes()),
                "configuration": {k: configuration.get(k) for k in ("compiler", "compiler_path", "compiler_version", "compiler_flags")},
                "qualification": "Evidence from separate security compilation in the same attempt; not an attestation of the functional build compiler, target or SDK."}
        else:
            row["historical"]["adjacent_security_compiler_provenance"] = None
        trees = []
        for name, chosen in [("recorded-flags", flags), ("profile-1", profile_flags), ("profile-2", profile_flags)]:
            command = [clang, *chosen, "-fsyntax-only", "-Xclang", "-ast-dump=json", str(source)]
            result, tree = extract(command, env, directory / f"{stem}-{name}.json")
            result["label"] = name
            row["attempts"].append(result)
            trees.append(tree)
        baseline, first, second = trees
        row["repeat_ast_equal_after_id_normalization"] = first is not None and second is not None and canonical_ids(first) == canonical_ids(second)
        row["preprocessing"] = preprocessing(clang, profile_flags, source, env, directory / stem)
        row["recorded_flags_preprocessing"] = preprocessing(clang, flags, source, env, directory / (stem + "-recorded"))
        row["macro_changes_from_recorded_flags"] = macro_changes(
            row["recorded_flags_preprocessing"]["macro_dump"]["stdout"],
            row["preprocessing"]["macro_dump"]["stdout"])
        row["source_preprocessor_directives"] = [line for line in data.decode().splitlines() if line.lstrip().startswith("#")]
        row["driver_configuration"] = execute([clang, *profile_flags, "-fsyntax-only", "-###", str(source)], env)
        row["profile_extraction_success"] = first is not None and second is not None
        row["source_unchanged"] = source.read_bytes() == data
        row["structure_evidence"] = summarize_ast(first, source, data) if first else None
        row["attribution"] = attribution(first, source, data) if first else None
        row["implicit_nodes"] = body_audit(first, source) if first else None
        if baseline and first:
            b = main_definitions(baseline, source)[0]
            a = main_definitions(first, source)[0]
            row["recorded_vs_profile_candidate_definitions_equal"] = canonical_ids(b) == canonical_ids(a)
            before = summarize_ast(baseline, source, data)
            keys = ("function_count", "function_body_nodes", "call_count", "call_resolutions", "direct_edges", "operators", "node_kinds", "control_kinds", "transfer_kinds")
            row["recorded_vs_profile_summary_changes"] = {k: {"before": before[k], "after": row["structure_evidence"][k]} for k in keys if before[k] != row["structure_evidence"][k]}
        else:
            row["recorded_vs_profile_candidate_definitions_equal"] = None
            row["recorded_vs_profile_summary_changes"] = None
        row["phase26_summary_changes"] = {k: {"before": prior["structure_evidence"][k], "after": row["structure_evidence"][k]} for k in ("function_count", "function_body_nodes", "call_count", "call_resolutions", "direct_edges", "operators", "node_kinds") if prior["structure_evidence"] and row["structure_evidence"] and prior["structure_evidence"][k] != row["structure_evidence"][k]}
        if prior["structure_evidence"] is None or row["structure_evidence"] is None:
            row["phase26_summary_changes"] = None
        report["candidates"].append(row)
        print(row["candidate_id"], "success", row["profile_extraction_success"], "repeat", row["repeat_ast_equal_after_id_normalization"], flush=True)
    report["pairs"] = {utility: all(r["profile_extraction_success"] and r["repeat_ast_equal_after_id_normalization"] and r["source_unchanged"] and r["preprocessing"]["returncode"] == 0 and r["preprocessing"]["macro_dump"]["returncode"] == 0 and r["attribution"]["candidate_name_offsets_verified"] for r in report["candidates"] if r["utility"] == utility) for utility in ("mkdir", "grep")}
    (ROOT / "docs/ordered_diversity_phase27_feasibility.json").write_text(stable_json(report), encoding="utf-8")


if __name__ == "__main__":
    run()
