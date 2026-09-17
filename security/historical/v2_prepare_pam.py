"""Acquire PAM development inputs locally; never install system packages."""
import json
import os
import subprocess
from security.historical.v2_study import ROOT, write
from security.historical.semantic_validation import _run, _sha256


def main():
    repo = ROOT.parents[1]
    local = repo / "build/historical-v2/dependencies/pam"
    local.mkdir(parents=True, exist_ok=True)
    runtime = _run(["dpkg-query", "-W", "-f=${Version}", "libpam0g:amd64"])
    if runtime.returncode:
        raise RuntimeError("installed PAM runtime version unavailable")
    version = runtime.stdout.strip()
    command = ["apt-get", "download", "libpam0g-dev=" + version]
    result = _run(command, cwd=local)
    (local / "download.log").write_text(result.stdout + result.stderr)
    row = {"schema_version": 1, "purpose": "isolated development headers/link stubs matching installed PAM runtime; no system install",
           "runtime_version": version, "command": command, "returncode": result.returncode, "diagnostics": result.stdout + result.stderr}
    if not result.returncode:
        archives = list(local.glob("libpam0g-dev_*.deb"))
        if len(archives) != 1:
            raise RuntimeError("ambiguous PAM development-package archive")
        archive = archives[0]
        root = local / "sysroot"
        extracted = _run(["dpkg-deb", "-x", str(archive), str(root)])
        row.update(archive=archive.relative_to(repo).as_posix(), sha256=_sha256(archive), extraction_returncode=extracted.returncode,
                   extraction_diagnostic=extracted.stderr, sysroot=root.relative_to(repo).as_posix())
        # Development symlinks are relative to sibling shared objects. Supply
        # the matching runtime locally too, rather than rewriting their paths.
        runtime_command = ["apt-get", "download", "libpam0g=" + version]
        acquired = _run(runtime_command, cwd=local)
        row["runtime_package"] = {"command": runtime_command, "returncode": acquired.returncode,
                                  "diagnostics": acquired.stdout + acquired.stderr}
        if not acquired.returncode:
            runtimes = list(local.glob("libpam0g_*.deb"))
            if len(runtimes) != 1:
                raise RuntimeError("ambiguous PAM runtime archive")
            unpacked = _run(["dpkg-deb", "-x", str(runtimes[0]), str(root)])
            row["runtime_package"].update(archive=runtimes[0].relative_to(repo).as_posix(), sha256=_sha256(runtimes[0]),
                                          extraction_returncode=unpacked.returncode, extraction_diagnostic=unpacked.stderr)
    write("v2_pam_dependency.json", row)
    print("PAM isolated acquisition:", row["returncode"])


if __name__ == "__main__":
    main()
