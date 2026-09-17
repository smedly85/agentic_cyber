"""Verify and reference the frozen pilot; initialize explicit v2 accounting."""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path

from security.historical import semantic_validation as v
from security.historical.analysis import load_records, load_source_manifest, verify_source_tree_sha256
from security.historical.v2_study import ROOT, INSTRUMENT, read, write, fingerprint, validate_population


def graph_quality(graph: dict) -> dict:
    identities = Counter((f.get("source_file"), f["name"]) for f in graph["functions"])
    return {
        "defined_function_count": len(graph["functions"]),
        "reachable_function_count": sum(f["reachable_from_entry"] for f in graph["functions"]),
        "call_edge_count": len(graph["call_edges"]),
        "direct_edge_count": sum(e["edge_type"] == "direct" for e in graph["call_edges"]),
        "resolved_indirect_edge_count": sum(e["edge_type"] == "indirect_resolved" for e in graph["call_edges"]),
        "unresolved_indirect_callsite_count": len(graph["unresolved_indirect_callsites"]),
        "external_unavailable_definition_count": len({e["callee_name"] for e in graph["external_calls"]}),
        "external_callsite_count": len(graph["external_calls"]),
        "ambiguous_source_identity_count": sum(n > 1 for n in identities.values()),
    }


def main() -> None:
    population = read("v2_population.json")
    validate_population(population)
    for name in ("v2_vulnerable_function_mappings.json", "v2_semantic_results.json", "v2_source_manifest.json"):
        if (ROOT / name).exists():
            raise RuntimeError(f"refusing to overwrite existing v2 work: {name}")
    records = load_records(ROOT / "records.json")
    v.verify_frozen_queries(records)
    entries = load_source_manifest(ROOT / "source_manifest.json")
    baseline = read("semantic_validation.json")
    audit = read("source_scope_audit.json")
    fedora = read("fedora_sort_scope_validation.json")
    mappings, results, specimens = [], [], []
    graphs = {}
    for entry in entries:
        verify_source_tree_sha256(Path(entry["resolved_source_tree"]), entry["source_tree_sha256"])
        program = next(iter(entry["programs"]))
        key = v._program_key(entry, program)
        scope = next(r for r in audit["programs"] if r["program_key"] == list(key))
        assert scope["source_scope_kind"] == "linker_exact"
        version = entry["affected_version"]
        if version in ("8.17-7.fc18", "8.23-9.fc22"):
            graph_path = v.REPO / "build/fedora-sort-scope-checkpoint" / version / "linker_exact/graph.json"
            artifact = "fedora_sort_scope_validation.json"
            evidence = read(v.COREUTILS_LINKER_SCOPES[version])
            provenance = next(p for p in fedora["programs"] if p["program_key"] == list(key))["analyses"]["linker_exact"]["provenance"]
        elif version == "9.7":
            graph_path = v.REPO / "build/semantic-scope-checkpoint/linker_exact/graph.json"
            artifact = "semantic_scope_validation.json"
            evidence = read("coreutils_9_7_linker_scope.json")
            provenance = None
        else:
            slug = "-".join(key).replace(".", "-")
            graph_path = v.REPO / "build/semantic-historical-validation" / slug / "primary-graph.json"
            artifact = "semantic_validation.json"
            evidence = scope
            provenance = None
        graph = json.loads(graph_path.read_text())
        assert graph["analysis_status"] == "success" and graph["analysis_backend"] == "clang_llvm_svf"
        assert graph["provenance"]["svf_analysis_command"][1:3] == list(v.PRIMARY_OPTIONS)
        assert len(graph["source_files"]) == scope["source_count"]
        if provenance is not None:
            assert provenance == graph["provenance"]
        source_root = Path(entry["resolved_source_tree"])
        for src in graph["source_files"]:
            if not src["path"].startswith("generated-config/"):
                assert hashlib.sha256((source_root / src["path"]).read_bytes()).hexdigest() == src["sha256"]
        specimen = {"specimen_id": "/".join(key), "program_key": list(key),
                    "reuse_status": "verified_instrument_checkpoint_result", "instrument_commit": INSTRUMENT,
                    "source_manifest_reference": "security/historical/source_manifest.json",
                    "source_tree": entry["source_tree"], "source_revision": entry["source_revision"],
                    "source_tree_sha256": entry["source_tree_sha256"], "source_scope_kind": "linker_exact",
                    "source_scope_evidence": evidence, "source_count": scope["source_count"],
                    "measurement_reference": "security/historical/" + artifact,
                    "measurement_reference_sha256": hashlib.sha256((ROOT / artifact).read_bytes()).hexdigest(),
                    "retained_graph_path": graph_path.relative_to(v.REPO).as_posix(),
                    "retained_graph_sha256": hashlib.sha256(graph_path.read_bytes()).hexdigest(),
                    "entry_point": "main", "analysis_backend": graph["analysis_backend"],
                    "graph_quality": graph_quality(graph), "analysis_provenance": graph["provenance"]}
        specimens.append(specimen)
        graphs[key] = graph
        print("verified pilot specimen:", specimen["specimen_id"], flush=True)
    by_cve = {r["id"]: r for r in records}
    for member in population["members"]:
        cve = member["cve_id"]
        mapping = {"cve_id": cve, "mapping_status": "pending", "completed": False, "functions": [],
                   "authoritative_sources": member["authoritative_sources"], "mapping_confidence": None}
        result = {"cve_id": cve, "population_member": True, "completed": False, "disposition": "pending",
                  "depth_applicability": "not_yet_determined", "observations": [],
                  "reason": "Independent evidence/source/function/build investigation is not complete; this is not an unavailable or not-applicable finding."}
        if cve in by_cve:
            record = by_cve[cve]
            key = (record["upstream_project"], record["affected_version"], record["utility"])
            graph = graphs[key]
            mapping.update(mapping_status="verified_pilot_reuse", completed=True, project=key[0],
                           affected_version=key[1], affected_revision=record["source_revision"],
                           mapping_confidence="verified", specimen_id="/".join(key),
                           vulnerability_evidence=record, mapping_frozen_before_new_measurement=True,
                           freeze_stage="reuse_of_previously_verified_pilot_mapping")
            rows = [r for r in baseline["observations"] if r["cve"] == cve]
            assert {r["vulnerable_function_identity"].split("::")[1] for r in rows} == set(record["vulnerable_functions"])
            for row in rows:
                source, name = row["vulnerable_function_identity"].split("::")
                matched = v.map_source_identity(graph, source, name)
                assert matched["candidate_count"] == 1
                candidate = matched["candidates"][0]
                assert candidate["raw_call_depth"] == row["semantic_raw_call_depth"]
                assert candidate["shortest_call_path"] == row["shortest_semantic_path"]
                mapping["functions"].append({"source_file": source, "function": name,
                                             "source_identity": row["vulnerable_function_identity"],
                                             "definition_location": candidate["definition"]})
                result["observations"].append({"source_identity": row["vulnerable_function_identity"],
                    "specimen_id": "/".join(key), "analysis_backend": "clang_llvm_svf", "source_scope_kind": "linker_exact",
                    "mapping": matched, "raw_call_depth": candidate["raw_call_depth"],
                    "shortest_semantic_path": candidate["shortest_call_path"],
                    "reuse_status": "verified_pilot_semantic_result", "pilot_depth_changed": False})
            result.update(completed=True, disposition="depth_applicable", depth_applicability="applicable",
                          reason="Verified pilot mappings and current linker-exact results reused without changing revision or depth.")
        mapping["mapping_fingerprint"] = fingerprint(mapping)
        result["mapping_fingerprint"] = mapping["mapping_fingerprint"]
        mappings.append(mapping)
        results.append(result)
    common = {"schema_version": 1, "population_fingerprint": population["population_fingerprint"], "instrument_commit": INSTRUMENT}
    mapping_artifact = {**common, "freeze_status": "pilot_entries_frozen_new_entries_pending", "members": mappings}
    mapping_artifact["mapping_artifact_fingerprint"] = fingerprint(mapping_artifact)
    write("v2_vulnerable_function_mappings.json", mapping_artifact)
    write("v2_source_manifest.json", {**common, "specimens": specimens})
    write("v2_semantic_results.json", {**common, "study_status": "in_progress_no_population_statistics", "members": results})


if __name__ == "__main__":
    main()
