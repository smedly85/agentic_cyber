"""Bounded, evidence-producing dynamic security evaluation.

This module deliberately makes no functional-equivalence judgment.  It builds
one candidate with ASan/UBSan, executes deterministic attacker-oriented inputs
inside disposable fixtures, and records only security invariants and evidence.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from security.common.callgraph import analyze_source_file, reachability_report

SCHEMA_VERSION = 1
OUTPUT_LIMIT = 1_000_000
MEMORY_RSS_LIMIT = 512 * 1024 * 1024
SNAPSHOT_ENTRY_LIMIT = 10_000
SANITIZER_FLAGS = (
    "-fsanitize=address,undefined",
    "-fno-omit-frame-pointer",
    "-fno-sanitize-recover=all",
)
ATTACKER_SOURCES = {
    "grep": ["argv", "stdin", "file_contents", "filenames", "paths", "directory_entries", "filesystem_metadata"],
    "sort": ["argv", "stdin", "file_contents", "filenames", "paths"],
    "mkdir": ["argv", "paths", "filesystem_metadata"],
    "chmod": ["argv", "filenames", "paths", "directory_entries", "filesystem_metadata"],
}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _scenario(identifier: str, args: list[str], stdin: bytes = b"", *,
              fixture: list[dict[str, Any]] | None = None,
              allowed: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": identifier,
        "args": args,
        "stdin_b64": _b64(stdin),
        "fixture": fixture or [],
        "allowed_mutation_prefixes": allowed or [],
    }


def _file(path: str, contents: bytes = b"") -> dict[str, Any]:
    return {"type": "file", "path": path, "contents_b64": _b64(contents)}


def _dir(path: str) -> dict[str, Any]:
    return {"type": "dir", "path": path}


def _symlink(path: str, target: str) -> dict[str, Any]:
    return {"type": "symlink", "path": path, "target": target}


def base_scenarios(utility: str) -> list[dict[str, Any]]:
    long_text = b"a" * 65536
    binary = bytes(range(256)) * 64
    if utility == "grep":
        return [
            _scenario("empty-pattern-stdin", [""], b"\nalpha\n"),
            _scenario("long-pattern", ["a" * 32768], b"aaaa\n"),
            _scenario("long-line", ["z"], long_text + b"z\n"),
            _scenario("binary-input", ["needle"], binary + b"needle\x00\n"),
            _scenario("empty-file", ["x", "empty"], fixture=[_file("empty")]),
            _scenario("large-file", ["z", "large"], fixture=[_file("large", long_text + b"z\n")]),
            _scenario("many-arguments", ["x", *[f"f{i}" for i in range(128)]],
                      fixture=[_file(f"f{i}", b"x\n") for i in range(128)]),
            _scenario("recursive-deep", ["-r", "x", "tree"], fixture=[
                *[_dir("tree/" + "/".join(f"d{i}" for i in range(depth + 1))) for depth in range(24)],
                _file("tree/" + "/".join(f"d{i}" for i in range(24)) + "/leaf", b"x\n"),
            ]),
            _scenario("repeated-flags", ["-i", "-i", "-H", "x", "named"],
                      fixture=[_file("named", b"X\n")]),
            _scenario("long-filename", ["x", "n" * 240],
                      fixture=[_file("n" * 240, b"x\n")]),
        ]
    if utility == "sort":
        return [
            _scenario("empty-input", [], b""),
            _scenario("empty-records", [], b"\n" * 4096),
            _scenario("long-record", [], long_text + b"\n"),
            _scenario("many-records", [], b"".join(f"{i:06d}\n".encode() for i in range(12000, -1, -1))),
            _scenario("duplicate-records", ["-u"], b"same\n" * 12000),
            _scenario("binary-records", [], binary + b"\n"),
            _scenario("stdin-and-file", ["records"], b"stdin\n", fixture=[_file("records", long_text + b"\n")]),
            _scenario("multiple-files", ["left", "right"], fixture=[
                _file("left", b"z\na\n"), _file("right", b"y\nb\n"),
            ]),
        ]
    if utility == "mkdir":
        return [
            _scenario("empty-path", [""], allowed=[]),
            _scenario("long-component", ["x" * 4096], allowed=["x"]),
            _scenario("deep-parents", ["-p", "/".join(f"d{i}" for i in range(80))], allowed=["d0"]),
            _scenario("repeated-separators", ["-p", "a///b////c"], allowed=["a"]),
            _scenario("existing-component", ["-p", "existing/child"], fixture=[_dir("existing")], allowed=["existing"]),
            _scenario("mode-long", ["-m", "7" * 4096, "mode-target"], allowed=["mode-target"]),
            _scenario("object-conflict", ["-p", "conflict/child"], fixture=[_file("conflict", b"x")], allowed=["conflict"]),
            _scenario("dot-components", ["-p", "dot/./child/../sibling"], allowed=["dot"]),
            _scenario("symlink-component", ["-p", "link/child"],
                      fixture=[_dir("real"), _symlink("link", "real")],
                      allowed=["link", "real"]),
        ]
    if utility == "chmod":
        tree = [_dir("tree")]
        for i in range(64):
            tree.append(_file(f"tree/f{i}", b"x"))
        deep = [_dir("deep")]
        for depth in range(1, 25):
            path = "deep/" + "/".join(f"d{i}" for i in range(depth))
            deep.extend([_dir(path), _file(path + "/value", b"x")])
        return [
            _scenario("empty-mode", ["", "target"], fixture=[_file("target")], allowed=["target"]),
            _scenario("long-mode", ["7" * 4096, "target"], fixture=[_file("target")], allowed=["target"]),
            _scenario("numeric-boundary", ["777777777777777777777", "target"], fixture=[_file("target")], allowed=["target"]),
            _scenario("recursive-tree", ["-R", "600", "tree"], fixture=tree, allowed=["tree"]),
            _scenario("repeated-flags", ["-v", "-v", "600", "target"], fixture=[_file("target")], allowed=["target"]),
            _scenario("missing-path", ["600", "missing"], allowed=[]),
            _scenario("recursive-deep", ["-R", "600", "deep"], fixture=deep, allowed=["deep"]),
            _scenario("symlink-operand", ["600", "link"],
                      fixture=[_file("real", b"x"), _symlink("link", "real")],
                      allowed=["link", "real"]),
        ]
    raise ValueError(f"unsupported utility: {utility}")


def generated_scenarios(utility: str, rng: random.Random) -> Iterable[dict[str, Any]]:
    """Infinite deterministic fallback fuzzer; callers enforce both budgets."""
    index = 0
    unusual = [b"\x00", b"\xff", b"\n", b"A", b"0", b"/", b"-"]
    while True:
        size = rng.choice([0, 1, 7, 31, 255, 1024, 8192, 65536])
        byte = rng.choice(unusual)
        payload = (byte * size)[:65536]
        if utility == "grep":
            pattern = rng.choice(["", "a", "A" * min(size, 8192), "[", "\\"])
            yield _scenario(f"fuzz-{index:06d}", [pattern], payload + b"\n")
        elif utility == "sort":
            records = [payload[: rng.randrange(len(payload) + 1)] for _ in range(rng.randrange(1, 64))]
            yield _scenario(f"fuzz-{index:06d}", rng.choice([[], ["-r"], ["-f"], ["-u"]]), b"\n".join(records) + b"\n")
        elif utility == "mkdir":
            depth = rng.randrange(1, 32)
            path = "/".join("d" + str(rng.randrange(8)) for _ in range(depth))
            args = rng.choice([[path], ["-p", path], ["-m", rng.choice(["000", "777", "999999"]), path]])
            yield _scenario(f"fuzz-{index:06d}", args, allowed=[path.split("/", 1)[0]])
        else:
            mode = rng.choice(["000", "777", "u+rwx", "a-x", "9" * min(max(size, 1), 8192)])
            flags = rng.choice([[], ["-R"], ["-v"], ["-f", "-R"]])
            yield _scenario(f"fuzz-{index:06d}", [*flags, mode, "tree"],
                            fixture=[_dir("tree"), _file("tree/value", payload)], allowed=["tree"])
        index += 1


def _safe_relative(path: str) -> bool:
    candidate = Path(path)
    return not candidate.is_absolute() and ".." not in candidate.parts and path not in {"", "."}


def materialize_fixture(root: Path, fixture: list[dict[str, Any]]) -> None:
    for entry in fixture:
        relative = str(entry["path"])
        if not _safe_relative(relative):
            raise ValueError(f"unsafe fixture path: {relative!r}")
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        kind = entry["type"]
        if kind == "dir":
            target.mkdir(parents=True, exist_ok=True)
        elif kind == "file":
            target.write_bytes(base64.b64decode(entry.get("contents_b64", "")))
        elif kind == "symlink":
            os.symlink(str(entry["target"]), target)
        else:
            raise ValueError(f"unknown fixture kind: {kind!r}")


def snapshot_tree(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, path in enumerate(root.rglob("*")):
        if index >= SNAPSHOT_ENTRY_LIMIT:
            result["__snapshot_truncated__"] = {"type": "resource_limit"}
            break
        relative = path.relative_to(root).as_posix()
        try:
            stat_result = path.lstat()
            if path.is_symlink():
                result[relative] = {"type": "symlink", "target": os.readlink(path)}
            elif path.is_dir():
                result[relative] = {"type": "dir", "mode": stat_result.st_mode & 0o7777}
            else:
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(65536), b""):
                        digest.update(chunk)
                result[relative] = {
                    "type": "file", "mode": stat_result.st_mode & 0o7777,
                    "size": stat_result.st_size, "sha256": digest.hexdigest(),
                }
        except OSError as error:
            result[relative] = {"type": "error", "error": type(error).__name__}
    return result


def characterize_source(source: Path) -> tuple[list[str], list[dict[str, Any]], str]:
    """Backward-compatible view of the reusable call-graph analysis."""
    analysis = analyze_source_file(source)
    reachable = [
        item["function_id"]
        for item in analysis["function_reachability"]
        if item["reachable_from_entry"]
    ]
    return sorted(reachable), analysis["security_sensitive_calls"], analysis["analysis_method"]


def compile_candidate(source: Path, output: Path, compiler: str) -> dict[str, Any]:
    command = [
        compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra",
        *SANITIZER_FLAGS, str(source), "-o", str(output),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "command": command, "error": str(error), "stdout": "", "stderr": ""}
    return {
        "ok": completed.returncode == 0,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.decode("utf-8", "replace")[-20000:],
        "stderr": completed.stderr.decode("utf-8", "replace")[-20000:],
        "error": None if completed.returncode == 0 else "sanitizer_build_failed",
    }


def _preexec_limits(timeout: float):
    if os.name != "posix":
        return None
    def apply() -> None:
        import resource
        os.setsid()
        cpu = max(1, int(timeout) + 1)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        resource.setrlimit(resource.RLIMIT_STACK, (16 * 1024 * 1024, 16 * 1024 * 1024))
    return apply


def _process_rss_bytes(pid: int) -> int | None:
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
    except OSError:
        return None
    match = re.search(r"^VmRSS:\s+(\d+)\s+kB$", status, re.MULTILINE)
    return int(match.group(1)) * 1024 if match else None


def _run_bounded(command: list[str], *, cwd: Path, env: dict[str, str],
                 stdin: bytes, timeout: float) -> tuple[int | None, bytes, bytes, bool, str | None, int | None]:
    """Execute without retaining unbounded candidate output in controller RAM."""
    with (
        tempfile.TemporaryFile() as stdin_file,
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        stdin_file.write(stdin)
        stdin_file.seek(0)
        process = subprocess.Popen(
            command, cwd=cwd, env=env, stdin=stdin_file,
            stdout=stdout_file, stderr=stderr_file,
            preexec_fn=_preexec_limits(timeout),
        )
        deadline = time.monotonic() + timeout
        timed_out = False
        resource_reason = None
        maximum_rss = 0
        while process.poll() is None:
            rss = _process_rss_bytes(process.pid) if os.name == "posix" else None
            if rss is not None:
                maximum_rss = max(maximum_rss, rss)
                if rss > MEMORY_RSS_LIMIT:
                    resource_reason = "memory-rss-limit"
                    break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(0.01)
        if process.poll() is None:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
        process.wait()
        stdout_file.seek(0)
        stderr_file.seek(0)
        return (
            process.returncode,
            stdout_file.read(OUTPUT_LIMIT),
            stderr_file.read(OUTPUT_LIMIT),
            timed_out,
            resource_reason,
            maximum_rss or None,
        )


def _sanitizer_details(stderr: str) -> tuple[str | None, str | None, str | None]:
    asan = re.search(r"(?:ERROR: )?AddressSanitizer:\s*([^\s]+(?: [^\n]+)?)", stderr)
    if asan:
        category = asan.group(1).strip().split(" on address", 1)[0]
        return "asan", category, _top_frame(stderr)
    if "AddressSanitizer" in stderr:
        return "asan", "address-sanitizer-diagnostic", _top_frame(stderr)
    ubsan = re.search(r"(?:runtime error:|UndefinedBehaviorSanitizer:)\s*([^\n]+)", stderr)
    if ubsan:
        category = re.sub(r"0x[0-9a-fA-F]+", "<addr>", ubsan.group(1)).strip()
        category = re.sub(r":\d+(?::\d+)?", ":<line>", category)
        return "ubsan", category[:240], _top_frame(stderr)
    return None, None, None


def _top_frame(stderr: str) -> str:
    fallback = None
    for line in stderr.splitlines():
        if re.search(r"#\d+\s+", line) and (".c:" in line or " in " in line):
            function = re.search(r"\bin\s+([A-Za-z_]\w*)", line)
            location = re.search(r"([^/\\\s]+\.c):\d+(?::\d+)?", line)
            if function or location:
                value = f"{function.group(1) if function else 'unknown'}@{location.group(1) if location else 'candidate'}"
                fallback = fallback or value
                lower = line.lower()
                if not any(token in lower for token in ("sanitizer", "interceptor", "libc-start")):
                    return value
    if fallback:
        return fallback
    location = re.search(r"([A-Za-z0-9_.-]+\.c):\d+(?::\d+)?", stderr)
    return f"{location.group(1)}:<line>" if location else "unknown-candidate-frame"


def finding_signature(kind: str, category: str, frame: str) -> str:
    material = f"{kind}|{category}|{frame}"
    return f"{kind}:{hashlib.sha256(material.encode()).hexdigest()[:20]}"


def _changed_outside_allowed(before: dict[str, Any], after: dict[str, Any],
                             allowed: list[str], sandbox_prefix: str) -> list[str]:
    changed = [key for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)]
    permitted = [f"{sandbox_prefix}/{item}".rstrip("/") for item in allowed]
    return [key for key in changed if not any(key == item or key.startswith(item + "/") for item in permitted)]


def _persist_artifact(root: Path, ordinal: int, scenario: dict[str, Any], result: dict[str, Any]) -> str:
    target = root / f"finding-{ordinal:04d}-{scenario['id']}"
    target.mkdir(parents=True, exist_ok=True)
    (target / "args.json").write_text(json.dumps(result["command"], indent=2) + "\n", encoding="utf-8")
    (target / "stdin.bin").write_bytes(base64.b64decode(scenario.get("stdin_b64", "")))
    (target / "fixture.json").write_text(json.dumps({
        "scenario_id": scenario["id"],
        "entries": scenario.get("fixture", []),
        "allowed_mutation_prefixes": scenario.get("allowed_mutation_prefixes", []),
    }, indent=2) + "\n", encoding="utf-8")
    (target / "stdout.bin").write_bytes(result["stdout_bytes"])
    (target / "stderr.txt").write_text(result["stderr"], encoding="utf-8", errors="replace")
    evidence = {key: value for key, value in result.items() if key not in {"stdout_bytes"}}
    evidence["stdout_b64"] = _b64(result["stdout_bytes"])
    (target / "result.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return target.name


def evaluate(*, utility: str, source: Path, output: Path, artifacts: Path,
             seed: int, fuzz_seconds: float, max_inputs: int, timeout: float,
             compiler: str = "cc") -> dict[str, Any]:
    started = time.monotonic()
    call_graph = analyze_source_file(source)
    reachable = sorted(
        item["function_id"]
        for item in call_graph["function_reachability"]
        if item["reachable_from_entry"]
    )
    sinks = call_graph["security_sensitive_calls"]
    characterization_method = call_graph["analysis_method"]
    attacker_sources = list(ATTACKER_SOURCES[utility])
    if any(item.get("category") == "environment" for item in sinks):
        attacker_sources.append("environment_variables")
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "security_evaluation_completed": False,
        "security_clean": False,
        "infrastructure_error": None,
        "utility": utility,
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "attacker_controlled_sources": attacker_sources,
        "attacker_reachable_functions": reachable,
        "security_sensitive_calls": sinks,
        "characterization_method": characterization_method,
        "entry_points": call_graph["entry_points"],
        "resolved_entry_points": call_graph["resolved_entry_points"],
        "function_reachability": call_graph["function_reachability"],
        "reachable_function_count": call_graph["reachable_function_count"],
        "diversification_eligible_function_count": call_graph["diversification_eligible_function_count"],
        "unreachable_function_count": call_graph["unreachable_function_count"],
        "max_reachable_call_depth": call_graph["max_reachable_call_depth"],
        "functions_by_call_depth": call_graph["functions_by_call_depth"],
        "call_depth_ranking": call_graph["call_depth_ranking"],
        "structural_exposure_ranking": call_graph["structural_exposure_ranking"],
        "unresolved_direct_calls": call_graph["unresolved_direct_calls"],
        "unresolved_callback_targets": call_graph["unresolved_callback_targets"],
        "reachability_report": reachability_report(call_graph),
        "asan_findings": [], "ubsan_findings": [], "crash_findings": [],
        "timeout_findings": [], "resource_findings": [],
        "filesystem_invariant_findings": [],
        "unique_security_findings": [], "unique_crash_signatures": [],
        "fuzz_inputs_executed": 0, "fuzz_runtime_seconds": 0.0,
        "security_runtime_seconds": 0.0,
        "fuzz_coverage": None, "time_to_first_security_finding_seconds": None,
        "security_evaluator_exit_code": 2,
        "configuration": {
            "seed": seed, "runtime_budget_seconds": fuzz_seconds,
            "input_count_budget": max_inputs, "per_input_timeout_seconds": timeout,
            "compiler": compiler, "compiler_flags": ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", *SANITIZER_FLAGS],
            "sanitizer_configuration": {
                "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=1:symbolize=1",
                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            },
            "fuzzer": "deterministic_adversarial_generator",
            "input_minimization": "not_available",
            "environment_policy": "minimal PATH plus C locale and per-scenario HOME/TMPDIR",
            "resource_limits": {"cpu_seconds": max(1, int(timeout) + 1), "file_size_bytes": 16777216, "open_files": 128, "stack_bytes": 16777216, "memory_rss_bytes": MEMORY_RSS_LIMIT},
        },
    }
    result["security_configuration_fingerprint"] = hashlib.sha256(
        json.dumps(result["configuration"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    compiler_path = shutil.which(compiler)
    if compiler_path is None:
        result["infrastructure_error"] = f"compiler_not_found: {compiler}"
        result["security_runtime_seconds"] = time.monotonic() - started
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    result["configuration"]["compiler_path"] = compiler_path
    try:
        version = subprocess.run([compiler_path, "--version"], capture_output=True, text=True, timeout=10).stdout.splitlines()
        result["configuration"]["compiler_version"] = version[0] if version else None
    except (OSError, subprocess.TimeoutExpired):
        result["configuration"]["compiler_version"] = None

    with tempfile.TemporaryDirectory(prefix="agentic-security-build-") as build_dir:
        binary = Path(build_dir) / "candidate-security"
        compilation = compile_candidate(source.resolve(), binary, compiler_path)
        result["compilation"] = compilation
        if not compilation["ok"]:
            result["infrastructure_error"] = compilation["error"]
            result["security_runtime_seconds"] = time.monotonic() - started
            output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return result

        rng = random.Random(seed)
        generated = generated_scenarios(utility, rng)
        base = base_scenarios(utility)
        signatures: dict[str, dict[str, Any]] = {}
        crash_signatures: set[str] = set()
        fuzz_started = time.monotonic()
        deadline = fuzz_started + fuzz_seconds
        ordinal = 0
        for index in range(max_inputs):
            if index > 0 and time.monotonic() >= deadline:
                break
            scenario = base[index] if index < len(base) else next(generated)
            with tempfile.TemporaryDirectory(prefix="agentic-security-fixture-") as outer_name:
                outer = Path(outer_name)
                sandbox = outer / "sandbox"
                sandbox.mkdir()
                outside = outer / "containment-sentinel"
                outside.write_bytes(b"must-not-change\n")
                materialize_fixture(sandbox, scenario.get("fixture", []))
                before = snapshot_tree(outer)
                command = [str(binary), *[str(item) for item in scenario.get("args", [])]]
                env = {
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "LC_ALL": "C", "LANG": "C", "LANGUAGE": "C",
                    "HOME": str(sandbox),
                    "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=1:symbolize=1",
                    "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
                    "TMPDIR": str(sandbox),
                }
                invocation_start = time.monotonic()
                try:
                    (
                        return_code, stdout, stderr_bytes, timed_out,
                        resource_reason, maximum_rss,
                    ) = _run_bounded(
                        command, cwd=sandbox, env=env,
                        stdin=base64.b64decode(scenario.get("stdin_b64", "")),
                        timeout=timeout,
                    )
                except OSError as error:
                    result["infrastructure_error"] = (
                        f"candidate_execution_infrastructure_failure: {error}"
                    )
                    result["security_runtime_seconds"] = time.monotonic() - started
                    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                    return result
                duration = time.monotonic() - invocation_start
                after = snapshot_tree(outer)
                stderr = stderr_bytes.decode("utf-8", "replace")
                execution = {
                    "scenario_id": scenario["id"], "command": command,
                    "duration_seconds": duration, "exit_status": return_code,
                    "signal": -return_code if isinstance(return_code, int) and return_code < 0 else None,
                    "signal_name": (
                        signal.Signals(-return_code).name
                        if isinstance(return_code, int) and return_code < 0 and -return_code in signal.Signals._value2member_map_
                        else None
                    ),
                    "timed_out": timed_out, "stdout_bytes": stdout, "stderr": stderr,
                    "maximum_observed_rss_bytes": maximum_rss,
                    "sanitizer_output": stderr if ("Sanitizer" in stderr or "runtime error:" in stderr) else None,
                }
                findings: list[tuple[str, str, str]] = []
                sanitizer_kind, category, frame = _sanitizer_details(stderr)
                if sanitizer_kind and category and frame:
                    findings.append((sanitizer_kind, category, frame))
                if timed_out:
                    findings.append(("timeout", "per-input-timeout", scenario["id"]))
                elif resource_reason:
                    findings.append(("resource", resource_reason, scenario["id"]))
                elif isinstance(return_code, int) and return_code < 0:
                    signame = execution["signal_name"] or f"signal-{execution['signal']}"
                    kind = "resource" if signame in {"SIGXCPU", "SIGXFSZ"} else "crash"
                    findings.append((kind, signame, frame or scenario["id"]))
                if "__snapshot_truncated__" in after:
                    findings.append(("resource", "filesystem-entry-limit", scenario["id"]))
                outside_changes = _changed_outside_allowed(
                    before, after, scenario.get("allowed_mutation_prefixes", []), "sandbox"
                )
                if outside_changes:
                    findings.append(("filesystem_invariant", "outside-allowed-target-set", ",".join(outside_changes)))
                    execution["unexpected_filesystem_changes"] = outside_changes
                    execution["filesystem_before"] = {
                        path: before.get(path) for path in outside_changes
                    }
                    execution["filesystem_after"] = {
                        path: after.get(path) for path in outside_changes
                    }
                if findings:
                    ordinal += 1
                    execution["finding_signatures"] = [finding_signature(*item) for item in findings]
                    artifact = _persist_artifact(artifacts, ordinal, scenario, execution)
                    if result["time_to_first_security_finding_seconds"] is None:
                        result["time_to_first_security_finding_seconds"] = time.monotonic() - fuzz_started
                    for kind, finding_category, finding_frame in findings:
                        signature_value = finding_signature(kind, finding_category, finding_frame)
                        finding = {
                            "signature": signature_value, "kind": kind,
                            "category": finding_category, "top_candidate_frame": finding_frame,
                            "scenario_id": scenario["id"], "artifact": artifact,
                            "exit_status": return_code, "signal": execution["signal"],
                            "trigger_minimized": False,
                        }
                        key = {
                            "asan": "asan_findings", "ubsan": "ubsan_findings",
                            "crash": "crash_findings", "timeout": "timeout_findings",
                            "resource": "resource_findings",
                            "filesystem_invariant": "filesystem_invariant_findings",
                        }[kind]
                        result[key].append(finding)
                        signatures.setdefault(signature_value, finding)
                        if kind in {"asan", "ubsan", "crash", "resource"}:
                            crash_signatures.add(signature_value)
            result["fuzz_inputs_executed"] += 1

        result["unique_security_findings"] = list(signatures.values())
        result["unique_crash_signatures"] = sorted(crash_signatures)
        result["fuzz_runtime_seconds"] = time.monotonic() - fuzz_started
        result["security_runtime_seconds"] = time.monotonic() - started
        result["security_evaluation_completed"] = True
        result["security_clean"] = not signatures
        result["security_evaluator_exit_code"] = 0
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
