from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from security.common.callgraph import analyze_source_bytes, select_functions
from security.generated_structural_census import (
    CensusError,
    aggregate_rows,
    analyze_manifest_candidate,
    compare_summaries,
    content_sha256,
    main as census_main,
    manifest_fingerprint_payload,
    run_census,
    structural_metrics,
    validate_manifest,
)

REPO = Path(__file__).resolve().parents[1]


def workspace_tempdir():
    """Keep mutable fixtures inside the repository sandbox on Windows."""
    root = REPO / "build"
    root.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=root)


def candidate_row(identifier: str, source: str, data: bytes, **updates):
    row = {
        "candidate_id": identifier,
        "formal_run_id": "formal-run",
        "lineage_id": "lineage-001",
        "checkpoint_id": "000",
        "checkpoint_name": "base",
        "utility": "sort",
        "attempt_id": "attempt-001",
        "candidate_source": source,
        "candidate_source_sha256": hashlib.sha256(data).hexdigest(),
        "functional_population_status": "public_checkpoint_stage_success",
        "final_population_member": True,
    }
    row.update(updates)
    return row


def manifest_for(candidates):
    value = {
        "schema_version": 1,
        "population_definition": {
            "checkpoint_population": "test",
            "host_filesystem_discovery": False,
        },
        "formal_runs": [{
            "formal_run_id": "formal-run",
            "utility": "sort",
            "lineage_root": "runs/formal-run",
            "checkpoint_ids": ["000"],
            "generation_repository_commit": "abc",
        }],
        "candidates": sorted(candidates, key=lambda row: (
            row["utility"], row["formal_run_id"], row["lineage_id"],
            row["checkpoint_id"], row["candidate_id"],
        )),
    }
    value["candidate_population_sha256"] = content_sha256(
        manifest_fingerprint_payload(value)
    )
    return value


class StructuralUniverseTests(unittest.TestCase):
    def test_main_is_in_measurement_but_not_default_diversification_universe(self):
        analysis = analyze_source_bytes(
            "static int helper(void) { return 1; }\n"
            "int main(void) { return helper(); }\n",
            force_fallback=True,
        )
        metrics = structural_metrics(analysis)
        self.assertEqual(metrics["measurement_universe_function_count"], 2)
        self.assertEqual(metrics["diversification_eligible_function_count"], 1)
        self.assertEqual(metrics["function_count_by_call_depth"], {"0": 1, "1": 1})
        selected = select_functions(analysis, policy="SHALLOW", k=2)
        self.assertEqual(selected["selected_functions"], ["helper"])
        self.assertNotIn("main", selected["selected_functions"])

    def test_single_function_has_measurement_one_and_empty_diversification(self):
        analysis = analyze_source_bytes(
            "int main(void) { return 0; }\n", force_fallback=True
        )
        metrics = structural_metrics(analysis)
        self.assertEqual(metrics["measurement_universe_function_count"], 1)
        self.assertEqual(metrics["diversification_eligible_function_count"], 0)
        self.assertTrue(metrics["entry_point_only_reachable"])
        self.assertTrue(metrics["diversification_universe_empty"])

    def test_depths_unreachable_loc_and_tree_sitter_ast_are_exact(self):
        source = (
            "static int d2(void) { return 0; }\n"
            "static int d1(void) { return d2(); }\n"
            "int main(void) { return d1(); }\n"
            "static int dead(void) { return 1; }\n"
        )
        analysis = analyze_source_bytes(source)
        if analysis["analysis_method"] != "tree_sitter":
            self.skipTest("Tree-sitter unavailable")
        metrics = structural_metrics(analysis)
        self.assertEqual(metrics["function_count_by_call_depth"], {
            "0": 1, "1": 1, "2": 1,
        })
        self.assertEqual(metrics["lines_of_code_by_call_depth"], {
            "0": 1, "1": 1, "2": 1,
        })
        self.assertEqual(metrics["unreachable_function_count"], 1)
        dead = next(
            row for row in analysis["function_reachability"]
            if row["function"] == "dead"
        )
        self.assertIsNone(dead["call_depth"])
        self.assertFalse(dead["reachable_from_entry"])
        self.assertTrue(all(
            isinstance(value, int) and value > 0
            for value in metrics["ast_node_count_by_call_depth"].values()
        ))
        self.assertIsInstance(metrics["total_reachable_ast_node_count"], int)

    def test_regex_ast_mass_is_missing_not_zero(self):
        analysis = analyze_source_bytes(
            "int main(void) { return 0; }\n", force_fallback=True
        )
        metrics = structural_metrics(analysis)
        self.assertEqual(metrics["ast_node_count_by_call_depth"], {"0": None})
        self.assertIsNone(metrics["total_reachable_ast_node_count"])


