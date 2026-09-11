from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from security.common.callgraph import analyze_source_bytes, analyze_sources
from security.historical.analysis import (
    analyze_versioned_records,
    load_census,
    load_records,
    load_source_manifest,
    map_record_to_graph,
    summarize_historical_analysis,
    validate_record,
    version_specific_hvc,
)


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "historical"
SCHEMA = json.loads((REPO / "security" / "historical" / "schema.json").read_text())
GREP_REVISION = next(
    item["source_revision"]
    for item in json.loads(
        (REPO / "security" / "historical" / "source_manifest.json").read_text()
    )
    if item["upstream_project"] == "gnu-grep"
)


def fixture_records():
    return load_records(FIXTURES / "records.json")


def fixture_manifest():
    return load_source_manifest(FIXTURES / "source_manifest.json")


def sample_record(functions):
    return {**fixture_records()[0], "id": "SYNTHETIC-MULTI", "vulnerable_functions": functions}


def grep_fixture():
    record = copy.deepcopy(fixture_records()[1])
    record.update({
        "id": "SYNTHETIC-GREP",
        "utility": "grep",
        "upstream_project": "gnu-grep",
    })
    manifest = copy.deepcopy(fixture_manifest()[1])
    manifest["upstream_project"] = "gnu-grep"
    manifest["programs"] = {"grep": manifest["programs"].pop("sort")}
    return record, manifest


def graph(source):
    return analyze_source_bytes(source.replace("} ", "}\n"), force_fallback=True)


class HistoricalSchemaTests(unittest.TestCase):
    def assertSchemaAccepts(self, record):
        self.assertEqual(validate_record(record), [])
        try:
            import jsonschema
        except ImportError:
            return
        jsonschema.Draft202012Validator(SCHEMA).validate([record])

    def assertSchemaRejects(self, record):
        self.assertTrue(validate_record(record))
        try:
            import jsonschema
        except ImportError:
            return
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(SCHEMA).validate([record])

    def test_schema_accepts_one_vulnerable_function(self):
        self.assertSchemaAccepts(sample_record(["vulnerable"]))

    def test_schema_accepts_several_unique_vulnerable_functions(self):
        self.assertSchemaAccepts(sample_record(["first", "second"]))

    def test_empty_vulnerable_function_list_is_rejected(self):
        self.assertSchemaRejects(sample_record([]))

    def test_duplicate_vulnerable_function_names_are_rejected(self):
        self.assertSchemaRejects(sample_record(["same", "same"]))

    def test_empty_vulnerable_function_strings_are_rejected(self):
        self.assertSchemaRejects(sample_record(["valid", " "]))

    def test_checked_in_records_and_census_validate(self):
        records = load_records(REPO / "security/historical/records.json")
        census = load_census(REPO / "security/historical/cve_census.json")
        manifest = load_source_manifest(REPO / "security/historical/source_manifest.json")
        self.assertEqual([item["id"] for item in records], [
            "CVE-2025-5278", "CVE-2015-1345",
        ])
        self.assertEqual([item["id"] for item in census], [
            "CVE-2025-5278", "CVE-2015-1345",
        ])
        self.assertEqual(
            [(item["upstream_project"], item["affected_version"]) for item in manifest],
            [("gnu-coreutils", "9.7"), ("gnu-grep", "2.21")],
        )
        grep_record = next(item for item in records if item["id"] == "CVE-2015-1345")
        grep_source = next(
            item for item in manifest if item["upstream_project"] == "gnu-grep"
        )
        self.assertEqual(grep_record["vulnerable_functions"], ["bmexec_trans"])
        self.assertEqual(grep_source["programs"]["grep"]["entry_point"], {
            "source_file": "src/grep.c", "function": "main",
        })
        self.assertEqual(len(grep_source["programs"]["grep"]["source_files"]), 43)
        self.assertIn(
            "src/kwset.c", grep_source["programs"]["grep"]["source_files"]
        )
        try:
            import jsonschema
        except ImportError:
            return
        historical = REPO / "security" / "historical"
        for data_name, schema_name in (
            ("records.json", "schema.json"),
            ("source_manifest.json", "source_manifest.schema.json"),
            ("cve_census.json", "cve_census.schema.json"),
        ):
            with self.subTest(data=data_name):
                data = json.loads((historical / data_name).read_text())
                schema = json.loads((historical / schema_name).read_text())
                jsonschema.Draft202012Validator(schema).validate(data)


