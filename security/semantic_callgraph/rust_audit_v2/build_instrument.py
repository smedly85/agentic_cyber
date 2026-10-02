"""Build an explicitly patched instrument; retain old provenance untouched."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "security/historical/rust"))
from semantic_gate import verify_frozen


def main():
    verify_frozen()
    svf = ROOT / "build/semantic-toolchain/SVF"
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=svf, text=True).strip()
    if revision != "67efb7745ce47b2b6853fd5696fc22c83d701e6c":
        raise ValueError("SVF pinned revision mismatch")
    cache = ROOT / "build/rust-instrument-v2"
    cache.mkdir(parents=True, exist_ok=True)
    helper = svf / "Release-build/bin/semantic-callgraph-svf"
    if not (cache / "original-helper.sha256").exists():
        (cache / "original-helper.sha256").write_text(hashlib.sha256(helper.read_bytes()).hexdigest() + "\n")
    patch = ROOT / "security/semantic_callgraph/rust_audit_v2/svf-byte-offset.patch"
    check = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=svf, capture_output=True)
    if check.returncode:
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=svf, check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=svf, check=True)
    shutil.copy2(ROOT / "security/semantic_callgraph/native/semantic_callgraph_svf.cpp",
                 svf / "svf-llvm/tools/SemanticCallGraph/semantic_callgraph_svf.cpp")
    cmake = ROOT / "build/semantic-toolchain/venv/bin/cmake"
    command = [str(cmake), "--build", str(svf / "Release-build"), "--target", "semantic-callgraph-svf", "--parallel", "2"]
    with (cache / "build.log").open("w") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    (cache / "build-command.json").write_text(json.dumps({"command": command, "exit": result.returncode}, indent=2))
    print("build status", result.returncode, "log", cache / "build.log")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
