"""Fail-closed Clang/LLVM/SVF semantic may-call graph backend.

Clang creates one bitcode module per translation unit and llvm-link combines
them.  A dedicated SVF API helper emits structured raw functions/callsites;
this module validates that output, computes deterministic shortest paths, and
records scientific provenance.  Syntax-derived call edges are never used.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
BACKEND = "clang_llvm_svf"
POINTER_ANALYSIS = "andersen_wave_diff"
# LLVM opaque-pointer IR may address a struct's first field through the base
# object. SVF's first-field/base equivalence preserves that C layout fact for
# field-sensitive points-to analysis. Statistics are disabled so stdout is the
# helper's single structured JSON document.
SVF_HELPER_OPTIONS = ("-stat=false", "-ff-eq-base")
DEFAULT_CFLAGS = (
    "-std=c11",
    "-g",
    "-O0",
    "-fno-inline",
    "-fno-builtin",
    "-fno-discard-value-names",
)
TOOL_NAMES = ("clang", "llvm-link", "llvm-dis", "opt", "SVF", "wpa")
VERSION_RE = re.compile(r"(?:clang|LLVM) version\s+([0-9]+(?:\.[0-9]+){0,2})", re.I)


class SemanticCallgraphError(ValueError):
    """The semantic backend received invalid or inconsistent input."""


@dataclass(frozen=True)
class BuildResult:
    status: str
    linked_bitcode: Path | None
    source_files: tuple[dict[str, str], ...]
    build_commands: tuple[tuple[str, ...], ...]
    bitcode_files: tuple[dict[str, str], ...]
    diagnostics: tuple[dict[str, Any], ...]
    target_triple: str | None
    configuration: Mapping[str, Any] | None = None


def _run(command: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )


def _version(path: str) -> str | None:
    try:
        result = _run((path, "--version"))
    except OSError:
        return None
    if result.returncode != 0:
        return None
    text = (result.stdout + result.stderr).strip()
    return text or None


def _repository_local_svf_version(helper_path: str | None) -> str | None:
    """Identify an in-tree helper without requiring an unsupported --version."""
    if not helper_path:
        return None
    for root in Path(helper_path).resolve().parents:
        cmake_file = root / "CMakeLists.txt"
        if not (root / ".git").exists() or not cmake_file.is_file():
            continue
        cmake_text = cmake_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"project\s*\(\s*SVF\s+VERSION\s+([0-9.]+)", cmake_text, re.I)
        commit = _run(("git", "-C", str(root), "rev-parse", "HEAD"))
        if match and commit.returncode == 0:
            return f"SVF {match.group(1)} (commit {commit.stdout.strip()})"
    return None


def _llvm_sibling(name: str, clang_path: str | None) -> str | None:
    """Find matching versioned LLVM tools without mixing LLVM installations."""
    direct = shutil.which(name)
    if direct:
        return str(Path(direct).resolve())
    if not clang_path:
        return None
    clang = Path(clang_path).resolve()
    match = re.search(r"(?:clang-)?([0-9]+)$", clang.name)
    version = match.group(1) if match else None
    candidates = [clang.parent / name]
    if version:
        candidates.extend((clang.parent / f"{name}-{version}", Path(f"/usr/lib/llvm-{version}/bin/{name}")))
    else:
        version_text = _version(str(clang)) or ""
        major = VERSION_RE.search(version_text)
        if major:
            candidates.append(Path(f"/usr/lib/llvm-{major.group(1).split('.')[0]}/bin/{name}"))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None


def inventory_toolchain(*, helper: str | Path | None = None) -> dict[str, Any]:
    """Return paths and exact version banners; never installs or substitutes tools."""
    clang = shutil.which("clang")
    paths: dict[str, str | None] = {"clang": str(Path(clang).resolve()) if clang else None}
    for name in ("llvm-link", "llvm-dis", "opt"):
        paths[name] = _llvm_sibling(name, paths["clang"])
    for name in ("SVF", "wpa"):
        found = shutil.which(name)
        paths[name] = str(Path(found).resolve()) if found else None
    helper_path = str(Path(helper).resolve()) if helper and Path(helper).is_file() else shutil.which("semantic-callgraph-svf")
    paths["semantic-callgraph-svf"] = str(Path(helper_path).resolve()) if helper_path else None
    tools = {
        name: {
            "available": path is not None,
            "path": path,
            "version": _version(path) if path else None,
        }
        for name, path in paths.items()
    }
    helper_row = tools["semantic-callgraph-svf"]
    if helper_row["available"] and helper_row["version"] is None:
        helper_row["version"] = _repository_local_svf_version(helper_row["path"])
    clang_major = _major(tools["clang"]["version"])
    llvm_majors = {
        _major(tools[name]["version"])
        for name in ("llvm-link", "llvm-dis", "opt") if tools[name]["available"]
    }
    compatible = bool(clang_major and llvm_majors and llvm_majors == {clang_major})
    return {
        "host": platform.platform(),
        "tools": tools,
        "clang_llvm_major_compatible": compatible,
        "svf_available": bool(tools["semantic-callgraph-svf"]["available"]),
        "svf_compatibility": (
            "helper_present_version_must_be_verified"
            if tools["semantic-callgraph-svf"]["available"]
            else "not_testable_svf_unavailable"
        ),
    }


def _major(version: str | None) -> int | None:
    if not version:
        return None
    match = VERSION_RE.search(version)
    return int(match.group(1).split(".")[0]) if match else None


def _safe_source(root: Path, value: str | Path) -> tuple[str, Path]:
    text = str(value).replace("\\", "/")
    relative = PurePosixPath(text)
    if not text or relative.is_absolute() or ".." in relative.parts or PureWindowsPath(text).drive:
        raise SemanticCallgraphError(f"source file must be a safe relative path: {value}")
    candidate = root.joinpath(*relative.parts).resolve()
    try:
        normalized = candidate.relative_to(root).as_posix()
    except ValueError as error:
        raise SemanticCallgraphError(f"source file escapes source root: {value}") from error
    if not candidate.is_file() or candidate.suffix.lower() != ".c":
        raise SemanticCallgraphError(f"source file is not an existing C file: {value}")
    return normalized, candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scientific_command(command: Sequence[str], *, source_root: Path, output_root: Path) -> tuple[str, ...]:
    source_text = str(source_root)
    output_text = str(output_root)
    return tuple(
        str(item).replace(source_text, "$SOURCE_ROOT").replace(output_text, "$OUTPUT_ROOT").replace("\\", "/")
        for item in command
    )


def _target_triple(clang: str) -> str | None:
    result = _run((clang, "-dumpmachine"))
    return result.stdout.strip() if result.returncode == 0 else None


def build_bitcode(
    source_root: str | Path,
    source_files: Iterable[str | Path],
    output_dir: str | Path,
    *,
    compile_flags: Iterable[str] = (),
    inventory: Mapping[str, Any] | None = None,
) -> BuildResult:
    """Compile/link bitcode with conservative source-preserving flags."""
    root = Path(source_root).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    checked = [_safe_source(root, value) for value in source_files]
    if not checked:
        raise SemanticCallgraphError("at least one source file is required")
    info = dict(inventory or inventory_toolchain())
    tools = info.get("tools", {})
    clang = tools.get("clang", {}).get("path")
    linker = tools.get("llvm-link", {}).get("path")
    sources = tuple({"path": name, "sha256": _sha256(path)} for name, path in checked)
    if not clang or (len(checked) > 1 and not linker):
        missing = ["clang"] if not clang else ["llvm-link"]
        return BuildResult(
            "build_or_ir_unavailable", None, sources, (), (),
            ({"stage": "toolchain", "missing_tools": missing, "message": "required LLVM tool unavailable"},),
            None,
        )
    flags = [*DEFAULT_CFLAGS, *map(str, compile_flags)]
    flags.extend(("-fdebug-compilation-dir=.", f"-fdebug-prefix-map={root}=."))
    commands: list[tuple[str, ...]] = []
    modules: list[Path] = []
    diagnostics: list[dict[str, Any]] = []
    for index, (relative, path) in enumerate(checked):
        module = output / f"tu-{index:04d}.bc"
        command = [clang, *flags, "-emit-llvm", "-c", str(path), "-o", str(module)]
        commands.append(_scientific_command(command, source_root=root, output_root=output))
        result = _run(command, cwd=root)
        if result.returncode != 0:
            diagnostics.append({
                "stage": "clang", "source_file": relative, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr,
            })
            return BuildResult(
                "build_or_ir_unavailable", None, sources, tuple(commands), (),
                tuple(diagnostics), _target_triple(clang),
            )
        modules.append(module)
    linked = output / "linked.bc"
    if len(modules) == 1:
        shutil.copyfile(modules[0], linked)
    else:
        assert linker
        command = [linker, *map(str, modules), "-o", str(linked)]
        commands.append(_scientific_command(command, source_root=root, output_root=output))
        result = _run(command, cwd=root)
        if result.returncode != 0:
            diagnostics.append({
                "stage": "llvm-link", "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr,
            })
            return BuildResult(
                "build_or_ir_unavailable", None, sources, tuple(commands),
                tuple({"path": f"tu-{i:04d}.bc", "sha256": _sha256(path)} for i, path in enumerate(modules)),
                tuple(diagnostics), _target_triple(clang),
            )
    bitcode = tuple([
        *({"path": f"tu-{i:04d}.bc", "sha256": _sha256(path)} for i, path in enumerate(modules)),
        {"path": "linked.bc", "sha256": _sha256(linked)},
    ])
    return BuildResult("success", linked, sources, tuple(commands), bitcode, tuple(diagnostics), _target_triple(clang))


def _location_key(location: Mapping[str, Any] | None) -> tuple[str, int, int]:
    value = location or {}
    return (str(value.get("source_file") or ""), int(value.get("line") or 0), int(value.get("column") or 0))


def _edge_key(edge: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(edge["caller"]), str(edge["callee"]), str(edge["edge_type"]),
        *_location_key(edge.get("callsite")), int(edge.get("indirect_target_count") or 0),
    )


def _path_status(edges: Sequence[Mapping[str, Any]]) -> str:
    indirect = [edge for edge in edges if edge["edge_type"] == "indirect_resolved"]
    if not indirect:
        return "resolved_direct_only"
    if any(int(edge.get("indirect_target_count") or 0) > 1 for edge in indirect):
        return "resolved_indirect_multi_target"
    return "resolved_with_indirect_edges"


def finalize_semantic_graph(
    raw: Mapping[str, Any], *, entry_point: str,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate raw SVF helper data and calculate deterministic shortest paths."""
    function_rows = [dict(row) for row in raw.get("functions", [])]
    identities = [str(row.get("identity", "")) for row in function_rows]
    if not identities or any(not identity for identity in identities) or len(set(identities)) != len(identities):
        raise SemanticCallgraphError("functions require unique nonempty identities")
    by_id = {row["identity"]: row for row in function_rows}
    matches = sorted(
        identity for identity, row in by_id.items()
        if identity == entry_point or row.get("name") == entry_point
    )
    if len(matches) != 1:
        status = "not_found" if not matches else "ambiguous"
        raise SemanticCallgraphError(f"entry point {entry_point!r} is {status}: {matches}")
    entry_id = matches[0]
    edges: list[dict[str, Any]] = []
    for value in raw.get("call_edges", []):
        edge = dict(value)
        if edge.get("edge_type") not in {"direct", "indirect_resolved"}:
            raise SemanticCallgraphError(f"invalid edge type: {edge.get('edge_type')}")
        if edge.get("caller") not in by_id or edge.get("callee") not in by_id:
            raise SemanticCallgraphError("internal call edge references an unknown function")
        if edge["edge_type"] == "indirect_resolved" and int(edge.get("indirect_target_count") or 0) < 1:
            raise SemanticCallgraphError("indirect edge lacks positive target-set size")
        if edge["edge_type"] == "indirect_resolved":
            target_set = edge.get("indirect_target_set")
            if not isinstance(target_set, list) or any(not isinstance(value, str) for value in target_set):
                raise SemanticCallgraphError("indirect edge lacks a structured target set")
            if sorted(set(target_set)) != target_set:
                raise SemanticCallgraphError("indirect target set must be sorted and unique")
            if len(target_set) != int(edge["indirect_target_count"]):
                raise SemanticCallgraphError("indirect target-set cardinality is inconsistent")
            if edge["callee"] not in target_set:
                raise SemanticCallgraphError("indirect edge callee is absent from its target set")
        else:
            edge["indirect_target_count"] = None
            edge["indirect_target_set"] = None
        edge["pointer_analysis_backend"] = edge.get("pointer_analysis_backend", "SVF")
        edge["pointer_analysis"] = edge.get("pointer_analysis", POINTER_ANALYSIS)
        edges.append(edge)
    edges.sort(key=_edge_key)
    outgoing: dict[str, list[tuple[int, dict[str, Any]]]] = {identity: [] for identity in by_id}
    for index, edge in enumerate(edges):
        outgoing[edge["caller"]].append((index, edge))
    depths = {entry_id: 0}
    paths: dict[str, list[int]] = {entry_id: []}
    pending: deque[str] = deque([entry_id])
    while pending:
        caller = pending.popleft()
        for edge_index, edge in outgoing[caller]:
            callee = edge["callee"]
            candidate = [*paths[caller], edge_index]
            if callee not in depths:
                depths[callee] = depths[caller] + 1
                paths[callee] = candidate
                pending.append(callee)
    functions = []
    for identity, row in sorted(by_id.items()):
        path_edges = [edges[index] for index in paths.get(identity, [])]
        reachable = identity in depths
        functions.append({
            **row,
            "reachable_from_entry": reachable,
            "raw_call_depth": depths.get(identity),
            "semantic_status": _path_status(path_edges) if reachable else "unreachable_in_semantic_graph",
            "shortest_call_path": {
                "function_identities": [entry_id, *(edge["callee"] for edge in path_edges)] if reachable else None,
                "edges": path_edges if reachable else None,
            },
        })
    unresolved = sorted((dict(row) for row in raw.get("unresolved_indirect_callsites", [])), key=lambda row: (str(row.get("caller", "")), *_location_key(row.get("callsite"))))
    external = sorted((dict(row) for row in raw.get("external_calls", [])), key=lambda row: (str(row.get("caller", "")), str(row.get("callee_name", "")), *_location_key(row.get("callsite"))))
    provenance_row = dict(provenance or {})
    versions = _result_versions(provenance_row)
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_backend": BACKEND,
        "analysis_status": "success",
        **versions,
        "pointer_analysis": POINTER_ANALYSIS,
        "entry_point": {"configured": entry_point, "resolved_identity": entry_id},
        "source_files": list(provenance_row.get("source_files", [])),
        "build_commands": list(provenance_row.get("build_commands", [])),
        "provenance": provenance_row,
        "functions": functions,
        "call_edges": edges,
        "unresolved_indirect_callsites": unresolved,
        "external_calls": external,
        "failures": sorted((dict(row) for row in raw.get("failures", [])), key=lambda row: json.dumps(row, sort_keys=True)),
    }


