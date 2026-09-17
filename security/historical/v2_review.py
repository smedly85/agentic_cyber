"""Freeze independently reviewed mapping/disposition decisions before analysis."""
from __future__ import annotations
import hashlib
from pathlib import Path
from security.historical.v2_study import ROOT, read, write, fingerprint, validate_population, ledger_transaction


def evidence(name: str) -> dict:
    index = read("v2_primary_acquisition.json")
    row = next(r for r in index["requests"] if r["name"] == name)
    assert row["status"] == "downloaded"
    path = ROOT.parents[1] / row["cache_path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
    return {k: row[k] for k in ("name", "url", "cache_path", "sha256")}


@ledger_transaction
def install(decisions: list[dict]) -> None:
    population = read("v2_population.json")
    validate_population(population)
    mappings = read("v2_vulnerable_function_mappings.json")
    results = read("v2_semantic_results.json")
    for decision in decisions:
        decision["mapping_fingerprint"] = fingerprint(decision)
        pos = next(i for i, m in enumerate(mappings["members"]) if m["cve_id"] == decision["cve_id"])
        old = mappings["members"][pos]
        if old["completed"]:
            if old != decision:
                amendment = decision.get("premeasurement_metadata_amendment")
                result = next(r for r in results["members"] if r["cve_id"] == decision["cve_id"])
                if (not amendment or amendment["supersedes_mapping_fingerprint"] != old["mapping_fingerprint"]
                    or result["observations"] or result["completed"]):
                    raise RuntimeError("refusing to revise a frozen mapping decision")
                # Only an explicit premeasurement descriptive-metadata correction,
                # never a new function/revision chosen after observing depth.
                changed = {k for k in set(old) | set(decision) if old.get(k) != decision.get(k)}
                if changed - {"project", "mapping_fingerprint", "premeasurement_metadata_amendment"}:
                    raise RuntimeError("amendment changes frozen scientific mapping")
            else:
                continue
        mappings["members"][pos] = decision
        result = next(r for r in results["members"] if r["cve_id"] == decision["cve_id"])
        result["mapping_fingerprint"] = decision["mapping_fingerprint"]
        result["depth_applicability"] = decision["depth_applicability"]
        if decision["mapping_status"] == "not_applicable":
            result.update(completed=True, disposition="not_applicable_build_or_configuration_only",
                          reason=decision["reason"], disposition_evidence=decision["vulnerability_evidence"])
        else:
            result.update(reason="Vulnerable-function mapping frozen independently; configured build/scope and semantic measurement pending.")
    mappings.pop("mapping_artifact_fingerprint", None)
    mappings["freeze_status"] = ("all_member_mapping_decisions_frozen_before_aggregate_statistics"
                                if all(m["completed"] for m in mappings["members"])
                                else "completed_entries_frozen_remaining_entries_pending")
    mappings["mapping_artifact_fingerprint"] = fingerprint(mappings)
    write("v2_vulnerable_function_mappings.json", mappings)
    write("v2_semantic_results.json", results)


def main() -> None:
    common = {"completed": True, "mapping_confidence": "verified_primary_evidence",
              "mapping_frozen_before_new_measurement": True, "freeze_stage": "before_expanded_semantic_measurement"}
    decisions = [
        {**common, "cve_id": "CVE-2009-4135", "project": "GNU Coreutils build machinery",
         "mapping_status": "not_applicable", "depth_applicability": "not_applicable", "functions": [],
         "affected_version": "5.2.1 through 8.1 (advisory range)", "affected_revision": None,
         "fix_revision": "ae034822c535fa5168069a75fb5e1c58f93a7834",
         "vulnerability_evidence": [evidence("distcheck-fix"), evidence("distcheck-disclosure")],
         "reason": "The upstream fix changes only dist-check.mk build/test-directory handling. The vulnerable unit is a Make rule, not a runtime C function; no executable call-depth observation is applicable."},
        {**common, "cve_id": "CVE-2008-1946", "project": "Red Hat GNU Coreutils packaging/PAM configuration",
         "mapping_status": "not_applicable", "depth_applicability": "not_applicable", "functions": [],
         "affected_version": "RHEL 4 coreutils 5.2.1 packages before 5.2.1-31.8.el4 advisory update",
         "affected_revision": None, "fix_revision": "RHSA-2008:0780 / coreutils-5.2.1-31.8.el4",
         "vulnerability_evidence": [evidence("pam-advisory")],
         "reason": "The vendor identifies incorrect pam_succeed_if use in /etc/pam.d/su. This is an authentication-stack configuration vulnerability, not a demonstrated defect in su's C function or in the PAM module implementation. No runtime-function mapping is invented."},
    ]
    source = ROOT / "sources/coreutils-8.17-fedora-8.17-7.fc18"
    for cve, program, names in (("CVE-2013-0222", "uniq", ("different", "different_multi")),
                                ("CVE-2013-0223", "join", ("keycmp",))):
        file = f"src/{program}.c"
        text = (source / file).read_text()
        assert all(name + " (" in text for name in names) and "alloca (" in text
        decisions.append({**common, "cve_id": cve, "project": "GNU Coreutils with Fedora downstream i18n patch",
            "mapping_status": "verified", "depth_applicability": "applicable", "affected_version": "8.17-7.fc18",
            "affected_revision": "1b40d50d5e34ef5a47fcee49d6df689a458a2251",
            "fix_revision": "8def2175102337e5c315fa9c0dbe265a76358dda",
            "source_tree": "sources/coreutils-8.17-fedora-8.17-7.fc18",
            "source_tree_sha256": "ca93c8d1e49487648549a1755bc13bc8ab56c0613f8f7fc49d0456597a12c7b8",
            "programs": [program], "entry_point": "main",
            "functions": [{"source_file": file, "function": n, "source_identity": file + "::" + n,
                           "source_sha256": hashlib.sha256((source / file).read_bytes()).hexdigest()} for n in names],
            "vulnerability_evidence": [evidence("i18n-disclosure"), evidence("i18n-followup"),
                {"url": "https://src.fedoraproject.org/rpms/coreutils/c/8def2175102337e5c315fa9c0dbe265a76358dda",
                 "local_source_evidence": "security/historical/evidence/CVE-2013-0221.md",
                 "operation_audit": "Independent comparison of authenticated 8.17-7 and 8.17-8 source trees: input-sized alloca replaced with xmalloc/free in these functions."}],
            "mapping_reason": ("different has input-sized stack copies under -i; different_multi has input-sized stack copies for multibyte comparison. Both contain the actual vulnerable allocation, not merely a changed helper."
                               if program == "uniq" else "Both byte and multibyte -i branches allocate input-field-sized stack copies in keycmp. Callers and allocation helpers are not additional vulnerable functions."),
            "specimen_selection_reason": "The primary disclosure identifies the downstream i18n family; authenticated adjacent Fedora vulnerable/fixed revisions explicitly fix these CVEs. Selection precedes depth measurement, and reuses source reconstruction rather than inventing a pristine upstream vulnerability."})
    install(decisions)
    print("Frozen four independent decisions: two configuration/build dispositions and two runtime mappings.")


if __name__ == "__main__":
    main()
