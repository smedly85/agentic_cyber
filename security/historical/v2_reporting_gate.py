"""Enforce the approved statistical unit and complete-disposition gate."""
from collections import defaultdict
from security.historical.v2_study import ROOT, read, write, IDS


def assess(population, mappings, results):
    if len(results["members"]) != 24 or {r["cve_id"] for r in results["members"]} != set(IDS):
        raise RuntimeError("population accounting must remain exactly the frozen 24")
    if results["population_fingerprint"] != population["population_fingerprint"]:
        raise RuntimeError("population fingerprint mismatch")
    groups = defaultdict(list)
    for row in results["members"]:
        for obs in row["observations"]:
            groups[(row["cve_id"], obs["source_identity"])].append(obs)
    collisions = []
    for (cve, identity), values in sorted(groups.items()):
        if len(values) > 1:
            if len({v["specimen_id"] for v in values}) != len(values):
                raise RuntimeError("duplicate specimen observation")
            collisions.append({"cve_id": cve, "source_identity": identity,
                               "executable_specific_depths": [{"specimen_id": v["specimen_id"], "raw_call_depth": v["raw_call_depth"]}
                                                              for v in sorted(values, key=lambda v: v["specimen_id"])]})
    pending = [r["cve_id"] for r in results["members"] if not r["completed"]]
    coverage_pending = [{"cve_id": row["cve_id"], "executable": item["executable"]}
                        for row in results["members"] for item in row.get("executable_coverage", [])
                        if item["status"] == "pending"]
    coverage_complete = not coverage_pending
    numeric_context_count = sum(obs["raw_call_depth"] is not None
                                for row in results["members"] for obs in row["observations"])
    numeric_group_count = sum(any(obs["raw_call_depth"] is not None for obs in values)
                              for values in groups.values())
    unavailable = sum(row["depth_applicability"] == "applicable_in_principle" or
                      row["disposition"] == "affected_specimen_unavailable" for row in results["members"])
    reportable = not pending and coverage_complete
    return {"schema_version": 1, "population_fingerprint": population["population_fingerprint"],
            "mapping_artifact_fingerprint": mappings["mapping_artifact_fingerprint"],
            "population_count": 24, "completed_disposition_count": 24 - len(pending),
            "pending_cves": pending, "all_dispositions_complete": not pending,
            "depth_applicable_cve_count": sum(r["depth_applicability"] == "applicable" for r in results["members"]),
            "numeric_cve_count": sum(any(o["raw_call_depth"] is not None for o in r["observations"]) for r in results["members"]),
            "not_applicable_cve_count": sum(r["depth_applicability"] == "not_applicable" for r in results["members"]),
            "measurement_unavailable_cve_count": unavailable,
            "verified_cve_function_count": sum(len(m["functions"]) for m in mappings["members"]),
            "numeric_executable_function_measurement_count": numeric_context_count,
            "cve_function_groups_with_numeric_measurements": numeric_group_count,
            "multiple_executable_function_groups": collisions,
            "dependent_call_depth_locations": read("v2_protocol.json")["dependence_disclosure"],
            "approved_primary_observation_unit": "CVE_vulnerable_function",
            "approved_multi_executable_rule": "arithmetic_mean_within_CVE_vulnerable_function",
            "sensitivity_context_count": numeric_context_count,
            "sensitivity_contexts_are_independent_observations": False,
            "executable_coverage_gate_passed": coverage_complete,
            "pending_executable_coverage": coverage_pending,
            "statistics_reportable": reportable,
            "gate_reason": (f"Passed: all 24 dispositions and enumerated-executable coverage are complete; the approved function-level averaging rule preserves {numeric_context_count} raw contexts as sensitivity only."
                            if reportable else "Pending member dispositions or enumerated-executable coverage"),
            "statistics_computed": False}


def require_reportable(report):
    if not report["statistics_reportable"]:
        raise RuntimeError(report["gate_reason"])


if __name__ == "__main__":
    from security.historical.v2_validate import validate
    population, mappings, results, manifest = validate()
    manifest["specimens"].sort(key=lambda s: s["specimen_id"])
    for row in results["members"]:
        row["observations"].sort(key=lambda o: (o["specimen_id"], o["source_identity"]))
    write("v2_source_manifest.json", manifest)
    report = assess(population, mappings, results)
    statistics_path = ROOT / "v2_statistics.json"
    if statistics_path.exists() and results.get("study_status") == "complete":
        statistics = read("v2_statistics.json")
        report.update(statistics_reportable=True, statistics_computed=True,
                      statistics_artifact="security/historical/v2_statistics.json",
                      statistics_artifact_fingerprint=statistics["statistics_artifact_fingerprint"])
    write("v2_reporting_gate.json", report)
    if report["all_dispositions_complete"]:
        results["study_status"] = "all_dispositions_complete_aggregation_pending" if not report["statistics_reportable"] else results["study_status"]
        write("v2_semantic_results.json", results)
    print(report)
