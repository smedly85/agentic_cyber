"""Compiler-semantic call graph construction and depth measurement.

This package intentionally has no Tree-sitter fallback.  Missing compiler or
SVF components produce explicit nonnumeric states.
"""

from .backend import (
    BuildResult,
    SemanticCallgraphError,
    analyze_build,
    build_bitcode,
    finalize_semantic_graph,
    inventory_toolchain,
    stable_json,
)

__all__ = [
    "BuildResult",
    "SemanticCallgraphError",
    "analyze_build",
    "build_bitcode",
    "finalize_semantic_graph",
    "inventory_toolchain",
    "stable_json",
]
