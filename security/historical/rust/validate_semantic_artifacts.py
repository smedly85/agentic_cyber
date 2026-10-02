"""Offline fail-closed validation of the stopped Rust semantic experiment."""
from copy import deepcopy
import json
import sys

from semantic_gate import EXPECTED, HERE, ROOT, fingerprint, verify_frozen
from semantic_validation_checks import audit_case
from validate import validate_directory
from validate_semantic_instrument import CASES, sha
from publish_semantic_stop import make_accounting, render_table

sys.path.insert(0, str(ROOT))
from security.semantic_callgraph.backend import finalize_semantic_graph


def require(ok, message):
    if not ok:
        raise ValueError(message)


def validate_controlled(value):
    require(value["frozen_inputs"] == EXPECTED, "wrong frozen inputs")
    require(len(value["cases"]) == len(CASES), "missing/duplicate controlled cases")
    require({c["case"] for c in value["cases"]} == {c[0] for c in CASES}, "wrong controlled cases")
    require(value["definition_inventory_complete"] is True, "incomplete LLVM definition inventory")
    native = finalize_semantic_graph(value["semantic_graph"], entry_point="main")
    reachable = {f["name"] for f in native["functions"] if f["reachable_from_entry"]}
    require(all("entry_" + name in reachable for name, _, _ in CASES),
            "controlled entry pruned from native root")
    expected = {name: (target, depth) for name, target, depth in CASES}
    for case in value["cases"]:
        target, depth = expected[case["case"]]
        require(case["expected_depth"] == depth and case["target_source_name"] == target,
                "changed controlled expectation")
        require(case["configured_entry"] == "entry_" + case["case"], "changed scientific entry")
        graph = finalize_semantic_graph(value["semantic_graph"], entry_point=case["configured_entry"])
        matches = [f for f in graph["functions"] if f["name"].split("<")[0] == target]
        require(case["target_instances"] == matches, "instance/path evidence differs from semantic graph")
        depths = [f["raw_call_depth"] for f in matches if f["raw_call_depth"] is not None]
        require(case["measured_depth"] == (min(depths) if depths else None), "incorrect instance reduction")
        recomputed = audit_case(deepcopy(case), graph)
        require(case == recomputed, "incorrect controlled case verdict")
    failures = [c["case"] for c in value["cases"] if c["status"] != "passed"]
    require(value["status"] == ("failed" if failures else "passed"), "incorrect instrument verdict")
    if failures:
        require(value["failure"]["failed_cases"] == failures, "omitted failing cases")
        require(value["population_measurement_permitted"] is False, "failure gate bypass")


def validate_accounting(results, mappings):
    require(results == make_accounting(mappings), "blocked accounting mutated or contains measurements")
    require(len(results["records"]) == 45, "population accounting incomplete")


def validate_all():
    verify_frozen()
    original = validate_directory()  # Includes all 159 protected C artifact hashes.
    read = lambda name: json.loads((HERE / name).read_text(encoding="utf-8"))
    manifest = read("semantic_artifact_manifest.json")
    require(manifest["frozen_inputs"] == EXPECTED, "semantic lock has wrong frozen inputs")
    for name, expected in manifest["canonical_json_fingerprints"].items():
        require(fingerprint(read(name)) == expected, "semantic artifact changed: " + name)
    validation = read("semantic_validation.json")
    validate_controlled(validation)
    for name, checksum in validation["fixture_sha256"].items():
        require(sha(ROOT / "tests/fixtures/rust_semantic" / name) == checksum, "fixture changed")
    backend = read("semantic_backend.json")
    require(backend["helper_source_sha256"] == sha(ROOT / "security/semantic_callgraph/native/semantic_callgraph_svf.cpp"),
            "C semantic helper source changed")
    require(backend["syntax_call_graph_fallback"] is False, "lexical fallback forbidden")
    require(backend["projection_used"] is False, "unexpected path contraction")
    mappings = read("vulnerable_function_mappings.json")
    results = read("semantic_results.json")
    validate_accounting(results, mappings)
    table = HERE / "evidence/final-depth-table.md"
    require(table.read_text(encoding="utf-8") == render_table(mappings), "depth table mismatch")
    require(sha(table) == manifest["table_sha256"], "depth table changed")
    gate = read("reporting_gate.json")
    require(gate["status"] == "blocked" and not gate["population_measurement_permitted"] and
            not gate["primary_numeric_reporting_permitted"], "reporting gate bypass")
    require(not read("program_scopes.json")["historical_scopes"], "historical scope fabricated")
    return {**original, "controlled_passed": 12, "controlled_failed": 1,
            "historical_measurements": 0, "status": "valid_fail_closed_stop"}


if __name__ == "__main__":
    print(json.dumps(validate_all(), indent=2, sort_keys=True))
