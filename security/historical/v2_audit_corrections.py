"""Apply the independent primary-evidence corpus corrections without measuring."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from security.historical.analysis import verify_source_tree_sha256
from security.historical.v2_study import ROOT, fingerprint, read, write
from security.historical import semantic_validation as v


PRIOR_4998_REVIEW_REASON = (
    "The package ledger includes the cp symlink-preservation vulnerability; cp is not a target utility.")
CURRENT_4998_CORRECTION_RATIONALE = (
    "The study selects the disclosure-demonstrated FreeBSD 5.0 implementation for the single "
    "CVE-2007-4998 measurement. GNU Fileutils 4.1 predates the later destination-history guard "
    "and contains a related weaker overwrite-existing-files form of the defect, but is retained "
    "only as descriptive defect-class proxy evidence and is excluded from every CVE denominator "
    "and statistic.")
PROXY_4998_REASON = (
    "GNU Fileutils 4.1 contains a related weaker overwrite-existing-files form of the defect. "
    "The study uses FreeBSD 5.0 as the single selected historically affected implementation for "
    "CVE-2007-4998; the GNU specimen is descriptive defect-class proxy evidence only and does not "
    "enter any CVE denominator or statistic.")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coverage_for(mapping, observations):
    expected = mapping.get("expected_affected_executables", [])
    pairs = {(o["specimen_id"].rsplit("/", 1)[1], o["source_identity"]): o
             for o in observations if o["raw_call_depth"] is not None}
    rows = []
    for program in expected:
        identities = {function["source_identity"] for function in mapping["functions"]
                      if program in function.get("executables", mapping.get("programs", []))}
        measured = identities and all((program, identity) in pairs for identity in identities)
        rows.append({"executable": program,
                     "status": "measured_vulnerable_context" if measured else "pending",
                     "required_source_identities": sorted(identities)})
    return rows


def freeze():
    population = read("v2_population.json")
    mappings = read("v2_vulnerable_function_mappings.json")
    results = read("v2_semantic_results.json")
    manifest = read("v2_source_manifest.json")
    protocol = read("v2_protocol.json")
    repo = ROOT.parents[1]

    pop_4998 = next(row for row in population["members"] if row["cve_id"] == "CVE-2007-4998")
    pop_4998.update(affected_project_package="FreeBSD base system and other affected cp implementations",
                    implementation_family="FreeBSD base-system cp",
                    gnu_lineage_relationship="non_gnu_affected_implementation_in_fixed_population")
    pop_4998["prior_review_provenance"]["reason"] = PRIOR_4998_REVIEW_REASON
    population["population_fingerprint"] = fingerprint({k: value for k, value in population.items()
                                                          if k != "population_fingerprint"})
    population_fp = population["population_fingerprint"]

    by_mapping = {row["cve_id"]: row for row in mappings["members"]}
    old_4998 = by_mapping["CVE-2007-4998"]
    acquisition = read("v2_freebsd_cp_acquisition.json")
    source = ROOT / acquisition["source_tree"]
    verify_source_tree_sha256(source, acquisition["source_tree_sha256"])
    disclosure = repo / "build/historical-v2/downloads/cp-disclosure"
    cve_record = repo / "build/historical-v2/downloads/CVE-2007-4998.json"
    freebsd_cp = source / "bin/cp/cp.c"
    by_mapping["CVE-2007-4998"] = {
        "cve_id": "CVE-2007-4998", "completed": True, "mapping_status": "verified",
        "depth_applicability": "applicable", "mapping_confidence": "verified_primary_disclosure_and_authenticated_release_source",
        "mapping_frozen_before_new_measurement": True, "freeze_stage": "blocking_audit_correction_before_semantic_measurement",
        "project": "FreeBSD base-system cp", "affected_version": "FreeBSD 5.0-RELEASE",
        "affected_revision": acquisition["release_revision"], "fix_revision": None,
        "source_tree": acquisition["source_tree"], "source_tree_sha256": acquisition["source_tree_sha256"],
        "programs": ["cp"], "expected_affected_executables": ["cp"], "entry_point": "main",
        "functions": [{"source_file": "bin/cp/cp.c", "function": "copy",
                       "source_identity": "bin/cp/cp.c::copy", "source_sha256": sha(freebsd_cp),
                       "executables": ["cp"]}],
        "authoritative_sources": [
            {"role": "substantive_vendor_disclosure_and_reproducer", "url": "https://bugzilla.redhat.com/show_bug.cgi?id=356471"},
            {"role": "CVE_record", "url": "https://cveawg.mitre.org/api/cve/CVE-2007-4998"},
            {"role": "affected_release_source", "url": "https://github.com/freebsd/freebsd-src/tree/release/5.0.0/bin/cp"}],
        "vulnerability_evidence": [
            {"name": "cp-disclosure", "url": "https://bugzilla.redhat.com/show_bug.cgi?id=356471",
             "cache_path": disclosure.relative_to(repo).as_posix(), "sha256": sha(disclosure)},
            {"name": "CVE-2007-4998.json", "url": "https://cveawg.mitre.org/api/cve/CVE-2007-4998",
             "cache_path": cve_record.relative_to(repo).as_posix(), "sha256": sha(cve_record)},
            {"name": "freebsd-5.0-source-and-sysroot-acquisition",
             "artifact": "security/historical/v2_freebsd_cp_acquisition.json",
             "sha256": sha(ROOT / "v2_freebsd_cp_acquisition.json")}],
        "mapping_reason": (
            "The vendor disclosure gives an executable FreeBSD 5.0 reproducer: under cp -R, a first source symlink and later regular source with the same basename are copied to one destination. Independently reading the pinned release source identifies bin/cp/cp.c::copy as the vulnerable orchestration point: it reuses the destination pathname across source roots, follows the just-created destination link with stat, and dispatches the later regular source without rejecting a destination created earlier in the invocation. copy_link implements the requested preservation operation; copy_file performs ordinary single-destination open/truncate behavior and is reached only after copy has lost the security-relevant destination history, so neither is promoted as a separate vulnerable function."),
        "correction_rationale": CURRENT_4998_CORRECTION_RATIONALE,
        "specimen_selection_reason": (
            "The disclosure explicitly demonstrates FreeBSD 5.0 as affected. The source is pinned by the annotated release/5.0.0 tag and Git blob identities; selection was completed before semantic depth measurement."),
        "nearby_function_exclusions": [
            {"source_identity": "bin/cp/utils.c::copy_link", "reason": "Creates the preserved link requested for the first source; it does not decide whether a later source may reuse that destination."},
            {"source_identity": "bin/cp/utils.c::copy_file", "reason": "Ordinary file-copy sink; the CVE-specific multi-source destination-history failure occurs in copy before dispatch."}],
        "non_cve_proxy_evidence": {
            "status": "descriptive_defect_class_proxy_only", "project": "GNU Fileutils", "version": "4.1",
            "specimen_id": "fileutils-4.1/cp", "source_identity": "src/copy.c::copy_internal",
            "semantic_depth": 3, "retained_mapping_fingerprint": old_4998["mapping_fingerprint"],
            "excluded_from": ["verified_CVE_function_observations", "numeric_CVE_denominator",
                              "primary_function_statistics", "CVE_weighted_statistics",
                              "executable_context_sensitivity_statistics"],
            "reason": PROXY_4998_REASON}}

    old_1039 = by_mapping["CVE-2005-1039"]
    source_1039 = ROOT / "sources/coreutils-5.2.1"
    verify_source_tree_sha256(source_1039, "7c7ad7a1955ca0ef4a1f899bcd1974a2ab17fee7c6a1a7a239ec08b0aff8ecf5")
    by_mapping["CVE-2005-1039"] = {
        **old_1039, "mapping_status": "verified", "freeze_stage": "blocking_audit_correction_before_new_measurement",
        "project": "GNU Coreutils", "source_tree": "sources/coreutils-5.2.1",
        "source_tree_sha256": "7c7ad7a1955ca0ef4a1f899bcd1974a2ab17fee7c6a1a7a239ec08b0aff8ecf5",
        "programs": ["mkdir", "mkfifo", "mknod"],
        "expected_affected_executables": ["mkdir", "mkfifo", "mknod"], "entry_point": "main",
        "functions": [
            {"source_file": "src/mkdir.c", "function": "main", "source_identity": "src/mkdir.c::main",
             "source_sha256": sha(source_1039 / "src/mkdir.c"), "executables": ["mkdir"]},
            {"source_file": "lib/makepath.c", "function": "make_path", "source_identity": "lib/makepath.c::make_path",
             "source_sha256": sha(source_1039 / "lib/makepath.c"), "executables": ["mkdir"]},
            {"source_file": "src/mkfifo.c", "function": "main", "source_identity": "src/mkfifo.c::main",
             "source_sha256": sha(source_1039 / "src/mkfifo.c"), "executables": ["mkfifo"]},
            {"source_file": "src/mknod.c", "function": "main", "source_identity": "src/mknod.c::main",
             "source_sha256": sha(source_1039 / "src/mknod.c"), "executables": ["mknod"]}],
        "mapping_reason": (
            "The disclosure explicitly enumerates mkdir, mkfifo and mknod when -m is used. In Coreutils 5.2.1 each executable's main creates the filesystem object and then changes mode through the pathname, permitting substitution between creation and chmod. mkdir's -p path independently uses lib/makepath.c::make_path for create-then-pathname-chmod behavior. make_path is not linked by mkfifo or mknod and is therefore restricted to the mkdir context; make_dir only creates/reports state and remains excluded."),
        "specimen_selection_reason": "Authenticated frozen Coreutils 5.2.1 pilot source; add linker-exact mkfifo and mknod contexts without changing the pilot mkdir specimen or depths."}

    # Clean machine-readable source serialization and self-contained rationale
    # for every reused pilot without altering its mapping.
    for mapping in by_mapping.values():
        if mapping.get("mapping_status") == "verified_pilot_reuse":
            record = mapping["vulnerability_evidence"]
            urls = mapping.get("authoritative_sources", [])
            mapping["authoritative_evidence"] = [
                {"role": "authoritative_source", "ordinal": index + 1, "url": url}
                for index, url in enumerate(urls)]
            mapping.pop("authoritative_sources", None)
            mapping["mapping_reason"] = record["notes"]
            mapping.setdefault("programs", [record["utility"]])
            mapping.setdefault("expected_affected_executables", list(mapping["programs"]))
            for function in mapping["functions"]:
                function.setdefault("executables", list(mapping["programs"]))
        elif mapping.get("programs"):
            mapping.setdefault("expected_affected_executables", list(mapping["programs"]))
            for function in mapping["functions"]:
                function.setdefault("executables", list(mapping["programs"]))
        mapping.setdefault("mapping_reason", mapping.get("reason"))

    by_mapping["CVE-2009-4135"]["fix_revision"] = "ae034822c535fa5168069a75fb5e1c58f93a7834"
    for evidence in by_mapping["CVE-2009-4135"]["vulnerability_evidence"]:
        if "ae034822c535fa5" in evidence.get("url", ""):
            evidence["url"] = "https://github.com/coreutils/coreutils/commit/ae034822c535fa5168069a75fb5e1c58f93a7834.patch"
    by_mapping["CVE-2017-2616"]["affected_range_discrepancy"] = (
        "The CNA/NVD serialization lists version 2.32.1 as affected while its prose says versions before 2.32.1. The primary upstream fix is dated 2017-02-01 and release 2.29.1 predates and contains the exact stale-child-PID code fixed by that commit. The authenticated 2.29.1 specimen therefore remains directly source-validated despite the inconsistent database version field.")

    mappings["members"] = [by_mapping[row["cve_id"]] for row in mappings["members"]]
    for mapping in mappings["members"]:
        mapping.pop("mapping_fingerprint", None)
        mapping["mapping_fingerprint"] = fingerprint(mapping)
    mappings.update(population_fingerprint=population_fp,
                    freeze_status="blocking_audit_corrections_frozen_before_new_semantic_measurement")
    mappings.pop("mapping_artifact_fingerprint", None)
    mappings["mapping_artifact_fingerprint"] = fingerprint(mappings)

    by_result = {row["cve_id"]: row for row in results["members"]}
    for cve, mapping in by_mapping.items():
        row = by_result[cve]
        row["mapping_fingerprint"] = mapping["mapping_fingerprint"]
        if cve == "CVE-2007-4998":
            row.update(completed=False, disposition="pending", depth_applicability="applicable",
                       observations=[], analysis_status="pending",
                       reason="Affected FreeBSD 5.0 mapping frozen; linker-exact semantic measurement pending. The GNU proxy is excluded.")
        elif cve == "CVE-2005-1039":
            row.update(completed=False, disposition="pending",
                       reason="Corrected four-function mapping frozen; mkfifo and mknod linker-exact measurements pending.")
        row["executable_coverage"] = coverage_for(mapping, row["observations"])
    results.update(population_fingerprint=population_fp, study_status="in_progress_no_population_statistics")
    manifest["population_fingerprint"] = population_fp
    proxy = next(specimen for specimen in manifest["specimens"] if specimen["specimen_id"] == "fileutils-4.1/cp")
    proxy.update(evidence_role="non_CVE_proxy_only", excluded_from_CVE_2007_4998_statistics=True)
    protocol["population_fingerprint"] = population_fp
    protocol["multi_program_rule"] = (
        "The observation unit is (CVE, vulnerable function). Executable membership is disclosure-governed and frozen per CVE; shared functions preserve each affected executable context and use the approved arithmetic mean within (CVE,function).")
    protocol["dependence_disclosure"] = [
        {"specimen": "coreutils-5.0/ls", "source_identity": "src/ls.c::init_column_info", "depth": 2,
         "counted_for": ["CVE-2003-0853", "CVE-2003-0854"]},
        {"specimen": "gnu-coreutils/8.23-9.fc22/sort", "source_identity": "src/sort.c::keycompare_mb", "depth": 3,
         "counted_for": ["CVE-2015-4041", "CVE-2015-4042"]}]
    protocol["dependence_interpretation"] = (
        "These are distinct vulnerability IDs/defects under the (CVE,function) estimand, but not independent call-depth locations; neither CVE is deduplicated.")
    write("v2_population.json", population)
    write("v2_protocol.json", protocol)
    write("v2_vulnerable_function_mappings.json", mappings)
    write("v2_semantic_results.json", results)
    write("v2_source_manifest.json", manifest)
    print("population fingerprint:", population_fp)
    print("mapping fingerprint:", mappings["mapping_artifact_fingerprint"])


def finalize():
    mappings = read("v2_vulnerable_function_mappings.json")
    results = read("v2_semantic_results.json")
    by_mapping = {row["cve_id"]: row for row in mappings["members"]}
    for row in results["members"]:
        mapping = by_mapping[row["cve_id"]]
        row["executable_coverage"] = coverage_for(mapping, row["observations"])
        if any(item["status"] == "pending" for item in row["executable_coverage"]):
            raise RuntimeError("uncovered enumerated executable: " + row["cve_id"])
        if row["depth_applicability"] == "applicable":
            row.update(completed=True, disposition="depth_applicable", analysis_status="success",
                       reason="All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope.")
    results["study_status"] = "all_dispositions_complete_aggregation_pending"
    write("v2_semantic_results.json", results)


def refresh_provenance():
    """Refresh descriptive provenance and dependent hashes without touching science."""
    population = read("v2_population.json")
    mappings = read("v2_vulnerable_function_mappings.json")
    results = read("v2_semantic_results.json")
    manifest = read("v2_source_manifest.json")
    protocol = read("v2_protocol.json")
    statistics = read("v2_statistics.json")
    gate = read("v2_reporting_gate.json")
    integrity = read("v2_source_integrity.json")
    checks = read("v2_validation_checks.json")

    population_4998 = next(row for row in population["members"] if row["cve_id"] == "CVE-2007-4998")
    population_4998["prior_review_provenance"]["reason"] = PRIOR_4998_REVIEW_REASON
    population.pop("population_fingerprint", None)
    population["population_fingerprint"] = fingerprint(population)

    mapping_4998 = next(row for row in mappings["members"] if row["cve_id"] == "CVE-2007-4998")
    mapping_4998["correction_rationale"] = CURRENT_4998_CORRECTION_RATIONALE
    mapping_4998["non_cve_proxy_evidence"]["reason"] = PROXY_4998_REASON
    mapping_4998.pop("mapping_fingerprint", None)
    mapping_4998["mapping_fingerprint"] = fingerprint(mapping_4998)
    mappings["population_fingerprint"] = population["population_fingerprint"]
    mappings.pop("mapping_artifact_fingerprint", None)
    mappings["mapping_artifact_fingerprint"] = fingerprint(mappings)

    results["population_fingerprint"] = population["population_fingerprint"]
    result_4998 = next(row for row in results["members"] if row["cve_id"] == "CVE-2007-4998")
    result_4998["mapping_fingerprint"] = mapping_4998["mapping_fingerprint"]
    manifest["population_fingerprint"] = population["population_fingerprint"]
    protocol["population_fingerprint"] = population["population_fingerprint"]

    statistics["population_fingerprint"] = population["population_fingerprint"]
    statistics["mapping_artifact_fingerprint"] = mappings["mapping_artifact_fingerprint"]
    statistics.pop("statistics_artifact_fingerprint", None)
    statistics["statistics_artifact_fingerprint"] = fingerprint(statistics)
    gate["population_fingerprint"] = population["population_fingerprint"]
    gate["mapping_artifact_fingerprint"] = mappings["mapping_artifact_fingerprint"]
    gate["statistics_artifact_fingerprint"] = statistics["statistics_artifact_fingerprint"]
    integrity["population_fingerprint"] = population["population_fingerprint"]
    integrity["mapping_artifact_fingerprint"] = mappings["mapping_artifact_fingerprint"]
    checks["population_fingerprint"] = population["population_fingerprint"]
    checks["mapping_artifact_fingerprint"] = mappings["mapping_artifact_fingerprint"]
    checks["statistics_artifact_fingerprint"] = statistics["statistics_artifact_fingerprint"]

    write("v2_population.json", population)
    write("v2_vulnerable_function_mappings.json", mappings)
    write("v2_semantic_results.json", results)
    write("v2_source_manifest.json", manifest)
    write("v2_protocol.json", protocol)
    write("v2_statistics.json", statistics)
    write("v2_reporting_gate.json", gate)
    write("v2_source_integrity.json", integrity)
    write("v2_validation_checks.json", checks)
    print("population fingerprint:", population["population_fingerprint"])
    print("mapping fingerprint:", mappings["mapping_artifact_fingerprint"])
    print("statistics fingerprint:", statistics["statistics_artifact_fingerprint"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "finalize", "refresh_provenance"))
    globals()[parser.parse_args().stage]()