class FrozenPopulationTests(unittest.TestCase):
    def test_checked_in_population_manifest_is_frozen_and_complete(self):
        manifest = validate_manifest(json.loads(
            (REPO / "security/generated_candidate_population.json").read_text(
                encoding="utf-8"
            )
        ))
        candidates = manifest["candidates"]
        self.assertEqual(len(candidates), 140)
        self.assertEqual(
            {utility: sum(row["utility"] == utility for row in candidates)
             for utility in ("chmod", "grep", "mkdir", "sort")},
            {"chmod": 31, "grep": 50, "mkdir": 21, "sort": 38},
        )
        self.assertEqual(
            {stage: sum(row["checkpoint_id"] == stage for row in candidates)
             for stage in ("000", "001", "002", "003", "004")},
            {"000": 32, "001": 31, "002": 31, "003": 23, "004": 23},
        )
        self.assertEqual(sum(row["final_population_member"] for row in candidates), 23)

    def test_formal_candidate_does_not_mix_regex_fallback(self):
        data = b"int main(void) { return 0; }\n"
        with workspace_tempdir() as directory:
            root = Path(directory)
            source = root / "candidate.c"
            source.write_bytes(data)
            row, functions = analyze_manifest_candidate(
                candidate_row("formal-run/lineage-001/000", "candidate.c", data),
                root,
                formal=True,
                force_fallback=True,
            )
        self.assertEqual(row["analysis_status"], "formal_method_unavailable")
        self.assertEqual(row["analysis_method"], "regex_fallback")
        self.assertEqual(functions, [])

    def test_security_outcome_fields_are_rejected_from_manifest(self):
        data = b"int main(void) { return 0; }\n"
        row = candidate_row("formal-run/lineage-001/000", "candidate.c", data)
        row["security_clean"] = True
        with self.assertRaisesRegex(CensusError, "security outcomes"):
            validate_manifest(manifest_for([row]))

    def test_machine_local_extra_runs_do_not_enter_frozen_population(self):
        data = b"int main(void) { return 0; }\n"
        with workspace_tempdir() as directory:
            root = Path(directory)
            (root / "candidate.c").write_bytes(data)
            (root / "runs" / "local-extra-run").mkdir(parents=True)
            manifest = validate_manifest(manifest_for([
                candidate_row("formal-run/lineage-001/000", "candidate.c", data)
            ]))
            summary, _ = run_census(
                manifest, root, host_role="other", force_fallback=True
            )
        science = summary["scientific_results"]
        self.assertEqual(science["expected_candidate_count"], 1)
        self.assertEqual(len(science["candidate_rows"]), 1)

    def test_missing_frozen_candidate_is_reported_in_denominator(self):
        data = b"int main(void) { return 0; }\n"
        with workspace_tempdir() as directory:
            manifest = validate_manifest(manifest_for([
                candidate_row("formal-run/lineage-001/000", "missing.c", data)
            ]))
            summary, _ = run_census(
                manifest, Path(directory), host_role="other", force_fallback=True
            )
        row = summary["scientific_results"]["candidate_rows"][0]
        overall = summary["scientific_results"]["aggregates"]["overall"][0]
        self.assertEqual(row["analysis_status"], "unavailable")
        self.assertEqual(overall["candidate_count"], 1)
        self.assertEqual(overall["characterized_candidate_count"], 0)

    def test_source_hash_mismatch_is_reported_without_analysis(self):
        expected = b"int main(void) { return 0; }\n"
        actual = b"int main(void) { return 1; }\n"
        with workspace_tempdir() as directory:
            root = Path(directory)
            (root / "candidate.c").write_bytes(actual)
            manifest = validate_manifest(manifest_for([
                candidate_row("formal-run/lineage-001/000", "candidate.c", expected)
            ]))
            summary, _ = run_census(
                manifest, root, host_role="other", force_fallback=True
            )
        row = summary["scientific_results"]["candidate_rows"][0]
        self.assertEqual(row["analysis_status"], "source_hash_mismatch")
        self.assertEqual(summary["scientific_results"]["function_rows"], [])

    def test_source_hash_mismatch_fails_formal_cli(self):
        expected = b"int main(void) { return 0; }\n"
        actual = b"int main(void) { return 1; }\n"
        with workspace_tempdir() as directory:
            root = Path(directory)
            (root / "candidate.c").write_bytes(actual)
            manifest_path = root / "population.json"
            manifest_path.write_text(
                json.dumps(manifest_for([
                    candidate_row(
                        "formal-run/lineage-001/000", "candidate.c", expected
                    )
                ])),
                encoding="utf-8",
            )
            result = census_main([
                "census", "--repo-root", str(root),
                "--manifest", str(manifest_path),
                "--output-dir", str(root / "output"),
                "--host-role", "vessel", "--formal",
            ])
            summary = json.loads((
                root / "output/generated_reachability_summary.json"
            ).read_text(encoding="utf-8"))
        self.assertEqual(result, 2)
        self.assertEqual(
            summary["scientific_results"]["candidate_rows"][0]["analysis_status"],
            "source_hash_mismatch",
        )

    def test_candidate_order_is_deterministic_and_manifest_order_fail_closed(self):
        data = b"int main(void) { return 0; }\n"
        first = candidate_row(
            "formal-run/lineage-001/001", "one.c", data,
            checkpoint_id="001",
        )
        second = candidate_row(
            "formal-run/lineage-001/000", "zero.c", data,
            checkpoint_id="000",
        )
        valid = manifest_for([first, second])
        self.assertEqual(
            [row["checkpoint_id"] for row in validate_manifest(valid)["candidates"]],
            ["000", "001"],
        )
        invalid = copy.deepcopy(valid)
        invalid["candidates"].reverse()
        invalid["candidate_population_sha256"] = content_sha256(
            manifest_fingerprint_payload(invalid)
        )
        with self.assertRaisesRegex(CensusError, "deterministic order"):
            validate_manifest(invalid)

    def test_aggregate_utility_and_stage_denominators_are_explicit(self):
        rows = [
            {
                "candidate_id": "a", "utility": "sort", "checkpoint_id": "000",
                "analysis_status": "analyzed", "analysis_method": "tree_sitter",
                "defined_function_count": 1, "reachable_function_count": 1,
                "measurement_universe_function_count": 1,
                "diversification_eligible_function_count": 0,
                "max_reachable_call_depth": 0, "entry_point_only_reachable": True,
                "diversification_universe_empty": True,
                "unreachable_function_count": 0, "final_population_member": True,
            },
            {
                "candidate_id": "b", "utility": "sort", "checkpoint_id": "000",
                "analysis_status": "unavailable", "analysis_method": None,
                "final_population_member": False,
            },
        ]
        aggregates = aggregate_rows(rows)
        for key in ("overall", "utility", "stage", "utility_stage"):
            self.assertEqual(aggregates[key][0]["candidate_count"], 2)
            self.assertEqual(aggregates[key][0]["characterized_candidate_count"], 1)
            self.assertIsNone(
                aggregates[key][0]["empty_diversification_universe_prevalence"]
            )

    def test_formal_execution_role_requires_vessel(self):
        data = b"int main(void) { return 0; }\n"
        manifest = validate_manifest(manifest_for([
            candidate_row("formal-run/lineage-001/000", "candidate.c", data)
        ]))
        with workspace_tempdir() as directory:
            (Path(directory) / "candidate.c").write_bytes(data)
            with self.assertRaisesRegex(CensusError, "host-role vessel"):
                run_census(manifest, Path(directory), formal=True, host_role="wsl")


