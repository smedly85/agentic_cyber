"""Reconstruct and measure the affected FreeBSD 5.0 cp for CVE-2007-4998.

Stages are deliberately separate: acquire authentic source/sysroot material,
freeze the independently reasoned mapping, establish a BSD-Make linker-exact
scope, then run the unchanged LLVM/SVF semantic backend.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import tarfile
import tempfile

from security.historical import semantic_validation as v
from security.historical.analysis import source_tree_sha256, verify_source_tree_sha256
from security.historical.v2_acquire import CACHE, fetch
from security.historical.v2_build import persist
from security.historical.v2_seed import graph_quality
from security.historical.v2_study import ROOT, fingerprint, read, write
from security.semantic_callgraph import BuildResult, analyze_build, inventory_toolchain, stable_json

TAG_OBJECT = "3aa7e13ebf50bbd7087bc2a03f5e05bd2a13bd75"
REVISION = "47227ef0ef663b7abb81ab5a60a450da9a93d24b"
BASE = "https://archive.freebsd.org/old-releases/i386/5.0-RELEASE/base/"


def acquire():
    repo = ROOT.parents[1]
    ref = fetch(("freebsd-5.0-release-ref",
                 "https://api.github.com/repos/freebsd/freebsd-src/git/ref/tags/release%2F5.0.0"))
    tag = fetch(("freebsd-5.0-release-tag",
                 "https://api.github.com/repos/freebsd/freebsd-src/git/tags/" + TAG_OBJECT))
    ref_data = json.loads((repo / ref["cache_path"]).read_text())
    tag_data = json.loads((repo / tag["cache_path"]).read_text())
    if ref_data["object"] != {"sha": TAG_OBJECT, "type": "tag",
                              "url": "https://api.github.com/repos/freebsd/freebsd-src/git/tags/" + TAG_OBJECT}:
        raise RuntimeError("FreeBSD 5.0 tag ref changed")
    if tag_data["object"]["sha"] != REVISION or tag_data["object"]["type"] != "commit":
        raise RuntimeError("FreeBSD 5.0 annotated tag does not peel to pinned release commit")
    directory = fetch(("freebsd-5.0-cp-directory",
                       "https://api.github.com/repos/freebsd/freebsd-src/contents/bin/cp?ref=" + REVISION))
    entries = json.loads((repo / directory["cache_path"]).read_text())
    tree = ROOT / "sources/v2/freebsd-5.0-cp"
    source_rows = []
    for entry in entries:
        if entry["type"] != "file" or Path(entry["path"]).parent.as_posix() != "bin/cp":
            raise RuntimeError("unexpected FreeBSD cp directory entry")
        row = fetch(("freebsd-5.0-cp-" + entry["name"],
                     "https://raw.githubusercontent.com/freebsd/freebsd-src/" + REVISION + "/" + entry["path"]))
        if row["status"] != "downloaded":
            raise RuntimeError("FreeBSD 5.0 cp source retrieval failed")
        data = (repo / row["cache_path"]).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != entry["sha"]:
            raise RuntimeError("raw cp source disagrees with pinned Git blob")
        target = tree / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError("refusing to overwrite changed historical source")
        if not target.exists():
            target.write_bytes(data)
        source_rows.append({"path": entry["path"], "git_blob": blob, **row})
    cp_text = (tree / "bin/cp/cp.c").read_text()
    utils_text = (tree / "bin/cp/utils.c").read_text()
    required = ("if (stat(to.p_path, &to_stat) == -1)", "if (copy_link(curr, !dne))")
    if not all(text in cp_text for text in required) or "O_WRONLY | O_TRUNC" not in utils_text:
        raise RuntimeError("pinned source lacks the independently identified exploit path")

    index = fetch(("freebsd-5.0-binary-archive-index", BASE))
    listing = (repo / index["cache_path"]).read_text()
    parts = sorted(set(re.findall(r'href="(base\.[a-z]{2})"', listing)))
    sums = fetch(("freebsd-5.0-CHECKSUM.MD5", BASE + "CHECKSUM.MD5"))
    expected = dict(re.findall(r"MD5 \((base\.[a-z]{2})\) = ([0-9a-f]{32})",
                               (repo / sums["cache_path"]).read_text()))
    if not parts or set(parts) != set(expected):
        raise RuntimeError("official FreeBSD 5.0 split archive/checksum inventory unavailable")
    with ThreadPoolExecutor(max_workers=4) as pool:
        archive_rows = list(pool.map(fetch, (("freebsd-5.0-" + p, BASE + p) for p in parts)))
    dependency = repo / "build/historical-v2/dependencies/freebsd-5.0"
    dependency.mkdir(parents=True, exist_ok=True)
    archive = dependency / "base.tgz"
    with archive.open("wb") as handle:
        for part, row in zip(parts, archive_rows):
            data = (repo / row["cache_path"]).read_bytes()
            if row["status"] != "downloaded" or hashlib.md5(data).hexdigest() != expected[part]:
                raise RuntimeError("FreeBSD 5.0 vendor archive checksum failure")
            handle.write(data)
    sysroot = dependency / "sysroot"
    sysroot.mkdir(exist_ok=True)
    retained, links = [], []
    with tarfile.open(archive, ignore_zeros=True) as tar:
        for member in tar:
            normalized = Path(member.name.removeprefix("./"))
            if normalized.is_absolute() or ".." in normalized.parts:
                raise RuntimeError("unsafe archive member")
            path = normalized.as_posix()
            if not path.startswith(("usr/include/", "usr/lib/", "usr/share/mk/")):
                continue
            if member.issym() or member.islnk():
                links.append({"path": path, "target": member.linkname})
                continue
            if not member.isfile():
                continue
            data = tar.extractfile(member).read()
            target = sysroot / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != data:
                raise RuntimeError("existing FreeBSD 5.0 sysroot file differs")
            if not target.exists():
                target.write_bytes(data)
            retained.append({"path": path, "sha256": hashlib.sha256(data).hexdigest()})
    write("v2_freebsd_cp_acquisition.json", {
        "schema_version": 1, "release": "FreeBSD 5.0-RELEASE/i386",
        "release_ref": ref, "release_tag": tag, "release_revision": REVISION,
        "source_tree": tree.relative_to(ROOT).as_posix(),
        "source_tree_sha256": source_tree_sha256(tree), "source_files": source_rows,
        "official_archive_url": BASE, "archive_index": index, "archive_parts": archive_rows,
        "vendor_checksums": sums, "combined_archive_sha256": v._sha256(archive),
        "sysroot": sysroot.relative_to(repo).as_posix(), "development_files": retained,
        "omitted_links": links, "status": "authenticated_source_and_cross_build_inputs_acquired"})
    print("FreeBSD 5.0 cp source files:", len(source_rows), "sysroot files:", len(retained))


def _restore_links(sysroot: Path, links):
    restored = []
    for item in links:
        link = sysroot / item["path"]
        target = (link.parent / item["target"]).resolve()
        if not target.is_relative_to(sysroot.resolve()) or not target.is_file():
            continue
        if not link.is_symlink():
            if link.exists():
                raise RuntimeError("refusing to replace a sysroot file")
            link.symlink_to(item["target"])
        restored.append(item)
    return restored


def build():
    mapping = next(m for m in read("v2_vulnerable_function_mappings.json")["members"]
                   if m["cve_id"] == "CVE-2007-4998")
    if mapping["mapping_status"] != "verified" or mapping["project"] != "FreeBSD base-system cp":
        raise RuntimeError("affected mapping must be frozen before build")
    acquisition = read("v2_freebsd_cp_acquisition.json")
    repo = ROOT.parents[1]
    original = ROOT / mapping["source_tree"]
    verify_source_tree_sha256(original, mapping["source_tree_sha256"])
    sysroot = repo / acquisition["sysroot"]
    restored = _restore_links(sysroot, acquisition["omitted_links"])
    stage = Path(tempfile.mkdtemp(prefix="agentic-v2-freebsd5-cp-"))
    source = stage / "source"
    shutil.copytree(original, source)
    (stage / "sysroot").symlink_to(sysroot, target_is_directory=True)
    objects = stage / "objects"
    objects.mkdir()
    audit = repo / "build/historical-v2/freebsd-5.0-cp"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "staging.json").write_text(json.dumps({"stage": str(stage), "source": str(source), "objects": str(objects)}))
    bmake = repo / "build/historical-v2/dependencies/freebsd-4.1.1/native-bmake/root/usr/bin/bmake"
    linker = repo / read("v2_lld_dependency.json")["linker"]
    (stage / "linker").mkdir()
    (stage / "linker/ld.lld").symlink_to(linker)
    attributes = ["-D__dead2=__attribute__((__noreturn__))",
                  "-D__pure2=__attribute__((__const__))",
                  "-D__unused=__attribute__((__unused__))",
                  "-D__packed=__attribute__((__packed__))",
                  "-D__aligned(x)=__attribute__((__aligned__(x)))",
                  "-D__section(x)=__attribute__((__section__(x)))"]
    compiler = (f"clang-21 -std=gnu89 -fcommon --target=i386-unknown-freebsd5.0 "
                f"--sysroot={stage / 'sysroot'} -B{stage / 'sysroot/usr/lib'} "
                f"-fuse-ld={stage / 'linker/ld.lld'} " + shlex.join(attributes))
    command = [str(bmake), "-m", str(stage / "sysroot/usr/share/mk"),
               "-C", str(source / "bin/cp"), "MACHINE=i386", "MACHINE_ARCH=i386",
               "OBJFORMAT=elf", "CPUTYPE=", "NOMAN=yes", "CC=" + compiler,
               "CFLAGS=-O -pipe -DVM_AND_BUFFER_CACHE_SYNCHRONIZED",
               "LDFLAGS=-nodefaultlibs -Wl,--dynamic-linker=/usr/libexec/ld-elf.so.1 -Wl,-Map=cp-v2.map -Wl,-t",
               "LDADD=-lgcc -lc -lgcc"]
    env = dict(os.environ, MAKEOBJDIR=str(objects))
    import subprocess
    invoke = lambda extra: subprocess.run(command + extra, env=env, text=True, capture_output=True)
    variables = {}
    for name in (".CURDIR", ".OBJDIR", "PROG", "SRCS", "OBJS", "LDADD", "DPADD", "CFLAGS", "LDFLAGS", "CC"):
        result = invoke(["-V", "${" + name + "}"])
        if result.returncode:
            raise RuntimeError("FreeBSD 5.0 BSD Make configuration failed: " + result.stderr)
        variables[name] = result.stdout.strip()
    result = invoke(["cp"])
    (audit / "native-cross-link.log").write_text(result.stdout + result.stderr)
    normalize = lambda text: text.replace(str(stage), "$STAGING").replace(str(repo), "$REPO")
    receipt = {"schema_version": 1, "status": "native_cross_link_succeeded" if not result.returncode else "historical_cross_build_failed",
               "returncode": result.returncode, "source_tree": mapping["source_tree"],
               "source_tree_sha256": mapping["source_tree_sha256"], "source_revision": REVISION,
               "configured_make_variables": {key: normalize(value) for key, value in variables.items()},
               "command": [normalize(item) for item in command + ["cp"]],
               "environment": {"MAKEOBJDIR": "$STAGING/objects"}, "restored_distribution_symlinks": restored,
               "target_triple": "i386-unknown-freebsd5.0", "source_integrity_verified": True,
               "compiler_diagnostics": normalize(result.stderr), "link_build_output": normalize(result.stdout),
               "historical_binaries_executed": False, "sysroot_reference": "security/historical/v2_freebsd_cp_acquisition.json",
               "compiler_header_compatibility": {"flags": attributes, "header": "usr/include/sys/cdefs.h",
                    "header_sha256": v._sha256(sysroot / "usr/include/sys/cdefs.h"),
                    "rationale": "The release sys/cdefs.h defines these exact attributes for GCC 2.7 through 3 but not Clang's GCC-4 compatibility version. Carry the historical expansions across that compiler-version boundary without changing source or headers."},
               "compiler_runtime_linkage": {"rationale": "Use the historical FreeBSD GCC driver sequence -lgcc -lc -lgcc and release sysroot startup objects instead of modern host defaults."}}
    receipt["compiler_cpu_flag_compatibility"] = {
        "make_override": "CPUTYPE=; CFLAGS=-O -pipe -DVM_AND_BUFFER_CACHE_SYNCHRONIZED", "rationale": (
            "The release sys.mk otherwise emits GCC's historical -mcpu=pentiumpro spelling, which Clang 21 rejects for this target. The official i386 release supports the baseline architecture; leaving CPUTYPE unset removes tuning only and does not alter source, ABI, linkage, or semantic flags.")}
    receipt_path = ROOT / "v2_freebsd_cp_cross_build.json"
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text())
        attempts = list(previous.get("previous_attempts", []))
        if not attempts:
            attempts.append({
                "status": "historical_cross_build_failed",
                "failure": "Clang 21 rejected release sys.mk's GCC-only -mcpu=pentiumpro spelling for the i386 FreeBSD target",
                "remedy": "Use the release-supported baseline i386 target by clearing CPUTYPE; preserve the original optimization and required VM_AND_BUFFER_CACHE_SYNCHRONIZED define",
            })
        attempts.append({
            "status": previous["status"],
            "returncode": previous["returncode"],
            "command": previous["command"],
            "compiler_diagnostics": previous["compiler_diagnostics"],
        })
        receipt["previous_attempts"] = attempts
    write("v2_freebsd_cp_cross_build.json", receipt)
    verify_source_tree_sha256(original, mapping["source_tree_sha256"])
    if result.returncode:
        raise RuntimeError("FreeBSD 5.0 cp cross-link failed; diagnostics retained")
    print("FreeBSD 5.0 cp BSD-Make cross-link succeeded")


def measure():
    mapping = next(m for m in read("v2_vulnerable_function_mappings.json")["members"]
                   if m["cve_id"] == "CVE-2007-4998")
    if mapping["mapping_fingerprint"] != fingerprint({k: value for k, value in mapping.items() if k != "mapping_fingerprint"}):
        raise RuntimeError("mapping changed after freeze")
    build_receipt = read("v2_freebsd_cp_cross_build.json")
    if build_receipt["returncode"]:
        raise RuntimeError("linker-exact historical cross-build unavailable")
    repo = ROOT.parents[1]
    audit = repo / "build/historical-v2/freebsd-5.0-cp"
    staging = json.loads((audit / "staging.json").read_text())
    stage, source, objects = (Path(staging[key]) for key in ("stage", "source", "objects"))
    verify_source_tree_sha256(source, mapping["source_tree_sha256"])
    variables = build_receipt["configured_make_variables"]
    expected_objects, expected_sources = shlex.split(variables["OBJS"]), shlex.split(variables["SRCS"])
    raw = (audit / "native-cross-link.log").read_text()
    trace = [line.strip() for line in raw.splitlines() if line.strip() in expected_objects]
    if sorted(trace) != sorted(expected_objects) or len(trace) != len(set(trace)):
        raise RuntimeError("actual linker inputs differ from BSD Make OBJS")
    recipes = [shlex.split(line) for line in raw.splitlines() if line.startswith("clang-21 ") and " -c " in line]
    by_source = {Path(row[row.index("-c") + 1]).name: row for row in recipes}
    if set(by_source) != set(expected_sources):
        raise RuntimeError("compile recipes do not uniquely cover BSD Make SRCS")
    normalize = lambda text: text.replace(str(stage), "$STAGING").replace(str(repo), "$REPO")
    evidence = ROOT / "evidence/v2/freebsd-5.0-cp"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "linker-evidence.map").write_text(normalize((objects / "cp-v2.map").read_text()))
    output = audit / "semantic"
    output.mkdir(exist_ok=True)
    inventory = inventory_toolchain(helper=repo / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf")
    units, commands, bitcodes, modules = [], [], [], []
    for index, name in enumerate(sorted(expected_sources)):
        identity = "bin/cp/" + name
        actual, recipe = source / identity, by_source[name]
        module = output / f"tu-{index:04d}.bc"
        command, _ = v._clang_command(recipe, cwd=objects, output=module, source_root=source,
                                      build_root=objects, clang=inventory["tools"]["clang"]["path"],
                                      manifest_source=identity)
        command.insert(1, f"-fdebug-prefix-map={stage / 'sysroot'}=external-sysroot")
        result = v._run(command, cwd=objects)
        (output / (name + ".log")).write_text(normalize(result.stdout + result.stderr))
        if result.returncode:
            raise RuntimeError("LLVM build failed for " + identity)
        normalized = [normalize(item) for item in command]
        commands.append(normalized)
        units.append({"source_file": identity, "source_provenance_kind": "authenticated_release_translation_unit",
                      "source_sha256": v._sha256(actual), "object": Path(name).with_suffix(".o").name,
                      "archive": None, "compile_recipe_provenance": {
                          "configured_compiler_recipe": [normalize(item) for item in recipe], "clang_command": normalized}})
        modules.append(module)
        bitcodes.append({"path": module.name, "sha256": v._sha256(module), "manifest_source": identity})
    linked = output / "linked.bc"
    link_command = [inventory["tools"]["llvm-link"]["path"], *map(str, modules), "-o", str(linked)]
    linked_result = v._run(link_command)
    if linked_result.returncode:
        raise RuntimeError("llvm-link failed: " + linked_result.stderr)
    commands.append([normalize(item) for item in link_command])
    bitcodes.append({"path": linked.name, "sha256": v._sha256(linked)})
    scope = {"schema_version": 1, "program": "cp", "source_scope_kind": "linker_exact",
             "source_tree": mapping["source_tree"], "source_tree_sha256": mapping["source_tree_sha256"],
             "source_revision": REVISION, "configured_make_variables": variables,
             "objects_directly_linked": sorted(trace), "archive_members_required": {},
             "translation_units": units, "source_files": sorted(unit["source_file"] for unit in units),
             "translation_unit_count": len(units), "object_count": len(trace), "generated_build_modules": [],
             "external_link_inputs": sorted(normalize(line.strip()) for line in raw.splitlines() if line.startswith(str(stage / "sysroot"))),
             "scope_derivation_method": "Pinned release BSD Make SRCS/OBJS plus successful lld -t input trace and link map; two direct release objects, no program archive",
             "build_evidence": "security/historical/v2_freebsd_cp_cross_build.json",
             "evidence": (evidence / "linker-evidence.map").relative_to(repo).as_posix(),
             "external_boundary": "Historical sysroot startup objects and system libraries excluded as in the frozen instrument",
             "source_integrity_verified": True}
    (evidence / "scope.json").write_text(stable_json(scope))
    built = BuildResult("success", linked, tuple({"path": unit["source_file"], "sha256": unit["source_sha256"]} for unit in units),
                        tuple(commands), tuple(bitcodes), (), "i386-unknown-freebsd5.0",
                        {"source_scope_kind": "linker_exact", "original_bsd_make": build_receipt,
                         "translation_units": units})
    graph = analyze_build(built, entry_point="main", inventory=inventory, svf_options=v.PRIMARY_OPTIONS)
    graph_path = audit / "graph.json"
    graph_path.write_text(stable_json(graph))
    specimen = {"specimen_id": "freebsd/5.0/cp", "source_tree": mapping["source_tree"],
                "source_revision": REVISION, "source_tree_sha256": mapping["source_tree_sha256"],
                "source_scope_kind": "linker_exact", "source_count": len(units),
                "source_scope_evidence": (evidence / "scope.json").relative_to(repo).as_posix(),
                "mapping_fingerprint_before_measurement": mapping["mapping_fingerprint"],
                "analysis_status": graph["analysis_status"], "graph_quality": graph_quality(graph),
                "analysis_provenance": graph["provenance"], "failures": graph["failures"],
                "retained_graph_path": graph_path.relative_to(repo).as_posix(),
                "retained_graph_sha256": v._sha256(graph_path)}
    persist(specimen, [mapping], graph)
    verify_source_tree_sha256(ROOT / mapping["source_tree"], mapping["source_tree_sha256"])


def reconstruct():
    """Keep the WSL /tmp staging tree alive across native link and measurement."""
    build()
    measure()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("acquire", "build", "measure", "reconstruct"))
    args = parser.parse_args()
    globals()[args.stage]()
