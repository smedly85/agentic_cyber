"""Configured GNU Make link-closure adapter for new v2 specimens.

This does not change the frozen semantic backend or infer vulnerability mappings.
GNU ld maps establish native object inclusion only; SVF supplies every call edge.
"""
from __future__ import annotations
import argparse
import json
import re
import shlex
from pathlib import Path

from security.historical import semantic_validation as v
from security.historical.analysis import verify_source_tree_sha256
from security.historical.v2_study import (ROOT, read, write, fingerprint,
    validate_population, ledger_transaction, function_executables,
    expected_executable_function_pairs)
from security.historical.v2_seed import graph_quality
from security.semantic_callgraph import BuildResult, inventory_toolchain, analyze_build, stable_json


def checked(command, cwd, log):
    result = v._run(command, cwd=cwd)
    content = result.stdout + result.stderr
    if log.exists() and log.read_text() != content:
        old = log.with_name(log.stem + ".attempt-" + v._sha256(log)[:12] + log.suffix)
        if not old.exists():
            old.write_bytes(log.read_bytes())
    log.write_text(content)
    if result.returncode:
        raise RuntimeError(f"configured command failed ({result.returncode}); see {log.relative_to(v.REPO)}")
    return result.stdout


def derive_scope(source: Path, source_hash: str, spec, program: str, output: Path) -> dict:
    build = (v.REPO / spec.build_dir).resolve()
    source = source.resolve()
    verify_source_tree_sha256(source, source_hash)
    recursive = spec.layout == "recursive"
    cwd = build / "src" if recursive else build
    prefix = "" if recursive else "src_"
    names = [prefix + program + suffix for suffix in ("_OBJECTS", "_LDADD", "_DEPENDENCIES")]
    names += ["CC", "LDFLAGS", "LIBS", "PACKAGE_VERSION"]
    variables = {n: list(v._configured_make_variable(cwd, n)) for n in names}
    direct = variables[prefix + program + "_OBJECTS"]
    archives = {x for x in variables[prefix + program + "_LDADD"] if x.endswith(".a")}
    if not direct or not all(x.endswith(".o") for x in direct):
        raise RuntimeError("unrecognized program object closure")
    target = program if recursive else "src/" + program
    map_name = program + "-v2-linker.map"
    make = ["make", "--no-print-directory", "-f", "Makefile", "-o",
            "../config.status" if recursive else "config.status", "-o", "Makefile", "V=1", "MAKEINFO=true",
            *(f"{k}={val}" for k, val in spec.make_variables)]
    preparation = []
    # Realize lazy configured gnulib headers before requesting individual objects.
    for directory in ([build / "lib", cwd] if recursive else [build]):
        targets = list(v._configured_make_variable(directory, "BUILT_SOURCES"))
        if targets:
            for item in targets:
                resolved = (directory / item).resolve()
                if resolved.is_relative_to(source) and not resolved.is_file():
                    raise RuntimeError("BUILT_SOURCES would create a historical release input")
            prep = ["make", "--no-print-directory", "-f", "Makefile", "-o", "Makefile", "-o",
                    "../config.status" if recursive else "config.status", "-j2", *targets,
                    *(f"{k}={val}" for k, val in spec.make_variables)]
            checked(prep, directory, output / ("built-sources-" + directory.name + ".log"))
            preparation.append({"cwd": directory.relative_to(build).as_posix(), "command": prep})
    for archive in sorted(archives):
        if recursive and Path(archive).parent != Path("."):
            archive_cwd = (cwd / archive).resolve().parent
            checked([*make, "-j2", Path(archive).name], archive_cwd, output / (Path(archive).name + ".log"))
    # Build genuinely required objects first; then force only the executable link.
    checked([*make, *direct], cwd, output / "native-objects.log")
    command = [*make, *(x for obj in direct for x in ("-W", obj)),
               "LDFLAGS=" + " ".join([*variables["LDFLAGS"], "-Wl,-Map=" + map_name]), target]
    text = checked(command, cwd, output / "native-link.log")
    lines = [x for x in text.splitlines() if f"-o {target} " in x and " -c " not in x]
    if len(lines) != 1:
        raise RuntimeError("configured native link command is not unique")
    map_path = cwd / map_name
    linkmap = map_path.read_text()
    members = {}
    for archive, member in re.findall(r"(?m)^(\S+\.a)\(([^()]+)\)", linkmap):
        members.setdefault(archive, set()).add(member)
    loads = re.findall(r"(?m)^LOAD (.+)$", linkmap)
    local_loads = {x for x in loads if not Path(x).is_absolute()}
    if local_loads != set(direct) | archives:
        raise RuntimeError(f"configured objects/archives do not account for native LOAD inputs: {local_loads}")
    if {x for x in members if not Path(x).is_absolute()} - archives:
        raise RuntimeError("unaccounted local archive extraction")
    objects = [((cwd / obj).resolve(), None) for obj in direct]
    for archive in sorted(archives):
        for member in sorted(members.get(archive, set())):
            objects.append(((cwd / archive).resolve().parent / member, (cwd / archive).resolve()))
    units = []
    for obj, archive in objects:
        relative = obj.relative_to(build)
        dep = obj.parent / ".deps" / (obj.stem + ".Po")
        rule = dep.read_text().replace("\\\n", " ").splitlines()[0]
        lhs, rhs = rule.split(":", 1)
        compile_cwd = obj.parent if recursive else build
        if (compile_cwd / lhs.strip()).resolve() != obj:
            raise RuntimeError("compiler dependency object disagrees with native closure")
        dependencies = shlex.split(rhs)
        if not dependencies or not dependencies[0].endswith(".c"):
            raise RuntimeError("unsupported non-C primary compilation input")
        actual = (compile_cwd / dependencies[0]).resolve()
        if actual.is_relative_to(source):
            identity = actual.relative_to(source).as_posix()
            kind = "authenticated_historical_tree"
        elif actual.is_relative_to(build):
            identity = "generated-config/" + actual.relative_to(build).as_posix()
            kind = "configured_build_generated"
        else:
            raise RuntimeError("compile input outside authenticated/configured roots")
        unit = {"source_file": identity, "source_provenance_kind": kind, "source_sha256": v._sha256(actual),
                "configured_object_target": relative.as_posix(), "object_name": obj.name,
                "archive": archive.relative_to(build).as_posix() if archive else None,
                "link_role": "static_archive_member" if archive else "direct_program_object",
                "dependency_evidence": dep.relative_to(build).as_posix(), "dependency_rule": rule,
                "dependency_c_inputs": [s for s in dependencies if s.endswith(".c")]}
        if kind == "configured_build_generated":
            generated_target = actual.name if recursive else actual.relative_to(build).as_posix()
            make_text = (compile_cwd / "Makefile").read_text()
            matched = re.search(rf"(?m)^{re.escape(generated_target)}: [^\n]*\n(?:\t[^\n]*\n)+", make_text)
            if not matched:
                raise RuntimeError("generated TU has no established configured generation rule")
            unit["generation_rule"] = matched.group(0)
            unit["generated_contents"] = actual.read_text()
        units.append(unit)
    identities = [u["source_file"] for u in units]
    if len(identities) != len(set(identities)):
        raise RuntimeError("multiple compile instances of one TU require an explicit source-instance adapter")
    excerpt = linkmap.split("Merging ", 1)[0].split("Discarded input sections", 1)[0]
    excerpt += "\n" + "\n".join("LOAD " + x for x in loads) + "\n"
    (output / "linker-evidence.map").write_text(excerpt)
    verify_source_tree_sha256(source, source_hash)
    return {"schema_version": 1, "program": program, "source_scope_kind": "linker_exact",
            "source_tree": source.relative_to(ROOT).as_posix(), "source_tree_sha256": source_hash,
            "configured_build_directory": spec.build_dir, "configure_options": list(spec.configure_options),
            "configured_cc": spec.configured_cc, "make_overrides": dict(spec.make_variables),
            "make_variables": variables, "link_working_directory": cwd.relative_to(build).as_posix(),
            "native_link_command": shlex.split(lines[0]), "native_link_make_command": command,
            "objects_directly_linked": sorted((cwd / x).resolve().relative_to(build).as_posix() for x in direct),
            "archive_members_required": {(cwd / a).resolve().relative_to(build).as_posix(): sorted(members.get(a, set())) for a in sorted(archives)},
            "translation_units": sorted(units, key=lambda x: x["source_file"]),
            "source_files": sorted(identities), "translation_unit_count": len(units), "object_count": len(objects),
            "external_link_inputs": sorted(x for x in loads if Path(x).is_absolute()),
            "external_boundary": "system startup objects/libraries remain external, as in the frozen instrument",
            "scope_derivation_method": "configured native link; actual GNU ld archive extraction; compiler .Po primary-input correspondence",
            "built_sources_preparation": preparation,
            "source_integrity_verified": True}


