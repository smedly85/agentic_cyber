from __future__ import annotations

import unittest

from scripts.unified_controlled_comparison import run


class ControlledComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run()
        cls.rows = {row["case"]: row for row in cls.result["cases"]}

    def test_all_three_methods_return_structured_results(self):
        self.assertEqual(len(self.rows), 8)
        for row in self.rows.values():
            self.assertEqual(row["existing_A_S"]["architecture"]["status"], "success")
            self.assertEqual(row["existing_A_S"]["strategy"]["status"], "success")
            self.assertEqual(row["A_with_S_node"]["strategy_node"]["status"], "success")
            self.assertEqual(row["unified_U"]["status"], "success")

    def test_parent_raw_costs_expose_amplification(self):
        row = self.rows["parent_insertion"]
        self.assertEqual(row["existing_A_S"]["strategy"]["evaluated_alignments"][0]["raw_cost"], 16)
        self.assertEqual(row["A_with_S_node"]["strategy_node"]["evaluated_alignments"][0]["node_edit_cost"], 1)
        self.assertEqual(row["unified_U"]["components"], {"node": 3, "edge": 5, "content": 5})

    def test_collision_regressions_are_nonzero_in_U(self):
        for name in ("constant_change", "operand_change", "branch_change"):
            self.assertGreater(self.rows[name]["unified_U"]["distance"], 0.0)

    def test_helper_extraction_uses_unary_argument_splicing(self):
        for name in ("helper_extraction", "inlining"):
            row = self.rows[name]
            self.assertEqual(row["existing_A_S"]["strategy"]["evaluated_alignments"][0]["raw_cost"], 8)
            evaluated = row["A_with_S_node"]["strategy_node"]["evaluated_alignments"][0]
            self.assertEqual(evaluated["node_edit_cost"], 7)
            main = next(edit for edit in evaluated["function_edits"] if edit["left"] is not None)
            self.assertTrue(any(op.get("unary_unordered_splice") for op in main["operations"]))


if __name__ == "__main__":
    unittest.main()
