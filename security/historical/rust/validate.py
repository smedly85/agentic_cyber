"""Offline integrity/consistency validation only; never measures historical code."""
from __future__ import annotations

import csv
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

import jsonschema

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CUTOFF = "2026-09-11"
ALLOWED_DEPTH_KEYS = {"depth_applicability", "depth_nonapplicability_reason"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def read(name, directory=HERE):
    return json.loads((directory / name).read_text(encoding="utf-8"))


def reject_measurements(value):
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            require(not (re.search(r"depth|call_?graph|bfs|shallow|threshold", lowered)
                         and key not in ALLOWED_DEPTH_KEYS), "Forbidden measurement field: " + key)
            reject_measurements(child)
    elif isinstance(value, list):
        for child in value:
            reject_measurements(child)


def unique(rows, key, label):
    values = [r[key] for r in rows]
    require(len(values) == len(set(values)), "Duplicate " + label)
    return {r[key]: r for r in rows}


def safe_relative(path):
    p = PurePosixPath(path)
    require(not p.is_absolute() and ".." not in p.parts and "\\" not in path and ":" not in path,
            "Unsafe artifact path: " + path)


def validate_records(population, mappings, manifest):
    for artifact in (population, mappings, manifest):
        reject_measurements(artifact)
        require(artifact["mapping_frozen_before_semantic_measurement"] is True, "Missing pre-measurement freeze")
    require(population["cutoff_date"] == CUTOFF, "Wrong cutoff")
    pops = unique(population["records"], "cve_id", "population ID")
    maps = unique(mappings["records"], "cve_id", "mapping ID")
    specimens = unique(manifest["specimens"], "cve_id", "specimen ID")
    members = {cid for cid, p in pops.items() if p["population_member"]}
    require(set(maps) == members == set(specimens), "Members/mappings/specimens do not correspond")
    require(population["discovery_audit"]["verified_member_count"] == len(members), "Incorrect census count")
    alias_owners = {}
    for cid, p in pops.items():
        require(re.fullmatch(r"CVE-\d{4}-\d{4,}", cid), "Non-normalized CVE ID")
        published = date.fromisoformat(p["publication_date"])
        require(p["cutoff_date"] == CUTOFF, "Record cutoff mismatch")
        require(p["aliases"] == sorted(set(p["aliases"])), "Aliases not normalized/deduplicated")
        for alias in p["aliases"]:
            require(re.fullmatch(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}|RUSTSEC-\d{4}-\d{4}", alias), "Invalid alias")
            require(alias not in alias_owners or alias_owners[alias] == cid, "Alias assigned to multiple CVEs")
            alias_owners[alias] = cid
        require(p["evidence_file"] == f"evidence/{cid}.md", "Missing per-CVE evidence identity")
        require(p["authoritative_sources"] and p["affected_versions"], "Missing population evidence/versions")
        if p["population_member"]:
            require(published <= date.fromisoformat(CUTOFF), "Population member published after cutoff")
            require(p["project"] == "uutils/coreutils" and p["implementation_family"] == "uutils" and p["language"] == "Rust", "Wrong project/language in population")
            require(p["cve_state"] == "PUBLISHED" and p["category"] != "dependency", "Rejected/dependency CVE included")
        else:
            require(bool(p["exclusion_reason"]) and p["mapping_status"] == "excluded", "Unexplained exclusion")
        if p["depth_applicability"] == "not_applicable":
            require(bool(p["depth_nonapplicability_reason"]), "Missing nonapplicability reason")
    files = {}
    for f in manifest["source_files"]:
        key = (f["revision"], f["source_file"])
        require(key not in files, "Duplicate source-file identity")
        safe_relative(f["source_file"])
        require(re.fullmatch(r"[a-f0-9]{64}", f["sha256"]), "Invalid source hash")
        files[key] = f["sha256"]
    evidence = unique(manifest["evidence_cache"], "url", "evidence URL")
    for e in evidence.values():
        require(re.fullmatch(r"[a-f0-9]{64}", e["sha256"]), "Invalid evidence hash")
        date.fromisoformat(e["retrieval_date"])
    for cid, m in maps.items():
        p, specimen = pops[cid], specimens[cid]
        require(m["mapping_frozen_before_semantic_measurement"] is True, "Unfrozen mapping")
        require(m["mapping_status"] == p["mapping_status"], "Mapping status mismatch")
        require(m["category"] == p["category"] and m["depth_applicability"] == p["depth_applicability"], "Applicability/category mismatch")
        require(re.fullmatch(r"[a-f0-9]{40}", m["affected_revision"] or ""), "Missing exact vulnerable revision")
        require(re.fullmatch(r"[a-f0-9]{40}", m["fix_revision"] or ""), "Missing public fix revision")
        require(m["fix_revision"] != m["affected_revision"], "Patched specimen selected")
        require(specimen["vulnerable_revision"] == m["affected_revision"] and specimen["fix_revision"] == m["fix_revision"], "Specimen revision mismatch")
        require(specimen["vulnerable_tag"] == m["affected_version"] and specimen["selection_rationale"], "Missing specimen rationale/version")
        require(f"https://codeload.github.com/uutils/coreutils/tar.gz/{m['affected_revision']}" in evidence, "Missing vulnerable archive provenance")
        require(m["fix_evidence"] and all(u in evidence for u in m["fix_evidence"]), "Uncached public fix evidence")
        if m["mapping_status"] == "unresolved":
            require(bool(m["unresolved_reason"]) and m["mapping_completeness"] == "partial_verified_locations", "Unexplained unresolved mapping")
        elif m["mapping_status"] == "verified":
            require(bool(m["vulnerable_functions"]) and m["mapping_completeness"] == "reviewed_primary_evidence", "Verified runtime member without functions")
        else:
            require(m["mapping_status"] == "not_applicable" and not m["vulnerable_functions"] and bool(m["depth_nonapplicability_reason"]), "Invalid non-function mapping")
        unique(m["vulnerable_functions"], "source_identity", "source identity within " + cid)
        for f in m["vulnerable_functions"]:
            safe_relative(f["source_file"])
            require(f["source_file"].startswith("src/") and f["source_file"].endswith(".rs"), "Verified function missing Rust source file")
            require(f["source_identity"] == f["source_file"] + "::" + f["function"], "Unqualified source identity")
            require(f["mapping_frozen_before_semantic_measurement"] is True, "Unfrozen function")
            require(f["mapping_status"] == "verified" and f["mapping_evidence"] and f["mapping_reason"], "Unsubstantiated function")
            require(f["affected_revision"] == m["affected_revision"] and f["fix_revision"] == m["fix_revision"], "Function specimen mismatch")
            require(files.get((f["affected_revision"], f["source_file"])) == f["source_sha256"], "Source file hash mismatch")
            require(f["affected_executables"] and f["executable_scope_basis"], "Missing executable scope evidence")
        for path in m.get("configuration_source_files", []):
            require((m["affected_revision"], path) in files, "Unpinned configuration source")


def validate_directory(directory=HERE, root=ROOT):
    pop = read("population.json", directory)
    maps = read("vulnerable_function_mappings.json", directory)
    source = read("source_manifest.json", directory)
    for name, value in (("population", pop), ("vulnerable_function_mappings", maps)):
        schema = read(name + ".schema.json", directory)
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(value)
    validate_records(pop, maps, source)
    lock = read("freeze_manifest.json", directory)
    require(lock["mapping_frozen_before_semantic_measurement"] is True, "Unfrozen manifest")
    for name, value in (("population.json", pop), ("vulnerable_function_mappings.json", maps), ("source_manifest.json", source)):
        require(fingerprint(value) == lock["canonical_json_fingerprints"][name], "Fingerprint mismatch: " + name)
    for name, expected in lock["schema_fingerprints"].items():
        require(fingerprint(read(name, directory)) == expected, "Schema changed after freeze: " + name)
    require(maps["population_fingerprint"] == fingerprint(pop), "Mappings bound to wrong population")
    require(source["population_fingerprint"] == fingerprint(pop) and source["mapping_fingerprint"] == fingerprint(maps), "Source provenance binding mismatch")
    require(digest((directory / "review.py").read_bytes().replace(b"\r\n", b"\n")) == lock["review_sha256"], "Review decisions changed after freeze")
    for name, checksum in lock["rendered_file_sha256"].items():
        safe_relative(name)
        require(digest((directory / name).read_bytes().replace(b"\r\n", b"\n")) == checksum, "Rendered artifact changed: " + name)
    for p in pop["records"]:
        require(p["evidence_file"] in lock["rendered_file_sha256"], "Evidence not frozen")
        require((directory / p["evidence_file"]).is_file(), "Missing evidence file")
    with (directory / "mapping_table.tsv").open(encoding="utf-8", newline="") as stream:
        table = list(csv.DictReader(stream, delimiter="\t"))
    require({r["CVE"] for r in table} == {r["cve_id"] for r in pop["records"]} and len(table) == len(pop["records"]), "Table omissions/duplicates")
    protected = read("protected_c_artifacts.json", directory)
    require(fingerprint(protected) == lock["protected_c_artifacts_fingerprint"], "Protected C baseline changed")
    for name, checksum in protected["files"].items():
        safe_relative(name)
        require(digest((root / name).read_bytes().replace(b"\r\n", b"\n")) == checksum, "Pre-existing C historical artifact changed: " + name)
    require(not list(directory.rglob("*.rs")), "Historical source must stay in ignored research cache")
    return {"members": sum(p["population_member"] for p in pop["records"]),
            "excluded": sum(not p["population_member"] for p in pop["records"]),
            "verified_cves": sum(m["mapping_status"] == "verified" for m in maps["records"]),
            "unresolved_cves": sum(m["mapping_status"] == "unresolved" for m in maps["records"]),
            "not_applicable_cves": sum(m["mapping_status"] == "not_applicable" for m in maps["records"]),
            "verified_function_records": sum(len(m["vulnerable_functions"]) for m in maps["records"]),
            "protected_c_files": len(protected["files"])}


if __name__ == "__main__":
    print(json.dumps(validate_directory(), indent=2, sort_keys=True))
