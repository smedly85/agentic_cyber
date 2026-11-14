"""Small exact three-method construct comparison; never reads historical data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analysis import ordered_distances as old
from .analysis.clang_ordered import BACKEND, comparison_tree
from .analysis.strategy_node import compare as compare_node
from .analysis.unified_distance import compare as compare_unified
from .analysis.unified_graph import extract_llvm_ir


def event(kind, children=(), *, role=None, ordering="syntax_only_no_execution_order_claim",
          token="", operator="", call_site=None):
    value = {"kind": kind, "role": role, "ordering": ordering, "token": token,
             "operator": operator, "children": list(children)}
    if call_site is not None:
        value["call_site"] = call_site
    return value


def body(*children):
    return event("CompoundStmt", children, role="body", ordering="source_statement_sequence")


def representation(main_body, *, helper_body=None, internal_call=False):
    functions = [{"id": "f0", "name": "main", "entry_point": True,
                  "structure": {"children": [main_body]}}]
    calls = []
    if helper_body is not None:
        functions.append({"id": "f1", "name": "worker", "entry_point": False,
                          "structure": {"children": [helper_body]}})
    if internal_call:
        calls.append({"id": "c0", "function": "f0", "target": "f1", "callee_name": "worker",
                      "resolution": "internal_direct"})
    return {"backend": BACKEND, "status": "success", "source_file": "controlled-synthetic.c",
            "entry_points": ["main"], "functions": functions, "call_sites": calls, "audit": []}


def literal(value):
    return event("IntegerLiteral", token=str(value))


def binding(slot):
    return event("DeclRefExpr", token=f"binding:{slot}")


def binary(operator, left, right):
    return event("BinaryOperator", (left, right), operator=operator, ordering="unsequenced_operands")


def ir_graph(ir):
    return extract_llvm_ir(ir, source_bytes=b"controlled-synthetic", source_path="controlled-synthetic.c",
                           compiler_version="hand-authored LLVM IR test double", compiler_sha256=None,
                           command=["fixture-only"])


def existing(left, right):
    budget = old.Budget(old.Limits(max_alignments=20_000, max_work=2_000_000))
    architecture_distance, mappings = old._align(left, right, budget)
    first = mappings[0]
    left_labels, right_labels = old._label_maps(left, right, first)
    left_atoms, right_atoms = old._atoms(left, left_labels), old._atoms(right, right_labels)
    evaluated = []
    for mapping in mappings:
        ll, rr = old._label_maps(left, right, mapping)
        lc = {call["id"]: call for call in left["call_sites"]}
        rc = {call["id"]: call for call in right["call_sites"]}
        lt = {function["id"]: comparison_tree(function, lc, ll) for function in left["functions"]}
        rt = {function["id"]: comparison_tree(function, rc, rr) for function in right["functions"]}
        paired = {a: b for a, b in mapping.items() if a in lt and b in rt}
        denominator = sum(old._size(tree) for tree in lt.values()) + sum(old._size(tree) for tree in rt.values())
        tree_budget = old.Budget(old.Limits(max_work=2_000_000))
        cost = sum(old._tree_distance(lt[a], rt[b], tree_budget) for a, b in paired.items())
        cost += sum(old._size(tree) for a, tree in lt.items() if a not in paired)
        cost += sum(old._size(tree) for b, tree in rt.items() if b not in paired.values())
        evaluated.append({"mapping": mapping, "raw_cost": cost, "denominator": denominator,
                          "distance": cost / denominator if denominator else 0.0})
    values = [row["distance"] for row in evaluated]
    return {"architecture": {"status": "success", "exact": True,
                              "raw_cost": len(left_atoms ^ right_atoms),
                              "denominator": len(left_atoms) + len(right_atoms),
                              "distance": architecture_distance},
            "strategy": {"status": "success", "exact": True,
                         "alignment_range": [min(values), max(values)], "evaluated_alignments": evaluated}}


def cases():
    statements = [literal(index) for index in range(8)]
    parent_left, parent_right = representation(body(*statements)), representation(body(event("IfStmt", statements)))
    calculation = binary("+", binding(0), literal(1))
    call = event("CallExpr", (event("argument_list", (binding(0),), ordering="unsequenced_arguments"),),
                 call_site="c0", ordering="callee_and_arguments_before_invocation_no_sibling_order")
    helper_left = representation(body(calculation))
    helper_right = representation(body(call), helper_body=body(calculation), internal_call=True)
    branch_left = representation(body(event("IfStmt", (binary(">", binding(0), literal(0)), calculation))))
    branch_right = representation(body(event("IfStmt", (binary(">=", binding(0), literal(0)), calculation))))
    constant_left, constant_right = representation(body(calculation)), representation(body(binary("+", binding(0), literal(9))))
    operand_left = representation(body(binary("+", binding(0), binding(1))))
    operand_right = representation(body(binary("+", binding(0), binding(0))))
    padding_left, padding_right = representation(body(calculation)), representation(body(event("NullStmt"), calculation))
    control_left = representation(body(event("IfStmt", (binary(">", binding(0), literal(0)), calculation))))
    control_right = representation(body(event("WhileStmt", (binary(">", binding(0), literal(0)), calculation),
                                              ordering="condition_body_repeat")))

    base_ir = "define i32 @main(i32 %x) {\nentry:\n %a = add i32 %x, 1\n ret i32 %a\n}"
    operations = "\n".join(f" %v{i} = add i32 %x, {i + 2}" for i in range(8))
    parent_ir_left = f"define i32 @main(i32 %x) {{\nentry:\n{operations}\n ret i32 %v7\n}}"
    parent_ir_right = f"""define i32 @main(i32 %x) {{
entry:
 %c = icmp sgt i32 %x, 0
 br i1 %c, label %body, label %exit
body:
{operations}
 br label %exit
exit:
 %r = phi i32 [ %v7, %body ], [ %x, %entry ]
 ret i32 %r
}}"""
    helper_ir = """define i32 @worker(i32 %x) {
entry:
 %a = add i32 %x, 1
 ret i32 %a
}
define i32 @main(i32 %x) {
entry:
 %r = call i32 @worker(i32 %x)
 ret i32 %r
}"""
    branch_ir = parent_ir_right.replace("icmp sgt", "icmp sge")
    operand_ir_left = "define i32 @main(i32 %x, i32 %y) {\nentry:\n %a = add i32 %x, %y\n ret i32 %a\n}"
    operand_ir_right = operand_ir_left.replace("%x, %y", "%x, %x")
    loop_ir = parent_ir_right.replace("br label %exit\nexit:", "br label %entry\nexit:")
    padded_ir = base_ir.replace("ret i32 %a", "%d = xor i32 %x, %x\n ret i32 %a")
    return [
        ("parent_insertion", parent_left, parent_right, parent_ir_left, parent_ir_right, "synthetic_shape_only"),
        ("helper_extraction", helper_left, helper_right, base_ir, helper_ir, "C_fixture_output_equivalence"),
        ("inlining", helper_right, helper_left, helper_ir, base_ir, "C_fixture_output_equivalence"),
        ("branch_change", branch_left, branch_right, parent_ir_right, branch_ir, "meaningful_change"),
        ("constant_change", constant_left, constant_right, base_ir, base_ir.replace(", 1", ", 9"), "meaningful_change"),
        ("operand_change", operand_left, operand_right, operand_ir_left, operand_ir_right, "meaningful_change"),
        ("control_flow_restructuring", control_left, control_right, parent_ir_right, loop_ir, "synthetic_not_equivalent"),
        ("semantics_preserving_padding", padding_left, padding_right, base_ir, padded_ir, "C_fixture_output_equivalence")]


def run():
    rows = []
    for name, left, right, left_ir, right_ir, functional_status in cases():
        rows.append({"case": name, "functional_status": functional_status,
                     "representation_status": "synthetic Clang-adapter structures and hand-authored LLVM IR; not compiler-backed",
                     "existing_A_S": existing(left, right),
                     "A_with_S_node": compare_node(left, right),
                     "unified_U": compare_unified(ir_graph(left_ir), ir_graph(right_ir))})
    return {"schema_version": 1, "study": "controlled_three_method_construct_comparison_v1",
            "qualification": "Normalized values are representation-specific and are not interchangeable.",
            "cases": rows}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    value = json.dumps(run(), sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(value, encoding="utf-8")
    else:
        print(value, end="")


if __name__ == "__main__":
    main()
