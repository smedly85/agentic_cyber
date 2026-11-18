"""Rust call graph via the repository's lightweight compiler-resolved MIR graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.callgraph.common import run_extractor
from src.callgraph.rust_common import SPAN, collapse, load_items
from src.model import CallGraph
from src.project import Project


def normalize_mir(graph: Mapping[str, Any], items: list[dict[str, Any]], crate: str) -> CallGraph:
    by_place = {(i["file"], i["line"]): i["key"] for i in items}

    def node_to_key(node: dict[str, Any]) -> str | None:
        if node.get("crate") != crate or node.get("compiler_generated"):
            return None
        if "{closure" in str(node.get("source_identity", "")):
            return None
        span = (node.get("definition") or {}).get("source_span") or ""
        match = SPAN.match(span)
        if not match:
            return None
        path = match["path"]
        for prefix in ("/work/project/", "./"):
            if path.startswith(prefix):
                path = path[len(prefix):]
        return by_place.get((path, int(match["line"])))

    return collapse("mir", graph, items, node_to_key)


class MirBackend:
    name = "mir"

    def build(self, project: Project, config: Mapping[str, Any], keep_dir: Path | None = None) -> CallGraph:
        graph, out_dir = run_extractor("mir", project, config, keep_dir=keep_dir, with_dir=True)
        return normalize_mir(graph, load_items(out_dir), project.crate_name or "")
