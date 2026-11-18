"""Rust call graph via RUPTA (Andersen pointer analysis; pinned nightly-2024-02-03).

The repository marks RUPTA as not ready for historical depths (missing
drop/callback edges, old compiler that rejects edition 2024). The pipeline uses it as
the default because the user chose so; failures are reported, never silently
replaced by another backend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.callgraph.common import run_extractor
from src.callgraph.rust_common import collapse, load_items, strip_trailing_generics
from src.model import CallGraph
from src.project import Project


def normalize_rupta(graph: Mapping[str, Any], items: list[dict[str, Any]], crate: str) -> CallGraph:
    by_verbose = {i["key"].lstrip(":"): i["key"] for i in items}
    prefix = f"{crate}::"

    def node_to_key(node: dict[str, Any]) -> str | None:
        name = node["identity"]
        if not name.startswith(prefix) or "{closure" in name:
            return None
        return by_verbose.get(strip_trailing_generics(name[len(prefix):]))

    return collapse("rupta", graph, items, node_to_key)


class RuptaBackend:
    name = "rupta"

    def build(self, project: Project, config: Mapping[str, Any], keep_dir: Path | None = None) -> CallGraph:
        extra = ["--pta-type", config["callgraph"].get("options", {}).get("rupta_pta_type", "ander")]
        graph, out_dir = run_extractor("rupta", project, config, extra, keep_dir=keep_dir, with_dir=True)
        return normalize_rupta(graph, load_items(out_dir), project.crate_name or "")
