from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from security.historical.analysis import (
    HistoricalDataError,
    _percentile_bootstrap_ci,
    analyze_versioned_records,
    load_records,
    load_source_manifest,
    map_record_to_graph,
    source_tree_sha256,
    validate_manifest_entry,
    version_specific_hvc,
)


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "historical"
MULTI_PROGRAM = FIXTURES / "multi_program"


def fixture_records():
    return load_records(FIXTURES / "records.json")


def fixture_manifest():
    return load_source_manifest(FIXTURES / "source_manifest.json")


class HistoricalAnalysisTests(unittest.TestCase):
    def test_source_manifest_entries_are_version_specific(self):
        manifest = fixture_manifest()
        identities = {
            (item["upstream_project"], item["affected_version"], item["source_revision"])
            for item in manifest
        }
        self.assertEqual(identities, {
            ("gnu-coreutils", "fixture-a", "revision-a"),
            ("gnu-coreutils", "fixture-b", "revision-b"),
        })
        self.assertNotEqual(
            manifest[0]["resolved_source_tree"], manifest[1]["resolved_source_tree"]
        )

    def test_exact_project_version_revision_identity_matches(self):
        result = analyze_versioned_records(
            fixture_records()[:1], fixture_manifest(), force_fallback=True
        )
        mapping = result["historical_function_mappings"][0]
        self.assertEqual(mapping["source_version_status"], "source_version_matched")
        self.assertEqual(mapping["affected_version"], "fixture-a")
        self.assertEqual(mapping["source_revision"], "revision-a")

    def test_unavailable_and_revision_mismatch_are_distinct(self):
        record = fixture_records()[0]
        unavailable = analyze_versioned_records(
            [record], [], force_fallback=True
        )["historical_function_mappings"][0]
        wrong_revision = copy.deepcopy(fixture_manifest()[0])
        wrong_revision["source_revision"] = "another-revision"
        mismatch = analyze_versioned_records(
            [record], [wrong_revision], force_fallback=True
        )["historical_function_mappings"][0]
        self.assertEqual(unavailable["source_version_status"], "source_version_unavailable")
        self.assertEqual(mismatch["source_version_status"], "source_version_mismatch")

    def test_source_tree_fingerprint_mismatch_is_rejected(self):
        manifest = fixture_manifest()
        manifest[0]["source_tree_sha256"] = "0" * 64
        result = analyze_versioned_records(
            fixture_records()[:1], manifest, force_fallback=True
        )
        mapping = result["historical_function_mappings"][0]
        self.assertEqual(mapping["source_version_status"], "source_version_mismatch")
        self.assertIn("fingerprint", mapping["source_version_error"])
        self.assertEqual(result["call_graphs_constructed"], 0)

    def test_function_mapping_states_remain_distinct(self):
        graph = {
            "max_reachable_call_depth": 2,
            "reachable_function_count": 3,
            "diversification_eligible_function_count": 2,
            "function_reachability": [
                {"function": "reachable", "function_id": "reachable", "call_depth": 1,
                 "reachable_from_entry": True},
                {"function": "unreachable", "function_id": "unreachable", "call_depth": None,
                 "reachable_from_entry": False},
                {"function": "duplicate", "function_id": "a.c::duplicate", "call_depth": 1,
                 "reachable_from_entry": True},
                {"function": "duplicate", "function_id": "b.c::duplicate", "call_depth": 2,
                 "reachable_from_entry": True},
            ],
        }
        record = fixture_records()[0]
        observed = {}
        for target in ("missing", "duplicate", "unreachable", "reachable"):
            candidate = {**record, "id": target, "vulnerable_function": target}
            observed[target] = map_record_to_graph(candidate, graph)["mapping_status"]
        self.assertEqual(observed, {
            "missing": "function_not_found",
            "duplicate": "ambiguous_function_name",
            "unreachable": "mapped_but_unreachable",
            "reachable": "mapped_and_reachable",
        })

    def test_two_vulnerable_revisions_construct_distinct_graphs(self):
        result = analyze_versioned_records(
            fixture_records(), fixture_manifest(), force_fallback=True
        )
        mappings = result["historical_function_mappings"]
        self.assertEqual(result["call_graphs_constructed"], 2)
        self.assertEqual(len(result["call_graphs"]), 2)
        self.assertNotEqual(mappings[0]["source_analysis_id"], mappings[1]["source_analysis_id"])
        self.assertEqual([item["call_depth"] for item in mappings], [1, 2])

    def test_identical_source_identity_reuses_cached_graph(self):
        records = fixture_records()[:1]
        records.append({**records[0], "id": "SYNTHETIC-A-SECOND"})
        result = analyze_versioned_records(
            records, fixture_manifest(), force_fallback=True
        )
        mappings = result["historical_function_mappings"]
        self.assertEqual(result["call_graphs_constructed"], 1)
        self.assertEqual(result["call_graph_cache_hits"], 1)
        self.assertEqual(mappings[0]["source_analysis_id"], mappings[1]["source_analysis_id"])

    def test_hvc_selection_is_independent_within_each_version_graph(self):
        versioned = analyze_versioned_records(
            fixture_records(), fixture_manifest(), force_fallback=True
        )
        hvc = version_specific_hvc(versioned, policy="SHALLOW", k=1)
        details = {
            item["vulnerability_id"]: item
            for item in hvc["per_vulnerability_selections"]
        }
        self.assertEqual(details["SYNTHETIC-A"]["selected_functions"], ["vulnerable"])
        self.assertEqual(details["SYNTHETIC-B"]["selected_functions"], ["bridge"])
        self.assertEqual(hvc["covered_vulnerability_ids"], ["SYNTHETIC-A"])

    def test_unverified_records_are_excluded_from_hvc_denominator(self):
        records = fixture_records()
        records[1]["verified"] = False
        versioned = analyze_versioned_records(
            records, fixture_manifest(), force_fallback=True
        )
        hvc = version_specific_hvc(versioned, policy="SHALLOW", percent=100)
        self.assertEqual(
            hvc["historical_vulnerabilities_with_valid_version_specific_mappings"], 1
        )
        self.assertEqual(len(hvc["per_vulnerability_selections"]), 1)
        self.assertEqual(hvc["historical_vulnerability_coverage_at_budget"], 1.0)

    def test_random_hvc_repeats_exactly_with_a_fixed_seed(self):
        versioned = analyze_versioned_records(
            fixture_records(), fixture_manifest(), force_fallback=True
        )
        first = version_specific_hvc(versioned, policy="RANDOM", k=1, seed=4815)
        second = version_specific_hvc(versioned, policy="RANDOM", k=1, seed=4815)
        self.assertEqual(first, second)

    def test_percentile_bootstrap_interval_is_deterministic(self):
        values = [0.0, 0.25, 0.75, 1.0]
        first = _percentile_bootstrap_ci(values, seed=73, replicates=500)
        second = _percentile_bootstrap_ci(values, seed=73, replicates=500)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertLessEqual(first[0], first[1])

    def test_python_loaders_reject_non_array_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records_path = root / "records.json"
            manifest_path = root / "manifest.json"
            records_path.write_text("{}\n", encoding="utf-8")
            manifest_path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(HistoricalDataError, "root must be an array"):
                load_records(records_path)
            with self.assertRaisesRegex(HistoricalDataError, "root must be an array"):
                load_source_manifest(manifest_path)

    def test_checked_in_complete_file_schemas_describe_checked_in_arrays(self):
        pairs = (
            ("records.json", "schema.json"),
            ("source_manifest.json", "source_manifest.schema.json"),
        )
        for data_name, schema_name in pairs:
            with self.subTest(data=data_name):
                data = json.loads((REPO / "security" / "historical" / data_name).read_text())
                schema = json.loads((REPO / "security" / "historical" / schema_name).read_text())
                self.assertIsInstance(data, list)
                self.assertEqual(schema["type"], "array")
                self.assertTrue(schema["items"]["$ref"].startswith("#/$defs/"))
                definition = schema["items"]["$ref"].removeprefix("#/$defs/")
                self.assertEqual(schema["$defs"][definition]["type"], "object")

    def test_sort_scope_excludes_other_program_from_every_hvc_policy(self):
        records = load_records(MULTI_PROGRAM / "records.json")
        manifest = load_source_manifest(MULTI_PROGRAM / "source_manifest.json")
        versioned = analyze_versioned_records(
            records[:1], manifest, force_fallback=True
        )
        mapping = versioned["historical_function_mappings"][0]
        graph = versioned["call_graphs"][mapping["source_analysis_id"]]
        rows = graph["function_reachability"]
        self.assertEqual(mapping["source_qualified_entry_point"], "sort.c::main")
        self.assertEqual(mapping["resolved_source_files"], ["sort.c"])
        self.assertEqual(graph["analyzed_source_files"], ["sort.c"])
        self.assertEqual(
            [row["function"] for row in rows if row["call_depth"] == 0], ["main"]
        )
        self.assertEqual(graph["reachable_function_count"], 3)
        self.assertEqual(graph["diversification_eligible_function_count"], 2)
        self.assertFalse(any("chmod" in row["function"] for row in rows))

        for policy in ("SHALLOW", "RANDOM", "DEEP"):
            hvc = version_specific_hvc(
                versioned, policy=policy, percent=100, seed=29
            )
            detail = hvc["per_vulnerability_selections"][0]
            self.assertEqual(detail["selection_universe_function_count"], 2)
            self.assertEqual(detail["diversification_eligible_function_count"], 2)
            self.assertEqual(detail["resolved_source_files"], ["sort.c"])
            self.assertEqual(detail["source_qualified_entry_point"], "sort.c::main")
            self.assertFalse(any("chmod" in name for name in detail["selected_functions"]))
        half = version_specific_hvc(versioned, policy="SHALLOW", percent=50)
        self.assertEqual(
            half["per_vulnerability_selections"][0]["selected_function_count"], 1
        )

    def test_same_revision_different_utilities_use_distinct_graphs(self):
        records = load_records(MULTI_PROGRAM / "records.json")
        manifest = load_source_manifest(MULTI_PROGRAM / "source_manifest.json")
        versioned = analyze_versioned_records(
            records, manifest, force_fallback=True
        )
        mappings = {
            item["utility"]: item
            for item in versioned["historical_function_mappings"]
        }
        self.assertEqual(versioned["call_graphs_constructed"], 2)
        self.assertEqual(versioned["call_graph_cache_hits"], 0)
        self.assertNotEqual(
            mappings["sort"]["source_analysis_id"],
            mappings["chmod"]["source_analysis_id"],
        )
        self.assertEqual(mappings["sort"]["resolved_source_files"], ["sort.c"])
        self.assertEqual(mappings["chmod"]["resolved_source_files"], ["chmod.c"])

    def test_invalid_empty_and_outside_program_scopes_are_explicit(self):
        record = load_records(MULTI_PROGRAM / "records.json")[0]
        base_manifest = load_source_manifest(MULTI_PROGRAM / "source_manifest.json")

        escaping = copy.deepcopy(base_manifest[0])
        escaping["programs"]["sort"]["source_globs"] = ["../*.c"]
        self.assertTrue(any(
            "must not escape" in error for error in validate_manifest_entry(escaping)
        ))
        escaping_result = analyze_versioned_records(
            [record], [escaping], force_fallback=True
        )["historical_function_mappings"][0]
        self.assertEqual(escaping_result["mapping_status"], "analysis_scope_invalid")

        empty = copy.deepcopy(base_manifest[0])
        empty["programs"]["sort"]["source_globs"] = ["missing/*.c"]
        empty_result = analyze_versioned_records(
            [record], [empty], force_fallback=True
        )["historical_function_mappings"][0]
        self.assertEqual(empty_result["mapping_status"], "analysis_scope_empty")

        outside = copy.deepcopy(base_manifest[0])
        outside["programs"]["sort"]["entry_point"]["source_file"] = "chmod.c"
        outside_result = analyze_versioned_records(
            [record], [outside], force_fallback=True
        )["historical_function_mappings"][0]
        self.assertEqual(outside_result["mapping_status"], "entry_point_outside_scope")

        unsupported_record = {**record, "utility": "grep"}
        unsupported_result = analyze_versioned_records(
            [unsupported_record], base_manifest, force_fallback=True
        )["historical_function_mappings"][0]
        self.assertEqual(unsupported_result["mapping_status"], "program_scope_unavailable")

    def test_missing_and_ambiguous_historical_entry_points_are_unevaluable(self):
        record = load_records(MULTI_PROGRAM / "records.json")[0]
        manifest = load_source_manifest(MULTI_PROGRAM / "source_manifest.json")
        missing = copy.deepcopy(manifest[0])
        missing["programs"]["sort"]["entry_point"]["function"] = "missing"
        missing_result = analyze_versioned_records(
            [record], [missing], force_fallback=True
        )["historical_function_mappings"][0]
        self.assertEqual(missing_result["mapping_status"], "entry_point_not_found")
        self.assertFalse(missing_result["eligible_for_hvc"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "program.c").write_text(
                "int main(void) { return 0; }\nint main(void) { return 1; }\n",
                encoding="utf-8",
            )
            ambiguous_record = {
                **record,
                "affected_version": "ambiguous",
                "source_revision": "ambiguous-revision",
            }
            ambiguous_manifest = [{
                "upstream_project": "gnu-coreutils",
                "affected_version": "ambiguous",
                "source_revision": "ambiguous-revision",
                "source_tree": str(root),
                "resolved_source_tree": str(root),
                "source_tree_sha256": source_tree_sha256(root),
                "programs": {
                    "sort": {
                        "entry_point": {"source_file": "program.c", "function": "main"},
                        "source_globs": ["program.c"],
                    }
                },
            }]
            ambiguous_result = analyze_versioned_records(
                [ambiguous_record], ambiguous_manifest, force_fallback=True
            )["historical_function_mappings"][0]
        self.assertEqual(ambiguous_result["mapping_status"], "entry_point_ambiguous")
        self.assertFalse(ambiguous_result["eligible_for_hvc"])


if __name__ == "__main__":
    unittest.main()
