"""Plugin registry.

A plugin reference is either a built-in short name registered here, or a
dotted import path "package.module:Attribute". Built-ins are lazy so that
optional heavy dependencies are only imported when selected.
"""

from __future__ import annotations

import importlib
from typing import Any

BUILTINS: dict[str, dict[str, str]] = {
    "callgraph": {
        "svf": "src.callgraph.svf:SVFBackend",
        "rupta": "src.callgraph.rupta:RuptaBackend",
        "mir": "src.callgraph.mir:MirBackend",
    },
    "selector": {
        "depth": "src.select:DepthSelector",
    },
    "generator": {
        "minisweagent": "src.agents.minisweagent:MiniSweAgentGenerator",
    },
    "test_runner": {
        "suite": "src.suite:SuiteRunner",
    },
    "feedback": {
        "summary": "src.suite:SummaryFormatter",
    },
}


class PluginError(LookupError):
    pass


def kinds() -> tuple[str, ...]:
    return tuple(BUILTINS)


def register(kind: str, name: str, target: str) -> None:
    if ":" not in target:
        raise PluginError(f"target must be 'module:attr', got {target!r}")
    BUILTINS.setdefault(kind, {})[name] = target


def _import(target: str) -> Any:
    module_name, _, attr = target.partition(":")
    if not module_name or not attr:
        raise PluginError(f"invalid plugin path {target!r}; expected 'module:attr'")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise PluginError(f"cannot import {module_name!r}: {exc}") from exc
    obj: Any = module
    for part in attr.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError as exc:
            raise PluginError(f"{module_name!r} has no attribute {attr!r}") from exc
    return obj


def resolve(kind: str, ref: str) -> Any:
    """Return the plugin object (usually a class) for `ref`."""
    if not isinstance(ref, str) or not ref:
        raise PluginError(f"empty {kind} plugin reference")
    if ":" in ref:
        return _import(ref)
    table = BUILTINS.get(kind)
    if table is None:
        raise PluginError(f"unknown plugin kind {kind!r}")
    if ref not in table:
        raise PluginError(f"unknown {kind} plugin {ref!r}; built-ins: {sorted(table)}")
    return _import(table[ref])