def analyze_build(
    build: BuildResult, *, entry_point: str,
    inventory: Mapping[str, Any] | None = None,
    helper: str | Path | None = None,
    svf_options: Sequence[str] = SVF_HELPER_OPTIONS,
) -> dict[str, Any]:
    """Run the dedicated SVF helper or return an explicit nonnumeric status."""
    info = dict(inventory or inventory_toolchain(helper=helper))
    provenance = {
        "toolchain": info,
        "repository": _repository_state(),
        "source_files": list(build.source_files),
        "build_commands": [list(command) for command in build.build_commands],
        "bitcode_files": list(build.bitcode_files),
        "target_triple": build.target_triple,
        "historical_build_configuration": dict(build.configuration or {}),
        "svf_analysis_command": [
            "semantic-callgraph-svf", *svf_options, "$LINKED_BITCODE",
        ],
    }
    if build.status != "success" or build.linked_bitcode is None:
        return _failure_result("build_or_ir_unavailable", entry_point, provenance, list(build.diagnostics))
    helper_path = info.get("tools", {}).get("semantic-callgraph-svf", {}).get("path")
    if not helper_path:
        return _failure_result(
            "analysis_failure", entry_point, provenance,
            [{"stage": "svf", "reason": "svf_unavailable", "message": "dedicated SVF API helper is unavailable; no syntax fallback used"}],
        )
    # The dedicated helper selects AndersenWaveDiff through the SVF API; no
    # human-readable wpa mode or undocumented CLI-output parsing is involved.
    result = _run((helper_path, *svf_options, str(build.linked_bitcode)))
    if result.returncode != 0:
        return _failure_result(
            "analysis_failure", entry_point, provenance,
            [{"stage": "svf", "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}],
        )
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        return _failure_result(
            "analysis_failure", entry_point, provenance,
            [{"stage": "svf", "reason": "invalid_helper_json", "message": str(error), "stdout": result.stdout}],
        )
    return finalize_semantic_graph(raw, entry_point=entry_point, provenance=provenance)


def _failure_result(status: str, entry_point: str, provenance: Mapping[str, Any], failures: list[dict[str, Any]]) -> dict[str, Any]:
    provenance_row = dict(provenance)
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_backend": BACKEND,
        "analysis_status": status,
        **_result_versions(provenance_row),
        "pointer_analysis": POINTER_ANALYSIS,
        "entry_point": {"configured": entry_point, "resolved_identity": None},
        "source_files": list(provenance_row.get("source_files", [])),
        "build_commands": list(provenance_row.get("build_commands", [])),
        "provenance": provenance_row,
        "functions": [],
        "call_edges": [],
        "unresolved_indirect_callsites": [],
        "external_calls": [],
        "failures": failures,
    }


def stable_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _result_versions(provenance: Mapping[str, Any]) -> dict[str, str | None]:
    tools = provenance.get("toolchain", {}).get("tools", {})
    llvm = next(
        (tools.get(name, {}).get("version") for name in ("llvm-link", "llvm-dis", "opt")
         if tools.get(name, {}).get("version")),
        None,
    )
    return {
        "clang_version": tools.get("clang", {}).get("version"),
        "llvm_version": llvm,
        "svf_version": tools.get("semantic-callgraph-svf", {}).get("version"),
    }


@lru_cache(maxsize=1)
def _repository_state() -> dict[str, Any]:
    """Capture once per process; a calibration run has one repository state."""
    head = _run(("git", "rev-parse", "HEAD"))
    status = _run(("git", "status", "--short"))
    return {
        "commit": head.stdout.strip() if head.returncode == 0 else None,
        "worktree_clean": status.returncode == 0 and not status.stdout.strip(),
        "worktree_status": sorted(status.stdout.splitlines()) if status.returncode == 0 else [],
    }
