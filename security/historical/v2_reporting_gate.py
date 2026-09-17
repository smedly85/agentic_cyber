"""Enforce the approved statistical unit and complete-disposition gate."""
from collections import defaultdict
from security.historical.v2_study import read, write, IDS


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
    return {"schema_version": 1, "population_fingerprint": population["population_fingerprint"],
            "mapping_artifact_fingerprint": mappings["mapping_artifact_fingerprint"],
            "population_count": 24, "completed_disposition_count": 24 - len(pending),
            "pending_cves": pending, "all_dispositions_complete": not pending,
            "depth_applicable_cve_count": sum(r["depth_applicability"] == "applicable" for r in results["members"]),
            "numeric_cve_count": sum(any(o["raw_call_depth"] is not None for o in r["observations"]) for r in results["members"]),
            "not_applicable_cve_count": sum(r["depth_applicability"] == "not_applicable" for r in results["members"]),
            "verified_cve_function_count": sum(len(m["functions"]) for m in mappings["members"]),
            "numeric_executable_function_measurement_count": sum(o["raw_call_depth"] is not None for values in groups.values() for o in values),
            "cve_function_groups_with_numeric_measurements": sum(any(o["raw_call_depth"] is not None for o in values) for values in groups.values()),
            "multiple_executable_function_groups": collisions,
            "approved_primary_observation_unit": "CVE_vulnerable_function",
            "approved_multi_executable_rule": "arithmetic_mean_within_CVE_vulnerable_function",
            "sensitivity_context_count": sum(len(values) for values in groups.values()),
            "sensitivity_contexts_are_independent_observations": False,
            "statistics_reportable": not pending,
            "gate_reason": "Passed: all 24 dispositions complete; approved function-level averaging rule preserves raw contexts and treats the 28-context analysis only as sensitivity." if not pending else "Pending member dispositions",
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
