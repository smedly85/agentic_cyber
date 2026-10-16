"""Phase-1 syntax-derived C structure; NOT a semantic may-call/depth backend.

Run: python -m scripts.analysis.ordered_callgraph candidate.c
Only the lightweight validation parser is reused. No evaluator or metric imports.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from .diversity_validation import iter_nodes, parse_source

SCHEMA_VERSION = 1
BACKEND = "tree_sitter_c_syntax_exploratory"


def _identifier(node: Any, data: bytes) -> tuple[str | None, str | None]:
    """Follow declarator fields, never mistake a parameter for the name.

    The wrapper nearest the identifier distinguishes f() from (*fp)().
    """
    parent = None
    while node is not None:
        if node.type == "identifier":
            return data[node.start_byte:node.end_byte].decode("utf-8"), parent
        parent = node.type
        child = node.child_by_field_name("declarator")
        if child is None and node.type == "parenthesized_declarator":
            child = next((n for n in node.named_children if n.type != "comment"), None)
        node = child
    return None, None


def _location(node: Any) -> dict[str, Any]:
    return {
        "start_byte": node.start_byte, "end_byte": node.end_byte,
        "start": [node.start_point[0] + 1, node.start_point[1]],
        "end": [node.end_point[0] + 1, node.end_point[1]],
    }


def _ordering(kind: str, operator: str | None) -> str:
    return {
        "compound_statement": "source_statement_sequence",
        "if_statement": "condition_then_exclusive_branch",
        "conditional_expression": "condition_then_exclusive_branch",
        "else_clause": "alternative_branch",
        "while_statement": "condition_body_repeat",
        "do_statement": "body_condition_repeat",
        "for_statement": "initializer_condition_body_update_repeat",
        "switch_statement": "condition_then_label_dispatch",
        "case_statement": "label_with_possible_fallthrough",
        "call_expression": "callee_and_arguments_before_invocation_no_sibling_order",
        "argument_list": "unsequenced_arguments",
        "comma_expression": "left_before_right",
        "binary_expression": (
            "left_then_conditional_right" if operator in {"&&", "||"}
            else "unsequenced_operands"
        ),
        "assignment_expression": "unsequenced_operands",
        "initializer_list": "indeterminately_sequenced_initializers",
        "sizeof_expression": "unevaluated_or_vla_dependent",
        "alignof_expression": "unevaluated",
        "generic_expression": "generic_selection_unresolved",
    }.get(kind, "syntax_only_no_execution_order_claim")


def analyze_source_bytes(
    source: bytes | str, *, source_file: str = "candidate.c",
    entry_points: Iterable[str] = ("main",),
) -> dict[str, Any]:
    """Extract one unpreprocessed C translation unit, failing closed on errors.

    A success means syntax extraction, not compilation or complete call resolution.
    Arrays always use source traversal order, never implied execution order.
    """
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "backend": BACKEND,
        "status": "success", "source_file": source_file,
        "entry_points": sorted(set(entry_points)), "functions": [],
        "call_sites": [], "direct_edges": [], "unresolved_calls": [],
        "diagnostics": [],
    }

    def fail(status: str, message: str) -> dict[str, Any]:
        result.update(status=status, diagnostics=[message])
        return result

    if Path(source_file).suffix.lower() != ".c":
        return fail("unsupported_language", "Only .c translation units are supported")
    try:
        data = source.encode("utf-8") if isinstance(source, str) else source
        data.decode("utf-8")
        parsed = parse_source(data)
    except ImportError:
        return fail("dependency_unavailable", "tree-sitter and tree-sitter-c are required")
    except UnicodeError:
        return fail("invalid_encoding", "Source must be UTF-8")
    except Exception as exc:
        return fail("parser_failure", f"Parser failed: {type(exc).__name__}")
    nodes = list(iter_nodes(parsed.root))
    if parsed.root.has_error or any(n.is_missing or n.type == "ERROR" for n in nodes):
        return fail("malformed_input", "Tree-sitter reports ERROR or missing syntax")
    if any(n.type.startswith("preproc_") and n.type != "preproc_include" for n in nodes):
        return fail("unsupported_input", "Macro definitions/conditional preprocessing require a future policy")
    if any(
        n.type in {"sizeof_expression", "alignof_expression"}
        and n.child_by_field_name("type") is not None
        and any(c.type == "abstract_function_declarator" for c in iter_nodes(n))
        for n in nodes
    ):
        return fail("unsupported_input", "Ambiguous function-type versus call syntax in size/alignment operand")
    definitions = [n for n in nodes if n.type == "function_definition"]
    if any(
        any(child.type == "function_definition" for child in iter_nodes(n) if child != n)
        for n in definitions
    ):
        return fail("unsupported_input", "Nested function definitions require a future scope policy")
    if any(
        n.type == "call_expression"
        and not any(f.start_byte <= n.start_byte < f.end_byte for f in definitions)
        for n in nodes
    ):
        return fail("unsupported_input", "Call syntax outside function definitions is not in the extraction scope")
    names = [_identifier(n.child_by_field_name("declarator"), data)[0] for n in definitions]
    if any(name is None for name in names) or len(set(names)) != len(names):
        return fail("unsupported_input", "Missing or duplicate function identity")
    by_name = {name: f"f{i}:{name}" for i, name in enumerate(names)}

    # Conservative object-name exclusion: any local/parameter binding anywhere in
    # a function suppresses resolution for that name throughout that function.
    # This can under-resolve calls but never guesses a function-pointer target.
    def bindings(root: Any) -> tuple[set[str], set[str]]:
        objects, prototypes = set(), set()
        for n in iter_nodes(root):
            if n.type not in {"declaration", "parameter_declaration"}:
                continue
            for i, child in enumerate(n.children):
                if n.field_name_for_child(i) != "declarator":
                    continue
                name, wrapper = _identifier(child, data)
                if name:
                    target = prototypes if wrapper == "function_declarator" and n.type != "parameter_declaration" else objects
                    target.add(name)
        return objects, prototypes

    global_objects, global_prototypes = set(), set()
    for child in parsed.root.named_children:
        if child.type == "declaration":
            objects, prototypes = bindings(child)
            global_objects.update(objects)
            global_prototypes.update(prototypes)
    for definition, name in zip(definitions, names):
        function_id = by_name[name]
        objects, prototypes = bindings(definition)
        objects |= global_objects
        prototypes |= global_prototypes
        event_counter = 0

        def event(node: Any, role: str | None = None) -> dict[str, Any]:
            nonlocal event_counter
            event_id = f"{function_id}/e{event_counter}"
            event_counter += 1
            op_node = node.child_by_field_name("operator")
            operator = data[op_node.start_byte:op_node.end_byte].decode() if op_node else None
            row: dict[str, Any] = {
                "id": event_id, "kind": node.type, "role": role,
                "ordering": _ordering(node.type, operator),
                "location": _location(node), "children": [],
            }
            if operator is not None:
                row["operator"] = operator
            if node.child_count == 0 and node.type != "comment":
                row["token"] = data[node.start_byte:node.end_byte].decode()
            if node.type == "call_expression":
                callee = node.child_by_field_name("function")
                # Parentheses around a bare identifier do not change its identity.
                while callee is not None and callee.type == "parenthesized_expression":
                    callee = next((c for c in callee.named_children if c.type != "comment"), None)
                called = data[callee.start_byte:callee.end_byte].decode() if callee is not None and callee.type == "identifier" else None
                target = None
                if called is None or called in objects:
                    resolution = "unresolved_indirect"
                elif called in by_name:
                    resolution, target = "internal_direct", by_name[called]
                elif called in prototypes:
                    resolution = "external_declared"
                else:
                    resolution = "unresolved_name"
                call_id = f"c{len(result['call_sites'])}"
                row["call_site"] = call_id
                call = {
                    "id": call_id, "function": function_id, "event": event_id,
                    "callee_name": called, "target": target, "resolution": resolution,
                    "location": _location(node),
                }
                result["call_sites"].append(call)
                if resolution in {"internal_direct", "external_declared"}:
                    result["direct_edges"].append({
                        "caller": function_id, "target": target,
                        "callee_name": called, "call_site": call_id,
                    })
                else:
                    result["unresolved_calls"].append(call_id)
            row["children"] = [
                event(child, node.field_name_for_child(i))
                for i, child in enumerate(node.children)
                if child.is_named and child.type != "comment"
            ]
            return row

        result["functions"].append({
            "id": function_id, "name": name,
            "entry_point": name in result["entry_points"],
            "location": _location(definition), "structure": event(definition),
        })
    return result


def normalized_structure(result: dict[str, Any]) -> dict[str, Any]:
    """Audit-free projection for fixture equality ONLY; no name/graph matching.

    Failed measurements must not compare equal as empty software structures.
    """
    if result["status"] != "success":
        raise ValueError("Cannot normalize an unsuccessful extraction")

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in {"location", "source_file", "diagnostics"}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return clean(result)


def stable_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        data = args.source.read_bytes()
    except OSError as exc:
        result = analyze_source_bytes(b"", source_file=str(args.source))
        result.update(status="io_error", diagnostics=[f"Cannot read source: {type(exc).__name__}"])
    else:
        result = analyze_source_bytes(data, source_file=str(args.source))
    print(stable_json(result), end="")
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