def compile_scope(scope, spec, output, inventory):
    source = (ROOT / scope["source_tree"]).resolve()
    build = (v.REPO / spec.build_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    commands, modules, bitcodes, failures, units = [], [], [], [], []
    configuration = {"source_scope_kind": scope["source_scope_kind"], "configured_build": spec.build_dir,
                     "configure_options": list(spec.configure_options), "configured_cc": spec.configured_cc,
                     "make_variables": dict(spec.make_variables), "translation_units": units}
    native_macros = v._run([*shlex.split(spec.configured_cc), "-dM", "-E", "-x", "c", "/dev/null"])
    dialect = re.search(r"(?m)^#define __STDC_VERSION__ (\d+)L$", native_macros.stdout)
    implicit_standard = {"202311": "gnu23", "202000": "gnu2x", "201710": "gnu17", "201112": "gnu11", "199901": "gnu99"}.get(dialect.group(1) if dialect else "")
    configuration["native_language_probe"] = {"command": [*shlex.split(spec.configured_cc), "-dM", "-E", "-x", "c", "/dev/null"],
                                              "stdc_version": dialect.group(1) if dialect else None,
                                              "implicit_standard_if_recipe_omits_std": implicit_standard}
    source_rows = tuple({"path": u["source_file"], "sha256": u["source_sha256"]} for u in scope["translation_units"])
    normalize = lambda cmd: v._normalize_command(cmd, source_root=source, build_root=build, output_root=output)
    for index, unit in enumerate(scope["translation_units"]):
        module = output / f"tu-{index:04d}.bc"
        identity = unit["source_file"]
        generated = identity.startswith("generated-config/")
        actual = build / identity.removeprefix("generated-config/") if generated else source / identity
        if v._sha256(actual) != unit["source_sha256"]:
            raise RuntimeError("scope input changed before LLVM compilation")
        if unit.get("compile_driver") == "libtool" or Path(shlex.split(spec.configured_cc)[0]).name not in {"gcc", "cc", "clang"}:
            import os
            obj = Path(unit["configured_object_target"])
            cwd, target = (build / obj.parent, obj.name) if spec.layout == "recursive" else (build, obj.as_posix())
            make_command = ["make", "-f", "Makefile", "-n", "-o", "Makefile", "-o", "config.status", "V=1",
                            "-W", os.path.relpath(actual, cwd), target, *(f"{k}={val}" for k, val in spec.make_variables)]
            if spec.layout == "recursive":
                make_command[make_command.index("config.status")] = "../config.status"
            dry = v._run(make_command, cwd=cwd)
            if dry.returncode:
                raise RuntimeError("configured libtool compile expansion failed: " + dry.stderr)
            logical = dry.stdout.replace("\\\n", " ")
            compiler = shlex.split(spec.configured_cc)[0]
            candidates = []
            for segment in re.split(r"\n|\s*(?:&&|;)\s*", logical):
                if " -c " not in " " + segment + " ":
                    continue
                tokens = shlex.split(segment)
                if compiler in tokens:
                    candidates.append(tokens[tokens.index(compiler):])
            if len(candidates) != 1:
                raise RuntimeError("libtool compiler invocation not unique")
            recipe = candidates[0]
            if recipe[0] != compiler:
                raise RuntimeError("libtool compiler differs from configured compiler")
        else:
            cwd, target, recipe, make_command = v._configured_recipe(
                identity.removeprefix("generated-config/"), source_root=build if generated else source,
                build_root=build, spec=spec, configured_object_target=unit["configured_object_target"])
        command, _ = v._clang_command(recipe, cwd=cwd, output=module, source_root=source, build_root=build,
                                     clang=inventory["tools"]["clang"]["path"], manifest_source=identity,
                                     compile_input_override=actual)
        if implicit_standard and not any(x.startswith("-std=") for x in command):
            # GCC 15 defaults to C23; Clang 21 defaults to C17. Carry the
            # configured native dialect across the compiler boundary explicitly.
            command.insert(1, "-std=" + implicit_standard)
        commands.append(normalize(command))
        units.append({**unit, "compile_recipe_provenance": {"make_command": normalize(make_command),
                     "configured_compiler_recipe": normalize(recipe), "clang_command": commands[-1],
                     "working_directory": cwd.relative_to(build).as_posix()}})
        result = v._run(command, cwd=cwd)
        if result.returncode:
            failures.append({"stage": "clang", "source_file": identity, "returncode": result.returncode,
                             "stdout": result.stdout, "stderr": result.stderr})
            break
        modules.append(module)
        bitcodes.append({"path": module.name, "sha256": v._sha256(module), "manifest_source": identity})
    linked = output / "linked.bc"
    if not failures:
        command = [inventory["tools"]["llvm-link"]["path"], *map(str, modules), "-o", str(linked)]
        commands.append(normalize(command))
        result = v._run(command)
        if result.returncode:
            failures.append({"stage": "llvm-link", "returncode": result.returncode, "stderr": result.stderr})
        else:
            bitcodes.append({"path": linked.name, "sha256": v._sha256(linked)})
    verify_source_tree_sha256(source, scope["source_tree_sha256"])
    return BuildResult("build_or_ir_unavailable" if failures else "success", None if failures else linked,
                       source_rows, tuple(commands), tuple(bitcodes), tuple(failures),
                       v._run([inventory["tools"]["clang"]["path"], "-dumpmachine"]).stdout.strip(), configuration)


def run(program, release=None, configured_build=None):
    population = read("v2_population.json")
    validate_population(population)
    mappings = read("v2_vulnerable_function_mappings.json")
    if release is None:
        cve = {"uniq": "CVE-2013-0222", "join": "CVE-2013-0223"}[program]
        selected = [m for m in mappings["members"] if m["cve_id"] == cve]
        spec = v.BUILD_SPECS[("gnu-coreutils", "8.17-7.fc18", "sort")]
        slug = "fedora-8.17-" + program
        specimen_id = "gnu-coreutils/8.17-7.fc18/" + program
    else:
        selected = [m for m in mappings["members"]
                    if (m.get("affected_version") == release
                        or m.get("source_tree", "").rstrip("/").endswith("/" + release))
                    and program in m.get("programs", [])]
        native = v.REPO / (configured_build or ("build/historical-v2/native/" + release))
        allowed_roots = ((v.REPO / "build/historical-v2/native").resolve(),
                         (v.REPO / "build").resolve())
        if not any(native.resolve().is_relative_to(root) for root in allowed_roots):
            raise RuntimeError("configured build directory outside build roots")
        if release in ("coreutils-5.2.1", "5.2.1"):
            # Reuse the already authenticated/configured v1 historical build;
            # no v1 ledger or result is modified.  The new executables get
            # independent linker maps, LLVM modules, graphs and v2 specimens.
            configured = {"returncode": 0, "configure_options": ["--disable-nls"],
                          "configured_cc": "gcc -std=gnu89 -fcommon",
                          "source_tree": "sources/coreutils-5.2.1",
                          "source_tree_sha256": selected[0]["source_tree_sha256"]}
            spec = v.HistoricalBuildSpec(native.relative_to(v.REPO).as_posix(), "recursive",
                                         ("--disable-nls",), "gcc -std=gnu89 -fcommon")
        else:
            configured = json.loads((native / "v2-configure-status.json").read_text())
            if configured["returncode"]:
                raise RuntimeError("release configure unsuccessful; preserve diagnostics for review")
            spec = v.HistoricalBuildSpec(native.relative_to(v.REPO).as_posix(),
                                         "recursive" if (native / "src/Makefile").exists() else "nonrecursive",
                                         tuple(configured["configure_options"]), configured["configured_cc"],
                                         ((("CPPFLAGS", "-D_IO_ftrylockfile=1 -D_IO_IN_BACKUP=0x100"),) if release in ("coreutils-8.22", "coreutils-8.25", "coreutils-8.29") else ())
                                         + ((("CFLAGS", "-g -O2 -Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types -Wno-error=int-conversion"),) if release == "coreutils-8.25" else ()))
        release_slug = "coreutils-5.2.1" if release == "5.2.1" else release
        slug = release_slug + "-" + program
        specimen_id = release_slug + "/" + program
    if not selected:
        raise RuntimeError("no independently frozen mapping for this executable")
    for mapping in selected:
        if (not mapping["completed"] or mapping["mapping_status"] != "verified" or
            mapping["mapping_fingerprint"] != fingerprint({k: val for k, val in mapping.items() if k != "mapping_fingerprint"})):
            raise RuntimeError("independent verified mapping must be frozen before semantic measurement")
    mapping = selected[0]
    if release is not None and (configured["source_tree"] != mapping["source_tree"] or configured["source_tree_sha256"] != mapping["source_tree_sha256"]):
        raise RuntimeError("configured source revision disagrees with frozen mapping")
    source = ROOT / mapping["source_tree"]
    out = v.REPO / "build/historical-v2" / slug
    out.mkdir(parents=True, exist_ok=True)
    evidence_dir = ROOT / "evidence/v2" / slug
    evidence_dir.mkdir(parents=True, exist_ok=True)
    scope = derive_scope(source, mapping["source_tree_sha256"], spec, program, out)
    (evidence_dir / "linker-evidence.map").write_text((out / "linker-evidence.map").read_text())
    scope["evidence"] = (evidence_dir / "linker-evidence.map").relative_to(v.REPO).as_posix()
    (evidence_dir / "scope.json").write_text(stable_json(scope))
    print(program, "native linker-exact TUs:", scope["translation_unit_count"], flush=True)
    inventory = inventory_toolchain(helper=v.REPO / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf")
    built = compile_scope(scope, spec, out / "semantic", inventory)
    graph = analyze_build(built, entry_point="main", inventory=inventory, svf_options=v.PRIMARY_OPTIONS)
    graph_path = out / "graph.json"
    if graph_path.exists():
        previous = graph_path.with_name("graph.attempt-" + v._sha256(graph_path) + ".json")
        if not previous.exists():
            previous.write_bytes(graph_path.read_bytes())
    graph_path.write_text(stable_json(graph))
    specimen = {"specimen_id": specimen_id, "source_tree": mapping["source_tree"],
                "source_revision": mapping["affected_revision"], "source_tree_sha256": mapping["source_tree_sha256"],
                "source_scope_kind": "linker_exact", "source_count": scope["translation_unit_count"],
                "source_scope_evidence": (evidence_dir / "scope.json").relative_to(v.REPO).as_posix(),
                "mapping_fingerprint_before_measurement": mapping["mapping_fingerprint"],
                "analysis_status": graph["analysis_status"], "graph_quality": graph_quality(graph),
                "analysis_provenance": graph["provenance"], "failures": graph["failures"],
                "retained_graph_path": graph_path.relative_to(v.REPO).as_posix(), "retained_graph_sha256": v._sha256(graph_path)}
    persist(specimen, selected, graph)


@ledger_transaction
def persist(specimen, selected, graph):
    specimen_id = specimen["specimen_id"]
    manifest = read("v2_source_manifest.json")
    old = next((s for s in manifest["specimens"] if s["specimen_id"] == specimen_id), None)
    if old and old["retained_graph_sha256"] != specimen["retained_graph_sha256"]:
        preserved = {k: val for k, val in old.items() if k != "previous_attempts"}
        old_path = Path(old["retained_graph_path"])
        preserved["retained_graph_path"] = old_path.with_name("graph.attempt-" + old["retained_graph_sha256"] + ".json").as_posix()
        specimen["previous_attempts"] = old.get("previous_attempts", []) + [preserved]
    manifest["specimens"] = sorted([s for s in manifest["specimens"] if s["specimen_id"] != specimen_id] + [specimen], key=lambda s: s["specimen_id"])
    write("v2_source_manifest.json", manifest)
    results = read("v2_semantic_results.json")
    for mapping in selected:
        row = next(r for r in results["members"] if r["cve_id"] == mapping["cve_id"])
        observations = [o for o in row["observations"] if o["specimen_id"] != specimen_id]
        if graph["analysis_status"] == "success":
            program = specimen_id.rsplit("/", 1)[1]
            for query in mapping["functions"]:
                if program not in function_executables(mapping, query):
                    continue
                matched = v.map_source_identity(graph, query["source_file"], query["function"])
                candidate = matched["candidates"][0] if matched["candidate_count"] == 1 else None
                observations.append({"source_identity": query["source_identity"], "specimen_id": specimen_id,
                                     "analysis_backend": "clang_llvm_svf", "source_scope_kind": "linker_exact", "mapping": matched,
                                     "raw_call_depth": candidate["raw_call_depth"] if candidate else None,
                                     "shortest_semantic_path": candidate["shortest_call_path"] if candidate else None})
        observations.sort(key=lambda o: (o["specimen_id"], o["source_identity"]))
        row.update(observations=observations, analysis_status=graph["analysis_status"])
        observed_pairs = {(o["specimen_id"].rsplit("/", 1)[1], o["source_identity"])
                          for o in observations}
        if (observed_pairs == expected_executable_function_pairs(mapping)
            and all(o["raw_call_depth"] is not None for o in observations)):
            row.update(completed=True, disposition="depth_applicable", reason="Independently frozen vulnerable functions measured using configured linker-exact LLVM/SVF scope.")
        else:
            row.update(completed=False, disposition="pending", reason="Other executable builds or retained graph/mapping diagnostics require review before final disposition.")
        print(mapping["cve_id"], graph["analysis_status"], [(o["source_identity"], o["raw_call_depth"]) for o in observations], flush=True)
    write("v2_semantic_results.json", results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program")
    parser.add_argument("--release")
    parser.add_argument("--configured-build")
    args = parser.parse_args()
    run(args.program, args.release, args.configured_build)
