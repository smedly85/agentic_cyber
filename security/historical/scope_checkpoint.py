#!/usr/bin/env python3
"""Reproduce the pre-v2 Coreutils 9.7 native-link scope experiment.

GNU ld's map is a link-closure artifact, not a call-graph source. Call edges
continue to come exclusively from the existing LLVM/SVF helper.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import shlex
from pathlib import Path

from security.historical import semantic_validation as validation
from security.historical.analysis import load_records, load_source_manifest, verify_source_tree_sha256
from security.historical.derive_coreutils_sort_scope import expand_make_variables, derive_scope
from security.semantic_callgraph import analyze_build, inventory_toolchain, stable_json


def audit_existing_scopes(entries: list[dict]) -> list[dict]:
    """Re-expand the existing five link maps; do not rebuild programs."""
    modules = {"5.2.1": "derive_coreutils_mkdir_scope", "2.10": "derive_grep_2_10_scope",
               "2.21": "derive_grep_scope", "8.17-7.fc18": "derive_coreutils_8_17_sort_scope",
               "8.23-9.fc22": "derive_coreutils_8_23_sort_scope"}
    rows = []
    for entry in entries:
        version = entry["affected_version"]
        if version not in modules:
            continue
        program = next(iter(entry["programs"]))
        key = validation._program_key(entry, program)
        build = validation.REPO / validation.BUILD_SPECS[key].build_dir
        mod = importlib.import_module("security.historical." + modules[version])
        recursive = version in ("5.2.1", "2.10", "2.21")
        linkmap = build / (f"src/{program}.map" if recursive else "sort.map")
        source = Path(entry["resolved_source_tree"])
        if recursive:
            src_vars = mod.expand_make_variables(build / "src/Makefile", mod.SRC_VARIABLES, "audit-source-scope")
            lib_vars = mod.expand_make_variables(build / "lib/Makefile", mod.LIB_VARIABLES, "audit-library-scope")
            scope = mod.derive_scope(source, src_vars, lib_vars, linkmap)
        elif version == "8.17-7.fc18":
            scope = mod.derive_scope(source, build / "src/Makefile", build / "lib/Makefile", linkmap)
        else:
            scope = mod.derive_scope(source, build / "Makefile", linkmap)
        if scope["analyzed_source_files"] != entry["programs"][program]["source_files"] or not scope["linker_member_exact"]:
            raise RuntimeError(f"scope audit disagrees with frozen evidence: {key}")
        omitted_version = version in ("8.17-7.fc18", "8.23-9.fc22")
        rows.append({"program_key": list(key), "source_count": len(scope["analyzed_source_files"]),
                     "source_scope_kind": "reconstructed_program_scope" if omitted_version else "linker_exact",
                     "derivation_script": f"security/historical/{modules[version]}.py",
                     "configured_build_directory": validation.BUILD_SPECS[key].build_dir,
                     "link_map": str(linkmap.relative_to(validation.REPO)),
                     "link_map_sha256": validation._sha256(linkmap),
                     "confidence": "existing native GNU ld member map re-derived and compared exactly to frozen manifest; no rebuild",
                     "needs_future_linker_exact_reconstruction": omitted_version,
                     "qualification": (
                         "The configured GNU ld map also extracts libver.a(version.o). The frozen semantic list omits generated src/version.c (config include plus Version string). Library-member closure is proven, but complete program-TU closure is not the analyzed scope. No graph rerun or silent promotion in this provenance-only audit."
                         if omitted_version else "All configured program C objects and selected program archive members accounted for; system libraries/startup objects are external."
                     ),
                     "omitted_generated_source": "src/version.c" if omitted_version else None,
                     "omitted_generated_source_sha256": validation._sha256(build / "src/version.c") if omitted_version else None,
                     "derived_evidence": scope})
    completion_path = validation.HISTORICAL / "fedora_sort_scope_validation.json"
    if completion_path.is_file():
        completion = json.loads(completion_path.read_text())
        for completed in completion["programs"]:
            scope = completed["scope"]
            key = scope["program_key"]
            row = next(r for r in rows if r["program_key"] == key)
            entry = next(e for e in entries if e["affected_version"] == key[1])
            scope_file = validation.HISTORICAL / validation.COREUTILS_LINKER_SCOPES[key[1]]
            if (json.loads(scope_file.read_text()) != scope or
                    scope["source_tree_sha256"] != entry["source_tree_sha256"] or
                    completed["analyses"]["linker_exact"]["analysis_status"] != "success" or
                    scope["source_scope_kind"] != "linker_exact" or
                    set(scope["source_files"]) != set(row["derived_evidence"]["analyzed_source_files"]) | {"generated-config/src/version.c"}):
                raise RuntimeError("Fedora scope completion disagrees with audited link/build evidence")
            row.update({"source_count": scope["source_file_count"], "source_scope_kind": "linker_exact",
                        "release_source_count": scope["release_source_count"],
                        "needs_future_linker_exact_reconstruction": False,
                        "generated_build_modules_included": ["generated-config/src/version.c"],
                        "scope_derivation_method": scope["scope_derivation_method"],
                        "linker_exact_evidence": "security/historical/" + scope_file.name,
                        "confidence": "configured native relink and complete .Po object/source closure; generated source regenerated; LLVM/SVF successful",
                        "qualification": "The retained frozen manifest omitted version.o; the separately validated primary scope now includes its configured generated source."})
            row.pop("omitted_generated_source", None)
            row.pop("omitted_generated_source_sha256", None)
    return rows


def derive_linker_scope(entry: dict, build_root: Path) -> dict:
    source_root = Path(entry["resolved_source_tree"])
    verify_source_tree_sha256(source_root, entry["source_tree_sha256"])
    variables = expand_make_variables(build_root / "Makefile")
    archive_scope = derive_scope(source_root, variables)
    old = entry["programs"]["sort"]["source_files"]
    if archive_scope["analyzed_source_files"] != old:
        raise RuntimeError("configured archive scope differs from authenticated manifest")
    make_vars = {name: list(validation._configured_make_variable(build_root, name)) for name in (
        "src_sort_OBJECTS", "src_sort_LDADD", "src_sort_DEPENDENCIES",
        "src_libver_a_OBJECTS", "nodist_src_libver_a_SOURCES", "LDFLAGS", "CC",
    )}
    if make_vars["src_sort_OBJECTS"] != ["src/sort.o"]:
        raise RuntimeError("unrecognized direct-object mapping; inspect configured recipe")
    map_path = build_root / "sort-linker-exact.map"
    map_text = map_path.read_text(encoding="utf-8")
    members: dict[str, set[str]] = {}
    # GNU ld's documented archive(member) notation, cross-checked against LOAD
    # entries and configured archives. Never assume all archive members link.
    for archive, member in re.findall(r"(?m)^(\S+\.a)\(([^()]+)\)", map_text):
        members.setdefault(archive, set()).add(member)
    configured_archives = {v for v in make_vars["src_sort_LDADD"] if v.endswith(".a")}
    if configured_archives != {"lib/libcoreutils.a", "src/libver.a"}:
        raise RuntimeError(f"unrecognized configured archives: {configured_archives}")
    if not configured_archives <= set(members):
        raise RuntimeError("link map lacks an expected program archive")
    mappings = [{"object": "src/sort.o", "source_file": "src/sort.c", "origin": "release"}]
    for member in sorted(members["lib/libcoreutils.a"]):
        name = member.removeprefix("libcoreutils_a-")
        source = f"lib/{name[:-2]}.c"
        if not member.endswith(".o") or source not in old:
            raise RuntimeError(f"unrecognized archive-member source: {member}")
        mappings.append({"archive": "lib/libcoreutils.a", "object": member,
                         "source_file": source, "origin": "release"})
    if members["src/libver.a"] != {"version.o"} or [v for v in make_vars["nodist_src_libver_a_SOURCES"] if v.endswith(".c")] != ["src/version.c"]:
        raise RuntimeError("unrecognized generated version module")
    mappings.append({"archive": "src/libver.a", "object": "version.o",
                     "source_file": "generated-config/src/version.c", "origin": "configured_generated"})
    files = sorted(row["source_file"] for row in mappings)
    if len(files) != len(set(files)):
        raise RuntimeError("multiple compile instances need explicit provenance")
    loads = re.findall(r"(?m)^LOAD (.+)$", map_text)
    if "src/sort.o" not in loads or not configured_archives <= set(loads):
        raise RuntimeError("link LOAD evidence inconsistent with configured objects")
    command = ["make", "-C", str(build_root), "-n", "-W", "src/sort.o", "V=1",
               "LDFLAGS=" + " ".join(make_vars["LDFLAGS"] + ["-Wl,-Map=sort-linker-exact.map"]), "src/sort"]
    dry = validation._run(command)
    if dry.returncode:
        raise RuntimeError(dry.stderr)
    link_lines = [line for line in dry.stdout.splitlines() if "-o src/sort " in line]
    if len(link_lines) != 1:
        raise RuntimeError("configured sort link recipe is not unique")
    release_files = sorted(set(files) & set(old))
    return {
        "schema_version": 1, "historical_program": "gnu-coreutils/9.7/sort",
        "source_scope_kind": "linker_exact", "source_revision": entry["source_revision"],
        "source_tree_sha256": entry["source_tree_sha256"],
        "configured_build_directory": "build/coreutils-9.7-sort-scope",
        "evidence": "security/historical/evidence/coreutils-9.7-linker.map",
        "scope_derivation_method": "configured native GCC link and GNU ld extracted archive-member map; Automake source/object correspondence",
        "native_compiler_version": validation._run([make_vars["CC"][0], "--version"]).stdout.strip(),
        "native_linker_version": validation._run(["ld", "--version"]).stdout.strip(),
        "generated_config_h_sha256": validation._sha256(build_root / "lib/config.h"),
        "make_variables": make_vars, "link_command": shlex.split(link_lines[0]),
        "objects_directly_linked": make_vars["src_sort_OBJECTS"],
        "archive_members_required": {k: sorted(members[k]) for k in sorted(configured_archives)},
        "object_source_mapping": mappings, "source_files": files,
        "source_file_count": len(files), "release_source_file_count": len(release_files),
        "object_count": len(mappings), "old_scope_count": len(old),
        "removed_source_files": sorted(set(old) - set(files)),
        "removed_archive_objects": sorted(set(variables["library_objects"]) - {
            "lib/" + m for m in members["lib/libcoreutils.a"]}),
        "added_release_source_files": [],
        "added_generated_sources": ["generated-config/src/version.c"],
        "generated_source_justification": "Automake nodist_src_libver_a_SOURCES; version.o actually extracted. The prior 329-file scope omitted this data-only generated module. No release source added or modified.",
        "external_link_inputs": sorted(set(loads) - configured_archives - {"src/sort.o"}),
        "external_boundary": "system startup objects and system libraries remain external definitions; exact refers to this configured program's source/object/archive closure, not libc or the loader",
        "source_integrity_verified": True,
    }


def graph_summary(graph: dict) -> dict:
    return {"analysis_status": graph["analysis_status"],
            "function_count": len(graph["functions"]), "call_edge_count": len(graph["call_edges"]),
            "resolved_indirect_edge_count": sum(e["edge_type"] == "indirect_resolved" for e in graph["call_edges"]),
            "unresolved_indirect_callsite_count": len(graph["unresolved_indirect_callsites"]),
            "begfield": validation.map_source_identity(graph, "src/sort.c", "begfield")}


def reachable_target_sets(graph: dict) -> dict:
    functions = {f["identity"]: f for f in graph["functions"]}
    result = {}
    for edge in graph["call_edges"]:
        if edge["edge_type"] != "indirect_resolved" or not functions[edge["caller"]]["reachable_from_entry"]:
            continue
        caller = functions[edge["caller"]]
        # Comparisons use source-qualified names, never llvm-link numeric suffixes.
        key = stable_json([caller["source_file"], caller["name"], edge["callsite"]]).strip()
        targets = sorted({functions[t].get("source_qualified_identity", t.split("#llvm=")[0])
                          for t in edge["indirect_target_set"]})
        value = {"caller": caller["source_qualified_identity"], "callsite": edge["callsite"],
                 "source_target_set": targets, "semantic_target_count": edge["indirect_target_count"],
                 "run_local_target_set": edge["indirect_target_set"]}
        if key in result and result[key]["source_target_set"] != targets:
            raise RuntimeError("callsite source collision needs finer provenance for scope comparison")
        result[key] = value
    return result


def run(output: Path) -> dict:
    validation.verify_frozen_queries(load_records(validation.HISTORICAL / "records.json"))
    entries = load_source_manifest(validation.HISTORICAL / "source_manifest.json")
    entry = next(e for e in entries if e["affected_version"] == "9.7")
    native = validation.REPO / "build/coreutils-9.7-sort-scope"
    scope = derive_linker_scope(entry, native)
    if scope != derive_linker_scope(entry, native):
        raise RuntimeError("scope derivation is not deterministic")
    (validation.HISTORICAL / "coreutils_9_7_linker_scope.json").write_text(stable_json(scope))
    # Keep a normalized, inspectable link-map excerpt: inclusion reasons and all
    # LOAD inputs. Addresses/host paths do not become scientific identities.
    raw_map = (native / "sort-linker-exact.map").read_text()
    header = raw_map.split("Merging program properties", 1)[0].split("Discarded input sections", 1)[0]
    excerpt = header + "\n" + "\n".join(l for l in raw_map.splitlines() if l.startswith("LOAD ")) + "\n"
    (validation.HISTORICAL / "evidence/coreutils-9.7-linker.map").write_text(excerpt)
    helper = validation.REPO / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf"
    inventory = inventory_toolchain(helper=helper)
    graphs, builds = {}, {}
    for name, selected in (("archive_superset", {"source_scope_kind": "archive_superset",
            "source_files": entry["programs"]["sort"]["source_files"], "evidence": "security/historical/source_manifest.json"}),
                           ("linker_exact", scope)):
        print(f"scope checkpoint: {name}: compile LLVM IR", flush=True)
        build = validation.build_historical_bitcode(entry, "sort", output / name, inventory=inventory, scope=selected)
        graph = analyze_build(build, entry_point="main", inventory=inventory, svf_options=validation.PRIMARY_OPTIONS)
        (output / name / "graph.json").write_text(stable_json(graph))
        graphs[name], builds[name] = graph, build
        if graph["analysis_status"] != "success":
            raise RuntimeError(f"{name} failed; diagnostics retained in {output / name / 'graph.json'}")
        print(f"scope checkpoint: {name}: SVF success", flush=True)
    old, new = (graphs[k] for k in ("archive_superset", "linker_exact"))
    old_sets, new_sets = reachable_target_sets(old), reachable_target_sets(new)
    changes = [{"callsite_key": key, "archive_superset": old_sets.get(key), "linker_exact": new_sets.get(key)}
               for key in sorted(old_sets.keys() | new_sets.keys())
               if (old_sets.get(key, {}).get("source_target_set"), old_sets.get(key, {}).get("semantic_target_count")) !=
                  (new_sets.get(key, {}).get("source_target_set"), new_sets.get(key, {}).get("semantic_target_count"))]
    result = {"schema_version": 1, "primary_options": list(validation.PRIMARY_OPTIONS),
              "toolchain": inventory, "repository": new["provenance"]["repository"],
              "identity_ambiguity_diagnostic": {
                  name: validation.map_source_identity(graph, "lib/xstrtol.c", "bkm_scale")
                  for name, graph in graphs.items()
              },
              "scope": scope, "archive_superset": graph_summary(old), "linker_exact": graph_summary(new),
              "reachable_indirect_target_set_changes": changes,
              "target_set_comparison": "All reachable callers; compare source-qualified memberships and cardinality. Preserve run-local target identities for audit, not cross-run scientific identity.",
              "archive_superset_reachable_indirect_callsites": list(old_sets.values()),
              "linker_exact_reachable_indirect_callsites": list(new_sets.values()),
              "program_results": {k: validation._program_summary(entry, "sort", builds[k], graphs[k], graphs[k]) for k in graphs}}
    # The checkpoint reruns only the unchanged primary configuration. Do not
    # mislabel primary data as a new ff-eq-base sensitivity execution.
    for row in result["program_results"].values():
        row.pop("sensitivity_without_ff_eq_base")
    verify_source_tree_sha256(Path(entry["resolved_source_tree"]), entry["source_tree_sha256"])
    (validation.HISTORICAL / "semantic_scope_validation.json").write_text(stable_json(result))
    return result


def finalize_checkpoint(output: Path) -> None:
    """Attach first-class scope provenance without replacing milestone results."""
    root = validation.HISTORICAL
    validation.verify_frozen_queries(load_records(root / "records.json"))
    entries = load_source_manifest(root / "source_manifest.json")
    result = json.loads((root / "semantic_scope_validation.json").read_text())
    entry = next(e for e in entries if e["affected_version"] == "9.7")
    scope = derive_linker_scope(entry, validation.REPO / "build/coreutils-9.7-sort-scope")
    for key in ("source_files", "object_source_mapping", "source_revision", "source_tree_sha256"):
        if scope[key] != result["scope"][key]:
            raise RuntimeError("scope evidence changed since the semantic run; rerun analysis")
    result["scope"] = scope
    (root / "coreutils_9_7_linker_scope.json").write_text(stable_json(scope))
    graphs = {name: json.loads((output / name / "graph.json").read_text())
              for name in ("archive_superset", "linker_exact")}
    result["toolchain"] = graphs["linker_exact"]["provenance"]["toolchain"]
    result["repository"] = graphs["linker_exact"]["provenance"]["repository"]
    result["analysis_backend"] = graphs["linker_exact"]["analysis_backend"]
    result["pointer_analysis"] = graphs["linker_exact"]["pointer_analysis"]
    mappings = [result[k]["begfield"] for k in ("archive_superset", "linker_exact")]
    if any(m["candidate_count"] != 1 for m in mappings):
        raise RuntimeError("begfield scope comparison is not uniquely mapped")
    before, after = [m["candidates"][0] for m in mappings]
    result["begfield_scope_sensitivity"] = {
        "reachability_changed": before["reachable_from_entry"] != after["reachable_from_entry"],
        "raw_depth_changed": before["raw_call_depth"] != after["raw_call_depth"],
        "shortest_path_changed": before["shortest_call_path"] != after["shortest_call_path"],
        "direct_edges_on_new_path": sum(e["edge_type"] == "direct" for e in after["shortest_call_path"]["edges"] or []),
        "indirect_edges_on_new_path": sum(e["edge_type"] == "indirect_resolved" for e in after["shortest_call_path"]["edges"] or []),
    }
    result["identity_ambiguity_diagnostic"] = {
        name: validation.map_source_identity(graph, "lib/xstrtol.c", "bkm_scale")
        for name, graph in graphs.items()
    }
    for change in result["reachable_indirect_target_set_changes"]:
        if change["archive_superset"] and change["linker_exact"]:
            change["change_kind"] = "target_membership_or_cardinality_changed"
        elif not change["linker_exact"]:
            caller = change["archive_superset"]["caller"]
            matches = [f for f in graphs["linker_exact"]["functions"] if f["source_qualified_identity"] == caller]
            change["change_kind"] = (
                "caller_definition_removed" if not matches else
                "caller_no_longer_reachable" if not any(f["reachable_from_entry"] for f in matches) else
                "not_a_reachable_resolved_callsite_in_new_graph"
            )
        else:
            change["change_kind"] = "new_reachable_resolved_callsite"
    (root / "semantic_scope_validation.json").write_text(stable_json(result))
    rows = audit_existing_scopes(entries)
    rows.append({"program_key": ["gnu-coreutils", "9.7", "sort"],
                 "source_count": result["scope"]["source_file_count"],
                 "release_source_count": result["scope"]["release_source_file_count"],
                 "source_scope_kind": "linker_exact",
                 "derivation_script": "security/historical/scope_checkpoint.py",
                 "confidence": "successful configured native link; exact archive members mapped; generated version module included; all IR and SVF stages succeeded",
                 "needs_future_linker_exact_reconstruction": False,
                 "evidence": "security/historical/coreutils_9_7_linker_scope.json"})
    rows.sort(key=lambda row: row["program_key"])
    audit = {"schema_version": 1, "policy": "linker_exact_primary_when_faithfully_recoverable",
             "external_boundary": "system-library/startup definitions remain external",
             "programs": rows}
    (root / "source_scope_audit.json").write_text(stable_json(audit))
    baseline_path = root / "semantic_validation.json"
    baseline = json.loads(baseline_path.read_text())
    kinds = {tuple(r["program_key"]): r["source_scope_kind"] for r in rows}
    kinds[("gnu-coreutils", "9.7", "sort")] = "archive_superset"
    # This retained milestone analyzed the old lists. Never relabel it merely
    # because a later, separately stored measurement completed the closure.
    for version in ("8.17-7.fc18", "8.23-9.fc22"):
        kinds[("gnu-coreutils", version, "sort")] = "reconstructed_program_scope"
    for row in baseline["programs"]:
        kind = kinds[tuple(row["program_key"])]
        row["source_scope_kind"] = kind
        row["build_configuration"]["source_scope_kind"] = kind
        row["scope_audit"] = "security/historical/source_scope_audit.json"
        if kind == "archive_superset":
            row["primary_scope_superseded_by"] = "security/historical/semantic_scope_validation.json#/linker_exact"
    for row in baseline["observations"]:
        declared = next(q for q in validation.OBSERVATIONS
                        if q["cve"] == row["cve"] and f"{q['source_file']}::{q['function']}" == row["vulnerable_function_identity"])
        row["source_scope_kind"] = kinds[(declared["project"], declared["version"], declared["program"])]
    baseline_path.write_text(stable_json(baseline))
    lines = ["# Pre-v2 semantic scope and identity checkpoint", "",
             "The frozen records, census, and source manifest are unchanged. This is a six-program pilot instrument audit, not population v2.", "",
             "## Scope audit", "", "| Program | Sources | Scope kind | Further exact reconstruction? |", "|---|---:|---|---|"]
    for row in rows:
        lines.append(f"| {'/'.join(row['program_key'])} | {row['source_count']} | {row['source_scope_kind']} | {'yes' if row['needs_future_linker_exact_reconstruction'] else 'no'} |")
    lines.extend(["", "The retained milestone's 8.17/8.23 lists omit generated `src/version.c`. Later completion, when present, is recorded separately in `fedora_sort_scope_validation.json`; old measurements are never relabeled. The table reflects the latest validated scope audit.", "",
                  "## Coreutils 9.7", "",
                  "Reproduce with `bash scripts/run_semantic_scope_checkpoint.sh`. It authenticates the source, reconfigures the same GCC build, realizes Automake BUILT_SOURCES, links native sort with a GNU ld map, and runs the unchanged primary Clang/LLVM/SVF configuration on both scopes.", "",
                  "`coreutils_9_7_linker_scope.json` contains the configured variables/link command, complete selected object/source mapping, and exact removed source/object lists. `evidence/coreutils-9.7-linker.map` retains inclusion reasons and LOAD inputs.", "",
                  f"Old scope: {result['scope']['old_scope_count']} release C sources. New: {result['scope']['release_source_file_count']} release C sources plus generated version.c = {result['scope']['source_file_count']} translation units/objects. Removed {len(result['scope']['removed_source_files'])} release sources; no release source added. version.c is added because the native link actually extracts version.o, not because of any depth outcome.", "",
                  "| Metric | Archive superset | Linker exact |", "|---|---:|---:|"])
    for key in ("function_count", "call_edge_count", "resolved_indirect_edge_count", "unresolved_indirect_callsite_count"):
        lines.append(f"| {key} | {result['archive_superset'][key]} | {result['linker_exact'][key]} |")
    for name in ("archive_superset", "linker_exact"):
        mapping = result[name]["begfield"]
        lines.extend(["", f"### {name}: begfield", "", f"Mapping: `{mapping['semantic_mapping_status']}`; candidates: {mapping['candidate_count']}."])
        for candidate in mapping["candidates"]:
            path = candidate["shortest_call_path"]
            lines.extend(["", f"Depth: {candidate['raw_call_depth']}. Path: `{' -> '.join(path['function_identities'] or [])}`.", ""])
            for edge in path["edges"] or []:
                lines.append(f"- `{edge['caller']}` --{edge['edge_type']}--> `{edge['callee']}` at `{edge['callsite']}`; target cardinality `{edge['indirect_target_count']}`; complete targets `{edge['indirect_target_set']}`.")
    lines.extend(["", f"Changed reachable indirect callsite target sets/cardinalities: {len(result['reachable_indirect_target_set_changes'])}. Complete before/after sets are retained in semantic_scope_validation.json; source-qualified memberships and cardinalities are compared, not link-order-dependent LLVM numeric suffixes.", "",
                  "Seven retained reachable callsites have smaller target sets: two hash comparisons, hash's hasher, and three heap comparisons shrink from 25 targets to 2; randread's error callback shrinks from 3 to 1. One hash_free callsite is no longer reachable, and two mcel_tocmp callsites disappear with their definitions. This is a real scope sensitivity of the may-call graph, despite unchanged begfield depth.", "",
                  "## Identity and query guard", "",
                  "Missing and ambiguous source identities are distinct. Ambiguity retains every full candidate row, including LLVM symbol, linkage, source location, reachability, depth, and shortest-path provenance, without choosing one. Gnulib's xstrtol inclusion pattern creates separate static functions from the same source location; translation-unit provenance could distinguish instances but cannot justify selecting one for a source-only query. No automatic disambiguation rule is introduced.", "",
                  "The real archive-superset bkm_scale diagnostic retains four candidates, including the three unreachable instances and one depth-3 instance, as source_identity_ambiguous. The independently derived linker-exact scope has one instance. This is a scope-derived difference, not selection of the reachable candidate.", "",
                  "The fail-closed query guard checks exact per-CVE function membership against records.json and exact source/function pairs against the independently verified milestone location ledger. It also checks program/version and duplicate queries. Records never construct the graph.", "",
                  "The remaining legacy scope qualification is explicit; no historical mean, median, threshold, or expanded-population result is calculated.", ""])
    (root / "evidence/semantic-scope-checkpoint.md").write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--finalize-existing", action="store_true")
    args = parser.parse_args()
    if not args.finalize_existing:
        run(args.output_dir.resolve())
    finalize_checkpoint(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
