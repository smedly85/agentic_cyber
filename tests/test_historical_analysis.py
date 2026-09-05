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
    version_specific_hvc,
)


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "historical"


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


if __name__ == "__main__":
    unittest.main()
