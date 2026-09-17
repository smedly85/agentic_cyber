#!/usr/bin/env python3
"""Complete the two Fedora sort pilot link closures without altering v1 data."""
from __future__ import annotations

import argparse
import importlib
import json
import re
import shlex
from pathlib import Path

from security.historical import semantic_validation as v
from security.historical.analysis import load_records, load_source_manifest, verify_source_tree_sha256
from security.historical.scope_checkpoint import audit_existing_scopes
from security.semantic_callgraph import analyze_build, inventory_toolchain, stable_json

VERSIONS = ("8.17-7.fc18", "8.23-9.fc22")
GENERATED = "generated-config/src/version.c"


def checked(command: list[str], *, cwd: Path, log: Path) -> str:
    result = v._run(command, cwd=cwd)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"configured build command failed; diagnostics: {log}")
    return result.stdout


def derive_scope(entry: dict, output: Path) -> dict:
    """Actual native relink, all program archive extractions, and .Po mappings."""
    key = v._program_key(entry, "sort")
    spec = v.BUILD_SPECS[key]
    build = v.REPO / spec.build_dir
    source = Path(entry["resolved_source_tree"])
    verify_source_tree_sha256(source, entry["source_tree_sha256"])
    recursive = spec.layout == "recursive"
    cwd = build / "src" if recursive else build
    prefix = "" if recursive else "src_"
    names = [prefix + name for name in ("sort_OBJECTS", "sort_LDADD", "sort_DEPENDENCIES",
                                        "libver_a_OBJECTS", "libver_a_LIBADD")]
    names += ["nodist_" + prefix + "libver_a_SOURCES", "PACKAGE_VERSION", "CC", "LDFLAGS"]
    variables = {name: list(v._configured_make_variable(cwd, name)) for name in names}
    version_source = "version.c" if recursive else "src/version.c"
    version_object = "version.o" if recursive else "src/version.o"
    version_archive = "libver.a" if recursive else "src/libver.a"
    core_archive = "../lib/libcoreutils.a" if recursive else "lib/libcoreutils.a"
    sort_object = "sort.o" if recursive else "src/sort.o"
    sort_target = "sort" if recursive else "src/sort"
    if variables[prefix + "sort_OBJECTS"] != [sort_object]:
        raise RuntimeError("unexpected direct program objects")
    archives = {s for s in variables[prefix + "sort_LDADD"] if s.endswith(".a")}
    if archives != {version_archive, core_archive}:
        raise RuntimeError("unrecognized configured archive closure")
    if variables[prefix + "libver_a_OBJECTS"] != [version_object] or variables[prefix + "libver_a_LIBADD"]:
        raise RuntimeError("unexpected generated archive objects")
    if [s for s in variables["nodist_" + prefix + "libver_a_SOURCES"] if s.endswith(".c")] != [version_source]:
        raise RuntimeError("unexpected generated source mapping")
    makefile = (cwd / "Makefile").read_text()
    generation_rule = re.search(rf"(?m)^{re.escape(version_source)}: Makefile\n(?:\t[^\n]*\n)+", makefile)
    if not generation_rule:
        raise RuntimeError("configured version source generation rule unavailable")
    overrides = [f"{k}={value}" for k, value in spec.make_variables]
    config_status = "../config.status" if recursive else "config.status"
    make = ["make", "--no-print-directory", "-f", "Makefile", "-o", config_status, "V=1", "MAKEINFO=true", *overrides]
    before = v._sha256(build / "src/version.c") if (build / "src/version.c").exists() else None
    # -W Makefile regenerates only the requested legitimate build-tree source.
    # No source-tree target is passed or patched.
    generation_command = [*make, "-W", "Makefile", version_source]
    checked(generation_command, cwd=cwd, log=output / "generate-version.log")
    content = (build / "src/version.c").read_text()
    expected = '#include <config.h>\nchar const *Version = "' + variables["PACKAGE_VERSION"][0] + '";\n'
    if content != expected:
        raise RuntimeError("generated version.c disagrees with configured PACKAGE_VERSION recipe")
    checked([*make, version_archive], cwd=cwd, log=output / "native-version-archive.log")
    map_name = "sort-linker-exact.map"
    link_flags = "LDFLAGS=" + " ".join([*variables["LDFLAGS"], f"-Wl,-Map={map_name}"])
    link_command = [*make, "-W", sort_object, link_flags, sort_target]
    native_output = checked(link_command, cwd=cwd, log=output / "native-link.log")
    link_lines = [s for s in native_output.splitlines() if f"-o {sort_target} " in s and " -c " not in s]
    if len(link_lines) != 1:
        raise RuntimeError("native configured link command not unique")
    map_path = cwd / map_name
    text = map_path.read_text()
    members: dict[str, set[str]] = {}
    for archive, member in re.findall(r"(?m)^(\S+\.a)\(([^()]+)\)", text):
        members.setdefault(archive, set()).add(member)
    loads = re.findall(r"(?m)^LOAD (.+)$", text)
    relative_loads = {s for s in loads if not Path(s).is_absolute()}
    if relative_loads != archives | {sort_object} or members.get(version_archive) != {"version.o"}:
        raise RuntimeError("native link inputs not completely accounted for")
    if {s for s in members if not Path(s).is_absolute()} != archives:
        raise RuntimeError("unaccounted program archive member")
    derivation = importlib.import_module("security.historical.derive_coreutils_8_17_sort_scope" if recursive
                                         else "security.historical.derive_coreutils_8_23_sort_scope")
    narrow = (derivation.derive_scope(source, build / "src/Makefile", build / "lib/Makefile", map_path)
              if recursive else derivation.derive_scope(source, build / "Makefile", map_path))
    old_files = entry["programs"]["sort"]["source_files"]
    if narrow["analyzed_source_files"] != old_files:
        raise RuntimeError("native library closure changed beyond the predeclared generated-module correction")
    # Map every actual object from compiler-generated dependency metadata, not
    # from its basename. The library derivation above is an independent check.
    objects = [("src/sort.o", None)] + [(f"lib/{m}", "lib/libcoreutils.a") for m in sorted(members[core_archive])]
    objects += [("src/version.o", "src/libver.a")]
    units = []
    for object_path, archive in objects:
        obj = Path(object_path)
        dependency = build / obj.parent / ".deps" / (obj.stem + ".Po")
        first_rule = dependency.read_text().replace("\\\n", " ").splitlines()[0]
        target, rest = first_rule.split(":", 1)
        object_cwd = build / obj.parent if recursive else build
        actual_object = (object_cwd / target.strip()).resolve()
        if actual_object != (build / obj).resolve():
            raise RuntimeError("object dependency target mismatch")
        prerequisites = shlex.split(rest)
        # GCC dependency output starts with the compilation input. Further .c
        # prerequisites can be included implementation files (e.g. xstrtol.c),
        # not additional translation units. Retain that include context.
        if not prerequisites or not prerequisites[0].endswith(".c"):
            raise RuntimeError("primary compiler dependency is not a C input")
        actual_source = (object_cwd / prerequisites[0]).resolve()
        generated = object_path == "src/version.o"
        source_file = GENERATED if generated else actual_source.relative_to(source).as_posix()
        if generated and actual_source != (build / "src/version.c").resolve():
            raise RuntimeError("generated source escaped configured build")
        if not generated and source_file not in old_files:
            raise RuntimeError("unexpected authenticated source in object closure")
        units.append({"source_file": source_file,
                      "source_provenance_kind": "configured_build_generated" if generated else "authenticated_historical_tree",
                      "source_sha256": v._sha256(actual_source), "object_name": obj.name,
                      "configured_object_target": object_path, "archive": archive,
                      "link_role": "static_archive_member" if archive else "direct_program_object",
                      "dependency_evidence": dependency.relative_to(build).as_posix(),
                      "dependency_c_inputs": [s for s in prerequisites if s.endswith(".c")],
                      "dependency_rule": first_rule})
    files = sorted(u["source_file"] for u in units)
    if len(files) != len(set(files)) or set(files) != set(old_files) | {GENERATED}:
        raise RuntimeError("source/compile-instance closure mismatch")
    evidence_name = "coreutils-" + variables["PACKAGE_VERSION"][0] + "-linker.map"
    excerpt = text.split("Merging ", 1)[0].split("Discarded input sections", 1)[0]
    excerpt += "\n" + "\n".join(s for s in text.splitlines() if s.startswith("LOAD ")) + "\n"
    (v.HISTORICAL / "evidence" / evidence_name).write_text(excerpt)
    verify_source_tree_sha256(source, entry["source_tree_sha256"])
    return {"schema_version": 1, "program_key": list(key), "source_scope_kind": "linker_exact",
            "source_revision": entry["source_revision"], "source_tree_sha256": entry["source_tree_sha256"],
            "source_tree": entry["source_tree"], "source_files": files, "source_file_count": len(files),
            "object_count": len(objects), "release_source_count": len(old_files),
            "configured_build_directory": spec.build_dir, "link_working_directory": "src" if recursive else ".",
            "scope_derivation_method": "successful configured native link; GNU ld extracted members; compiler .Po object/source mappings; independent configured Automake library-source cross-check",
            "evidence": "security/historical/evidence/" + evidence_name,
            "make_variables": variables, "make_overrides": dict(spec.make_variables),
            "native_link_command": shlex.split(link_lines[0]), "native_link_make_command": link_command,
            "native_compiler_version": v._run([variables["CC"][0], "--version"]).stdout.strip(),
            "native_linker_version": v._run(["ld", "--version"]).stdout.strip(),
            "configured_config_h_sha256": v._sha256(build / "lib/config.h"),
            "objects_directly_linked": ["src/sort.o"],
            "archive_members_required": {"src/libver.a": ["version.o"], "lib/libcoreutils.a": sorted(members[core_archive])},
            "translation_units": sorted(units, key=lambda u: u["source_file"]),
            "generated_module": {"source_file": GENERATED, "configured_source_path": "src/version.c",
                                 "object": "src/version.o", "archive": "src/libver.a",
                                 "generation_rule": generation_rule.group(0), "generation_command": generation_command,
                                 "package_version": variables["PACKAGE_VERSION"][0], "contents": content,
                                 "previous_sha256": before, "regenerated_sha256": v._sha256(build / "src/version.c"),
                                 "authenticated_release_source": False},
            "removed_translation_units": [], "added_translation_units": [GENERATED],
            "external_link_inputs": sorted({s for s in loads if Path(s).is_absolute()}),
            "external_boundary": "system startup objects and system libraries remain external; no archive-wide inclusion",
            "source_integrity_verified": True}


