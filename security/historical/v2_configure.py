"""Prepare isolated configured release builds; never modify release sources."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
from security.historical.v2_study import ROOT, read, write
from security.historical.analysis import verify_source_tree_sha256

REPO = ROOT.parents[1]
CONFIGURATIONS = {
    "coreutils-8.25": ("gcc -std=gnu17", ["--disable-nls", "--without-selinux", "--without-gmp"]),
    "coreutils-8.29": ("gcc -std=gnu17", ["--disable-nls", "--without-selinux", "--without-gmp"]),
    "fileutils-4.1": ("gcc -std=gnu89 -fcommon", ["--disable-nls"]),
    "coreutils-9.11": ("gcc", ["--disable-nls", "--without-selinux"]),
    "coreutils-9.4": ("gcc -std=gnu17", ["--disable-nls", "--without-selinux"]),
    "coreutils-8.22": ("gcc -std=gnu17", ["--disable-nls", "--without-selinux", "--without-gmp"]),
    "coreutils-8.4": ("gcc -std=gnu17", ["--disable-nls", "--without-selinux", "--without-gmp"]),
    "coreutils-5.0": ("gcc -std=gnu89 -fcommon", ["--disable-nls"]),
    "util-linux-2.29.1": ("gcc -std=gnu17", ["--disable-nls", "--disable-all-programs", "--enable-su", "--without-python"]),
}


def configure(release, *, directory_name=None, compiler=None, extra_options=()):
    candidate = next(s for s in read("v2_candidate_sources.json")["sources"] if s["source_tree"] == "sources/v2/" + release)
    source = ROOT / candidate["source_tree"]
    verify_source_tree_sha256(source, candidate["source_tree_sha256"])
    build = REPO / "build/historical-v2/native" / (directory_name or release)
    build.mkdir(parents=True, exist_ok=True)
    cc, options = CONFIGURATIONS[release]
    cc = compiler or cc
    options = [*options, *extra_options]
    command = ["bash", os.path.relpath(source / "configure", build), *options, "CC=" + cc]
    log = build / "v2-configure.log"
    # Preserve failed diagnostics and do not accidentally reconfigure a completed build.
    marker = build / "v2-configure-status.json"
    if marker.exists():
        import json
        prior = json.loads(marker.read_text())
        if prior["command"] != command:
            raise RuntimeError("configured build exists with different provenance")
        print(release, "retained", prior["returncode"], flush=True)
        return prior
    env = dict(os.environ, FORCE_UNSAFE_CONFIGURE="1")
    with log.open("w") as handle:
        result = subprocess.run(command, cwd=build, env=env, stdout=handle, stderr=subprocess.STDOUT)
    verify_source_tree_sha256(source, candidate["source_tree_sha256"])
    row = {"release": release, "source_tree": candidate["source_tree"], "source_tree_sha256": candidate["source_tree_sha256"],
           "configured_build_directory": build.relative_to(REPO).as_posix(), "configured_cc": cc,
           "configure_options": options, "command": command, "environment": {"FORCE_UNSAFE_CONFIGURE": "1"},
           "returncode": result.returncode, "status": "configured" if result.returncode == 0 else "configure_failed_pending_review",
           "log": log.relative_to(REPO).as_posix(), "source_integrity_verified": True,
           "configuration_rationale": "Release-provided configure/Makefile machinery, native Linux feature checks, NLS disabled consistently with pilot. Language dialect preserves pre-C23 historical C semantics where needed. No source edits or outcome-dependent pointer-analysis changes."}
    from security.semantic_callgraph import stable_json
    marker.write_text(stable_json(row))
    print(release, row["status"], flush=True)
    return row


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("releases", nargs="*", choices=list(CONFIGURATIONS))
    args = parser.parse_args()
    selected = args.releases or list(CONFIGURATIONS)
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(configure, selected))
    # Reconstruct the index from all per-build receipts, so separate preparation
    # batches cannot silently remove one another's provenance.
    import json
    receipts = sorted((REPO / "build/historical-v2/native").glob("*/v2-configure-status.json"))
    write("v2_configured_builds.json", {"schema_version": 1, "builds": [json.loads(p.read_text()) for p in receipts]})
