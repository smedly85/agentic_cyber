"""Retained C99 diagnostic attempt; it did not solve modern glibc's gets removal.

The accepted build uses v2_configure_8_4_clang instead. This module preserves
the earlier investigation, not a scientifically accepted build correction.
"""
import json
import os
import subprocess
from security.historical.v2_study import ROOT
from security.historical.analysis import verify_source_tree_sha256
from security.semantic_callgraph import stable_json


def main():
    build = ROOT.parents[1] / "build/historical-v2/native/coreutils-8.4"
    receipt = build / "v2-configure-status.json"
    old = json.loads(receipt.read_text())
    if old.get("dialect_correction"):
        print("retained C99 configuration", old["returncode"])
        return
    command = [x if not x.startswith("CC=") else "CC=gcc -std=gnu99" for x in old["command"]]
    command += ["CPPFLAGS=-D_IO_ftrylockfile=1 -D_IO_IN_BACKUP=0x100"]
    log = build / "v2-configure-c99.log"
    with log.open("w") as handle:
        result = subprocess.run(command, cwd=build, env=dict(os.environ, FORCE_UNSAFE_CONFIGURE="1"),
                                stdout=handle, stderr=subprocess.STDOUT)
    verify_source_tree_sha256(ROOT / old["source_tree"], old["source_tree_sha256"])
    row = {**old, "previous_configure_attempt": old, "command": command, "configured_cc": "gcc -std=gnu99",
           "returncode": result.returncode, "status": "configured" if not result.returncode else "configure_failed_pending_review",
           "log": log.relative_to(ROOT.parents[1]).as_posix(),
           "dialect_correction": "Diagnostic hypothesis only: try C99 to test whether gets visibility is solely language-mode dependent. The subsequent native build disproved this on current glibc, which removes the declaration in C99 too. This is not the accepted semantic build; see v2_configure_8_4_clang and its separate receipt."}
    receipt.write_text(stable_json(row))
    print("8.4 historical C99 configure", row["status"])


if __name__ == "__main__":
    main()
