"""Prospective population-v2 ledger; never modifies the historical-v1 artifacts."""
from __future__ import annotations
from functools import wraps


def ledger_transaction(function):
    """Serialize read-modify-write operations by concurrent specimen workers."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        import fcntl
        lock = ROOT.parents[1] / "build/historical-v2/ledger.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            return function(*args, **kwargs)
    return wrapped

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INSTRUMENT = "e73c3a98ea3b4f5b8957674b9a05d182ced4558b"
IDS = """CVE-2026-56392 CVE-2026-56391 CVE-2025-5278 CVE-2024-0684
CVE-2017-18018 CVE-2017-2616 CVE-2016-2781 CVE-2015-4042 CVE-2015-4041
CVE-2015-1865 CVE-2014-9471 CVE-2013-0223 CVE-2013-0222 CVE-2013-0221
CVE-2009-4135 CVE-2008-1946 CVE-2007-4998 CVE-2005-1039 CVE-2003-0854
CVE-2003-0853 CVE-2015-1345 CVE-2012-5667 CVE-2002-0435 CVE-2001-0310""".split()
DISPOSITIONS = {
    "depth_applicable": "At least one uniquely mapped, verified vulnerable runtime function has a numeric semantic depth; any additional nonnumeric functions remain individually accounted for.",
    "not_applicable_no_vulnerable_runtime_function": "Primary evidence establishes a vulnerability unit that is not a runtime C function.",
    "not_applicable_build_or_configuration_only": "Primary evidence establishes build, packaging, or configuration vulnerability without an applicable runtime C-function depth.",
    "vulnerable_function_mapping_unresolved": "Evidence review completed but no defensible exact vulnerable function mapping established; not a synonym for not applicable.",
    "historical_source_unavailable": "Documented acquisition/reconstruction attempts could not establish the exact vulnerable source.",
    "historical_build_unavailable": "Documented faithful build/IR or executable-scope reconstruction could not be completed; diagnostics retained.",
    "semantic_analysis_unavailable": "Build/IR exists but the frozen semantic analysis failed or is unavailable; diagnostics retained.",
    "source_identity_not_found": "Verified vulnerable source identity is absent from the semantic graph.",
    "source_identity_ambiguous": "Multiple semantic identities match; all candidates retained without selection.",
    "semantic_unreachable": "Unique vulnerable identity is unreachable in the semantic may-call graph; depth remains null.",
    "unresolved_indirect_dispatch": "Unresolved semantic indirect flow prevents a numeric vulnerable-function path; no synthetic edge.",
}


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read(name: str) -> object:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def write(name: str, value: object) -> None:
    import os
    import tempfile
    destination = ROOT / name
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                     prefix=destination.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
        temporary = handle.name
    os.replace(temporary, destination)


def validate_population(population: dict) -> None:
    assert population["population_size"] == len(population["members"]) == 24
    assert len({m["cve_id"] for m in population["members"]}) == 24
    assert {m["cve_id"] for m in population["members"]} == set(IDS)
    assert all(m["population_member"] is True for m in population["members"])
    payload = {k: v for k, v in population.items() if k != "population_fingerprint"}
    if fingerprint(payload) != population["population_fingerprint"]:
        raise RuntimeError("frozen population fingerprint mismatch")
    if population["instrument_commit"] != INSTRUMENT:
        raise RuntimeError("instrument checkpoint mismatch")


def freeze_population() -> dict:
    path = ROOT / "v2_population.json"
    if path.exists():
        population = read(path.name)
        validate_population(population)
        return population
    prior = read("v2_population_reconnaissance.json")
    candidates = {r["cve_id"]: r for r in prior["candidates"]}
    assert set(candidates) == set(IDS) and len(prior["candidates"]) == 24
    members = []
    for cve in IDS:
        c = candidates[cve]
        family = ("FreeBSD base-system sort" if cve == "CVE-2001-0310" else
                  "util-linux/shadow su (project assignment to verify independently)" if cve == "CVE-2017-2616" else
                  "downstream GNU-derived patch" if c["gnu_lineage_relevance"] == "downstream_gnu_derived" else
                  c["affected_package_project"])
        members.append({
            "cve_id": cve, "population_member": True,
            "affected_project_package": c["affected_package_project"],
            "utility_component": c["affected_utility_component"],
            "implementation_family": family, "gnu_lineage_relationship": c["gnu_lineage_relevance"],
            "category_at_freeze": ("build" if cve == "CVE-2009-4135" else
                                   "configuration" if cve == "CVE-2008-1946" else "runtime"),
            "target_utility_relationship": c["target_utility_relevance"],
            "authoritative_sources": c["authoritative_sources"],
            "descriptors_are_not_inclusion_filters": True,
            "prior_review_provenance": c,
        })
    population = {
        "schema_version": 1, "population_name": "professor_confirmed_24_cve_discovery_universe_v2",
        "population_size": 24, "population_freeze_date": "2026-09-17",
        "population_freeze_timezone": "UTC", "local_confirmation_date": "2026-09-16",
        "population_definition": "The population consists of the 24 CVEs in the previously reconciled historical discovery/review universe, as explicitly confirmed by the professors before expanded semantic-depth measurement.",
        "population_source_artifact": "security/historical/v2_population_reconnaissance.json",
        "population_source_sha256": hashlib.sha256((ROOT / "v2_population_reconnaissance.json").read_bytes()).hexdigest(),
        "confirmation_provenance": "Explicit user instruction conveying professor confirmation; exact 24 IDs supplied before this freeze.",
        "instrument_commit": INSTRUMENT,
        "bias_protection": "The complete 24-CVE population was fixed before semantic call-depth measurement was expanded beyond the validated historical pilot. No CVE was excluded because its vulnerable function was deep, unreachable, unavailable, ambiguous, or not amenable to function-level depth measurement.",
        "membership_rule": "All listed members remain included regardless of applicability, build success, mapping, reachability, ambiguity, or numeric depth.",
        "members": members,
    }
    population["population_fingerprint"] = fingerprint(population)
    validate_population(population)
    write(path.name, population)
    protocol = {
        "schema_version": 1, "population_fingerprint": population["population_fingerprint"],
        "instrument_commit": INSTRUMENT,
        "primary_configuration": {"clang_llvm": "21.1.8", "svf": "3.4", "svf_commit": "67efb7745ce47b2b6853fd5696fc22c83d701e6c", "pointer_analysis": "AndersenWaveDiff", "options": ["-stat=false", "-ff-eq-base"]},
        "depth_definition": "Shortest number of direct or resolved-indirect static semantic may-call edges from the configured executable entry point; main is depth zero when main is that entry.",
        "mapping_order": "Freeze evidence-based specimen/function mapping and its per-decision fingerprint before new semantic measurement. Freeze the complete mapping-artifact fingerprint before aggregate statistics. Pilot reuse is explicitly labeled prior verified measurement.",
        "scope_rule": "Linker-exact whenever faithfully recoverable; other scope kinds require explicit justification and separate reporting, never silent pooling.",
        "disposition_taxonomy": DISPOSITIONS,
        "pending_is_not_final": True,
        "nonnumeric_rule": "Never impute. Not applicable, unavailable, unresolved, ambiguous and unreachable remain distinct. An unfinished investigation is pending, not a justified unavailability result.",
        "multi_program_rule": "The observation unit is (CVE, vulnerable function). If a shared function belongs to multiple affected executables, preserve each executable-specific depth; do not select the shallowest. Resolve the estimand prospectively or leave aggregation blocked.",
        "statistics_gate": "Exactly 24 final evidence-justified dispositions; complete verified mapping freeze; every numeric observation derives from the frozen semantic backend and has explicit scope/path provenance.",
        "statistics_conventions": {"sample_sd": "n-1 denominator; null for n<2", "quartiles": "Linear interpolation at p*(n-1), p=0.25 and 0.75; IQR=Q3-Q1", "missing_values": "Excluded from numeric arithmetic only, never population accounting; all denominators stated", "cve_weighting": "Arithmetic mean of per-CVE means among CVEs with >=1 legitimate numeric depth; distinguish from observation-level mean"},
    }
    write("v2_protocol.json", protocol)
    return population


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze-population", "validate-population"])
    args = parser.parse_args()
    population = freeze_population() if args.command == "freeze-population" else read("v2_population.json")
    validate_population(population)
    print("population members:", len(population["members"]))
    print("population fingerprint:", population["population_fingerprint"])


if __name__ == "__main__":
    main()
