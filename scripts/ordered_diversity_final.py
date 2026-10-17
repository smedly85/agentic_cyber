"""Run only the two approved real C pairs using the Phase-2.7 profile."""
import json
import os
from pathlib import Path
import time
from importlib.metadata import version, PackageNotFoundError

from .ordered_diversity_clang_repro import ROOT, PROFILE, ENV_REMOVE, execute, canonical_ids
from .ordered_diversity_clang_probe import sha, stable_json
from .analysis.clang_ordered import adapt
from .analysis.ordered_exact import compare
from .analysis.ordered_distances import DEFAULT_EXCLUDE, alignment_search_size, _align, Budget, Limits


def run(*, exclude_regex=DEFAULT_EXCLUDE, forced_includes=()):
    evidence_path = ROOT / "docs/ordered_diversity_phase27_feasibility.json"
    evidence = json.loads(evidence_path.read_bytes())
    env = dict(os.environ)
    for key in ENV_REMOVE:
        env.pop(key, None)
    env["LC_ALL"] = "C"
    try:
        scipy_version = version("scipy")
    except PackageNotFoundError:
        scipy_version = None
    report = {"schema_version": 1, "profile": PROFILE, "phase27_evidence_sha256": sha(evidence_path.read_bytes()),
              "scipy_version": scipy_version, "compiler": evidence["compiler"], "pairs": [],
              "implementation_sha256": {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in [Path(__file__), ROOT / "scripts/analysis/clang_ordered.py", ROOT / "scripts/analysis/ordered_exact.py", ROOT / "scripts/analysis/ordered_distances.py"]}}
    groups = {}
    for row in evidence["candidates"]:
        source = ROOT / row["source"]
        command = row["attempts"][1]["command"]
        if sha(source.read_bytes()) != row["source_sha256"]:
            raise ValueError("candidate_source_changed")
        if sha(Path(command[0]).resolve().read_bytes()) != evidence["compiler_binary_sha256"]:
            raise ValueError("compiler_changed_since_profile_audit")
        for item in row["preprocessing"]["input_files"]:
            if sha(Path(item["path"]).read_bytes()) != item["sha256"]:
                raise ValueError("profile_header_or_source_changed:" + item["path"])
        start = time.monotonic()
        result = execute(command, env)
        adapted = adapt(result["stdout"], result["returncode"], source)
        if adapted["status"] == "success":
            normalized = sha(stable_json(canonical_ids(json.loads(result["stdout"]))).encode())
            if normalized != row["attempts"][1]["id_normalized_ast_sha256"]:
                raise ValueError("profile_ast_changed_since_repeatability_audit")
        summary = {"candidate_id": row["candidate_id"], "source_sha256": row["source_sha256"],
                   "extraction_status": adapted["status"], "command": command, "diagnostics": result["stderr"],
                   "function_count": len(adapted["functions"]), "function_names": [f["name"] for f in adapted["functions"]],
                   "adapted_node_count": len(adapted["audit"]), "call_count": len(adapted["call_sites"]),
                   "extraction_seconds": time.monotonic() - start,
                   "audit_provenance": "phase27 evidence: verified compiler/header/source hashes and full AST equality"}
        if sha(source.read_bytes()) != row["source_sha256"]:
            raise ValueError("candidate_source_changed_during_extraction")
        groups.setdefault((row["utility"], row["checkpoint"]), []).append((adapted, summary))
    for (utility, checkpoint), members in groups.items():
        if len(members) != 2:
            raise ValueError("expected_one_pair_per_population")
        left, right = members
        print("Comparing", utility, checkpoint, flush=True)
        comparison = compare(left[0], right[0], exclude_regex=exclude_regex, forced_includes=forced_includes)
        size = alignment_search_size(sum(not f["entry_point"] for f in left[0]["functions"]),
                                     sum(not f["entry_point"] for f in right[0]["functions"]))
        comparison["exhaustive_oracle"] = {"partial_injection_count": size, "limit": Limits().max_alignments, "status": "not_run_above_original_limit"}
        if size <= Limits().max_alignments and comparison["architecture"]["status"] == "success":
            started = time.monotonic()
            distance, mappings = _align(left[0], right[0], Budget(Limits()))
            ls, rs = comparison["scope"]["left"], comparison["scope"]["right"]
            compatible = [m for m in mappings if all(ls[a] == rs[b] for a, b in m.items())]
            if distance != comparison["architecture"]["distance"] or len(compatible) != comparison["architecture"]["admissible_optima_found"]:
                raise ValueError("exhaustive_oracle_disagreement")
            comparison["exhaustive_oracle"].update(status="agrees", architecture_distance=distance,
                all_architecture_optima=len(mappings), compatible_optima=len(compatible), seconds=time.monotonic() - started)
        for side, member in (("left", left), ("right", right)):
            decisions = comparison.get("scope", {}).get(side, {})
            member[1]["scope_excluded"] = [f["name"] for f in member[0]["functions"] if decisions.get(f["id"]) is False]
        report["pairs"].append({"utility": utility, "checkpoint": checkpoint,
                                "left": left[1], "right": right[1], "comparison": comparison})
        print(json.dumps(comparison), flush=True)
    (ROOT / "docs/ordered_diversity_final_results.json").write_text(stable_json(report), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-exclude-regex", default=DEFAULT_EXCLUDE)
    parser.add_argument("--strategy-include-function", action="append", default=[])
    args = parser.parse_args()
    run(exclude_regex=args.strategy_exclude_regex, forced_includes=args.strategy_include_function)
