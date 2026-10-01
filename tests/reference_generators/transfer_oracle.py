"""Offline GNU 9.11 freezing, auditing and fuzzing for filesystem suites.

No implementation of either utility is present here. All outcomes come from
the explicitly verified external functional oracle through the suite engine.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import tempfile

from reference_generators import heldout_contract
from reference_generators.transfer_cases import definitions, heldout, file


def render(value):
    return (json.dumps(value, sort_keys=True, indent=1, ensure_ascii=True) + "\n").encode()


def load_engine(suite):
    spec = importlib.util.spec_from_file_location("transfer_engine", suite / "engine.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def oracle(utility):
    variable = utility.upper() + "_ORACLE_BIN"
    value = os.environ.get(variable)
    if not value:
        raise ValueError(f"set {variable} to an independently installed GNU Coreutils 9.11 {utility}")
    binary = Path(value).resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError(f"{variable} is not an executable file")
    version = subprocess.run([str(binary), "--version"], capture_output=True, timeout=10,
                             env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"})
    first = version.stdout.decode("utf-8", "replace").splitlines()
    expected = f"{utility} (GNU coreutils) 9.11"
    if version.returncode != 0 or not first or first[0] != expected:
        raise ValueError(f"refusing oracle: expected {expected!r}; got {first[:1]!r}")
    if binary.name.startswith("new_") or "/candidate/" in binary.as_posix():
        raise ValueError("an experiment candidate cannot be the functional oracle")
    return str(binary), expected


def frozen(case, engine, binary):
    result = engine.execute(case, [binary])
    if result.timed_out or result.crashed or result.exit_code is None:
        raise ValueError(f"cannot freeze {case['name']}: timeout/crash or non-root prerequisite missing")
    return dict(case, exit_code=result.exit_code,
                stdout_b64=base64.b64encode(result.stdout).decode(),
                stderr_class="nonempty" if result.stderr else "empty",
                expected_tree=result.modes)


def artifacts(suite, utility, engine, binary, version):
    visible = definitions(utility)
    hidden = heldout(visible)
    for case in visible + hidden:
        with tempfile.TemporaryDirectory() as temp:
            engine.validate_case(case, Path(temp).resolve())
    public_cases = [frozen(c, engine, binary) for c in visible]
    private_cases = [frozen(c, engine, binary) for c in hidden]
    provenance = {"role": "functional_behavioral_oracle", "project": "GNU Coreutils",
                  "version": "9.11", "version_line": version,
                  "historical_vulnerability_source": False}
    public = {"schema_version": 1, "cases": public_cases}
    private = heldout_contract.build(utility, provenance, private_cases)
    payloads = {"suites/cases.json.gz": gzip.compress(render(public), mtime=0),
                "heldout/heldout_cases.json.gz": gzip.compress(render(private), mtime=0)}
    manifest = {"schema_version": 1, "functional_oracle": provenance,
                "platform_contract": "POSIX Darwin/Linux bounded semantic state",
                "counts": {"visible": len(public_cases), "heldout": len(private_cases)},
                "sha256": {name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()}}
    payloads["suites/MANIFEST.json"] = render(manifest)
    return payloads


def audit(suite, utility):
    manifest_path = suite / "suites/MANIFEST.json"
    if not manifest_path.is_file():
        raise ValueError("goldens not frozen: verified GNU 9.11 generation is required")
    manifest = json.loads(manifest_path.read_text())
    for name, digest in manifest["sha256"].items():
        if hashlib.sha256((suite / name).read_bytes()).hexdigest() != digest:
            raise ValueError("corpus hash mismatch: " + name)
    engine = load_engine(suite)
    ladder = json.loads((suite.parents[1] / "experiments/utilities" / f"{utility}.json").read_text())
    allowed = set(ladder["checkpoints"][-1]["implemented_flags"])
    for group in ("suites/cases.json.gz", "heldout/heldout_cases.json.gz"):
        data = json.loads(gzip.decompress((suite / group).read_bytes()))
        names = set()
        for case in data["cases"]:
            required = {"name", "args", "fixture", "flags", "exit_code", "stdout_b64", "stderr_class", "expected_tree", "check"}
            if not required <= case.keys() or case["name"] in names:
                raise ValueError("invalid or duplicate frozen case")
            names.add(case["name"])
            if not set(case["flags"]) <= allowed or case["check"] != "golden":
                raise ValueError("invalid flag identifier or comparison")
            if case["stderr_class"] not in ("empty", "nonempty") or case["exit_code"] not in (0, 1):
                raise ValueError("invalid outcome")
            base64.b64decode(case["stdout_b64"], validate=True)
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                engine.validate_case(case, root)
                for path in case["expected_tree"]:
                    engine.safe_path(root, path)
        if group.startswith("heldout"):
            errors = heldout_contract.corpus_invariants(data, [c["implemented_flags"] for c in ladder["checkpoints"]])
            if errors:
                raise ValueError("; ".join(errors))
    # Audit every staged byte, including the generated bundle metadata, for
    # forbidden option tokens and controller-only case names/paths.
    sys.path.insert(0, str(suite.parents[1] / "scripts"))
    import stage_test_bundle
    import check_heldout_isolation
    import re
    for checkpoint in ladder["checkpoints"]:
        payload = stage_test_bundle.build_payload(suite.parents[1], f"tests/{utility}-test-suite", checkpoint, utility)
        content = b"\n".join(payload["files"].values()) + render(payload["manifest"])
        for flag in allowed - set(checkpoint["implemented_flags"]):
            for option in [flag, *ladder["flag_aliases"][flag]]:
                if re.search(rb"(?<![\w-])" + re.escape(option.encode()) + rb"(?![\w-])", content):
                    raise ValueError("future option leaked: " + option)
        for forbidden in (b"heldout-", b"private-", b"ORACLE_BIN", b"uutils"):
            if forbidden in content:
                raise ValueError("controller content leaked")
    leaks, _, _ = check_heldout_isolation.scan_utility(suite.parents[1], utility)
    if leaks:
        raise ValueError("; ".join(leaks))
    print(f"{utility}: schema, hashes, flags, held-out invariants and checkpoint isolation passed")


def fuzz(suite, utility, binary, candidate, seed, count, output):
    engine = load_engine(suite)
    candidate = str(Path(candidate).resolve(strict=True))
    if os.path.samefile(binary, candidate):
        raise ValueError("candidate and oracle must be independent binaries")
    repo = suite.parents[1].resolve()
    output = Path(output).resolve()
    if output == repo or repo in output.parents:
        raise ValueError("fuzz output must be outside the repository")
    if output.exists():
        raise ValueError("fuzz output already exists; choose a new report path")
    rng = random.Random(seed)
    pool = definitions(utility)
    regressions = []
    for index in range(count):
        case = json.loads(json.dumps(rng.choice(pool)))
        case["name"] = f"fuzz-{seed}-{index:05d}"
        for entry in case["fixture"]:
            if entry["type"] == "file":
                data = rng.randbytes(rng.choice([0, 1, 7, 255, 4096, 65536]))
                entry["contents_b64"] = base64.b64encode(data).decode()
        expected = frozen(case, engine, binary)
        got = engine.execute(case, [candidate])
        if (got.timed_out or got.crashed or got.exit_code != expected["exit_code"]
                or got.stdout != base64.b64decode(expected["stdout_b64"])
                or bool(got.stderr) != (expected["stderr_class"] == "nonempty")
                or got.modes != expected["expected_tree"]):
            expected["_observed"] = {
                "exit_code": got.exit_code, "timed_out": got.timed_out,
                "signal": got.signal_name,
                "stdout_b64": base64.b64encode(got.stdout).decode(),
                "stderr_b64": base64.b64encode(got.stderr).decode(),
                "filesystem": got.modes,
            }
            regressions.append(expected)
    # Developer evidence is deliberately kept outside the repository. It is
    # never appended automatically to the experimental distribution.
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(render({"schema_version": 1, "seed": seed, "cases": regressions}))
    print(f"{utility}: {count} fuzz cases, {len(regressions)} regressions at {output}")
    return bool(regressions)


def main(suite: Path, utility: str):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--fuzz", action="store_true")
    parser.add_argument("--candidate")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if args.audit:
            audit(suite, utility)
            return 0
        if platform.system() not in ("Darwin", "Linux"):
            raise ValueError("requires a POSIX Darwin/Linux host")
        binary, version = oracle(utility)
        print(f"functional oracle: {binary} -- {version}")
        if args.fuzz:
            if not args.candidate or not args.output or args.count < 1:
                raise ValueError("fuzz requires candidate, outside-repository output and positive count")
            return int(fuzz(suite, utility, binary, args.candidate, args.seed, args.count, args.output))
        engine = load_engine(suite)
        first = artifacts(suite, utility, engine, binary, version)
        if first != artifacts(suite, utility, engine, binary, version):
            raise ValueError("oracle outcomes are not reproducible")
        for name, data in first.items():
            path = suite / name
            if args.check:
                if not path.is_file() or path.read_bytes() != data:
                    raise ValueError("stale frozen artifact: " + name)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        audit(suite, utility)
        if args.check:
            with tempfile.TemporaryDirectory() as temp:
                config = Path(temp) / "config.json"
                config.write_text((suite / "config.json").read_text())
                command = [sys.executable, str(suite / "runner.py"),
                           str(suite / "suites/cases.json.gz"),
                           str(suite / "heldout/heldout_cases.json.gz"),
                           "--config", str(config), "--", binary]
                result = subprocess.run(command)
                if result.returncode:
                    raise ValueError("native runner oracle self-pass failed")
        print("frozen expectations reproduced byte-for-byte" if args.check else "functional goldens frozen")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2
