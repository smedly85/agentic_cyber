"""One bounded manifest-based study; existing Clang profile and A/S are unchanged."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from importlib.metadata import version

from .ordered_diversity_clang_probe import ROOT, recorded_flags, sha, stable_json
from .ordered_diversity_clang_repro import PROFILE, ADDITIONS, ENV_REMOVE, execute, preprocessing
from .analysis.clang_ordered import adapt
from .analysis.ordered_exact import compare, ExactLimits, scope
from .analysis.ordered_distances import DEFAULT_EXCLUDE
from .analysis.ordered_thresholds import GRID, analyze_population, population_key

REPORT = ROOT / "docs/ordered_diversity_threshold_pairwise.json"
RESULTS = ROOT / "docs/ordered_diversity_threshold_results.json"
TABLE = ROOT / "docs/ordered_diversity_threshold_results.csv"
COMPARISON_BUDGET_SECONDS = 900
PAIR_HARD_TIMEOUT = 100


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(stable_json(value), encoding="utf-8")
    temporary.replace(path)


def unavailable(reason):
    return {metric: {"status": "unavailable", "distance": None, "reason": reason}
            for metric in ("architecture", "strategy")}


def select_populations(manifest):
    groups = []
    for utility, checkpoint, expected in (("mkdir", "002", 7), ("grep", "004", 10)):
        members = sorted((c for c in manifest["candidates"] if c["utility"] == utility and c["checkpoint_id"] == checkpoint), key=lambda c: c["candidate_id"])
        if len(members) != expected or len({population_key(c) for c in members}) != 1:
            raise ValueError("population_size_or_formal_run_mismatch")
        if len({c["candidate_id"] for c in members}) != expected:
            raise ValueError("duplicate_candidate_identity")
        if any(c["functional_population_status"] != "public_checkpoint_stage_success" for c in members):
            raise ValueError("manifest_contains_non_successful_candidate")
        groups.append({"formal_run_id": members[0]["formal_run_id"], "utility": utility,
                       "checkpoint": checkpoint, "candidates": [], "pairs": [], "manifest_members": members})
    return groups


def extract_member(member, clang, env, directory, profile_error):
    row = dict(member)
    start = time.monotonic()
    row.update(extraction_status="unavailable", comparison_eligible=False, failure_reason=None)
    try:
        if profile_error:
            raise ValueError(profile_error)
        source = (ROOT / member["candidate_source"]).resolve()
        source.relative_to(ROOT.resolve())
        if source.suffix.lower() != ".c":
            raise ValueError("unsupported_language")
        data = source.read_bytes()
        row["source_sha256"] = sha(data)
        row["lf_normalized_sha256"] = sha(data.replace(b"\r\n", b"\n"))
        if member["candidate_source_sha256"] not in {row["source_sha256"], row["lf_normalized_sha256"]}:
            raise ValueError("manifest_source_hash_mismatch")
        row["source_verification"] = "raw_bytes_match" if row["source_sha256"] == member["candidate_source_sha256"] else "only_CRLF_to_LF_matches_manifest"
        experiment_path = source.parents[2] / "experiment.json"
        experiment = json.loads(experiment_path.read_bytes())
        flags = recorded_flags(experiment) + ADDITIONS
        row["experiment"] = {"path": str(experiment_path.relative_to(ROOT)), "sha256": sha(experiment_path.read_bytes()),
                             "recorded_build_command": experiment["build_command"], "analysis_flags": flags}
        command = [clang, *flags, "-fsyntax-only", "-Xclang", "-ast-dump=json", str(source)]
        result = execute(command, env)
        prefix = directory / sha(member["candidate_id"].encode())[:16]
        ast_path = prefix.with_suffix(".ast.json")
        ast_path.write_text(result["stdout"], encoding="utf-8")
        representation = adapt(result["stdout"], result["returncode"], source)
        row.update(command=command, compiler_returncode=result["returncode"], diagnostics=result["stderr"],
                   extraction_status=representation["status"], adapter_reason=representation.get("reason"),
                   raw_ast_artifact=str(ast_path.relative_to(ROOT)), raw_ast_sha256=sha(ast_path.read_bytes()))
        row["preprocessing"] = preprocessing(clang, flags, source, env, prefix)
        row["source_unchanged"] = source.read_bytes() == data
        if not row["source_unchanged"]:
            raise ValueError("source_changed_during_analysis")
        if row["preprocessing"]["returncode"] != 0 or row["preprocessing"]["macro_dump"]["returncode"] != 0:
            raise ValueError("preprocessing_provenance_unavailable")
        if representation["status"] != "success":
            raise ValueError("extraction:" + representation["status"] + ":" + str(representation.get("reason", "")))
        decisions = scope(representation, DEFAULT_EXCLUDE, ())
        row.update(function_count=len(representation["functions"]), call_count=len(representation["call_sites"]),
                   unresolved_calls=sum(c["resolution"].startswith("unresolved") for c in representation["call_sites"]),
                   event_count=len(representation["audit"]),
                   functions=[{"id": f["id"], "name": f["name"], "strategy_included": decisions[f["id"]]} for f in representation["functions"]])
        cache = prefix.with_suffix(".representation.json")
        save(cache, representation)
        row.update(representation_artifact=str(cache.relative_to(ROOT)), representation_sha256=sha(cache.read_bytes()), comparison_eligible=True)
    except Exception as exc:
        row["failure_reason"] = type(exc).__name__ + ":" + str(exc)
    row["extraction_seconds"] = time.monotonic() - start
    return row


def worker(left_path, right_path, output):
    try:
        value = compare(json.loads(Path(left_path).read_bytes()), json.loads(Path(right_path).read_bytes()), limits=ExactLimits())
    except Exception as exc:
        value = unavailable("comparison_exception:" + type(exc).__name__ + ":" + str(exc))
    save(Path(output), value)


def report_thresholds(report):
    result = {"schema_version": 1, "threshold_grid": GRID, "populations": [],
              "pairwise_report_sha256": sha(REPORT.read_bytes()), "scipy_version": version("scipy"),
              "method": "average linkage on complete precomputed scalar matrices only; endpoint scenarios for S",
              "silhouette": "precomputed distances; singleton observation silhouette=0; undefined unless 2<=k<n",
              "singleton_rate": "number of observations in singleton families / population size; duplicates retain their observation weight"}
    table = []
    for group in report["populations"]:
        analysis = analyze_population(group["candidates"], group["pairs"])
        metadata = {k: group[k] for k in ("formal_run_id", "utility", "checkpoint")}
        result["populations"].append({**metadata, **analysis})
        for scenario, data in analysis["scenarios"].items():
            metric = "architecture" if scenario == "architecture_exact" else "strategy"
            summary = analysis["matrices"][metric + "_summary"]
            for row in data["rows"]:
                table.append({**metadata, "scenario": scenario, "available_pairs": summary["available_pairs"],
                              "total_pairs": summary["total_pairs"], "estimate_scope": summary["estimate_scope"],
                              **{k: json.dumps(v) if isinstance(v, list) else v for k, v in row.items()}})
    save(RESULTS, result)
    fields = list(dict.fromkeys(key for row in table for key in row))
    with TABLE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(table)
    return result


def run():
    manifest_path = ROOT / "security/generated_candidate_population.json"
    manifest_bytes = manifest_path.read_bytes()
    populations = select_populations(json.loads(manifest_bytes))
    reference_path = ROOT / "docs/ordered_diversity_phase27_feasibility.json"
    reference = json.loads(reference_path.read_bytes())
    clang = shutil.which("clang")
    env = dict(os.environ)
    removed = {key: env.pop(key, None) for key in ENV_REMOVE}
    env["LC_ALL"] = "C"
    profile_error = None
    try:
        if not clang or sha(Path(clang).resolve().read_bytes()) != reference["compiler_binary_sha256"]:
            raise ValueError("compiler_does_not_match_phase27_profile")
        for row in reference["candidates"]:
            for item in row["preprocessing"]["input_files"]:
                if not item["path"].endswith(".c") and sha(Path(item["path"]).read_bytes()) != item["sha256"]:
                    raise ValueError("profile_header_drift:" + item["path"])
    except Exception as exc:
        profile_error = str(exc)
    directory = ROOT / "build/ordered-diversity-threshold-study"
    directory.mkdir(parents=True, exist_ok=True)
    paths = [Path(__file__), ROOT / "scripts/analysis/ordered_thresholds.py", ROOT / "scripts/analysis/ordered_exact.py",
             ROOT / "scripts/analysis/ordered_distances.py", ROOT / "scripts/analysis/clang_ordered.py",
             ROOT / "scripts/ordered_diversity_clang_repro.py", ROOT / "scripts/ordered_diversity_clang_probe.py"]
    report = {"schema_version": 1, "study": "bounded_exploratory_order_aware_threshold_sensitivity_v1",
              "manifest": str(manifest_path.relative_to(ROOT)), "manifest_sha256": sha(manifest_bytes),
              "profile": PROFILE, "phase27_evidence_sha256": sha(reference_path.read_bytes()),
              "compiler": execute([clang, "--version"], env) if clang else None,
              "compiler_binary_sha256": sha(Path(clang).resolve().read_bytes()) if clang else None,
              "profile_verification_error": profile_error, "removed_environment": removed, "LC_ALL": "C",
              "threshold_grid": GRID, "legacy_030": "comparison reference only; no selected primary threshold",
              "algorithm_sha256": {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in paths},
              "packages": {name: version(name) for name in ("scipy", "numpy")}, "python": sys.version,
              "comparison_limits": vars(ExactLimits()), "comparison_budget_seconds": COMPARISON_BUDGET_SECONDS,
              "pair_process_hard_timeout_seconds": PAIR_HARD_TIMEOUT,
              "extraction_budget": "17 AST calls maximum, each with the existing 120-second timeout; 2 preprocessing calls per candidate, also 120 seconds each",
              "comparison_order": "mkdir then grep; lexicographically sorted candidate IDs; unordered pairs only",
              "scope": {"exclude_regex": DEFAULT_EXCLUDE, "forced_includes": [], "main_always_included": True},
              "populations": populations}
    for group in populations:
        for member in group.pop("manifest_members"):
            row = extract_member(member, clang, env, directory, profile_error)
            group["candidates"].append(row)
            print("EXTRACT", member["candidate_id"], row["extraction_status"], row["failure_reason"], flush=True)
            save(REPORT, report)
    deadline = time.monotonic() + COMPARISON_BUDGET_SECONDS
    for group in populations:
        for left, right in itertools.combinations(group["candidates"], 2):
            if population_key(left) != population_key(right):
                raise ValueError("cross_population_comparison_refused")
            started = time.monotonic()
            if not left["comparison_eligible"] or not right["comparison_eligible"]:
                value = unavailable("candidate_extraction_or_provenance_unavailable")
            elif started >= deadline:
                value = unavailable("study_comparison_budget_exhausted")
            else:
                left_path, right_path = ROOT / left["representation_artifact"], ROOT / right["representation_artifact"]
                if sha(left_path.read_bytes()) != left["representation_sha256"] or sha(right_path.read_bytes()) != right["representation_sha256"]:
                    raise ValueError("cached_representation_hash_mismatch")
                output = directory / "current-comparison.json"
                if output.exists():
                    output.unlink()
                try:
                    process = subprocess.run([sys.executable, "-m", "scripts.ordered_diversity_threshold_study", "--worker",
                                              str(left_path), str(right_path), str(output)], cwd=ROOT,
                                             capture_output=True, text=True, timeout=min(PAIR_HARD_TIMEOUT, deadline - started), env=env)
                    value = json.loads(output.read_bytes()) if process.returncode == 0 and output.exists() else unavailable("comparison_worker_failure:" + process.stderr[-2000:])
                except subprocess.TimeoutExpired:
                    value = unavailable("pair_process_hard_timeout_or_study_budget")
            pair = {"left": left["candidate_id"], "right": right["candidate_id"],
                    "comparison_seconds": time.monotonic() - started, "comparison": value}
            group["pairs"].append(pair)
            print("PAIR", group["utility"], len(group["pairs"]), value["architecture"]["status"], value["strategy"]["status"], value["strategy"].get("reason", ""), flush=True)
            save(REPORT, report)
        group["coverage"] = {"population_size": len(group["candidates"]), "total_pairs": len(group["pairs"]),
                             "extraction_statuses": dict(Counter(c["extraction_status"] for c in group["candidates"])),
                             **{metric: dict(Counter(p["comparison"][metric]["status"] for p in group["pairs"])) for metric in ("architecture", "strategy")}}
    report["completed"] = True
    save(REPORT, report)
    report_thresholds(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", nargs=3)
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(*args.worker)
    elif args.summarize_only:
        report_thresholds(json.loads(REPORT.read_bytes()))
    else:
        run()
