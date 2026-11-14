"""Docker-only C/LLVM-IR extraction and unified graph comparison CLI.

This is an experimental pipeline.  It does not modify or import the accepted
A/S reporters and it never writes historical measurement artifacts.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .analysis.unified_distance import Limits, compare
from .analysis.unified_graph import extract_llvm_ir, unavailable

PROFILE = "c11-posix2008-v1"
PROFILE_ADDITIONS = ["-D_POSIX_C_SOURCE=200809L"]
ENV_REMOVE = ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH",
              "SDKROOT", "MACOSX_DEPLOYMENT_TARGET", "CCC_OVERRIDE_OPTIONS")


def stable_json(value) -> str:
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


def sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def extract(source: Path, *, clang: str = "clang", extra_flags=(), timeout: int = 120):
    if not Path("/.dockerenv").is_file():
        return unavailable("docker_required_for_compiler_extraction")
    if source.suffix.lower() != ".c":
        return unavailable("unsupported_language", suffix=source.suffix)
    executable = shutil.which(clang)
    if not executable:
        return unavailable("clang_unavailable_in_docker")
    data = source.read_bytes()
    environment = dict(os.environ)
    removed = {key: environment.pop(key, None) for key in ENV_REMOVE}
    environment["LC_ALL"] = "C"
    command = [executable, *extra_flags, *PROFILE_ADDITIONS, "-S", "-emit-llvm", "-o", "-", str(source)]
    try:
        process = subprocess.run(command, capture_output=True, env=environment, timeout=timeout)
        version = subprocess.run([executable, "--version"], capture_output=True, env=environment,
                                 timeout=30, check=False).stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return unavailable("compiler_timeout", timeout_seconds=timeout)
    if process.returncode != 0:
        return unavailable("compiler_failure", returncode=process.returncode,
                           stderr=process.stderr.decode("utf-8", "replace")[-4000:])
    artifact = extract_llvm_ir(process.stdout.decode("utf-8", "replace"), source_bytes=data,
                               source_path=str(source), compiler_version=version,
                               compiler_sha256=sha(Path(executable).resolve().read_bytes()),
                               command=command, profile=PROFILE)
    artifact["extraction_environment"] = {"LC_ALL": "C", "removed": removed,
                                          "docker_required": True}
    return artifact


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    extraction = sub.add_parser("extract")
    extraction.add_argument("source", type=Path)
    extraction.add_argument("output", type=Path)
    extraction.add_argument("--clang", default="clang")
    extraction.add_argument("--flag", action="append", default=[])
    comparison = sub.add_parser("compare")
    comparison.add_argument("left", type=Path); comparison.add_argument("right", type=Path)
    comparison.add_argument("output", type=Path)
    comparison.add_argument("--max-states", type=int, default=2_000_000)
    comparison.add_argument("--seconds", type=float, default=45)
    comparison.add_argument("--max-nodes", type=int, default=80)
    args = parser.parse_args(argv)
    if args.action == "extract":
        result = extract(args.source, clang=args.clang, extra_flags=args.flag)
    else:
        left, right = json.loads(args.left.read_text()), json.loads(args.right.read_text())
        result = compare(left, right, limits=Limits(args.max_states, args.seconds, args.max_nodes))
        result["inputs"] = {"left_path": str(args.left), "right_path": str(args.right),
                            "left_sha256": sha(args.left.read_bytes()), "right_sha256": sha(args.right.read_bytes())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(stable_json(result), encoding="utf-8")
    return 0 if result.get("status") == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
