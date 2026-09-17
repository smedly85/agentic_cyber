"""Retry the authentic util-linux configure with isolated PAM development inputs."""
import json
import os
import subprocess
from security.historical.v2_study import ROOT, read, write
from security.historical.analysis import verify_source_tree_sha256
from security.historical.semantic_validation import _sha256
from security.semantic_callgraph import stable_json


def main():
    repo = ROOT.parents[1]
    build = repo / "build/historical-v2/native/util-linux-2.29.1"
    receipt = build / "v2-configure-status.json"
    previous = json.loads(receipt.read_text())
    dependency = read("v2_pam_dependency.json")
    if dependency["returncode"] or dependency.get("extraction_returncode"):
        raise RuntimeError("isolated PAM development inputs unavailable")
    if previous.get("isolated_dependency"):
        print("retained PAM configuration", previous["returncode"])
        return
    sysroot = repo / dependency["sysroot"]
    include = os.path.relpath(sysroot / "usr/include", build)
    lib = os.path.relpath(sysroot / "usr/lib/x86_64-linux-gnu", build)
    command = [*previous["command"], "CPPFLAGS=-I" + include, "LDFLAGS=-L" + lib]
    log = build / "v2-configure-pam.log"
    with log.open("w") as handle:
        result = subprocess.run(command, cwd=build, env=dict(os.environ, FORCE_UNSAFE_CONFIGURE="1"),
                                stdout=handle, stderr=subprocess.STDOUT)
    verify_source_tree_sha256(ROOT / previous["source_tree"], previous["source_tree_sha256"])
    row = {**previous, "previous_configure_attempt": previous, "command": command,
           "returncode": result.returncode, "status": "configured" if result.returncode == 0 else "configure_failed_pending_review",
           "isolated_dependency": dependency, "log": log.relative_to(repo).as_posix(),
           "configuration_correction": "Required PAM headers and link stub matching the installed runtime, extracted locally without system installation; no source or pointer-analysis modification."}
    receipt.write_text(stable_json(row))
    print("util-linux isolated PAM configure:", row["status"])


if __name__ == "__main__":
    main()
