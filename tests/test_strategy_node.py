from __future__ import annotations

import unittest

from scripts.analysis import ordered_distances as old
from scripts.analysis.clang_ordered import BACKEND
from scripts.analysis.strategy_node import NodeBudget, NodeLimits, compare, node_tree_edit


def label(name, slot=None):
    return (name, None, "ordered", "", "", "", slot)


def tree(name, *children, unordered=False, slot=None):
    return (label(name, slot), unordered, tuple(children))


def event(kind, children=(), *, role=None, ordering="source_statement_sequence", token="", operator=""):
    return {"kind": kind, "role": role, "ordering": ordering, "token": token,
            "operator": operator, "children": list(children)}


def representation(body, helpers=()):
    functions = [{"id": "f0", "name": "main", "entry_point": True,
                  "structure": {"children": [body]}}]
    for index, helper_body in enumerate(helpers, 1):
        functions.append({"id": f"f{index}", "name": f"worker{index}", "entry_point": False,
                          "structure": {"children": [helper_body]}})
    return {"backend": BACKEND, "status": "success", "source_file": "synthetic.c",
            "entry_points": ["main"], "functions": functions, "call_sites": [], "audit": []}


class StrategyNodeTests(unittest.TestCase):
    def test_parent_insertion_splices_without_deleting_descendants(self):
        descendants = tuple(tree(f"stmt:{index}") for index in range(8))
        left = tree("body", *descendants)
        right = tree("body", tree("if", *descendants))
        old_cost = old._tree_distance(left, right, old.Budget(old.Limits()))
        edit = node_tree_edit(left, right, NodeBudget(NodeLimits()))
        self.assertEqual(old_cost, 16)
        self.assertEqual(edit["cost"], 1)
        self.assertEqual(sum(op["status"] == "inserted" for op in edit["operations"]), 1)
        self.assertEqual(sum(op["status"] == "retained" for op in edit["operations"]), 9)

    def test_operator_and_constant_labels_remain_distinct(self):
        left = tree("body", tree("BinaryOperator:+", tree("binding:0"), tree("literal:1")))
        operator = tree("body", tree("BinaryOperator:-", tree("binding:0"), tree("literal:1")))
        constant = tree("body", tree("BinaryOperator:+", tree("binding:0"), tree("literal:9")))
        self.assertEqual(node_tree_edit(left, operator, NodeBudget(NodeLimits()))["cost"], 1)
        self.assertEqual(node_tree_edit(left, constant, NodeBudget(NodeLimits()))["cost"], 1)

    def test_unordered_frontier_uses_exact_slot_constraints(self):
        left = tree("args", tree("A", slot=("argument_list", 0)),
                    tree("B", slot=("argument_list", 1)), unordered=True)
        swapped_contents = tree("args", tree("B", slot=("argument_list", 0)),
                                tree("A", slot=("argument_list", 1)), unordered=True)
        result = node_tree_edit(left, swapped_contents, NodeBudget(NodeLimits()))
        self.assertEqual(result["cost"], 2)
        self.assertTrue(any(op.get("unordered_frontier") for op in result["operations"]))

    def test_wrapper_inside_unordered_slot_is_node_spliced(self):
        left = tree("args", tree("value", slot=("argument_list", 0)), unordered=True)
        right = tree("args", tree("wrapper", tree("value"), slot=("argument_list", 0)), unordered=True)
        self.assertEqual(node_tree_edit(left, right, NodeBudget(NodeLimits()))["cost"], 1)

    def test_high_level_reuses_exact_architecture_alignment(self):
        statements = [event("IntegerLiteral", role=None, token=str(index)) for index in range(4)]
        left_body = event("CompoundStmt", statements, role="body")
        right_body = event("CompoundStmt", [event("IfStmt", statements)], role="body")
        result = compare(representation(left_body), representation(right_body))
        self.assertEqual(result["architecture"]["status"], "success")
        self.assertEqual(result["architecture"]["distance"], 0.0)
        self.assertEqual(result["strategy_node"]["status"], "success")
        evaluated = result["strategy_node"]["evaluated_alignments"][0]
        self.assertEqual(evaluated["node_edit_cost"], 1)
        self.assertEqual(evaluated["tree_size_sum"], 11)

    def test_alignment_sensitivity_is_reported_as_a_range(self):
        main = event("CompoundStmt", [event("IntegerLiteral", token="0")], role="body")
        helper_one = event("CompoundStmt", [event("IntegerLiteral", token="1")], role="body")
        helper_two = event("CompoundStmt", [event("IntegerLiteral", token="2")], role="body")
        helper_nine = event("CompoundStmt", [event("IntegerLiteral", token="9")], role="body")
        result = compare(representation(main, (helper_one, helper_two)),
                         representation(main, (helper_one, helper_nine)))
        strategy = result["strategy_node"]
        self.assertEqual(strategy["status"], "success")
        self.assertIsNone(strategy["distance"])
        self.assertEqual(strategy["reporting"], "alignment_sensitive_range")
        self.assertLess(strategy["alignment_range"][0], strategy["alignment_range"][1])
        self.assertGreater(result["alignment"]["optimal_mapping_count"], 1)

    def test_budget_failure_is_explicit(self):
        with self.assertRaisesRegex(old.Unavailable, "strategy_node_work_limit"):
            node_tree_edit(tree("a", tree("b")), tree("a", tree("c")),
                           NodeBudget(NodeLimits(max_work=1)))


if __name__ == "__main__":
    unittest.main()
