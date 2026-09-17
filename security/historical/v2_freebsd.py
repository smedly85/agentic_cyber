"""Acquire the actual FreeBSD 4.1.1 sort sources and audit build prerequisites."""
import hashlib
import json
from pathlib import Path
import shutil
from security.historical.v2_acquire import fetch, CACHE
from security.historical.v2_review import evidence, install
from security.historical.v2_study import ROOT, write
from security.historical.analysis import source_tree_sha256
from security.historical.semantic_validation import _run, _sha256


def main():
    tag = json.loads((CACHE / "freebsd-release-tag").read_text())
    revision = tag["object"]["sha"]
    if revision != "2641b0c407077fa8c3032d87d15ac6a103b0ed1b" or tag["object"]["type"] != "commit":
        raise RuntimeError("unexpected FreeBSD release-tag resolution")
    directory = json.loads((CACHE / "freebsd-sort-directory").read_text())
    tree = ROOT / "sources/v2/freebsd-4.1.1-sort"
    rows = []
    for item in directory:
        if item["type"] != "file" or Path(item["path"]).parent.as_posix() != "gnu/usr.bin/sort":
            raise RuntimeError("unexpected source-directory entry")
        url = "https://raw.githubusercontent.com/freebsd/freebsd-src/" + revision + "/" + item["path"]
        acquired = fetch(("freebsd-4.1.1-" + item["name"], url))
        if acquired["status"] != "downloaded":
            raise RuntimeError("FreeBSD source retrieval failed; retain acquisition diagnostics")
        data = (ROOT.parents[1] / acquired["cache_path"]).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != item["sha"]:
            raise RuntimeError("download disagrees with pinned source-tree Git blob")
        target = tree / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError("refusing to overwrite changed historical source")
        if not target.exists():
            target.write_bytes(data)
        rows.append({"path": item["path"], "git_blob": blob, **acquired})
    source = tree / "gnu/usr.bin/sort/sort.c"
    source_text = source.read_text()
    if "tempname (void)" not in source_text or '"%s%ssort%5.5d%5.5d"' not in source_text:
        raise RuntimeError("selected source does not contain the disclosed vulnerable tempname implementation")
    decision = {"cve_id": "CVE-2001-0310", "completed": True, "mapping_status": "verified",
        "depth_applicability": "applicable", "mapping_confidence": "verified_vendor_advisory_patch_and_release_source",
        "mapping_frozen_before_new_measurement": True, "freeze_stage": "before_specimen_semantic_measurement",
        "project": "FreeBSD base-system sort", "affected_version": "FreeBSD 4.1.1-RELEASE",
        "affected_revision": revision, "fix_revision": "FreeBSD CVS gnu/usr.bin/sort/sort.c 1.15.2.2 (2000-11-11)",
        "source_tree": tree.relative_to(ROOT).as_posix(), "source_tree_sha256": source_tree_sha256(tree),
        "programs": ["sort"], "entry_point": "main",
        "functions": [{"source_file": "gnu/usr.bin/sort/sort.c", "function": "tempname",
                       "source_identity": "gnu/usr.bin/sort/sort.c::tempname", "source_sha256": _sha256(source)}],
        "vulnerability_evidence": [evidence(n) for n in ("freebsd-sort-advisory", "freebsd-sort-fix", "freebsd-release-tag")],
        "mapping_reason": "Vendor patch replaces predictable PID/sequence filename construction in tempname with mkstemp. xtmpfopen's changed open flags accommodate prior secure creation and are not a separate vulnerable function. The advisory identifies denial of service, not arbitrary overwrite: the old O_EXCL already prevented clobbering.",
        "specimen_selection_reason": "The vendor distributes a patch explicitly for the affected 4.1.1 release; use that pinned release rather than fixed 4.2 or GNU sort."}
    install([decision])
    diagnostics = []
    for command in (["uname", "-srm"], ["make", "--version"]):
        result = _run(command)
        diagnostics.append({"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    makefile = tree / "gnu/usr.bin/sort/Makefile"
    output = {"schema_version": 1, "source_revision": revision, "source_tree": tree.relative_to(ROOT).as_posix(),
              "source_tree_sha256": decision["source_tree_sha256"], "source_files": rows,
              "historical_makefile": makefile.read_text(), "historical_makefile_sha256": _sha256(makefile),
              "build_tools": {tool: shutil.which(tool) for tool in ("bmake", "freebsd-make", "clang-21")},
              "diagnostics": diagnostics, "status": "historical_build_prerequisites_under_review",
              "qualification": "Release Makefile includes FreeBSD bsd.prog.mk and depends on the historical target headers/libraries. No Linux generic compile is substituted, and a source list alone is not called linker-exact."}
    write("v2_freebsd_source_build_audit.json", output)
    print("FreeBSD 4.1.1 pinned sources and tempname mapping preserved; native build prerequisites require review.")


if __name__ == "__main__":
    main()
