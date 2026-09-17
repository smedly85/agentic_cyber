"""Measure the pinned FreeBSD sort only after original BSD Make link success."""
import json
from pathlib import Path
import shlex
from security.historical import semantic_validation as v
from security.historical.analysis import verify_source_tree_sha256
from security.historical.v2_study import ROOT, read, fingerprint
from security.historical.v2_build import persist
from security.historical.v2_seed import graph_quality
from security.semantic_callgraph import BuildResult, inventory_toolchain, analyze_build, stable_json


def main():
    mapping = next(m for m in read("v2_vulnerable_function_mappings.json")["members"] if m["cve_id"] == "CVE-2001-0310")
    if not mapping["completed"] or mapping["mapping_fingerprint"] != fingerprint({k: val for k, val in mapping.items() if k != "mapping_fingerprint"}):
        raise RuntimeError("mapping must be frozen before measurement")
    build = read("v2_freebsd_cross_build.json")
    if build["returncode"] or build["source_tree_sha256"] != mapping["source_tree_sha256"]:
        raise RuntimeError("faithful historical cross-link unavailable")
    audit = v.REPO / "build/historical-v2/freebsd-4.1.1-sort"
    staging = json.loads((audit / "staging.json").read_text())
    stage, source, objects = (Path(staging[k]) for k in ("stage", "source", "objects"))
    verify_source_tree_sha256(source, mapping["source_tree_sha256"])
    normalize = lambda s: s.replace(str(stage), "$STAGING").replace(str(v.REPO), "$REPO")
    variables = build["configured_make_variables"]
    expected_objects = shlex.split(variables["OBJS"])
    expected_sources = shlex.split(variables["SRCS"])
    raw = (audit / "native-cross-link.log").read_text()
    # Linker -t emits one input per line. No program archive appears in this
    # original target; system CRT/libc stay explicitly external.
    trace = [line.strip() for line in raw.splitlines() if line.strip() in expected_objects]
    if sorted(trace) != sorted(expected_objects) or len(trace) != len(set(trace)):
        raise RuntimeError("actual linker inputs do not equal original Make OBJS")
    if any(".a(" in line for line in raw.splitlines()):
        raise RuntimeError("unexpected extracted archive member needs provenance review")
    recipes = [shlex.split(line) for line in raw.splitlines() if line.startswith("clang-21 ") and " -c " in line]
    recipe_by_source = {Path(r[r.index("-c") + 1]).name: r for r in recipes}
    if len(recipes) != len(expected_sources) or set(recipe_by_source) != set(expected_sources):
        raise RuntimeError("compile recipes do not uniquely cover original Make SRCS")
    evidence = ROOT / "evidence/v2/freebsd-4.1.1-sort"
    evidence.mkdir(parents=True, exist_ok=True)
    maptext = normalize((objects / "sort-v2.map").read_text())
    (evidence / "linker-evidence.map").write_text(maptext)
    output = audit / "semantic"
    output.mkdir(exist_ok=True)
    inventory = inventory_toolchain(helper=v.REPO / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf")
    units, commands, bitcodes, modules = [], [], [], []
    for index, name in enumerate(sorted(expected_sources)):
        identity = "gnu/usr.bin/sort/" + name
        actual = source / identity
        recipe = recipe_by_source[name]
        obj = Path(name).with_suffix(".o").name
        if obj not in trace or not (objects / obj).is_file():
            raise RuntimeError("native source/object association missing")
        module = output / f"tu-{index:04d}.bc"
        command, _ = v._clang_command(recipe, cwd=objects, output=module, source_root=source,
                                     build_root=objects, clang=inventory["tools"]["clang"]["path"], manifest_source=identity)
        command.insert(1, f"-fdebug-prefix-map={stage / 'sysroot'}=external-sysroot")
        result = v._run(command, cwd=objects)
        (output / (name + ".log")).write_text(normalize(result.stdout + result.stderr))
        if result.returncode:
            raise RuntimeError("IR unavailable: " + identity + "; diagnostics retained")
        commands.append([normalize(x) for x in command])
        units.append({"source_file": identity, "source_provenance_kind": "authenticated_release_translation_unit",
                      "source_sha256": v._sha256(actual), "object": obj, "archive": None,
                      "compile_recipe_provenance": {"configured_compiler_recipe": [normalize(x) for x in recipe],
                                                     "clang_command": commands[-1]}})
        modules.append(module)
        bitcodes.append({"path": module.name, "sha256": v._sha256(module), "manifest_source": identity})
    linked = output / "linked.bc"
    linkcommand = [inventory["tools"]["llvm-link"]["path"], *map(str, modules), "-o", str(linked)]
    linked_result = v._run(linkcommand)
    if linked_result.returncode:
        raise RuntimeError("llvm-link failed: " + linked_result.stderr)
    commands.append([normalize(x) for x in linkcommand])
    bitcodes.append({"path": linked.name, "sha256": v._sha256(linked)})
    scope = {"schema_version": 1, "program": "sort", "source_scope_kind": "linker_exact",
             "source_tree": mapping["source_tree"], "source_tree_sha256": mapping["source_tree_sha256"],
             "source_revision": mapping["affected_revision"], "configured_make_variables": variables,
             "objects_directly_linked": sorted(trace), "archive_members_required": {},
             "translation_units": units, "source_files": sorted(u["source_file"] for u in units),
             "translation_unit_count": len(units), "object_count": len(trace), "generated_build_modules": [],
             "external_link_inputs": sorted(normalize(line.strip()) for line in raw.splitlines() if line.startswith(str(stage / "sysroot"))),
             "scope_derivation_method": "Pinned BSD Make SRCS/OBJS, actual successful lld -t input trace and link map; seven direct release objects, no program archive",
             "build_evidence": "security/historical/v2_freebsd_cross_build.json",
             "evidence": (evidence / "linker-evidence.map").relative_to(v.REPO).as_posix(),
             "external_boundary": "Historical sysroot startup objects and system libraries excluded as in frozen instrument",
             "source_integrity_verified": True}
    (evidence / "scope.json").write_text(stable_json(scope))
    built = BuildResult("success", linked, tuple({"path": u["source_file"], "sha256": u["source_sha256"]} for u in units),
                        tuple(commands), tuple(bitcodes), (), "i386-unknown-freebsd4.1",
                        {"source_scope_kind": "linker_exact", "original_bsd_make": build, "translation_units": units})
    graph = analyze_build(built, entry_point="main", inventory=inventory, svf_options=v.PRIMARY_OPTIONS)
    graph_path = audit / "graph.json"
    if graph_path.exists():
        old = graph_path.with_name("graph.attempt-" + v._sha256(graph_path) + ".json")
        if not old.exists():
            old.write_bytes(graph_path.read_bytes())
    graph_path.write_text(stable_json(graph))
    verify_source_tree_sha256(source, mapping["source_tree_sha256"])
    verify_source_tree_sha256(ROOT / mapping["source_tree"], mapping["source_tree_sha256"])
    specimen = {"specimen_id": "freebsd/4.1.1/sort", "source_tree": mapping["source_tree"],
                "source_revision": mapping["affected_revision"], "source_tree_sha256": mapping["source_tree_sha256"],
                "source_scope_kind": "linker_exact", "source_count": len(units),
                "source_scope_evidence": (evidence / "scope.json").relative_to(v.REPO).as_posix(),
                "mapping_fingerprint_before_measurement": mapping["mapping_fingerprint"],
                "analysis_status": graph["analysis_status"], "graph_quality": graph_quality(graph),
                "analysis_provenance": graph["provenance"], "failures": graph["failures"],
                "retained_graph_path": graph_path.relative_to(v.REPO).as_posix(), "retained_graph_sha256": v._sha256(graph_path)}
    persist(specimen, [mapping], graph)


if __name__ == "__main__":
    main()