def stats(graph: dict, count: int) -> dict:
    return {"source_count": count, "function_count": len(graph["functions"]),
            "call_edge_count": len(graph["call_edges"]),
            "resolved_indirect_edge_count": sum(e["edge_type"] == "indirect_resolved" for e in graph["call_edges"]),
            "unresolved_indirect_callsite_count": len(graph["unresolved_indirect_callsites"])}


def run(output: Path) -> dict:
    v.verify_frozen_queries(load_records(v.HISTORICAL / "records.json"))
    entries = load_source_manifest(v.HISTORICAL / "source_manifest.json")
    helper = v.REPO / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf"
    inventory = inventory_toolchain(helper=helper)
    programs = []
    for version in VERSIONS:
        print(f"Fedora sort {version}: configured native link closure", flush=True)
        entry = next(e for e in entries if e["affected_version"] == version)
        local = output / version
        local.mkdir(parents=True, exist_ok=True)
        scope = derive_scope(entry, local)
        analyses = {}
        for kind, selected in (("reconstructed_program_scope", {"source_scope_kind": "reconstructed_program_scope",
                               "source_files": entry["programs"]["sort"]["source_files"], "evidence": "security/historical/source_manifest.json"}),
                               ("linker_exact", scope)):
            print(f"Fedora sort {version}: {kind}: LLVM/SVF", flush=True)
            build = v.build_historical_bitcode(entry, "sort", local / kind, inventory=inventory, scope=selected)
            graph = analyze_build(build, entry_point="main", inventory=inventory, svf_options=v.PRIMARY_OPTIONS)
            (local / kind / "graph.json").write_text(stable_json(graph))
            if graph["analysis_status"] != "success":
                raise RuntimeError(f"{version}/{kind} failed; see retained graph diagnostics")
            analyses[kind] = (build, graph)
        new_build, new_graph = analyses["linker_exact"]
        old_build, old_graph = analyses["reconstructed_program_scope"]
        provenance = {u["source_file"]: u for u in new_build.configuration["translation_units"]}
        for unit in scope["translation_units"]:
            compiled = provenance[unit["source_file"]]
            mismatches = {k: {"native": unit[k], "llvm": compiled[k]}
                          for k in ("source_sha256", "configured_object_target", "source_provenance_kind")
                          if unit[k] != compiled[k]}
            if mismatches:
                raise RuntimeError(f"LLVM compile instance disagrees with native closure: {unit['source_file']}: {mismatches}")
            unit["compile_recipe_provenance"] = compiled["compile_recipe_provenance"]
        scope_file = v.HISTORICAL / v.COREUTILS_LINKER_SCOPES[version]
        scope_file.write_text(stable_json(scope))
        observations = []
        for query in v.OBSERVATIONS:
            if query["version"] != version:
                continue
            before = v.map_source_identity(old_graph, query["source_file"], query["function"])
            after = v.map_source_identity(new_graph, query["source_file"], query["function"])
            # Preserve ambiguity rather than selecting a candidate. This pilot
            # comparison cannot be frozen as successful without unique mappings.
            row = {"cve": query["cve"], "requested_source_identity": after["requested_source_identity"],
                   "old": before, "new": after}
            if before["candidate_count"] != 1 or after["candidate_count"] != 1:
                row["comparison_status"] = "source_identity_not_uniquely_mapped"
            else:
                a, b = before["candidates"][0], after["candidates"][0]
                row.update({"comparison_status": "compared_unique_mappings",
                            "raw_depth_changed": a["raw_call_depth"] != b["raw_call_depth"],
                            "shortest_path_changed": a["shortest_call_path"] != b["shortest_call_path"],
                            "indirect_target_sets_changed": [e["indirect_target_set"] for e in a["shortest_call_path"]["edges"] or [] if e["edge_type"] == "indirect_resolved"] != [e["indirect_target_set"] for e in b["shortest_call_path"]["edges"] or [] if e["edge_type"] == "indirect_resolved"]})
            observations.append(row)
        programs.append({"program_key": scope["program_key"], "source_scope_kind": "linker_exact", "scope": scope,
                         "old_stats": stats(old_graph, len(old_build.source_files)), "new_stats": stats(new_graph, len(new_build.source_files)),
                         "observations": observations,
                         "graphs_identical_excluding_build_provenance": all(old_graph[k] == new_graph[k] for k in ("functions", "call_edges", "unresolved_indirect_callsites", "external_calls")),
                         "analyses": {kind: {"source_scope_kind": kind, "analysis_status": graph["analysis_status"],
                                             "provenance": graph["provenance"], "failures": graph["failures"]}
                                      for kind, (_, graph) in analyses.items()}})
        verify_source_tree_sha256(Path(entry["resolved_source_tree"]), entry["source_tree_sha256"])
    result = {"schema_version": 1, "analysis_backend": "clang_llvm_svf", "pointer_analysis": "andersen_wave_diff",
              "primary_options": list(v.PRIMARY_OPTIONS), "toolchain": inventory, "programs": programs,
              "modifies_historical_v1": False, "population_v2_started": False}
    (v.HISTORICAL / "fedora_sort_scope_validation.json").write_text(stable_json(result))
    return result


