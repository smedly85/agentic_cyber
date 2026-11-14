from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from scripts.analysis.unified_distance import Limits, brute_force_reference, compare
from scripts.analysis.unified_graph import extract_llvm_ir
from scripts.analysis.ordered_distances import Budget, Limits as OldLimits, _size, _tree_distance
from scripts.unified_diversity import extract


def graph(ir: str):
    return extract_llvm_ir(ir, source_bytes=b"fixture", source_path="fixture.c",
                           compiler_version="fixture LLVM IR test double",
                           compiler_sha256=None, command=["fixture-only"])


BASE = """
define i32 @main(i32 %x) {
entry:
  %a = add nsw i32 %x, 1
  ret i32 %a
}
"""


PARENT = """
define i32 @main(i32 %x) {
entry:
  %c = icmp sgt i32 %x, 0
  br i1 %c, label %body, label %exit
body:
  %a = add nsw i32 %x, 1
  br label %exit
exit:
  %r = phi i32 [ %a, %body ], [ %x, %entry ]
  ret i32 %r
}
"""


class UnifiedGraphTests(unittest.TestCase):
    def test_compiler_extraction_fails_closed_outside_docker(self):
        if not Path("/.dockerenv").is_file():
            result = extract(Path("tests/fixtures/ordered_callgraph/call_free.c"))
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["reason"], "docker_required_for_compiler_extraction")

    def test_real_cfg_and_api_are_extracted_from_ir(self):
        value = graph("""
declare i32 @puts(ptr)
define i32 @main(i32 %x) {
entry:
  %c = icmp eq i32 %x, 0
  br i1 %c, label %yes, label %no
yes:
  %r = call i32 @puts(ptr null)
  br label %no
no:
  ret i32 0
}
""")
        self.assertEqual(value["status"], "success")
        self.assertEqual(sum(n["kind"] == "block" for n in value["nodes"]), 3)
        self.assertIn("cfg:true", {e["label"] for e in value["edges"]})
        self.assertIn("api:puts", {n["label"] for n in value["nodes"]})
        self.assertIn("call", {e["label"] for e in value["edges"]})
        schema = json.loads(Path("scripts/analysis/unified_graph.schema.json").read_text())
        self.assertEqual(schema["properties"]["schema_version"]["const"], value["schema_version"])
        self.assertTrue(set(schema["required"]) <= set(value))

    def test_identical_zero_and_symmetric(self):
        left = graph(BASE)
        forward, reverse = compare(left, copy.deepcopy(left)), compare(copy.deepcopy(left), left)
        self.assertEqual(forward["distance"], 0.0)
        self.assertEqual(forward["distance"], reverse["distance"])
        self.assertEqual(compare(graph(BASE), graph(PARENT))["distance"],
                         compare(graph(PARENT), graph(BASE))["distance"])

    def test_ssa_and_source_local_names_are_invariant(self):
        renamed = BASE.replace("%x", "%renamed").replace("%a", "%temporary")
        self.assertEqual(compare(graph(BASE), graph(renamed))["distance"], 0.0)

    def test_parent_insertion_preserves_descendant_block_match(self):
        result = compare(graph(BASE), graph(PARENT))
        self.assertEqual(result["status"], "success")
        left_blocks = {n["id"] for n in graph(BASE)["nodes"] if n["kind"] == "block"}
        self.assertTrue(left_blocks <= set(result["mapping"]))
        # The shared add instruction is retained; only newly introduced local
        # atoms are charged, rather than deleting/recreating both sequences.
        self.assertLess(result["components"]["content"],
                        sum(len(n["content"]) for n in graph(BASE)["nodes"])
                        + sum(len(n["content"]) for n in graph(PARENT)["nodes"]))
        self.assertGreater(result["components"]["edge"], 0)

    def test_existing_rooted_subtree_recurrence_amplifies_parent(self):
        def leaf(index):
            return ((f"stmt:{index}", None, "", "", "", "", None), False, ())
        descendants = tuple(leaf(i) for i in range(8))
        left = (("body", None, "", "", "", "", None), False, descendants)
        parent = (("if", None, "", "", "", "", None), False, descendants)
        right = (("body", None, "", "", "", "", None), False, (parent,))
        cost = _tree_distance(left, right, Budget(OldLimits()))
        self.assertEqual((_size(left), _size(right), cost), (9, 10, 16))

    def test_parent_cost_does_not_scale_with_unchanged_operations(self):
        operations = "\n".join(f"  %v{i} = add i32 %x, {i + 2}" for i in range(8))
        left = graph(f"define i32 @main(i32 %x) {{\nentry:\n{operations}\n  ret i32 %v7\n}}")
        right = graph(f"""define i32 @main(i32 %x) {{
entry:
  %c = icmp sgt i32 %x, 0
  br i1 %c, label %body, label %exit
body:
{operations}
  br label %exit
exit:
  %r = phi i32 [ %v7, %body ], [ %x, %entry ]
  ret i32 %r
}}""")
        result = compare(left, right)
        self.assertEqual(result["components"], {"node": 3, "edge": 5, "content": 4})
        self.assertEqual(result["cost"], 12)

    def test_helper_decomposition_and_inlining_remain_detectable(self):
        helper = graph("""
define i32 @helper(i32 %x) {
entry:
  %a = add i32 %x, 1
  ret i32 %a
}
define i32 @main(i32 %x) {
entry:
  %r = call i32 @helper(i32 %x)
  ret i32 %r
}
""")
        inline = graph(BASE)
        result = compare(helper, inline)
        self.assertGreater(result["components"]["node"], 0)
        self.assertGreater(result["components"]["edge"], 0)

    def test_loop_replacement_reordering_and_padding_are_detectable(self):
        loop = PARENT.replace("br i1 %c, label %body, label %exit", "br i1 %c, label %body, label %exit").replace(
            "br label %exit\nexit:", "br label %entry\nexit:")
        reordered = BASE.replace("%a = add nsw i32 %x, 1", "%m = mul i32 %x, 2\n  %a = add nsw i32 %m, 1")
        padded = BASE.replace("ret i32 %a", "br label %dead\ndead:\n  %d = xor i32 %x, %x\n  ret i32 %a")
        self.assertGreater(compare(graph(PARENT), graph(loop))["components"]["edge"], 0)
        self.assertGreater(compare(graph(BASE), graph(reordered))["components"]["content"], 0)
        self.assertGreater(compare(graph(BASE), graph(padded))["distance"], 0)

    def test_operation_condition_and_api_changes_are_detected(self):
        operation = BASE.replace(" add nsw ", " sub nsw ")
        condition_a = PARENT
        condition_b = PARENT.replace("icmp sgt", "icmp sge")
        api_a = graph("declare i32 @puts(ptr)\ndefine i32 @main(){entry:\n %r=call i32 @puts(ptr null)\n ret i32 0\n}")
        api_b = graph("declare i32 @printf(ptr, ...)\ndefine i32 @main(){entry:\n %r=call i32 (ptr, ...) @printf(ptr null)\n ret i32 0\n}")
        self.assertGreater(compare(graph(BASE), graph(operation))["components"]["content"], 0)
        self.assertGreater(compare(graph(condition_a), graph(condition_b))["components"]["content"], 0)
        self.assertGreater(compare(api_a, api_b)["components"]["node"], 0)

    def test_oracle_agrees_with_bounded_search(self):
        left, right = graph(BASE), graph(BASE.replace("add", "sub"))
        optimized = compare(left, right)
        oracle = brute_force_reference(left, right)
        self.assertEqual(optimized["cost"], oracle["cost"])
        self.assertEqual(optimized["distance"], oracle["distance"])

    def test_limits_never_return_unqualified_approximation(self):
        result = compare(graph(BASE), graph(PARENT), limits=Limits(max_states=1, seconds=45, max_nodes=80))
        self.assertEqual(result["status"], "bounded")
        self.assertIsNone(result["distance"])
        self.assertEqual(result["bounds"][0], 0.0)

    def test_empty_behavior(self):
        empty = graph("; no definitions")
        self.assertEqual(compare(empty, empty)["distance"], 0.0)
        self.assertEqual(compare(empty, graph(BASE))["distance"], 1.0)


if __name__ == "__main__":
    unittest.main()
