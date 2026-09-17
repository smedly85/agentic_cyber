"""Inspect util-linux's own Make/libtool link closure, without GNU-source substitution."""
from pathlib import Path
import json
import re
import shlex
from security.historical.v2_study import ROOT, read, write
from security.historical import semantic_validation as v
from security.historical.v2_build import checked, compile_scope, persist
from security.historical.v2_seed import graph_quality
from security.semantic_callgraph import analyze_build, inventory_toolchain, stable_json
from security.historical.analysis import verify_source_tree_sha256


def main():
    mapping = next(m for m in read("v2_vulnerable_function_mappings.json")["members"] if m["cve_id"] == "CVE-2017-2616")
    source = ROOT / mapping["source_tree"]
    verify_source_tree_sha256(source, mapping["source_tree_sha256"])
    build = v.REPO / "build/historical-v2/native/util-linux-2.29.1"
    out = v.REPO / "build/historical-v2/util-linux-2.29.1-su"
    out.mkdir(parents=True, exist_ok=True)
    variables = {n: list(v._configured_make_variable(build, n)) for n in (
        "su_OBJECTS", "su_LDADD", "su_DEPENDENCIES", "su_SOURCES", "libcommon_la_OBJECTS", "CC", "LDFLAGS", "BUILT_SOURCES")}
    make = ["make", "-j2", "--no-print-directory", "-f", "Makefile", "-o", "Makefile", "-o", "config.status", "V=1"]
    if variables["BUILT_SOURCES"]:
        checked([*make, *variables["BUILT_SOURCES"]], build, out / "built-sources.log")
    command = [*make, "LDFLAGS=" + " ".join([*variables["LDFLAGS"], "-Wl,-Map=su-v2.map"]), "su"]
    try:
        checked(command, build, out / "native-link.log")
    finally:
        verify_source_tree_sha256(source, mapping["source_tree_sha256"])
        write("v2_util_linux_build_audit.json", {"schema_version": 1, "source_tree": mapping["source_tree"],
            "source_tree_sha256": mapping["source_tree_sha256"], "make_variables": variables,
            "native_command": command, "configured_build_directory": build.relative_to(v.REPO).as_posix(),
            "log": (out / "native-link.log").relative_to(v.REPO).as_posix(),
            "status": "native_build_and_libtool_closure_under_review"})
    linkmap = (build / "su-v2.map").read_text()
    members = {}
    for archive, member in re.findall(r"(?m)^(\S+\.a)\(([^()]+)\)", linkmap):
        members.setdefault(archive, set()).add(member)
    program_archives = {a for a in members if (build / a).resolve().is_relative_to(build.resolve())}
    if program_archives != {"./.libs/libcommon.a"} or "libcommon.la" not in variables["su_LDADD"]:
        raise RuntimeError("unrecognized util-linux configured library closure")
    la = (build / "libcommon.la").read_text()
    if "old_library='libcommon.a'" not in la:
        raise RuntimeError("libtool archive provenance mismatch")
    targets = [(obj, None, None) for obj in variables["su_OBJECTS"]]
    for member in sorted(members["./.libs/libcommon.a"]):
        matches = [obj for obj in variables["libcommon_la_OBJECTS"] if Path(obj).with_suffix(".o").name == member]
        if len(matches) != 1:
            raise RuntimeError("native archive member lacks unique configured libtool object")
        targets.append((matches[0], ".libs/libcommon.a", member))
    units = []
    for target, archive, member in targets:
        obj = Path(target)
        dependency = build / obj.parent / ".deps" / (obj.stem + (".Plo" if archive else ".Po"))
        rule = dependency.read_text().replace("\\\n", " ").splitlines()[0]
        lhs, rhs = rule.split(":", 1)
        if lhs.strip() != target:
            raise RuntimeError("compiler dependency target mismatch")
        prerequisites = shlex.split(rhs)
        if not prerequisites[0].endswith(".c"):
            raise RuntimeError("unexpected compilation language/input")
        actual = (build / prerequisites[0]).resolve()
        identity = actual.relative_to(source.resolve()).as_posix()
        units.append({"source_file": identity, "source_provenance_kind": "authenticated_historical_tree",
                      "source_sha256": v._sha256(actual), "configured_object_target": target,
                      "archive": archive, "archive_member": member,
                      "link_role": "static_archive_member" if archive else "direct_program_object",
                      "compile_driver": "libtool" if archive else "compiler",
                      "dependency_evidence": dependency.relative_to(build).as_posix(), "dependency_rule": rule})
    loads = re.findall(r"(?m)^LOAD (.+)$", linkmap)
    local_program_loads = {x for x in loads if (build / x).resolve().is_relative_to(build.resolve())}
    if local_program_loads != set(variables["su_OBJECTS"]) | program_archives:
        raise RuntimeError("unaccounted native program load")
    evidence_dir = ROOT / "evidence/v2/util-linux-2.29.1-su"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    excerpt = linkmap.split("Merging ", 1)[0] + "\n" + "\n".join("LOAD " + x for x in loads) + "\n"
    (evidence_dir / "linker-evidence.map").write_text(excerpt)
    configured = json.loads((build / "v2-configure-status.json").read_text())
    scope = {"schema_version": 1, "source_scope_kind": "linker_exact", "program": "su",
             "source_tree": mapping["source_tree"], "source_tree_sha256": mapping["source_tree_sha256"],
             "configured_build_directory": build.relative_to(v.REPO).as_posix(), "make_variables": variables,
             "native_link_make_command": command, "objects_directly_linked": variables["su_OBJECTS"],
             "archive_members_required": {a: sorted(members[a]) for a in program_archives},
             "source_files": sorted(u["source_file"] for u in units), "translation_unit_count": len(units),
             "translation_units": sorted(units, key=lambda u: u["source_file"]),
             "scope_derivation_method": "successful configured Make/libtool link; GNU ld actual archive-member extraction; configured .lo/.o identities and compiler dependency primary-source mapping",
             "external_link_inputs": sorted(set(loads) - local_program_loads),
             "external_boundary": "system startup/libc and isolated matching PAM shared libraries remain external",
             "evidence": (evidence_dir / "linker-evidence.map").relative_to(v.REPO).as_posix()}
    scope_file = evidence_dir / "scope.json"
    scope_file.write_text(stable_json(scope))
    spec = v.HistoricalBuildSpec(build.relative_to(v.REPO).as_posix(), "nonrecursive", tuple(configured["configure_options"]), configured["configured_cc"])
    inventory = inventory_toolchain(helper=v.REPO / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf")
    built = compile_scope(scope, spec, out / "semantic", inventory)
    graph = analyze_build(built, entry_point="main", inventory=inventory, svf_options=v.PRIMARY_OPTIONS)
    graph_path = out / "graph.json"
    graph_path.write_text(stable_json(graph))
    persist({"specimen_id": "util-linux-2.29.1/su", "source_tree": mapping["source_tree"],
             "source_revision": mapping["affected_revision"], "source_tree_sha256": mapping["source_tree_sha256"],
             "source_scope_kind": "linker_exact", "source_count": len(units),
             "source_scope_evidence": scope_file.relative_to(v.REPO).as_posix(),
             "mapping_fingerprint_before_measurement": mapping["mapping_fingerprint"],
             "analysis_status": graph["analysis_status"], "graph_quality": graph_quality(graph),
             "analysis_provenance": graph["provenance"], "failures": graph["failures"],
             "retained_graph_path": graph_path.relative_to(v.REPO).as_posix(), "retained_graph_sha256": v._sha256(graph_path)}, [mapping], graph)


if __name__ == "__main__":
    main()
