"""Map Rust call-graph nodes (MIR instances / RUPTA function refs) to source fns.

Both backends report monomorphised instances; the pipeline diversifies source
functions, so instances collapse onto the rs-items inventory of the crate
and a function's depth is the minimum over its instances.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from src.model import CallGraph, CGFunction

SPAN = re.compile(r"^(?P<path>.*):(?P<line>\d+):(?P<col>\d+): (?P<eline>\d+):(?P<ecol>\d+)$")


def strip_trailing_generics(name: str) -> str:
    if not name.endswith(">"):
        return name
    depth = 0
    for i in range(len(name) - 1, -1, -1):
        if name[i] == ">":
            depth += 1
        elif name[i] == "<":
            depth -= 1
            if depth == 0:
                return name[:i]
    return name


def collapse(
    backend: str,
    graph: Mapping[str, Any],
    items: list[dict[str, Any]],
    node_to_key: Callable[[dict[str, Any]], str | None],
) -> CallGraph:
    by_key = {item["key"]: item for item in items}
    depth: dict[str, int | None] = {}
    instances: dict[str, list[str]] = {}
    ident_to_key: dict[str, str] = {}
    for node in graph["functions"]:
        key = node_to_key(node)
        if key is None or key not in by_key:
            continue
        ident_to_key[node["identity"]] = key
        instances.setdefault(key, []).append(node["identity"])
        d = node.get("raw_call_depth")
        known = [x for x in (depth.get(key), d) if x is not None]
        depth[key] = min(known) if known else None
    functions = []
    for key, item in sorted(by_key.items(), key=lambda kv: (kv[1]["file"], kv[1]["line"])):
        is_entry = item["name"] == "main" and item.get("parent_kind") == "module"
        functions.append(
            CGFunction(
                id=f"{item['file']}::{item['name']}",
                name=item["name"],
                file=item["file"],
                def_line=item["line"],
                depth=0 if is_entry else depth.get(key),
                instances=tuple(sorted(instances.get(key, []))),
                is_entry=is_entry,
                is_local=True,
                attributes={"key": key, "parent_kind": item.get("parent_kind")},
            )
        )
    key_to_id = {f.attributes["key"]: f.id for f in functions}
    edges = sorted(
        {
            (key_to_id[ident_to_key[e["caller"]]], key_to_id[ident_to_key[e["callee"]]])
            for e in graph.get("call_edges", [])
            if e["caller"] in ident_to_key and e["callee"] in ident_to_key
        }
    )
    entry = next((f.id for f in functions if f.is_entry), "main")
    return CallGraph(backend, entry, functions, edges, raw=dict(graph))


def load_items(out_dir: Path) -> list[dict[str, Any]]:
    return json.loads((out_dir / "items.json").read_text())