def render_markdown(result: dict, audit: dict) -> str:
    lines = ["# Fedora sort linker-exact semantic scope completion", "",
             "This completes the existing pilot instrument; it does not start population v2 or change frozen records, census, source manifest, or reconnaissance.", "",
             "Primary configuration remains Clang/LLVM 21.1.8, SVF 3.4 commit `67efb7745ce47b2b6853fd5696fc22c83d701e6c`, AndersenWaveDiff, `-stat=false -ff-eq-base`.", "",
             "Reproduce with `bash scripts/run_fedora_sort_scope_checkpoint.sh` after the existing authenticated Fedora source/build reconstructions are available. Native objects are reused except legitimate generated version inputs; all selected C inputs are separately compiled to LLVM for both comparisons.", "",
             "## Generated-module provenance", "",
             "Both configured Makefiles generate build-tree `src/version.c` from `PACKAGE_VERSION`, then compile `src/version.o` and archive it in `src/libver.a`. The recursive 8.17 build executes these rules from its `src` directory; 8.23 uses its nonrecursive root Makefile. GNU ld explicitly extracts `version.o` to satisfy `sort.o`'s `Version` reference.", "",
             "The two-line generated source includes `<config.h>` and defines `char const *Version` as `8.17` or `8.23`. It is configured build data, not authenticated release source. The generation rule, command, before/after hashes, complete contents, native link recipe and selected archive members are retained in each linker-scope JSON.", "",
             "Every TU records `source_provenance_kind`, source path/hash, configured object target, direct/archive role, archive membership, compiler dependency mapping, configured Make/compiler recipe, and exact normalized Clang command. Included implementation `.c` files in a dependency list are preserved as include context, not counted as separate compilation units. System startup objects/libraries remain explicit external inputs.", ""]
    lines.extend(["The object/recipe cross-check also exposed a prior 8.23 adapter issue: source-only Makefile matching selected `src/src_libsinglebin_sort_a-sort.o` instead of linked `src/sort.o`. The linker-exact build now binds each recipe to the object proven by the native closure. The retained old-scope comparison still uses its original recipe; no source or pointer-analysis option was changed.", ""])
    for program in result["programs"]:
        version = program["program_key"][1]
        scope = program["scope"]
        lines.extend([f"## Coreutils {version}", "",
                      f"Closure: one direct sort object, {len(scope['archive_members_required']['lib/libcoreutils.a'])} selected libcoreutils members, and one libver/version member. No release translation unit removed or added; only `{GENERATED}` added.", "",
                      "| Metric | Retained reconstructed scope | Linker-exact scope |", "|---|---:|---:|"])
        for field in ("source_count", "function_count", "call_edge_count", "resolved_indirect_edge_count", "unresolved_indirect_callsite_count"):
            lines.append(f"| {field} | {program['old_stats'][field]} | {program['new_stats'][field]} |")
        lines.extend(["", f"Full function/edge/unresolved/external graph records identical excluding build provenance: `{program['graphs_identical_excluding_build_provenance']}`.", ""])
        for observation in program["observations"]:
            lines.extend([f"### {observation['cve']} — {observation['requested_source_identity']}", ""])
            for side in ("old", "new"):
                mapping = observation[side]
                lines.append(f"{side}: `{mapping['semantic_mapping_status']}`; candidates: {mapping['candidate_count']}.")
                if mapping["candidate_count"] == 1:
                    candidate = mapping["candidates"][0]
                    path = candidate["shortest_call_path"]
                    lines.extend(["", f"Raw depth {candidate['raw_call_depth']}: `{' -> '.join(path['function_identities'] or [])}`.", ""])
                    for edge in path["edges"] or []:
                        site = edge["callsite"]
                        detail = (f"; all {edge['indirect_target_count']} may-targets: `{edge['indirect_target_set']}`"
                                  if edge["edge_type"] == "indirect_resolved" else "")
                        lines.append(f"- `{edge['caller']}` --{edge['edge_type']}--> `{edge['callee']}` at `{site['source_file']}:{site['line']}:{site['column']}`{detail}.")
                    lines.append("")
            lines.append(f"Depth changed: `{observation.get('raw_depth_changed')}`; path changed: `{observation.get('shortest_path_changed')}`; path indirect target sets changed: `{observation.get('indirect_target_sets_changed')}`.")
            lines.append("")
    lines.extend(["## Final pilot scope audit", "", "| Program | TUs | Kind | Generated module included | Evidence |", "|---|---:|---|---|---|"])
    for row in audit["programs"]:
        evidence = row.get("linker_exact_evidence", row.get("evidence", row.get("link_map")))
        lines.append(f"| {'/'.join(row['program_key'])} | {row['source_count']} | {row['source_scope_kind']} | {', '.join(row.get('generated_build_modules_included', [])) or 'none required'} | {evidence} |")
    lines.extend(["", "All classifications refer to separately validated primary scopes. The old semantic milestone retains its original 45/46-file reconstructed scopes and the 9.7 archive-superset scope with explicit supersession pointers; it is not relabeled.", "",
                  "A resolved indirect edge remains a possible static may-call target, not guaranteed runtime execution. No candidate is chosen from an ambiguous source identity, and the frozen-query consistency guard remains active. No population mean, median, or threshold is calculated.", ""])
    return "\n".join(lines)


