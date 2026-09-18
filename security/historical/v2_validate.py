"""Fail-closed v2 accounting/provenance checks and non-final progress rendering."""
from collections import Counter
import json
import math
import statistics
from pathlib import Path
import subprocess
import jsonschema
from security.historical.v2_study import (ROOT, IDS, INSTRUMENT, read, fingerprint,
                                          validate_population, function_executables,
                                          expected_executable_function_pairs)
from security.historical import semantic_validation as v
from security.historical.v2_seed import graph_quality


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate():
    population = read("v2_population.json")
    validate_population(population)
    for artifact, schema in (("v2_population.json", "v2_population.schema.json"),
                             ("v2_protocol.json", "v2_protocol.schema.json"),
                             *((n, "v2_study_artifacts.schema.json") for n in (
                                 "v2_vulnerable_function_mappings.json", "v2_source_manifest.json", "v2_semantic_results.json"))):
        jsonschema.Draft202012Validator(read(schema)).validate(read(artifact))
    mappings = read("v2_vulnerable_function_mappings.json")
    results = read("v2_semantic_results.json")
    manifest = read("v2_source_manifest.json")
    require(mappings["mapping_artifact_fingerprint"] == fingerprint({k: val for k, val in mappings.items() if k != "mapping_artifact_fingerprint"}), "mapping artifact fingerprint mismatch")
    for ledger in (mappings, results):
        require(len(ledger["members"]) == 24 and {m["cve_id"] for m in ledger["members"]} == set(IDS), "24-member accounting mismatch")
        require(ledger["population_fingerprint"] == population["population_fingerprint"], "population fingerprint mismatch")
        require(ledger["instrument_commit"] == INSTRUMENT, "instrument mismatch")
    graphs = {}
    specimens = {specimen["specimen_id"]: specimen for specimen in manifest["specimens"]}
    for specimen in manifest["specimens"]:
        graph_path = v.REPO / specimen["retained_graph_path"]
        require(v._sha256(graph_path) == specimen["retained_graph_sha256"], "retained graph changed")
        graph = json.loads(graph_path.read_text())
        jsonschema.Draft202012Validator(json.loads((v.REPO / "security/semantic_callgraph/schema.json").read_text())).validate(graph)
        require(graph["analysis_backend"] == "clang_llvm_svf", "nonsemantic backend")
        require(graph["provenance"]["svf_analysis_command"][1:3] == list(v.PRIMARY_OPTIONS), "analysis configuration changed")
        require(graph_quality(graph) == specimen["graph_quality"], "graph diagnostics mismatch")
        require(len(graph["source_files"]) == specimen["source_count"], "scope count mismatch")
        if isinstance(specimen["source_scope_evidence"], str):
            scope = json.loads((v.REPO / specimen["source_scope_evidence"]).read_text())
            require(scope["source_scope_kind"] == specimen["source_scope_kind"], "scope classification mismatch")
            require(scope["source_tree_sha256"] == specimen["source_tree_sha256"], "scope/source fingerprint mismatch")
            require(set(scope["source_files"]) == {s["path"] for s in graph["source_files"]}, "LLVM scope differs from linked scope")
        graphs[specimen["specimen_id"]] = graph
    by_cve = {m["cve_id"]: m for m in mappings["members"]}
    for mapping in mappings["members"]:
        require((mapping.get("mapping_reason") or "").strip(), "missing self-contained mapping rationale: " + mapping["cve_id"])
        programs = mapping.get("programs", [])
        expected = mapping.get("expected_affected_executables", [])
        if programs:
            require(expected and len(expected) == len(set(expected)), "missing/duplicate frozen executable set: " + mapping["cve_id"])
            require(set(expected) == set(programs), "program list differs from authoritative executable set: " + mapping["cve_id"])
            associated = {program for function in mapping["functions"] for program in function_executables(mapping, function)}
            require(associated == set(expected), "vulnerable functions do not cover frozen executable set: " + mapping["cve_id"])
        else:
            require(not expected, "non-runtime mapping unexpectedly enumerates executables: " + mapping["cve_id"])
        if mapping.get("mapping_status") == "verified_pilot_reuse":
            require("authoritative_sources" not in mapping, "reused-v1 evidence still mixes bare URLs with field names")
            require(all(set(item) >= {"role", "url"} for item in mapping.get("authoritative_evidence", [])),
                    "reused-v1 authoritative evidence is not machine-readable")
    for row in results["members"]:
        mapping = by_cve[row["cve_id"]]
        require(mapping["mapping_fingerprint"] == fingerprint({k: val for k, val in mapping.items() if k != "mapping_fingerprint"}), "member mapping fingerprint mismatch")
        require(row["mapping_fingerprint"] == mapping["mapping_fingerprint"], "result queried a different mapping")
        for obs in row["observations"]:
            require(obs["source_identity"] in {f["source_identity"] for f in mapping["functions"]}, "depth query outside frozen mapping")
            program = obs["specimen_id"].rsplit("/", 1)[-1]
            function = next(f for f in mapping["functions"] if f["source_identity"] == obs["source_identity"])
            require(program in function_executables(mapping, function), "observation uses a non-CVE-enumerated executable context")
            graph = graphs[obs["specimen_id"]]
            file, name = obs["source_identity"].split("::")
            require(obs["mapping"] == v.map_source_identity(graph, file, name), "source-identity mapping changed")
            if obs["raw_call_depth"] is not None:
                require(obs["source_scope_kind"] == "linker_exact" and specimens[obs["specimen_id"]]["source_scope_kind"] == "linker_exact",
                        "numeric observation is not linker-exact")
                require(obs["mapping"]["candidate_count"] == 1, "numeric result from ambiguous or absent identity")
                candidate = obs["mapping"]["candidates"][0]
                require(candidate["raw_call_depth"] == obs["raw_call_depth"], "numeric depth mismatch")
                require(candidate["shortest_call_path"] == obs["shortest_semantic_path"], "path mismatch")
                edges = obs["shortest_semantic_path"]["edges"]
                require(len(edges) == obs["raw_call_depth"], "depth is not raw edge count")
                for edge in edges:
                    require(edge in graph["call_edges"], "synthetic or altered path edge")
                    if edge["edge_type"] == "indirect_resolved":
                        require(edge["indirect_target_count"] == len(edge["indirect_target_set"]), "incomplete indirect target set")
        expected_executables = set(mapping.get("expected_affected_executables", []))
        coverage = row.get("executable_coverage")
        require(isinstance(coverage, list), "missing executable-coverage disposition: " + row["cve_id"])
        require({item["executable"] for item in coverage} == expected_executables and
                len(coverage) == len(expected_executables), "executable-coverage set mismatch: " + row["cve_id"])
        observed_pairs = {(obs["specimen_id"].rsplit("/", 1)[-1], obs["source_identity"])
                          for obs in row["observations"] if obs["raw_call_depth"] is not None}
        for item in coverage:
            identities = {function["source_identity"] for function in mapping["functions"]
                          if item["executable"] in function_executables(mapping, function)}
            require(set(item["required_source_identities"]) == identities,
                    "coverage/function association mismatch: " + row["cve_id"] + "/" + item["executable"])
            if item["status"] == "measured_vulnerable_context":
                require(identities and all((item["executable"], identity) in observed_pairs for identity in identities),
                        "coverage claims an unmeasured executable: " + row["cve_id"] + "/" + item["executable"])
            elif item["status"] == "evidence_backed_exclusion":
                require(item.get("reason", "").strip() and item.get("evidence"),
                        "executable exclusion lacks reason/evidence: " + row["cve_id"] + "/" + item["executable"])
            else:
                require(item["status"] == "pending" and not row["completed"],
                        "completed result has pending/unknown executable coverage: " + row["cve_id"])
        require(not row["completed"] or row["disposition"] != "pending", "unfinished work mislabeled completed")
        if row["completed"] and row["disposition"] == "depth_applicable":
            require({o["source_identity"] for o in row["observations"]} == {f["source_identity"] for f in mapping["functions"]}, "completed result omits verified vulnerable functions")
            require(len({(o["specimen_id"], o["source_identity"]) for o in row["observations"]}) == len(row["observations"]), "duplicate executable/function measurement")
            require(observed_pairs == expected_executable_function_pairs(mapping), "completed result omits or adds executable/function contexts")
        require(row["reason"].strip(), "missing disposition justification")
    require({item["executable"] for item in next(r for r in results["members"] if r["cve_id"] == "CVE-2005-1039")["executable_coverage"]} == {"mkdir", "mkfifo", "mknod"}, "CVE-2005-1039 executable set regressed")
    for cve, expected in (("CVE-2014-9471", {"date", "touch"}), ("CVE-2017-18018", {"chown", "chgrp"}),
                          ("CVE-2002-0435", {"rm", "mv"})):
        require(set(by_cve[cve]["expected_affected_executables"]) == expected, cve + " executable set regressed")
    for cve in ("CVE-2003-0853", "CVE-2003-0854"):
        require(set(by_cve[cve]["expected_affected_executables"]) == {"ls"}, cve + " must not infer dir/vdir membership")
    proxy = by_cve["CVE-2007-4998"].get("non_cve_proxy_evidence", {})
    require(proxy.get("semantic_depth") == 3 and proxy.get("status") == "descriptive_defect_class_proxy_only",
            "GNU Fileutils proxy provenance missing")
    require(not any(obs["specimen_id"] == proxy.get("specimen_id")
                    for row in results["members"] for obs in row["observations"]), "GNU proxy counted as a CVE observation")
    proxy_specimen = specimens[proxy["specimen_id"]]
    require(proxy_specimen.get("evidence_role") == "non_CVE_proxy_only" and
            proxy_specimen.get("excluded_from_CVE_2007_4998_statistics") is True, "GNU proxy manifest exclusion missing")
    frozen = ["records.json", "cve_census.json", "source_manifest.json", "semantic_query_locations.json",
              "semantic_scope_validation.json", "semantic_validation.json", "semantic_validation_pending.json",
              "source_scope_audit.json", "v2_population_reconnaissance.json"]
    for name in frozen:
        original = subprocess.run(["git", "show", INSTRUMENT + ":security/historical/" + name], cwd=v.REPO, capture_output=True, check=True).stdout
        require(original == (ROOT / name).read_bytes(), "frozen historical artifact changed: " + name)
    if results["study_status"] == "complete":
        statistics_artifact = read("v2_statistics.json")
        jsonschema.Draft202012Validator(read("v2_statistics.schema.json")).validate(statistics_artifact)
        require(statistics_artifact["statistics_artifact_fingerprint"] == fingerprint({k: value for k, value in statistics_artifact.items() if k != "statistics_artifact_fingerprint"}), "statistics fingerprint mismatch")
        require(statistics_artifact["population_fingerprint"] == population["population_fingerprint"], "statistics population mismatch")
        require(statistics_artifact["mapping_artifact_fingerprint"] == mappings["mapping_artifact_fingerprint"], "statistics mapping mismatch")
        contexts = {(row["cve_id"], obs["source_identity"], obs["specimen_id"]): obs["raw_call_depth"]
                    for row in results["members"] for obs in row["observations"] if obs["raw_call_depth"] is not None}
        retained = {(row["cve_id"], row["source_identity"], row["specimen_id"]): row["raw_semantic_depth"]
                    for row in statistics_artifact["executable_context_sensitivity"]["contexts"]}
        require(contexts == retained, "statistics lost or altered raw executable contexts")
        grouped = {}
        for (cve, identity, _), depth in contexts.items():
            grouped.setdefault((cve, identity), []).append(depth)
        primary = {(row["cve_id"], row["source_identity"]): row["function_level_depth"]
                   for row in statistics_artifact["primary_function_observations"]}
        expected_primary = {key: statistics.fmean(depths) for key, depths in grouped.items()}
        require(primary == expected_primary, "primary observation averaging rule mismatch")
        values = statistics_artifact["primary_function_observation_statistics"]["values"]
        require(values == sorted(expected_primary.values()), "primary depth list mismatch")
        require(math.isclose(statistics_artifact["primary_function_observation_statistics"]["mean"], statistics.fmean(expected_primary.values())), "primary mean mismatch")
        require(len(statistics_artifact["per_cve"]) == 24 and {row["cve_id"] for row in statistics_artifact["per_cve"]} == set(IDS), "statistics per-CVE accounting mismatch")
        gate = read("v2_reporting_gate.json")
        jsonschema.Draft202012Validator(read("v2_reporting_gate.schema.json")).validate(gate)
        require(gate["statistics_computed"] and gate["statistics_artifact_fingerprint"] == statistics_artifact["statistics_artifact_fingerprint"], "reporting gate/statistics mismatch")
    return population, mappings, results, manifest


