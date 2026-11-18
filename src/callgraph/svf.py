"""C call graph via the repository's SVF backend (Andersen, BFS from main)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.callgraph.common import CallGraphError, run_extractor
from src.model import CallGraph, CGFunction
from src.project import Project


def _clean_identity(identity: str) -> str:
    # "file.c::name#llvm=sym" -> "file.c::name"
    return identity.split("#llvm=", 1)[0]


def normalize_svf(graph: Mapping[str, Any]) -> CallGraph:
    if graph.get("analysis_status") != "success":
        raise CallGraphError(f"SVF analysis status {graph.get('analysis_status')!r}: {graph.get('failures')}")
    merged: dict[str, dict[str, Any]] = {}
    for fn in graph["functions"]:
        definition = fn.get("definition") or {}
        file = definition.get("file") or fn.get("source_file")
        name = fn["name"]
        fid = f"{file}::{name}" if file else _clean_identity(fn["identity"])
        depth = fn.get("raw_call_depth")
        row = merged.setdefault(
            fid,
            {"name": name, "file": file, "line": definition.get("line"), "depth": depth, "instances": [], "attrs": {}},
        )
        row["instances"].append(fn["identity"])
        if depth is not None and (row["depth"] is None or depth < row["depth"]):
            row["depth"] = depth
        row["attrs"] = {
            "linkage": fn.get("linkage"),
            "address_taken": bool(fn.get("address_taken")) or row["attrs"].get("address_taken", False),
            "semantic_status": fn.get("semantic_status"),
        }
    functions = [
        CGFunction(
            id=fid,
            name=row["name"],
            file=row["file"],
            def_line=row["line"],
            depth=row["depth"],
            instances=tuple(sorted(row["instances"])),
            is_entry=row["name"] == "main",
            is_local=row["file"] is not None,
            attributes=row["attrs"],
        )
        for fid, row in sorted(merged.items())
    ]
    by_identity = {inst: f.id for f in functions for inst in f.instances}
    edges = sorted(
        {(by_identity[e["caller"]], by_identity[e["callee"]]) for e in graph.get("call_edges", []) if e["caller"] in by_identity and e["callee"] in by_identity}
    )
    entry = next((f.id for f in functions if f.is_entry), "main")
    return CallGraph("svf", entry, functions, edges, raw=dict(graph))


class SVFBackend:
    name = "svf"

    def build(self, project: Project, config: Mapping[str, Any], keep_dir: Path | None = None) -> CallGraph:
        flags = []
        for flag in config["build"].get("flags", []):
            flags += ["--flag", flag]
        graph = run_extractor("svf", project, config, flags, keep_dir=keep_dir)
        return normalize_svf(graph)