def finalize(result: dict) -> None:
    entries = load_source_manifest(v.HISTORICAL / "source_manifest.json")
    v.verify_frozen_queries(load_records(v.HISTORICAL / "records.json"))
    rows = audit_existing_scopes(entries)
    prior_audit = json.loads((v.HISTORICAL / "source_scope_audit.json").read_text())
    nine = next(r for r in prior_audit["programs"] if r["program_key"] == ["gnu-coreutils", "9.7", "sort"])
    nine_scope = json.loads((v.HISTORICAL / "coreutils_9_7_linker_scope.json").read_text())
    nine_validation = json.loads((v.HISTORICAL / "semantic_scope_validation.json").read_text())
    entry9 = next(e for e in entries if e["affected_version"] == "9.7")
    if (nine_scope != nine_validation["scope"] or nine_scope["source_tree_sha256"] != entry9["source_tree_sha256"] or
            nine_validation["linker_exact"]["analysis_status"] != "success" or
            nine_scope["source_files"] != [s["path"] for s in nine_validation["program_results"]["linker_exact"]["source_files"]]):
        raise RuntimeError("retained 9.7 linker-exact evidence mismatch")
    evidence9 = (v.REPO / nine_scope["evidence"]).read_text()
    for archive, members in nine_scope["archive_members_required"].items():
        actual = set(re.findall(rf"(?m)^{re.escape(archive)}\(([^()]+)\)", evidence9))
        if actual != set(members):
            raise RuntimeError("retained 9.7 archive-member evidence mismatch")
    nine.update({"generated_build_modules_included": [GENERATED],
                 "scope_derivation_method": nine_scope["scope_derivation_method"],
                 "linker_exact_evidence": "security/historical/coreutils_9_7_linker_scope.json"})
    rows.append(nine)
    for row in rows:
        row.setdefault("generated_build_modules_included", [])
        row.setdefault("scope_derivation_method", "configured Make/Automake metadata plus verified native GNU ld archive-member map")
    rows.sort(key=lambda r: r["program_key"])
    audit = {**prior_audit, "programs": rows,
             "completion_evidence": "security/historical/fedora_sort_scope_validation.json"}
    (v.HISTORICAL / "source_scope_audit.json").write_text(stable_json(audit))
    baseline_path = v.HISTORICAL / "semantic_validation.json"
    baseline = json.loads(baseline_path.read_text())
    for row in baseline["programs"]:
        version = row["program_key"][1]
        if version in VERSIONS:
            if row["source_scope_kind"] != "reconstructed_program_scope":
                raise RuntimeError("retained milestone must not be relabeled")
            row["primary_scope_superseded_by"] = f"security/historical/fedora_sort_scope_validation.json#/programs/{VERSIONS.index(version)}"
    baseline_path.write_text(stable_json(baseline))
    markdown = render_markdown(result, audit)
    if markdown != render_markdown(json.loads(stable_json(result)), json.loads(stable_json(audit))):
        raise RuntimeError("scope report rendering is nondeterministic")
    (v.HISTORICAL / "evidence/fedora-sort-scope-completion.md").write_text(markdown)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=v.REPO / "build/fedora-sort-scope-checkpoint")
    parser.add_argument("--refresh-existing", action="store_true")
    args = parser.parse_args()
    result = (json.loads((v.HISTORICAL / "fedora_sort_scope_validation.json").read_text())
              if args.refresh_existing else run(args.output_dir.resolve()))
    finalize(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