def render(population, mappings, results, manifest):
    by_cve = {m["cve_id"]: m for m in mappings["members"]}
    descriptions = {m["cve_id"]: m for m in population["members"]}
    completed = sum(r["completed"] for r in results["members"])
    lines = ["# Population v2 measurement accounting", "",
             f"Population: exactly 24 CVEs. Completed measurement dispositions: {completed}/24. " + ("No member remains pending." if completed == 24 else "All other members remain pending, not artificially unavailable."), "",
             f"Population fingerprint: `{population['population_fingerprint']}`.",
             f"Current frozen mapping artifact fingerprint: `{mappings['mapping_artifact_fingerprint']}`.", "",
             ("Final statistics use the approved (CVE, vulnerable function) unit with within-function averaging across affected executables; see `final-report.md`." if results["study_status"] == "complete" else "No population mean, median, SD, IQR, or threshold is published while dispositions or the multiple-executable aggregation rule remain unsettled."), "",
             "| CVE | Project / component | Implementation family | Applicability | Verified functions | Numeric executable measurements | Executable-specific raw depths | Scope | Disposition / reason |", "|---|---|---|---|---:|---:|---|---|---|"]
    for row in results["members"]:
        mapping = by_cve[row["cve_id"]]
        values = "; ".join(o["specimen_id"] + ": " + o["source_identity"] + " = " + str(o["raw_call_depth"]) for o in sorted(row["observations"], key=lambda o: (o["specimen_id"], o["source_identity"]))) or "—"
        description = descriptions[row["cve_id"]]
        component = ", ".join(mapping.get("programs", [])) or description["utility_component"]
        scopes = ", ".join(sorted({o["source_scope_kind"] for o in row["observations"]})) or "not applicable"
        numeric = sum(o["raw_call_depth"] is not None for o in row["observations"])
        lines.append(f"| {row['cve_id']} | {mapping.get('project', 'under review')} / {component} | {description['implementation_family']} | {row['depth_applicability']} | {len(mapping['functions'])} | {numeric} | {values} | {scopes} | {row['disposition']}: {row['reason']} |")
    lines += ["", ("Per-CVE and aggregate statistics are in `final-report.md`; every executable-specific raw depth remains visible above and in the machine-readable results." if results["study_status"] == "complete" else "Per-CVE means/minima/maxima and aggregate distribution statistics are deliberately deferred until the shared-function/executable aggregation rule is approved; executable-specific raw depths above are not imputed or collapsed.")]
    lines += ["", "## Build and scope evidence", "", "| Specimen | TUs | Scope | Functions | Edges | Indirect edges | Unresolved callsites |", "|---|---:|---|---:|---:|---:|---:|"]
    for s in sorted(manifest["specimens"], key=lambda s: s["specimen_id"]):
        q = s["graph_quality"]
        lines.append(f"| {s['specimen_id']} | {s['source_count']} | {s['source_scope_kind']} | {q['defined_function_count']} | {q['call_edge_count']} | {q['resolved_indirect_edge_count']} | {q['unresolved_indirect_callsite_count']} |")
    lines += ["", "All numeric observations come from the frozen LLVM/SVF static semantic may-call instrument. Reachability is possible static execution, not guaranteed runtime execution. Every may-target remains in the graph. Tree-sitter prototype depths are not imported.", "",
              "Sources, mapping evidence and source hashes are in the v2 ledgers. Raw graphs/build logs are retained under ignored build/historical-v2; compact linker maps and scope artifacts are under evidence/v2. Frozen historical-v1 files are unchanged.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    data = validate()
    first = render(*data)
    require(first == render(*data), "nondeterministic rendering")
    output = ROOT / "evidence/v2/progress.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(first, encoding="utf-8")
    print("Validated 24-member accounting, schemas, mapping/graph fingerprints, semantic paths/target sets, frozen-v1 integrity, deterministic progress rendering.")
