"""Conservative C call-graph reachability and structural selection helpers.

The graph records directly named calls and explicitly supported, statically
identifiable callback arguments. Other function-pointer dispatch,
preprocessor-generated calls, and calls hidden in unavailable translation
units remain unresolved rather than being guessed.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter, deque
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

CALL_GRAPH_SCHEMA_VERSION = 2
SELECTION_POLICIES = ("SHALLOW", "RANDOM", "DEEP")
KNOWN_CALLBACK_ARGUMENTS = {"qsort": -1}
SENSITIVE_CALL_CATEGORIES = {
    "allocation": {"malloc", "calloc", "realloc", "reallocarray", "free", "strdup"},
    "buffer": {
        "memcpy", "memmove", "memset", "strcpy", "strncpy", "strcat",
        "strncat", "sprintf", "snprintf", "gets", "getline", "getdelim",
    },
    "filesystem": {
        "open", "openat", "fopen", "freopen", "mkdir", "mkdirat", "chmod",
        "fchmod", "fchmodat", "stat", "lstat", "fstat", "opendir", "readdir",
        "unlink", "remove", "rename", "symlink", "readlink", "realpath",
    },
    "numeric_conversion": {"atoi", "atol", "strtol", "strtoul", "strtoll", "strtoull"},
    "comparison": {"qsort", "bsearch"},
    "environment": {"getenv", "secure_getenv"},
}

_CALL_PATTERN = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_FUNCTION_PATTERN = re.compile(
    r"(?m)^\s*(?:static\s+)?(?:inline\s+)?(?:[A-Za-z_]\w*[\s*]+)+"
    r"([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{"
)


def _identifier(node: Any, data: bytes) -> str | None:
    if node is None:
        return None
    if node.type == "identifier":
        return data[node.start_byte:node.end_byte].decode("utf-8", "replace")
    child = node.child_by_field_name("declarator")
    return _identifier(child, data) if child is not None else None


def _callback_identifier(node: Any, data: bytes) -> str | None:
    """Resolve only a bare identifier, optionally wrapped in parentheses/&."""
    if node.type == "identifier":
        return data[node.start_byte:node.end_byte].decode("utf-8", "replace")
    if node.type in {"parenthesized_expression", "pointer_expression"}:
        named = list(node.named_children)
        if len(named) == 1:
            return _callback_identifier(named[0], data)
    return None


def _regex_callback_uses(body: str) -> list[dict[str, str]]:
    uses: list[dict[str, str]] = []
    for api, argument_index in KNOWN_CALLBACK_ARGUMENTS.items():
        for match in re.finditer(rf"\b{re.escape(api)}\s*\(", body):
            cursor = match.end()
            depth = 1
            quote: str | None = None
            escaped = False
            while cursor < len(body) and depth:
                character = body[cursor]
                if quote is not None:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == quote:
                        quote = None
                elif character in {'"', "'"}:
                    quote = character
                elif character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                cursor += 1
            if depth:
                continue
            arguments_text = body[match.end():cursor - 1]
            arguments: list[str] = []
            start = 0
            nested = 0
            for index, character in enumerate(arguments_text):
                nested += (character == "(") - (character == ")")
                if character == "," and nested == 0:
                    arguments.append(arguments_text[start:index])
                    start = index + 1
            arguments.append(arguments_text[start:])
            try:
                argument = arguments[argument_index]
            except IndexError:
                continue
            identifier = re.fullmatch(
                r"\s*&?\s*\(*\s*([A-Za-z_]\w*)\s*\)*\s*", argument
            )
            if identifier:
                uses.append({"api": api, "target_text": identifier.group(1)})
    return uses


def _tree_sitter_definitions(data: bytes, source_file: str) -> list[dict[str, Any]]:
    from scripts.analysis.diversity_validation import _call_name, iter_nodes, parse_source

    parsed = parse_source(data)
    definitions: list[dict[str, Any]] = []
    for node in iter_nodes(parsed.root):
        if node.type != "function_definition":
            continue
        declarator = node.child_by_field_name("declarator")
        body = node.child_by_field_name("body")
        name = _identifier(declarator, parsed.data)
        if not name or body is None:
            continue
        body_text = parsed.data[body.start_byte:body.end_byte].decode("utf-8", "replace")
        calls: set[str] = set()
        callback_calls: list[dict[str, str]] = []
        for child in iter_nodes(body):
            if child.type != "call_expression":
                continue
            call = _call_name(child, parsed.data)
            if not call:
                continue
            calls.add(call)
            if call not in KNOWN_CALLBACK_ARGUMENTS:
                continue
            arguments = child.child_by_field_name("arguments")
            named_arguments = list(arguments.named_children) if arguments is not None else []
            try:
                argument = named_arguments[KNOWN_CALLBACK_ARGUMENTS[call]]
            except IndexError:
                continue
            target = _callback_identifier(argument, parsed.data)
            if target:
                callback_calls.append({"api": call, "target_text": target})
        definitions.append({
            "function": name,
            "source_file": source_file,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "lines_of_code": node.end_point[0] - node.start_point[0] + 1,
            "ast_node_count": sum(1 for child in iter_nodes(node) if child.is_named),
            "body": body_text,
            "calls": calls,
            "callback_calls": callback_calls,
        })
    return definitions


def _regex_definitions(data: bytes, source_file: str) -> list[dict[str, Any]]:
    text = data.decode("utf-8", "replace")
    definitions: list[dict[str, Any]] = []
    for match in _FUNCTION_PATTERN.finditer(text):
        depth = 1
        cursor = match.end()
        while cursor < len(text) and depth:
            depth += (text[cursor] == "{") - (text[cursor] == "}")
            cursor += 1
        body = text[match.end():max(match.end(), cursor - 1)]
        start_line = text.count("\n", 0, match.start()) + 1
        end_line = text.count("\n", 0, cursor) + 1
        definitions.append({
            "function": match.group(1),
            "source_file": source_file,
            "start_line": start_line,
            "end_line": end_line,
            "lines_of_code": end_line - start_line + 1,
            "ast_node_count": None,
            "body": body,
            "calls": set(_CALL_PATTERN.findall(body)),
            "callback_calls": _regex_callback_uses(body),
        })
    return definitions


def _definitions(data: bytes, source_file: str, force_fallback: bool) -> tuple[list[dict[str, Any]], str]:
    if not force_fallback:
        try:
            return _tree_sitter_definitions(data, source_file), "tree_sitter"
        except Exception:
            pass
    return _regex_definitions(data, source_file), "regex_fallback"


def analyze_sources(
    sources: Iterable[tuple[str, bytes]], *, entry_points: Iterable[str] = ("main",),
    force_fallback: bool = False,
) -> dict[str, Any]:
    """Analyze one or more C translation units without inventing indirect edges."""
    source_items = [(str(source_file), data) for source_file, data in sources]
    definitions: list[dict[str, Any]] = []
    methods: set[str] = set()
    for source_file, data in source_items:
        parsed, method = _definitions(data, source_file, force_fallback)
        definitions.extend(parsed)
        methods.add(method)
    method = next(iter(methods)) if len(methods) == 1 else "mixed"

    name_counts = Counter(item["function"] for item in definitions)
    file_name_counts = Counter((item["source_file"], item["function"]) for item in definitions)
    for item in definitions:
        name = item["function"]
        item["function_id"] = (
            name if name_counts[name] == 1
            else f"{item['source_file']}::{name}"
            if file_name_counts[(item["source_file"], name)] == 1
            else f"{item['source_file']}:{item['start_line']}::{name}"
        )
    by_id = {item["function_id"]: item for item in definitions}
    unique_by_name = {
        item["function"]: item["function_id"]
        for item in definitions if name_counts[item["function"]] == 1
    }
    local_by_name = {
        (item["source_file"], item["function"]): item["function_id"]
        for item in definitions
        if file_name_counts[(item["source_file"], item["function"])] == 1
    }

    direct_graph: dict[str, set[str]] = {identifier: set() for identifier in by_id}
    callback_graph: dict[str, set[str]] = {identifier: set() for identifier in by_id}
    unresolved: list[dict[str, str]] = []
    unresolved_callbacks: list[dict[str, str]] = []

    def resolve_target(called: str, source_file: str) -> str | None:
        target = unique_by_name.get(called)
        if target is None and name_counts[called] > 1:
            target = local_by_name.get((source_file, called))
        return target

    for identifier, item in by_id.items():
        for called in item["calls"]:
            target = resolve_target(called, item["source_file"])
            if target is not None:
                direct_graph[identifier].add(target)
            elif name_counts[called] == 0:
                unresolved.append({"caller": identifier, "callee_text": called})
        for callback in item["callback_calls"]:
            called = callback["target_text"]
            # Callback edges require a globally unique defined target. Unlike
            # direct calls, do not use same-file proximity as a linkage guess.
            target = unique_by_name.get(called)
            if target is not None:
                callback_graph[identifier].add(target)
            else:
                unresolved_callbacks.append({
                    "caller": identifier,
                    "api": callback["api"],
                    "target_text": called,
                    "reason": "ambiguous_target" if name_counts[called] > 1 else "target_not_found",
                })

    graph = {
        identifier: direct_graph[identifier] | callback_graph[identifier]
        for identifier in by_id
    }

    configured_entries = list(dict.fromkeys(str(item) for item in entry_points))
    entry_ids: list[str] = []
    entry_point_resolutions: list[dict[str, Any]] = []
    for specification in configured_entries:
        if "::" in specification:
            source_file, function = specification.rsplit("::", 1)
            matches = [
                identifier for identifier, item in by_id.items()
                if item["source_file"] == source_file and item["function"] == function
            ]
            qualified = True
        else:
            source_file, function = None, specification
            matches = [
                identifier for identifier, item in by_id.items()
                if item["function"] == function
            ]
            qualified = False
        status = "not_found" if not matches else (
            "ambiguous" if qualified and len(matches) > 1 else "resolved"
        )
        resolved = sorted(matches) if status == "resolved" else []
        entry_ids.extend(resolved)
        entry_point_resolutions.append({
            "entry_point": specification,
            "source_file": source_file,
            "function": function,
            "source_qualified": qualified,
            "status": status,
            "matching_function_ids": sorted(matches),
            "resolved_function_ids": resolved,
        })
    entry_ids = list(dict.fromkeys(entry_ids))
    depths: dict[str, int] = {}
    pending: deque[tuple[str, int]] = deque((identifier, 0) for identifier in sorted(entry_ids))
    while pending:
        identifier, depth = pending.popleft()
        if identifier in depths and depths[identifier] <= depth:
            continue
        depths[identifier] = depth
        pending.extend((callee, depth + 1) for callee in sorted(graph[identifier]))

    direct_callers: dict[str, set[str]] = {identifier: set() for identifier in by_id}
    callback_callers: dict[str, set[str]] = {identifier: set() for identifier in by_id}
    for caller, callees in direct_graph.items():
        for callee in callees:
            direct_callers[callee].add(caller)
    for caller, callees in callback_graph.items():
        for callee in callees:
            callback_callers[callee].add(caller)

    ordered_reachable = sorted(
        depths, key=lambda identifier: (depths[identifier], identifier)
    )
    ordered_eligible = [identifier for identifier in ordered_reachable if identifier not in entry_ids]
    ranks = {identifier: index + 1 for index, identifier in enumerate(ordered_eligible)}
    functions: list[dict[str, Any]] = []
    for identifier, item in sorted(by_id.items(), key=lambda pair: pair[0]):
        functions.append({
            "function": item["function"],
            "function_id": identifier,
            "source_file": item["source_file"],
            "start_line": item["start_line"],
            "end_line": item["end_line"],
            "lines_of_code": item["lines_of_code"],
            "ast_node_count": item["ast_node_count"],
            "call_depth": depths.get(identifier),
            "reachable_from_entry": identifier in depths,
            "diversification_eligible": identifier in depths and identifier not in entry_ids,
            "callers": sorted(direct_callers[identifier] | callback_callers[identifier]),
            "callees": sorted(graph[identifier]),
            "direct_callers": sorted(direct_callers[identifier]),
            "direct_callees": sorted(direct_graph[identifier]),
            "callback_callers": sorted(callback_callers[identifier]),
            "callback_callees": sorted(callback_graph[identifier]),
            "outgoing_call_edges": [
                *({"target": target, "edge_type": "direct_call"} for target in sorted(direct_graph[identifier])),
                *({"target": target, "edge_type": "callback"} for target in sorted(callback_graph[identifier])),
            ],
            "analysis_method": method,
            "diversification_rank": ranks.get(identifier),
        })

    by_depth: dict[str, list[str]] = {}
    for identifier in ordered_reachable:
        by_depth.setdefault(str(depths[identifier]), []).append(identifier)
    sensitive_names = {
        call: category
        for category, calls in SENSITIVE_CALL_CATEGORIES.items()
        for call in calls
    }
    sinks: list[dict[str, Any]] = []
    for identifier in ordered_reachable:
        item = by_id[identifier]
        for call in sorted(item["calls"] & sensitive_names.keys()):
            sinks.append({"function": identifier, "call": call, "category": sensitive_names[call]})
        if identifier in graph[identifier]:
            sinks.append({"function": identifier, "call": item["function"], "category": "recursive_traversal"})
        if "[" in item["body"]:
            sinks.append({"function": identifier, "call": "[]", "category": "array_or_buffer_access"})

    reachable_count = len(depths)
    return {
        "schema_version": CALL_GRAPH_SCHEMA_VERSION,
        "analysis_method": method,
        "analyzed_source_files": sorted({item[0] for item in source_items}),
        "entry_points": configured_entries,
        "resolved_entry_points": sorted(entry_ids),
        "entry_point_resolutions": entry_point_resolutions,
        "function_reachability": functions,
        "reachable_function_count": reachable_count,
        "diversification_eligible_function_count": len(ordered_eligible),
        "unreachable_function_count": len(functions) - reachable_count,
        "max_reachable_call_depth": max(depths.values()) if depths else None,
        "functions_by_call_depth": by_depth,
        "call_depth_ranking": ordered_reachable,
        "structural_exposure_ranking": ordered_eligible,
        "security_sensitive_calls": sinks,
        "unresolved_direct_calls": sorted(unresolved, key=lambda item: (item["caller"], item["callee_text"])),
        "unresolved_callback_targets": sorted(
            unresolved_callbacks,
            key=lambda item: (item["caller"], item["api"], item["target_text"]),
        ),
    }


def analyze_source_bytes(
    source: bytes | str, *, source_file: str = "candidate.c",
    entry_points: Iterable[str] = ("main",), force_fallback: bool = False,
) -> dict[str, Any]:
    data = source.encode() if isinstance(source, str) else source
    return analyze_sources([(source_file, data)], entry_points=entry_points, force_fallback=force_fallback)


def analyze_source_file(
    source: Path, *, entry_points: Iterable[str] = ("main",), force_fallback: bool = False,
) -> dict[str, Any]:
    return analyze_sources(
        [(source.name, source.read_bytes())],
        entry_points=entry_points,
        force_fallback=force_fallback,
    )


def analyze_source_tree(
    source_tree: Path, *, entry_points: Iterable[str] = ("main",), force_fallback: bool = False,
    source_files: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    root = source_tree.resolve()
    if source_files is None:
        files = sorted(path for path in root.rglob("*.c") if path.is_file())
    else:
        scoped: dict[str, Path] = {}
        for value in source_files:
            text = str(value).replace("\\", "/")
            relative = PurePosixPath(text)
            if (
                not text or relative.is_absolute() or ".." in relative.parts
                or PureWindowsPath(text).drive
            ):
                raise ValueError(f"source file must be a safe relative path: {value}")
            candidate = root.joinpath(*relative.parts).resolve()
            try:
                normalized = candidate.relative_to(root).as_posix()
            except ValueError as error:
                raise ValueError(f"source file escapes source tree: {value}") from error
            if not candidate.is_file() or candidate.suffix.lower() != ".c":
                raise ValueError(f"source file is not an existing C file: {value}")
            scoped[normalized] = candidate
        files = [scoped[name] for name in sorted(scoped)]
    return analyze_sources(
        [(path.relative_to(root).as_posix(), path.read_bytes()) for path in files],
        entry_points=entry_points,
        force_fallback=force_fallback,
    )


def selection_size(reachable_count: int, *, k: int | None = None, percent: float | None = None) -> int:
    if (k is None) == (percent is None):
        raise ValueError("specify exactly one of k or percent")
    if k is not None:
        if k < 0:
            raise ValueError("k must be non-negative")
        return min(k, reachable_count)
    assert percent is not None
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return min(reachable_count, math.ceil(reachable_count * percent / 100.0))


def select_functions(
    analysis: Mapping[str, Any], *, policy: str, k: int | None = None,
    percent: float | None = None, seed: int = 1,
    include_entry_points: bool = False,
) -> dict[str, Any]:
    """Select an equal function-count budget using a structural policy."""
    normalized_policy = policy.upper()
    if normalized_policy not in SELECTION_POLICIES:
        raise ValueError(f"unknown selection policy: {policy}")
    entry_points = set(analysis.get("resolved_entry_points", []))
    eligible = [
        dict(item) for item in analysis.get("function_reachability", [])
        if item.get("reachable_from_entry") is True and isinstance(item.get("call_depth"), int)
        and (include_entry_points or item.get("function_id") not in entry_points)
    ]
    count = selection_size(len(eligible), k=k, percent=percent)
    shallow = sorted(eligible, key=lambda item: (item["call_depth"], item["function_id"]))
    if normalized_policy == "SHALLOW":
        selected = shallow[:count]
    elif normalized_policy == "DEEP":
        selected = sorted(eligible, key=lambda item: (-item["call_depth"], item["function_id"]))[:count]
    else:
        selected = random.Random(seed).sample(sorted(eligible, key=lambda item: item["function_id"]), count)

    selected_lines = sum(int(item.get("lines_of_code") or 0) for item in selected)
    reachable_lines = sum(int(item.get("lines_of_code") or 0) for item in eligible)
    ast_values = [item.get("ast_node_count") for item in selected]
    selected_ast = (
        sum(int(value) for value in ast_values)
        if all(isinstance(value, int) for value in ast_values) else None
    )
    return {
        "selection_policy": normalized_policy,
        "selection_seed": seed if normalized_policy == "RANDOM" else None,
        "include_entry_points": include_entry_points,
        "selection_budget": {"k": k, "percent": percent},
        "selection_budget_unit": "function_count",
        "selection_universe_function_count": len(eligible),
        "selected_functions": [item["function_id"] for item in selected],
        "selected_function_count": len(selected),
        "selected_depths": {item["function_id"]: item["call_depth"] for item in selected},
        "selected_lines_of_code": selected_lines,
        "selected_ast_node_count": selected_ast,
        "selected_fraction_of_functions": len(selected) / len(eligible) if eligible else 0.0,
        "selected_fraction_of_lines": selected_lines / reachable_lines if reachable_lines else None,
    }


def reachability_report(analysis: Mapping[str, Any], *, top: int = 5) -> dict[str, Any]:
    """Compact per-candidate report; missing reachability is never inferred."""
    count = min(max(top, 0), int(analysis.get("diversification_eligible_function_count") or 0))
    shallow = select_functions(analysis, policy="SHALLOW", k=count)
    deep = select_functions(analysis, policy="DEEP", k=count)
    return {
        "reachable_function_count": analysis.get("reachable_function_count"),
        "diversification_eligible_function_count": analysis.get("diversification_eligible_function_count"),
        "unreachable_function_count": analysis.get("unreachable_function_count"),
        "max_reachable_call_depth": analysis.get("max_reachable_call_depth"),
        "functions_by_call_depth": analysis.get("functions_by_call_depth", {}),
        "top_shallow_functions": shallow["selected_functions"],
        "top_deep_functions": deep["selected_functions"],
        "top_list_limit": top,
    }
