"""Uniform language adapter + CLI used inside the images.

A *context* (JSON) describes the program:
  {"language": "c"|"rust", "sources": [...], "crate_root": str|null,
   "crate_name": str|null, "flags": [...], "build_cmd": str|null,
   "allow": {...}}

    python3 -m src.incontainer.lang list   --project P --context C --out F
    python3 -m src.incontainer.lang locate --project P --context C --key K --out F
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _c():
    from src.incontainer import c_lang

    return c_lang


def _rs():
    from src.incontainer import rs_lang

    return rs_lang


def describe_c(project: Path, fn) -> dict[str, Any]:
    c = _c()
    return {
        "language": "c",
        "key": f"{fn.file}::{fn.name}",
        "name": fn.name,
        "file": fn.file,
        "start": fn.start,
        "end": fn.end,
        "line": fn.line,
        "macro": fn.macro,
        "original_text": c.function_text(project, fn),
        "signature": fn.signature,
    }


def _custom(ctx: dict[str, Any]):
    module = ctx.get("lang_module")
    if not module:
        return None
    import importlib

    return importlib.import_module(module)


def list_functions(project: Path, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    custom = _custom(ctx)
    if custom is not None:
        return custom.list_functions(project, ctx)
    if ctx["language"] == "c":
        c = _c()
        return [describe_c(project, fn) for fn in c.list_definitions(project, ctx["sources"], ctx.get("flags", []))]
    return _rs().list_functions(project, ctx["crate_root"], ctx["crate_name"])


def locate(project: Path, ctx: dict[str, Any], key: str) -> dict[str, Any]:
    custom = _custom(ctx)
    if custom is not None:
        return custom.locate(project, ctx, key)
    if ctx["language"] == "c":
        file, _, name = key.rpartition("::")
        fn = _c().locate(project, ctx["sources"], ctx.get("flags", []), name, file or None)
        return describe_c(project, fn)
    return _rs().locate(project, ctx["crate_root"], ctx["crate_name"], key)


def splice(project: Path, ctx: dict[str, Any], target: dict[str, Any], edited: str):
    custom = _custom(ctx)
    if custom is not None:
        return custom.splice(project, ctx, target, edited)
    allow = ctx.get("allow", {})
    if ctx["language"] == "c":
        return _c().splice(project, ctx["sources"], ctx.get("flags", []), target, edited, allow)
    return _rs().splice(project, ctx["crate_root"], ctx["crate_name"], target, edited, allow)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("list", "locate"))
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--key")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    ctx = json.loads(args.context.read_text())
    try:
        if args.command == "list":
            data: Any = list_functions(args.project, ctx)
        else:
            data = locate(args.project, ctx, args.key)
    except Exception as exc:  # reported to the host verbatim
        args.out.write_text(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        print(exc, file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
