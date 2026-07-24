"""Optional security profiles; never inputs to structural clustering."""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
from pathlib import Path
from typing import Any

from analysis.diversity_validation import _call_name, parse_source


UNSAFE_CALLS = {"strcpy", "strcat", "sprintf", "gets", "vsprintf"}
BOUNDED_RISKY_CALLS = {"strncpy", "strncat", "snprintf", "memcpy", "memmove", "stpcpy"}
HEAP_CALLS = {"malloc", "calloc", "realloc", "free", "strdup", "reallocarray"}


def security_profile(source: bytes) -> dict[str, int]:
    parsed = parse_source(source)
    counts = {
        "unsafe_call_count": 0,
        "bounded_risky_call_count": 0,
        "heap_allocation_deallocation_call_count": 0,
        "fixed_size_stack_buffer_count": 0,
        "indexing_operation_count": 0,
    }
    stack = [(parsed.root, False)]
    while stack:
        node, inside_function = stack.pop()
        inside_function = inside_function or node.type == "function_definition"
        if node.type == "call_expression":
            name = _call_name(node, parsed.data)
            if name in UNSAFE_CALLS:
                counts["unsafe_call_count"] += 1
            elif name in BOUNDED_RISKY_CALLS:
                counts["bounded_risky_call_count"] += 1
            elif name in HEAP_CALLS:
                counts["heap_allocation_deallocation_call_count"] += 1
        elif inside_function and node.type == "array_declarator":
            size = node.child_by_field_name("size")
            if size is not None and size.type in {"number_literal", "identifier"}:
                counts["fixed_size_stack_buffer_count"] += 1
        elif node.type == "subscript_expression":
            counts["indexing_operation_count"] += 1
        stack.extend((child, inside_function) for child in reversed(node.children))
    return counts


def flawfinder_crosscheck(path: Path) -> dict[str, Any]:
    executable = shutil.which("flawfinder")
    if executable is None:
        return {"status": "unavailable", "reason": "flawfinder not found", "hits": []}
    try:
        result = subprocess.run(
            [executable, "--csv", "--dataonly", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "reason": str(exc), "hits": []}
    if result.returncode not in {0, 1}:
        return {
            "status": "unavailable",
            "reason": result.stderr.strip() or f"exit status {result.returncode}",
            "hits": [],
        }
    return {
        "status": "available",
        "reason": None,
        "hits": list(csv.DictReader(io.StringIO(result.stdout))),
    }