class CrossHostComparisonTests(unittest.TestCase):
    def make_summary(self):
        science = {
            "candidate_rows": [{
                "candidate_id": "c", "candidate_source_sha256": "a" * 64,
                "actual_candidate_source_sha256": "a" * 64,
                "analysis_status": "analyzed", "analysis_method": "tree_sitter",
                "entry_point_resolution_status": "resolved",
                "defined_function_count": 1, "reachable_function_count": 1,
                "numeric_depth_function_count": 1, "unreachable_function_count": 0,
                "measurement_universe_function_count": 1,
                "diversification_eligible_function_count": 0,
                "max_reachable_call_depth": 0,
                "functions_by_call_depth": {"0": ["main"]},
                "function_count_by_call_depth": {"0": 1},
                "lines_of_code_by_call_depth": {"0": 1},
                "ast_node_count_by_call_depth": {"0": 5},
            }],
            "function_rows": [{"candidate_id": "c", "function_id": "main", "call_depth": 0}],
            "aggregates": {"overall": []},
            "depth_distribution": [{"call_depth": 0, "function_count": 1}],
        }
        return {
            "candidate_population_sha256": "p" * 64,
            "structural_census_sha256": content_sha256(science),
            "scientific_results": science,
        }

    def test_identical_science_with_different_hosts_compares_equal(self):
        left = self.make_summary()
        right = copy.deepcopy(left)
        result = compare_summaries(
            left, right,
            {"os": "Linux", "python_version": "3.14"},
            {"os": "Darwin", "python_version": "3.13"},
        )
        self.assertTrue(result["scientific_results_identical"])
        self.assertEqual(len(result["environment_differences"]), 2)

    def test_different_depths_compare_unequal(self):
        left = self.make_summary()
        right = copy.deepcopy(left)
        right["scientific_results"]["candidate_rows"][0]["max_reachable_call_depth"] = 1
        right["structural_census_sha256"] = content_sha256(right["scientific_results"])
        result = compare_summaries(left, right)
        self.assertFalse(result["scientific_results_identical"])
        self.assertTrue(any(
            item.get("field") == "max_reachable_call_depth"
            for item in result["scientific_differences"]
        ))

    def test_tree_sitter_and_regex_methods_compare_unequal(self):
        left = self.make_summary()
        right = copy.deepcopy(left)
        right["scientific_results"]["candidate_rows"][0]["analysis_method"] = "regex_fallback"
        right["structural_census_sha256"] = content_sha256(right["scientific_results"])
        result = compare_summaries(left, right)
        self.assertFalse(result["scientific_results_identical"])
        self.assertTrue(any(
            item.get("field") == "analysis_method"
            for item in result["scientific_differences"]
        ))


if __name__ == "__main__":
    unittest.main()
