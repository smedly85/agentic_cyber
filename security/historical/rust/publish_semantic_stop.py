"""Publish controlled failure evidence and NONNUMERIC historical accounting only."""
import json
from pathlib import Path

from semantic_gate import EXPECTED, HERE, ROOT, fingerprint, verify_frozen
from validate_semantic_instrument import sha, write


def make_accounting(mappings):
    records = []
    for m in mappings["records"]:
        contexts = []
        for f in m["vulnerable_functions"]:
            for executable in f["affected_executables"]:
                contexts.append({"source_identity": f["source_identity"],
                    "source_function": f["function"], "executable": executable,
                    "vulnerable_revision": f["affected_revision"],
                    "status": "analysis_failure", "measurement_attempted": False,
                    "reason": "blocked_by_required_controlled_dynamic_trait_case",
                    "raw_shortest_call_depth": None, "shortest_path": None,
                    "configured_entry_point": None, "source_scope_kind": None,
                    "measurement_class": "partial_location_measurements" if
                        m["mapping_status"] == "unresolved" else "verified_function_context",
                    "included_in_primary_statistics": False})
        records.append({"cve_id": m["cve_id"], "mapping_status": m["mapping_status"],
            "depth_applicability": m["depth_applicability"],
            "status": "not_applicable" if m["mapping_status"] == "not_applicable" else
                      "mapping_unresolved_partial" if m["mapping_status"] == "unresolved" else
                      "analysis_failure",
            "measurement_attempted": False, "function_contexts": contexts,
            "cve_min_depth": None, "cve_max_depth": None})
    return {"schema_version": 1, "frozen_inputs": EXPECTED, "stage": "blocked_before_pilots",
            "historical_measurements_performed": False, "records": records,
            "primary_statistics": {"status": "not_computed_instrument_failed",
                "numeric_function_observations": 0, "verified_cves_with_numeric_measurements": 0,
                "function_depth_distribution": None, "cve_depth_distribution": None},
            "aggregation_policy": {"unit": ["CVE", "verified_source_function"],
                "instances_within_executable": "minimum_reachable_legitimate_instance_depth",
                "executables_within_source_function": "arithmetic_mean",
                "unresolved_mappings_excluded": True}}


def render_table(mappings):
    lines = ["# Rust historical depth accounting — measurement blocked", "",
        "No historical build or semantic measurement was attempted. `—` is missing, not zero.",
        "The required controlled trait-object dispatch case failed. No distributions exist.", "",
        "| CVE | Utility/component | Vulnerable function(s) | Function depth(s) | CVE min depth | Status |",
        "| --- | --- | --- | --- | --- | --- |"]
    for m in mappings["records"]:
        fs = m["vulnerable_functions"]
        components = "; ".join(sorted({f["utility_or_shared_component"] for f in fs})) or "configuration/platform selection"
        functions = "; ".join(f["function"] for f in fs) or "not applicable"
        status = "not_applicable" if m["mapping_status"] == "not_applicable" else (
                 "mapping_unresolved_partial; measurement blocked" if m["mapping_status"] == "unresolved"
                 else "analysis_failure; controlled-instrument gate")
        lines.append(f"| {m['cve_id']} | {components} | {functions} | — | — | {status} |")
    return "\n".join(lines) + "\n"


def main():
    verify_frozen()
    out = ROOT / "build/historical-rust/semantic/validation"
    validation = json.loads((out / "semantic_validation.json").read_text())
    if validation["frozen_inputs"] != EXPECTED or validation["status"] != "failed":
        raise ValueError("This publisher is ONLY for an authenticated controlled stop")
    if validation["failure"].get("failed_cases") != ["dynamic_trait"]:
        raise ValueError("Review changed failure evidence before publishing")
    # Do not commit local machine paths, while retaining exact commands in cache.
    def portable(value):
        if isinstance(value, str):
            return value.replace(str(ROOT), "$REPO")
        if isinstance(value, list):
            return [portable(v) for v in value]
        if isinstance(value, dict):
            return {k: portable(v) for k, v in value.items()}
        return value
    validation = portable(validation)
    validation["commands"] = portable(json.loads((out / "commands.json").read_text()))
    validation["evidence_kind"] = "controlled_fixtures_only_not_historical_results"
    write(HERE / "semantic_validation.json", validation)
    backend = {"schema_version": 1, "status": "incompatible_for_required_trait_dispatch",
        "frozen_inputs": EXPECTED, "toolchain": validation["toolchain"],
        "backend": "SVF", "svf_version": "3.4", "analysis": "AndersenWaveDiff",
        "helper_source_sha256": sha(ROOT / "security/semantic_callgraph/native/semantic_callgraph_svf.cpp"),
        "toolchain_acquisition": json.loads((out.parent / "toolchain_acquisition.json").read_text()),
        "controlled_bitcode_method": "rustc --emit=llvm-bc plus llvm-link of exactly two fixture crates",
        "rustc_flags": validation["rustc_flags"],
        "historical_bitcode_method": "not_selected_required_instrument_gate_failed",
        "syntax_call_graph_fallback": False,
        "entry_policy": "Use source-qualified utility uumain only after proving standalone wrapper is mechanical; retain wrapper provenance; substantive wrappers are not contracted.",
        "historical_entries_configured": [], "projection_used": False}
    write(HERE / "semantic_backend.json", backend)
    write(HERE / "program_scopes.json", {"schema_version": 1, "frozen_inputs": EXPECTED,
        "historical_scopes": [], "status": "not_attempted_instrument_gate_failed",
        "controlled_scope": {"kind": "explicit_two_crate_fixture_not_linker_exact_executable",
            "crates": ["semantic_instrument", "semantic_dependency"],
            "runtime_boundary": "core panic routine remains external; no application definition omitted",
            "cargo_metadata": None, "cargo_lock": None, "cargo_used": False,
            "features": [], "crate_type": "rlib", "target": "x86_64-unknown-linux-gnu"}})
    mappings = json.loads((HERE / "vulnerable_function_mappings.json").read_text())
    write(HERE / "semantic_results.json", make_accounting(mappings))
    write(HERE / "reporting_gate.json", {"schema_version": 1, "frozen_inputs": EXPECTED,
        "status": "blocked", "population_measurement_permitted": False,
        "primary_numeric_reporting_permitted": False,
        "reason": "Required controlled trait-object dispatch unresolved",
        "controlled_passed": 12, "controlled_failed": 1,
        "pilots": [{"cve_id": c, "status": "not_run_instrument_gate_failed"}
                   for c in ("CVE-2026-35365", "CVE-2021-29934", "CVE-2026-35354")]})
    (HERE / "evidence/final-depth-table.md").write_text(render_table(mappings), encoding="utf-8")
    # The deterministic lock covers new semantic artifacts, not the frozen inputs.
    names = ["semantic_backend.json", "semantic_validation.json", "program_scopes.json",
             "semantic_results.json", "reporting_gate.json"]
    write(HERE / "semantic_artifact_manifest.json", {"schema_version": 1,
        "frozen_inputs": EXPECTED,
        "canonical_json_fingerprints": {n: fingerprint(json.loads((HERE / n).read_text())) for n in names},
        "table_sha256": sha(HERE / "evidence/final-depth-table.md")})
    print("Published controlled failure evidence; all 45 CVEs accounted for without measurements.")


if __name__ == "__main__":
    main()
