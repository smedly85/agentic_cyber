"""Experimental Clang adapter for the existing graph/subtree objectives.

No production analyzer or semantic security dependencies. Audit provenance never
enters tree labels. This format is deliberately distinct from Tree-sitter v1.
"""
from __future__ import annotations

from copy import deepcopy

from scripts.ordered_diversity_clang_probe import main_definitions, direct_reference, walk
from scripts.ordered_diversity_clang_repro import accept_ast
from .ordered_distances import _tree, Unavailable

BACKEND = "clang_ordered_experimental_v1"


def adapt(stdout, returncode, source):
    tree, status = accept_ast(returncode, stdout)
    result = {"backend": BACKEND, "status": status, "source_file": str(source),
              "entry_points": ["main"], "functions": [], "call_sites": [], "audit": []}
    if tree is None:
        return result
    definitions, origins = main_definitions(tree, source)
    # These Clang forms need extra child-role/active-branch decoding. Reject them
    # rather than silently dropping non-inner expressions or counting alternatives.
    for function in definitions:
        for node, _, _ in walk(function):
            if "array_filler" in node or node.get("kind") in {"GenericSelectionExpr", "GCCAsmStmt", "MSAsmStmt", "AtomicExpr"}:
                result["status"] = "unsupported_clang_form"
                result["reason"] = node.get("kind", "array_filler")
                return result
    index = {n["id"]: n for n, _, _ in walk(tree) if n.get("id")}

    def canonical(identifier):
        seen = set()
        while identifier in index and index[identifier].get("previousDecl") and identifier not in seen:
            seen.add(identifier)
            identifier = index[identifier]["previousDecl"]
        return identifier

    internal = {canonical(f["id"]): f"f{i}" for i, f in enumerate(definitions)}
    global_bindings = {n["id"]: f"global:{i}" for i, n in enumerate(
        n for n in tree.get("inner", []) if n.get("kind") == "VarDecl" and origins.get(n.get("id")) == str(source))}
    for function in definitions:
        fid = internal[canonical(function["id"])]
        bindings = dict(global_bindings)
        # Lexical declaration slots preserve repeated-reference relationships and
        # shadowing without carrying arbitrary local names or compiler pointers.
        for n, _, _ in walk(function):
            if n.get("kind") in {"ParmVarDecl", "VarDecl", "LabelStmt"}:
                identifier = n.get("declId") if n.get("kind") == "LabelStmt" else n.get("id")
                if identifier:
                    bindings.setdefault(identifier, f"binding:{len(bindings) - len(global_bindings)}")

        def event(node, role=None):
            kind = node.get("kind", "EmptySlot")
            children = node.get("inner", [])
            ordering = "syntax_only_no_execution_order_claim"
            if kind == "CompoundStmt":
                ordering = "source_statement_sequence"
            elif kind in {"IfStmt", "ConditionalOperator", "BinaryConditionalOperator"}:
                ordering = "condition_then_exclusive_branch"
            elif kind in {"WhileStmt", "ForStmt", "DoStmt"}:
                ordering = {"WhileStmt": "condition_body_repeat", "ForStmt": "initializer_condition_body_update_repeat", "DoStmt": "body_condition_repeat"}[kind]
            elif kind == "SwitchStmt":
                ordering = "condition_then_label_dispatch"
            elif kind in {"CaseStmt", "DefaultStmt"}:
                ordering = "label_with_possible_fallthrough"
            elif kind in {"BinaryOperator", "CompoundAssignOperator", "ArraySubscriptExpr"}:
                ordering = "left_before_right" if node.get("opcode") == "," else "left_then_conditional_right" if node.get("opcode") in {"&&", "||"} else "unsequenced_operands"
            elif kind == "InitListExpr":
                ordering = "indeterminately_sequenced_initializers"
            elif kind == "UnaryExprOrTypeTraitExpr":
                ordering = "unevaluated_or_vla_dependent"
            token = str(node.get("value", ""))
            if kind in {"VarDecl", "ParmVarDecl"}:
                token = bindings[node["id"]]
            elif kind == "DeclRefExpr":
                ref = node.get("referencedDecl", {})
                identifier = ref.get("id")
                if ref.get("kind") == "FunctionDecl":
                    token = "internalref:" + internal[canonical(identifier)] if canonical(identifier) in internal else "externalref:" + ref.get("name", "")
                else:
                    token = bindings.get(identifier, "declared:" + ref.get("kind", "unknown") + ":" + ref.get("name", "unknown"))
            elif kind == "MemberExpr":
                # Member spelling is retained; field-renaming invariance is not claimed.
                token = "member:" + node.get("name", "")
            elif kind in {"GotoStmt", "LabelStmt"}:
                identifier = node.get("targetLabelDeclId", node.get("declId"))
                token = bindings.get(identifier, "unresolved-label")
            elif kind == "UnaryExprOrTypeTraitExpr":
                token = node.get("name", "")
            # Retain explicit compiler conversions; no coordinate-based authorship.
            if node.get("castKind"):
                token += "|cast:" + node["castKind"]
            if node.get("isImplicit"):
                token += "|compiler-implicit"
            output = {"kind": "initializer_list" if kind == "InitListExpr" else kind,
                      "role": role, "ordering": ordering, "token": token,
                      "operator": node.get("opcode", "") + (":postfix" if node.get("isPostfix") else ""), "children": []}
            result["audit"].append({"function": fid, "kind": kind, "range": node.get("range"),
                                    "location": node.get("loc"), "isImplicit": node.get("isImplicit"),
                                    "type": node.get("type")})
            if kind == "CallExpr":
                ref = direct_reference(node)
                target = internal.get(canonical(ref["id"])) if ref else None
                cid = f"c{len(result['call_sites'])}"
                result["call_sites"].append({"id": cid, "function": fid, "target": target,
                    "callee_name": ref["name"] if ref else None,
                    "resolution": "internal_direct" if target else "external_declared" if ref else "unresolved_indirect"})
                output["call_site"] = cid
                output["ordering"] = "callee_and_arguments_before_invocation_no_sibling_order"
                # The direct callee is represented by the aligned call label;
                # argument slots are distinct from their unordered evaluation.
                output["children"] = [{"kind": "argument_list", "role": "arguments", "ordering": "unsequenced_arguments",
                                        "children": [event(n) for n in children[1:]]}]
            else:
                # Semantic child slots (including empty ForStmt slots) survive;
                # statements use their sequence, not absolute indices as labels.
                output["children"] = [event(n, None if kind in {"CompoundStmt", "InitListExpr", "DeclStmt"} else f"operand:{i}") for i, n in enumerate(children)]
            return output

        body = next(n for n in function["inner"] if n.get("kind") == "CompoundStmt")
        result["functions"].append({"id": fid, "name": function["name"], "entry_point": function["name"] == "main",
            "structure": {"children": [event(body, "body")]}})
    return result


def comparison_tree(function, calls, labels):
    copied = deepcopy(function)
    def replace(e):
        token = e.get("token", "")
        if token.startswith("internalref:"):
            e["token"] = labels[token.removeprefix("internalref:")]
        for c in e.get("children", []):
            replace(c)
    replace(copied["structure"])
    return _tree(copied, calls, labels)


def validate(result, max_events):
    if result.get("status") != "success":
        raise Unavailable("extraction_unavailable:" + result.get("status", "missing"))
    if result.get("backend") != BACKEND:
        raise Unavailable("unsupported_backend")
    if len(result.get("audit", [])) > max_events:
        raise Unavailable("event_limit")
    if any(c["resolution"].startswith("unresolved") for c in result["call_sites"]):
        raise Unavailable("unresolved_call_targets")
