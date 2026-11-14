from __future__ import annotations

import unittest

from scripts.snode_historical_evaluation import build_plan


class HistoricalSNodePreparationTests(unittest.TestCase):
    def test_saved_historical_artifacts_are_routable_without_reextraction(self):
        plan = build_plan()
        self.assertEqual(plan["candidate_count"], 140)
        self.assertEqual(plan["pair_count"], 495)
        self.assertEqual(plan["eligible_representation_count"], 137)
        self.assertEqual(plan["representation_hash_check"], {"missing": [], "mismatched": []})
        self.assertEqual(plan["pair_routes"], {
            "recompute_architecture_alignments": 16,
            "reuse_saved_alignments": 363,
            "unavailable_incomplete_architecture_optima": 7,
            "unavailable_prior_alignment:no_scope_compatible_architecture_optimum": 94,
            "unavailable_prior_architecture": 15,
        })


if __name__ == "__main__":
    unittest.main()
