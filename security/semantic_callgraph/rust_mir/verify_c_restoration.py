"""C controlled regressions and nine authenticated C bitcode replays; no Rust CVEs."""
import hashlib
import json
import re
from pathlib import Path
import shutil
import sys
import argparse

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "security/historical/rust"))
from semantic_gate import verify_frozen
from security.semantic_callgraph import BuildResult, analyze_build, build_bitcode, inventory_toolchain
from security.calibration.semantic_callgraph.run_calibration import validate_observation


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    verify_frozen()
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-label')
    args = parser.parse_args()
    if args.output_label and not args.output_label.replace('-', '').isalnum():
        raise ValueError('Invalid output label')
    out = (ROOT / 'build/rust-mir/c-validation' / args.output_label if args.output_label else
           ROOT / "build/rust-mir/c-restoration/regression")
    out.mkdir(parents=True, exist_ok=not bool(args.output_label))
    protected = json.loads((ROOT / 'security/historical/rust/protected_c_artifacts.json').read_text())['files']
    def check_frozen():
        verify_frozen()
        for name, checksum in protected.items():
            if hashlib.sha256((ROOT / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() != checksum:
                raise ValueError('STOP: protected C artifact changed: ' + name)
        helper_path = ROOT / 'build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf'
        if sha(helper_path) != 'ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2':
            raise ValueError('STOP: canonical C helper changed')
    check_frozen()
    # Preserve failed restoration diagnostics rather than overwriting them.
    prior=out/'results.json'
    archive=out.parent/'initial-rust-guard-failure.json'
    if prior.exists() and not json.loads(prior.read_text())['passed'] and not archive.exists():
        shutil.copy2(prior,archive)
        failed=out/'gnu-coreutils-9-7-sort/graph.json'
        if failed.exists(): shutil.copy2(failed,out.parent/'initial-rust-guard-graph.json')
    helper = ROOT / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf"
    inventory = inventory_toolchain(helper=helper)
    for name in ("clang", "llvm-link", "llvm-dis", "opt"):
        inventory["tools"][name]["path"] = "/usr/lib/llvm-21/bin/" + name
    root = ROOT / "security/calibration/semantic_callgraph"
    fixture_manifest = json.loads((root / "fixtures.json").read_text())
    rows = []
    for fixture in fixture_manifest["fixtures"]:
        build = build_bitcode(root, fixture["source_files"], out / fixture["id"],
                              compile_flags=fixture_manifest["compile_flags"], inventory=inventory)
        graph = analyze_build(build, entry_point=fixture["entry_point"], inventory=inventory)
        errors = validate_observation(fixture, build.status, graph)
        rows.append({"fixture": fixture["id"], "passed": not errors, "errors": errors})
        (out / (fixture["id"] + ".json")).write_text(json.dumps(graph, indent=2))
        print("C controlled", fixture["id"], not errors, flush=True)
    baseline_path = ROOT / "security/historical/semantic_validation.json"
    baseline = json.loads(baseline_path.read_text())
    graphs = {}
    replay = []
    for program in baseline["programs"]:
        slug = re.sub(r"[^a-z0-9]+", "-", "-".join(program["program_key"]).lower()).strip("-")
        original = ROOT / "build/semantic-historical-validation" / slug / "linked.bc"
        expected = next(b["sha256"] for b in program["bitcode_files"] if b["path"] == "linked.bc")
        if not original.exists() and program["program_key"] == ["gnu-coreutils", "9.7", "sort"]:
            # The original v1 archive-superset module was relocated during the
            # later C scope study. Accept it ONLY by the frozen byte fingerprint.
            relocated = ROOT / "build/semantic-scope-checkpoint/archive_superset/linked.bc"
            if relocated.exists() and sha(relocated) == expected:
                original = relocated
        destination = out / slug
        destination.mkdir(exist_ok=True)
        if not original.exists() or sha(original) != expected:
            replay.append({"program": slug, "status": "authenticated_bitcode_unavailable"})
            continue
        copied = destination / "linked.bc"
        shutil.copyfile(original, copied)
        build = BuildResult("success", copied, tuple(program["source_files"]), (), (), (),
                            "x86_64-unknown-linux-gnu", {"replay_of_authenticated_frozen_bitcode": expected})
        entry = program["entry_point"]
        if isinstance(entry, dict):
            entry = entry.get("function") or entry.get("configured")
        graph = analyze_build(build, entry_point=entry, inventory=inventory)
        (destination / "graph.json").write_text(json.dumps(graph, indent=2))
        graphs[program["source_tree"]] = graph
        replay.append({"program": slug, "status": graph["analysis_status"], "bitcode_sha256": expected,
                       "authenticated_input_path": original.relative_to(ROOT).as_posix(),
                       "input_unchanged": sha(original) == expected})
        print("C historical replay", slug, graph["analysis_status"], flush=True)
    observations = []
    for old in baseline["observations"]:
        graph = graphs.get(old["vulnerable_source_tree"], {})
        matches = [f for f in graph.get("functions", []) if f["identity"] == old["mapped_semantic_identity"]]
        checks = {"one_source_identity": len(matches) == 1}
        current = None
        if len(matches) == 1:
            current = matches[0]
            checks.update({"depth_unchanged": current["raw_call_depth"] == old["semantic_raw_call_depth"],
                "full_path_and_target_sets_unchanged": current["shortest_call_path"] == old["shortest_semantic_path"],
                "reachability_unchanged": current["reachable_from_entry"] == (old["semantic_raw_call_depth"] is not None),
                "status_unchanged": current["semantic_status"] == old["semantic_mapping_status"]})
        observations.append({"cve": old["cve"], "source_identity": old["mapped_semantic_identity"],
                             "expected": old, "actual": current, "checks": checks, "passed": all(checks.values())})
    result = {"controlled": rows, "historical_programs": replay, "observations": observations,
              "baseline_sha256": sha(baseline_path), "method": "replay_of_frozen_hash_authenticated_LLVM_modules",
              "historical_rust_measurements": False,
              "passed": len(rows) == 11 and len(observations) == 9 and all(r["passed"] for r in rows + observations),
              "protected_c_files_unchanged": len(protected)}
    check_frozen()
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print("C regression overall", result["passed"], flush=True)
    if not result['passed']:
        raise SystemExit('STOP: C regression changed')


if __name__ == "__main__":
    main()
