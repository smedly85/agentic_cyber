from __future__ import annotations

import unittest
from pathlib import Path

from security.common.callgraph import (
    analyze_source_bytes,
    analyze_source_file,
    analyze_sources,
    select_functions,
)


REPO = Path(__file__).resolve().parents[1]


def analyze(source: str):
    return analyze_source_bytes(source, force_fallback=True)


def functions_by_id(result):
    return {item["function_id"]: item for item in result["function_reachability"]}


SELECTION_SOURCE = r"""
static void c(void) {}
static void d(void) {}
static void a(void) { c(); }
static void b(void) { d(); }
int main(void) { a(); b(); return 0; }
"""


class CallGraphReachabilityTests(unittest.TestCase):
    def test_shortest_bfs_depth_from_main(self):
        result = analyze(r"""
            static void target(void) {}
            static void hop(void) { target(); }
            static void long_path(void) { hop(); }
            int main(void) { long_path(); target(); return 0; }
        """)
        rows = functions_by_id(result)
        self.assertEqual(rows["target"]["call_depth"], 1)
        self.assertEqual(rows["hop"]["call_depth"], 2)

    def test_branching_graph_visits_every_branch(self):
        result = analyze(r"""
            static void left_leaf(void) {}
            static void right_leaf(void) {}
            static void left(void) { left_leaf(); }
            static void right(void) { right_leaf(); }
            int main(void) { left(); right(); return 0; }
        """)
        rows = functions_by_id(result)
        self.assertEqual(rows["left"]["call_depth"], 1)
        self.assertEqual(rows["right"]["call_depth"], 1)
        self.assertEqual(rows["left_leaf"]["call_depth"], 2)
        self.assertEqual(rows["right_leaf"]["call_depth"], 2)

    def test_cycles_and_recursion_terminate(self):
        result = analyze(r"""
            static void b(void);
            static void a(void) { b(); }
            static void b(void) { a(); b(); }
            int main(void) { a(); return 0; }
        """)
        rows = functions_by_id(result)
        self.assertEqual(result["reachable_function_count"], 3)
        self.assertEqual(rows["a"]["call_depth"], 1)
        self.assertEqual(rows["b"]["call_depth"], 2)
        self.assertIn(
            {"function": "b", "call": "b", "category": "recursive_traversal"},
            result["security_sensitive_calls"],
        )

    def test_unreachable_function_is_explicitly_unreachable(self):
        result = analyze(r"""
            static void reached(void) {}
            static void orphan(void) {}
            int main(void) { reached(); return 0; }
        """)
        orphan = functions_by_id(result)["orphan"]
        self.assertIsNone(orphan["call_depth"])
        self.assertIs(orphan["reachable_from_entry"], False)
        self.assertIs(orphan["diversification_eligible"], False)
        self.assertEqual(result["unreachable_function_count"], 1)

    def test_qsort_callback_is_a_typed_edge(self):
        result = analyze(r"""
            static int compare(const void *a, const void *b) { return a == b; }
            int main(void) { qsort(0, 0, 0, compare); return 0; }
        """)
        main = functions_by_id(result)["main"]
        compare = functions_by_id(result)["compare"]
        self.assertIn(
            {"target": "compare", "edge_type": "callback"},
            main["outgoing_call_edges"],
        )
        self.assertEqual(main["callback_callees"], ["compare"])
        self.assertEqual(compare["call_depth"], 1)

    def test_ambiguous_callback_target_is_not_guessed(self):
        result = analyze_sources(
            [
                ("a.c", b"static int compare(const void *a, const void *b) { return 0; }"),
                ("b.c", b"static int compare(const void *a, const void *b) { return 0; }"),
                ("main.c", b"int main(void) { qsort(0, 0, 0, compare); return 0; }"),
            ],
            force_fallback=True,
        )
        main = functions_by_id(result)["main"]
        self.assertEqual(main["callback_callees"], [])
        self.assertEqual(result["unresolved_callback_targets"], [{
            "caller": "main",
            "api": "qsort",
            "target_text": "compare",
            "reason": "ambiguous_target",
        }])
        compare_rows = [
            row for row in result["function_reachability"]
            if row["function"] == "compare"
        ]
        self.assertTrue(all(row["reachable_from_entry"] is False for row in compare_rows))

    def test_checked_in_new_sort_callback_makes_compare_lines_reachable(self):
        result = analyze_source_file(
            REPO / "src" / "new_sort" / "new_sort.c", force_fallback=True
        )
        rows = functions_by_id(result)
        self.assertIs(rows["compare_lines"]["reachable_from_entry"], True)
        callback_callers = rows["compare_lines"]["callback_callers"]
        self.assertEqual(callback_callers, ["sort_lines"])
        self.assertIn(
            {"target": "compare_lines", "edge_type": "callback"},
            rows["sort_lines"]["outgoing_call_edges"],
        )

    def test_all_resolved_entry_points_remain_depth_zero(self):
        result = analyze_source_bytes(
            r"""
                static void leaf(void) {}
                void helper(void) { leaf(); }
                int main(void) { helper(); return 0; }
            """,
            entry_points=("main", "helper"),
            force_fallback=True,
        )
        rows = functions_by_id(result)
        self.assertEqual(result["resolved_entry_points"], ["helper", "main"])
        self.assertEqual(rows["main"]["call_depth"], 0)
        self.assertEqual(rows["helper"]["call_depth"], 0)
        self.assertEqual(rows["leaf"]["call_depth"], 1)

    def test_entry_points_are_excluded_from_selection_by_default(self):
        result = analyze(SELECTION_SOURCE)
        for policy in ("SHALLOW", "RANDOM", "DEEP"):
            selection = select_functions(result, policy=policy, percent=100, seed=17)
            self.assertNotIn("main", selection["selected_functions"])
            self.assertEqual(selection["selection_universe_function_count"], 4)

    def test_include_entry_points_restores_them(self):
        result = analyze(SELECTION_SOURCE)
        selection = select_functions(
            result, policy="SHALLOW", percent=100, include_entry_points=True
        )
        self.assertIn("main", selection["selected_functions"])
        self.assertEqual(selection["selection_universe_function_count"], 5)
        self.assertEqual(selection["selected_depths"]["main"], 0)

    def test_shallow_and_deep_ordering_are_deterministic(self):
        result = analyze(SELECTION_SOURCE)
        shallow = select_functions(result, policy="SHALLOW", k=2)
        deep = select_functions(result, policy="DEEP", k=2)
        self.assertEqual(shallow["selected_functions"], ["a", "b"])
        self.assertEqual(deep["selected_functions"], ["c", "d"])
        self.assertEqual(shallow, select_functions(result, policy="SHALLOW", k=2))
        self.assertEqual(deep, select_functions(result, policy="DEEP", k=2))

    def test_fixed_random_seed_is_reproducible(self):
        result = analyze(SELECTION_SOURCE)
        first = select_functions(result, policy="RANDOM", k=3, seed=2026)
        second = select_functions(result, policy="random", k=3, seed=2026)
        self.assertEqual(first, second)
        self.assertEqual(first["selection_seed"], 2026)

    def test_percentage_budget_uses_diversification_eligible_count(self):
        result = analyze(SELECTION_SOURCE)
        self.assertEqual(result["reachable_function_count"], 5)
        self.assertEqual(result["diversification_eligible_function_count"], 4)
        selection = select_functions(result, policy="SHALLOW", percent=50)
        self.assertEqual(selection["selection_universe_function_count"], 4)
        self.assertEqual(selection["selected_function_count"], 2)


if __name__ == "__main__":
    unittest.main()