class MultiFunctionMappingTests(unittest.TestCase):
    def test_coreutils_and_grep_identities_resolve_independently(self):
        coreutils_record = fixture_records()[0]
        coreutils_manifest = fixture_manifest()[0]
        grep_record, grep_manifest = grep_fixture()
        combined = analyze_versioned_records(
            [coreutils_record, grep_record],
            [coreutils_manifest, grep_manifest],
            force_fallback=True,
        )
        rows = {
            item["vulnerability_id"]: item
            for item in combined["historical_function_mappings"]
        }
        self.assertEqual(combined["call_graphs_constructed"], 2)
        self.assertEqual(rows["SYNTHETIC-A"]["call_depth"], 1)
        self.assertEqual(rows["SYNTHETIC-GREP"]["call_depth"], 2)
        self.assertEqual(rows["SYNTHETIC-GREP"]["mapped_source_file"], "program.c")

    def test_source_identity_matching_uses_project_version_and_revision(self):
        record, manifest = grep_fixture()
        mutations = (
            ("upstream_project", "gnu-coreutils", "source_version_unavailable"),
            ("affected_version", "other-version", "source_version_unavailable"),
            ("source_revision", "c" * 40, "source_version_mismatch"),
        )
        for field, value, expected in mutations:
            with self.subTest(field=field):
                changed = copy.deepcopy(record)
                changed[field] = value
                result = analyze_versioned_records(
                    [changed], [manifest], force_fallback=True
                )
                row = result["historical_function_mappings"][0]
                self.assertEqual(row["source_version_status"], expected)
                self.assertEqual(result["call_graphs_constructed"], 0)

    def test_grep_source_fingerprint_mismatch_fails_closed(self):
        record, manifest = grep_fixture()
        manifest["source_tree_sha256"] = "0" * 64
        result = analyze_versioned_records([record], [manifest], force_fallback=True)
        row = result["historical_function_mappings"][0]
        self.assertEqual(row["source_version_status"], "source_version_mismatch")
        self.assertEqual(row["mapping_status"], "source_version_mismatch")
        self.assertEqual(result["call_graphs_constructed"], 0)

    def test_missing_exact_grep_source_file_fails_closed(self):
        record, manifest = grep_fixture()
        program = manifest["programs"]["grep"]
        program["source_files"] = [program.pop("source_globs")[0], "missing.c"]
        result = analyze_versioned_records([record], [manifest], force_fallback=True)
        row = result["historical_function_mappings"][0]
        self.assertEqual(row["mapping_status"], "analysis_scope_invalid")
        self.assertEqual(result["call_graphs_constructed"], 0)

    def test_exact_source_file_manifest_scope_is_supported_and_fail_closed(self):
        manifest = fixture_manifest()
        program = manifest[0]["programs"]["sort"]
        program["source_files"] = program.pop("source_globs")
        result = analyze_versioned_records(
            [fixture_records()[0]], manifest, force_fallback=True
        )
        self.assertEqual(result["call_graphs_constructed"], 1)
        self.assertEqual(
            result["historical_function_mappings"][0]["resolved_source_files"],
            ["program.c"],
        )

        program["source_files"].append("missing.c")
        failed = analyze_versioned_records(
            [fixture_records()[0]], manifest, force_fallback=True
        )
        self.assertEqual(failed["call_graphs_constructed"], 0)
        self.assertEqual(
            failed["historical_function_mappings"][0]["mapping_status"],
            "analysis_scope_invalid",
        )

    def test_every_declared_function_is_mapped_independently(self):
        result = map_record_to_graph(
            sample_record(["first", "second"]),
            graph("static void first(void) {} static void second(void) {} "
                  "int main(void) { first(); second(); return 0; }"),
        )
        self.assertEqual(
            [item["vulnerable_function"] for item in result["function_mappings"]],
            ["first", "second"],
        )
        self.assertEqual(result["successfully_mapped_function_count"], 2)
        self.assertEqual(result["reachable_vulnerable_function_count"], 2)

    def test_one_mapped_and_one_missing_is_explicitly_partial(self):
        result = map_record_to_graph(
            sample_record(["present", "missing"]),
            graph("static void present(void) {} int main(void) { present(); return 0; }"),
        )
        states = {item["vulnerable_function"]: item["mapping_status"]
                  for item in result["function_mappings"]}
        self.assertEqual(states, {
            "present": "mapped_and_reachable",
            "missing": "function_not_found",
        })
        self.assertEqual(result["mapping_status"], "partial_mapping")
        self.assertEqual(result["successfully_mapped_function_count"], 1)

    def test_reachable_and_unreachable_functions_remain_distinguishable(self):
        result = map_record_to_graph(
            sample_record(["reached", "orphan"]),
            graph("static void reached(void) {} static void orphan(void) {} "
                  "int main(void) { reached(); return 0; }"),
        )
        rows = {item["vulnerable_function"]: item for item in result["function_mappings"]}
        self.assertIs(rows["reached"]["reachable_from_entry"], True)
        self.assertIs(rows["orphan"]["reachable_from_entry"], False)
        self.assertEqual(rows["orphan"]["mapping_status"], "mapped_but_unreachable")
        self.assertEqual(result["mapping_status"], "mapped_with_mixed_reachability")

    def test_cve_minimum_and_maximum_reachable_depths(self):
        result = map_record_to_graph(
            sample_record(["near", "far"]),
            graph("static void far(void) {} static void bridge(void) { far(); } "
                  "static void near(void) {} "
                  "int main(void) { near(); bridge(); return 0; }"),
        )
        self.assertEqual(result["minimum_reachable_call_depth"], 1)
        self.assertEqual(result["maximum_reachable_call_depth"], 2)
        summary = summarize_historical_analysis(result["function_mappings"], [result])
        self.assertEqual(
            summary["vulnerable_function_location_depth_distribution"], {"1": 1, "2": 1}
        )
        self.assertEqual(
            summary["per_cve_shallowest_reachable_depth_distribution"], {"1": 1}
        )

    def test_hvc_counts_one_multifunction_cve_once_and_any_location_covers(self):
        analyzed = graph(
            "static void chosen(void) {} static void other(void) {} "
            "int main(void) { chosen(); other(); return 0; }"
        )
        record = map_record_to_graph(
            sample_record(["other", "chosen"]), analyzed, source_analysis_id="g"
        )
        versioned = {
            "historical_function_mappings": record["function_mappings"],
            "historical_record_mappings": [record],
            "call_graphs": {"g": analyzed},
        }
        hvc = version_specific_hvc(versioned, policy="SHALLOW", k=1)
        self.assertEqual(
            hvc["historical_vulnerabilities_with_valid_version_specific_mappings"], 1
        )
        self.assertEqual(hvc["historical_vulnerabilities_covered"], 1)
        self.assertEqual(hvc["covered_vulnerability_ids"], ["SYNTHETIC-MULTI"])
        coverage = hvc["per_vulnerability_selections"][0]["function_location_coverage"]
        self.assertEqual(sum(item["selected"] for item in coverage), 1)
        self.assertIs(coverage[0]["selected"], False)
        self.assertIs(coverage[1]["selected"], True)

    def test_hvc_duplicate_lower_level_records_use_one_cve_set(self):
        analyzed = graph(
            "static void chosen(void) {} "
            "int main(void) { chosen(); return 0; }"
        )
        record = map_record_to_graph(
            sample_record(["chosen"]), analyzed, source_analysis_id="g"
        )
        versioned = {
            "historical_function_mappings": record["function_mappings"],
            "historical_record_mappings": [record, copy.deepcopy(record)],
            "call_graphs": {"g": analyzed},
        }
        hvc = version_specific_hvc(versioned, policy="SHALLOW", k=1)
        self.assertEqual(
            hvc["historical_vulnerabilities_with_valid_version_specific_mappings"], 1
        )
        self.assertEqual(hvc["historical_vulnerabilities_covered"], 1)
        self.assertEqual(hvc["covered_vulnerability_ids"], ["SYNTHETIC-MULTI"])
        self.assertEqual(hvc["historical_vulnerability_coverage_at_budget"], 1.0)

    def test_single_function_migration_preserves_mapping_behavior(self):
        result = map_record_to_graph(
            sample_record(["vulnerable"]),
            graph("static void vulnerable(void) {} int main(void) { vulnerable(); return 0; }"),
        )
        location = result["function_mappings"][0]
        self.assertEqual(result["mapping_status"], "mapped_and_reachable")
        self.assertEqual(location["mapped_function_id"], "vulnerable")
        self.assertEqual(location["call_depth"], 1)
        self.assertEqual(location["shortest_call_path"], ["main", "vulnerable"])
        legacy_summary_call = summarize_historical_analysis([location])
        self.assertEqual(legacy_summary_call["historical_record_count"], 1)
        self.assertEqual(legacy_summary_call["reachable_mapped_vulnerability_count"], 1)

    def test_unresolved_and_ambiguous_functions_are_never_guessed(self):
        analyzed = analyze_sources([
            ("a.c", b"static void duplicate(void) {}"),
            ("b.c", b"static void duplicate(void) {}"),
            ("main.c", b"int main(void) { duplicate(); return 0; }"),
        ], force_fallback=True)
        result = map_record_to_graph(sample_record(["duplicate", "absent"]), analyzed)
        rows = {item["vulnerable_function"]: item for item in result["function_mappings"]}
        self.assertEqual(rows["duplicate"]["mapping_status"], "ambiguous_function_name")
        self.assertEqual(rows["absent"]["mapping_status"], "function_not_found")
        self.assertIsNone(rows["duplicate"]["mapped_function_id"])
        self.assertIsNone(rows["absent"]["mapped_function_id"])
        self.assertIn({
            "caller": "main",
            "callee_text": "duplicate",
            "reason": "ambiguous_target",
        }, analyzed["unresolved_direct_calls"])
        main = next(
            item for item in analyzed["function_reachability"]
            if item["function"] == "main"
        )
        self.assertEqual(main["direct_callees"], [])

    def test_bmexec_trans_must_resolve_uniquely_before_mapping(self):
        analyzed = analyze_sources([
            ("first-kwset.c", b"static void bmexec_trans(void) {}"),
            ("second-kwset.c", b"static void bmexec_trans(void) {}"),
            ("grep.c", b"int main(void) { bmexec_trans(); return 0; }"),
        ], force_fallback=True)
        result = map_record_to_graph(sample_record(["bmexec_trans"]), analyzed)
        row = result["function_mappings"][0]
        self.assertEqual(row["mapping_status"], "ambiguous_function_name")
        self.assertIsNone(row["mapped_function_id"])
        self.assertIsNone(row["mapped_source_file"])

    def test_shortest_call_path_reporting_works_for_grep_graph(self):
        analyzed = analyze_sources([(
            "grep.c",
            b"static void bmexec_trans(void) {}\n"
            b"static void bmexec(void) { bmexec_trans(); }\n"
            b"static void kwsexec(void) { bmexec(); }\n"
            b"static void Fexecute(void) { kwsexec(); }\n"
            b"static void grepbuf(void) { Fexecute(); }\n"
            b"int main(void) { grepbuf(); return 0; }\n",
        )], entry_points=("grep.c::main",), force_fallback=True)
        result = map_record_to_graph(sample_record(["bmexec_trans"]), analyzed)
        row = result["function_mappings"][0]
        self.assertEqual(row["mapping_status"], "mapped_and_reachable")
        self.assertEqual(row["mapped_source_file"], "grep.c")
        self.assertEqual(row["call_depth"], 5)
        self.assertEqual(row["shortest_call_path"], [
            "main", "grepbuf", "Fexecute", "kwsexec", "bmexec", "bmexec_trans",
        ])

    def test_gnu_attribute_macro_before_function_name_is_recovered(self):
        analyzed = analyze_source_bytes(
            b"static inline unsigned long _GL_ATTRIBUTE_PURE\n"
            b"bmexec_trans(void) { return 0; }\n"
            b"int main(void) { return (int) bmexec_trans(); }\n"
        )
        matches = [
            item for item in analyzed["function_reachability"]
            if item["function"] == "bmexec_trans"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["call_depth"], 1)

    def test_second_project_record_does_not_change_coreutils_result(self):
        coreutils_record = fixture_records()[0]
        coreutils_manifest = fixture_manifest()[0]
        baseline = analyze_versioned_records(
            [coreutils_record], [coreutils_manifest], force_fallback=True
        )["historical_function_mappings"][0]
        grep_record, grep_manifest = grep_fixture()
        combined = analyze_versioned_records(
            [coreutils_record, grep_record], [coreutils_manifest, grep_manifest],
            force_fallback=True,
        )["historical_function_mappings"][0]
        stable_fields = (
            "mapping_status", "mapped_function_id", "mapped_source_file",
            "call_depth", "shortest_call_path", "direct_callers", "direct_callees",
        )
        self.assertEqual(
            {field: baseline[field] for field in stable_fields},
            {field: combined[field] for field in stable_fields},
        )

    def test_source_fingerprint_mismatch_still_fails_closed_for_every_location(self):
        manifest = fixture_manifest()
        manifest[0]["source_tree_sha256"] = "0" * 64
        record = copy.deepcopy(fixture_records()[0])
        record["vulnerable_functions"] = ["vulnerable", "missing"]
        result = analyze_versioned_records([record], manifest, force_fallback=True)
        self.assertEqual(result["call_graphs_constructed"], 0)
        self.assertEqual(len(result["historical_function_mappings"]), 2)
        self.assertTrue(all(
            item["source_version_status"] == "source_version_mismatch"
            for item in result["historical_function_mappings"]
        ))


class HistoricalPreparationTests(unittest.TestCase):
    def test_preparation_scripts_use_portable_python_sha256(self):
        historical = REPO / "security" / "historical"
        for name in ("prepare_coreutils_9_7.sh", "prepare_grep_2_21.sh"):
            with self.subTest(script=name):
                text = (historical / name).read_text()
                self.assertIn("hashlib.sha256", text)
                self.assertNotIn("sha256sum", text)
                self.assertNotIn("shasum", text)

    def test_grep_scripts_do_not_duplicate_frozen_revision(self):
        historical = REPO / "security" / "historical"
        for name in (
            "prepare_grep_2_21.sh",
            "prepare_grep_2_21_scope.sh",
            "derive_grep_scope.py",
        ):
            with self.subTest(script=name):
                self.assertNotIn(GREP_REVISION, (historical / name).read_text())


if __name__ == "__main__":
    unittest.main()
