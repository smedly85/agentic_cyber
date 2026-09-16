from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from analysis.security_diagnostics import (  # noqa: E402
    CONSTRUCT_FIELDS,
    FLAWFINDER_FINDING_FIELDS,
    default_security_configuration,
    parse_flawfinder_csv,
    security_descriptor_occurrences,
    security_profile,
)
from security.common.callgraph import analyze_source_bytes  # noqa: E402
from security.generated_security_depth_localization import (  # noqa: E402
    FROZEN_CANDIDATE_POPULATION_SHA256,
    FROZEN_STRUCTURAL_CENSUS_SHA256,
    LocalizationError,
    _analyze_candidate_functions,
    _localize_descriptors,
    _localize_findings,
    aggregate_localization,
    compare_summaries,
    flawfinder_position_to_tree_sitter,
    localize_source_position,
    run_localization,
)
from security.generated_structural_census import (  # noqa: E402
    content_sha256,
    load_manifest,
    run_census,
)


SOURCE = b"""/* outside */
static int deep(char *p) {
    char buffer[16];
    strcpy(buffer, p);
    strncpy(buffer, p, 15);
    memcpy(buffer, p, 1);
    char *heap = malloc(4);
    free(heap);
    return p[0];
}
static int direct(char *p) { return deep(p); }
int main(void) { return direct("x"); }
"""


def analyzed_functions(source: bytes = SOURCE):
    analysis = analyze_source_bytes(source, include_source_columns=True)
    if analysis["analysis_method"] != "tree_sitter":
        raise unittest.SkipTest("Tree-sitter unavailable")
    resolved = analysis["resolved_entry_points"]
    functions = []
    for raw in analysis["function_reachability"]:
        row = dict(raw)
        row["_resolved_entry_points"] = resolved
        functions.append(row)
    return analysis, functions


def finding(line: int, column: int, fingerprint: str = "f"):
    return {
        "run_id": "candidate-a",
        "source_identifier": "runs/formal/candidate.c",
        "reported_filename": "candidate.c",
        "line": line,
        "column": column,
        "default_level": 2,
        "level": 3,
        "category": "buffer",
        "rule_name": "strcpy",
        "warning": "warning",
        "suggestion": "suggestion",
        "note": "note",
        "cwe_ids": '["CWE-120"]',
        "context": "strcpy(buffer, p);",
        "flawfinder_fingerprint": fingerprint,
        "tool_version": "2.0.20",
        "rule_id": "FF1001",
        "help_uri": "https://example.invalid/FF1001",
    }


def candidate(identifier="candidate-a", utility="sort", checkpoint="000", **updates):
    row = {
        "candidate_id": identifier,
        "utility": utility,
        "checkpoint": checkpoint,
        "checkpoint_name": "base",
        "lineage": "lineage-001",
        "formal_run_id": f"{utility}-formal",
        "source_identifier": f"runs/formal/{identifier}.c",
        "candidate_sha256": "a" * 64,
        "structural_status": "available",
        "descriptor_status": "available",
        "flawfinder_status": "available",
    }
    row.update(updates)
    return row


class FlawfinderMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis, cls.functions = analyzed_functions()

    def mapping(self, line, column=1):
        return localize_source_position(
            source=SOURCE,
            line=line,
            column=column,
            functions=self.functions,
            column_semantics="flawfinder_one_based_character",
        )

    def test_entry_direct_and_deeper_functions_map_to_exact_raw_depth(self):
        self.assertEqual(self.mapping(12, 1)["raw_call_depth"], 0)
        self.assertTrue(self.mapping(12, 1)["entry_point"])
        self.assertEqual(self.mapping(11, 1)["raw_call_depth"], 1)
        self.assertEqual(self.mapping(4, 5)["raw_call_depth"], 2)

    def test_outside_invalid_ambiguous_and_nonnumeric_are_explicit(self):
        self.assertEqual(
            self.mapping(1, 1)["function_mapping_status"], "outside_function"
        )
        invalid = self.mapping(999, 1)
        self.assertEqual(invalid["function_mapping_status"], "invalid_source_location")
        overlapping = [
            {
                "function_id": name, "function": name, "start_line": 1,
                "end_line": 1, "start_column": 0, "end_column": 20,
                "call_depth": depth, "reachable_from_entry": depth is not None,
                "shortest_call_path": None, "_resolved_entry_points": [],
            }
            for name, depth in (("one", 0), ("two", 1))
        ]
        ambiguous = localize_source_position(
            source=b"strcpy(x, y);\n", line=1, column=1,
            functions=overlapping,
            column_semantics="flawfinder_one_based_character",
        )
        self.assertEqual(ambiguous["function_mapping_status"], "ambiguous_function")
        nonnumeric = dict(overlapping[0], end_column=5, call_depth=None)
        mapped = localize_source_position(
            source=b"abcde     \n", line=1, column=1, functions=[nonnumeric],
            column_semantics="flawfinder_one_based_character",
        )
        self.assertEqual(
            mapped["function_mapping_status"], "mapped_without_numeric_depth"
        )
        self.assertIsNone(mapped["raw_call_depth"])

    def test_column_conversion_is_one_based_character_to_zero_based_utf8_byte(self):
        self.assertEqual(
            flawfinder_position_to_tree_sitter("\u00e9  strcpy\n".encode(), 1, 4),
            (0, 4, None),
        )
        self.assertIsNotNone(flawfinder_position_to_tree_sitter(b"abc\n", 1, 0)[2])
        self.assertIsNotNone(flawfinder_position_to_tree_sitter(b"abc\n", 1, 4)[2])

    def test_original_flawfinder_fields_and_cwe_level_metadata_survive(self):
        csv_text = (
            "File,Line,Column,DefaultLevel,Level,Category,Name,Warning,Suggestion,"
            "Note,CWEs,Context,Fingerprint,ToolVersion,RuleId,HelpUri\n"
            'candidate.c,4,5,2,3,buffer,strcpy,warn,suggest,note,"CWE-120 CWE-20",'
            'context,fp,2.0.20,FF1001,https://example.invalid/help\n'
        )
        parsed = parse_flawfinder_csv(
            csv_text, run_id="candidate-a", source_identifier="runs/formal/candidate.c"
        )[0]
        metadata = {
            "candidate_id": "candidate-a", "utility": "sort",
            "checkpoint_id": "000", "checkpoint_name": "base",
            "lineage_id": "lineage-001", "formal_run_id": "sort-formal",
            "candidate_source": "runs/formal/candidate.c",
            "candidate_source_sha256": "a" * 64,
        }
        localized = _localize_findings([parsed], metadata, SOURCE, self.functions)[0]
        self.assertEqual(
            {field: localized[field] for field in FLAWFINDER_FINDING_FIELDS}, parsed
        )
        self.assertEqual(localized["cwe_ids"], '["CWE-20","CWE-120"]')
        self.assertEqual(localized["level"], 3)

    def test_finding_rows_have_stable_order(self):
        metadata = {
            "candidate_id": "candidate-a", "utility": "sort",
            "checkpoint_id": "000", "checkpoint_name": "base",
            "lineage_id": "lineage-001", "formal_run_id": "sort-formal",
            "candidate_source": "runs/formal/candidate.c",
            "candidate_source_sha256": "a" * 64,
        }
        rows = _localize_findings(
            [finding(11, 1, "z"), finding(4, 5, "a")],
            metadata, SOURCE, self.functions,
        )
        self.assertEqual([(row["line"], row["flawfinder_fingerprint"]) for row in rows], [(4, "a"), (11, "z")])


class DescriptorOccurrenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis, cls.functions = analyzed_functions()

    def test_all_existing_descriptor_classes_localize_and_reaggregate(self):
        occurrences = security_descriptor_occurrences(SOURCE)
        counts = Counter(row["descriptor"] for row in occurrences)
        expected = {
            "unsafe_call_count": 1,
            "bounded_risky_call_count": 2,
            "heap_allocation_deallocation_call_count": 2,
            "fixed_size_stack_buffer_count": 1,
            "indexing_operation_count": 1,
        }
        self.assertEqual(security_profile(SOURCE), expected)
        self.assertEqual({field: counts[field] for field in CONSTRUCT_FIELDS}, expected)
        metadata = {
            "candidate_id": "candidate-a", "utility": "sort",
            "checkpoint_id": "000", "checkpoint_name": "base",
            "lineage_id": "lineage-001", "formal_run_id": "sort-formal",
            "candidate_source": "runs/formal/candidate.c",
            "candidate_source_sha256": "a" * 64,
        }
        rows, profile = _localize_descriptors(
            metadata, SOURCE, self.functions, default_security_configuration()
        )
        self.assertEqual(profile, expected)
        self.assertEqual(len(rows), sum(expected.values()))
        self.assertTrue(all(row["function_mapping_status"] == "mapped" for row in rows))
        self.assertTrue(all(row["raw_call_depth"] == 2 for row in rows))
        symbols = {row["specific_symbol"] for row in rows if row["specific_symbol"]}
        self.assertEqual(symbols, {"strcpy", "strncpy", "memcpy", "malloc", "free"})

    def test_indexing_outside_function_is_retained(self):
        source = b"int global = values[0];\nint main(void) { return 0; }\n"
        _, functions = analyzed_functions(source)
        metadata = {
            "candidate_id": "candidate-a", "utility": "sort",
            "checkpoint_id": "000", "checkpoint_name": "base",
            "lineage_id": "lineage-001", "formal_run_id": "sort-formal",
            "candidate_source": "runs/formal/candidate.c",
            "candidate_source_sha256": "a" * 64,
        }
        rows, _ = _localize_descriptors(
            metadata, source, functions, default_security_configuration()
        )
        indexing = next(row for row in rows if row["descriptor"] == "indexing_operation_count")
        self.assertEqual(indexing["function_mapping_status"], "outside_function")
        self.assertIsNone(indexing["raw_call_depth"])


class AggregationTests(unittest.TestCase):
    def structural(self):
        return [
            {
                "candidate_id": "candidate-a", "call_depth": 0,
                "lines_of_code": 10, "ast_node_count": 20,
            },
            {
                "candidate_id": "candidate-b", "call_depth": 0,
                "lines_of_code": 20, "ast_node_count": 30,
            },
        ]

    def localized_finding(self, identifier, utility, checkpoint, fingerprint):
        return {
            "candidate_id": identifier, "utility": utility,
            "checkpoint": checkpoint, "raw_call_depth": 0,
            "function_mapping_status": "mapped", "level": 2,
            "cwe_ids": '["CWE-120"]', "flawfinder_fingerprint": fingerprint,
        }

    def test_finding_and_candidate_denominators_are_distinct_and_group_totals_reconcile(self):
        candidates = [
            candidate("candidate-a", "sort", "000"),
            candidate("candidate-b", "grep", "001"),
        ]
        findings = [
            self.localized_finding("candidate-a", "sort", "000", "one"),
            self.localized_finding("candidate-a", "sort", "000", "two"),
        ]
        opportunities, finding_rows, _ = aggregate_localization(
            candidates, self.structural(), findings, []
        )
        overall = next(row for row in finding_rows if row["group_type"] == "overall" and row["depth_category"] == "0")
        self.assertEqual(overall["finding_count"], 2)
        self.assertEqual(overall["candidates_with_at_least_one_finding"], 1)
        self.assertEqual(overall["candidate_prevalence"], 0.5)
        self.assertEqual(overall["function_count_denominator"], 2)
        self.assertEqual(overall["physical_LOC_denominator"], 30)
        utilities = [row for row in finding_rows if row["group_type"] == "utility" and row["depth_category"] == "0"]
        stages = [row for row in finding_rows if row["group_type"] == "stage" and row["depth_category"] == "0"]
        self.assertEqual(sum(row["finding_count"] for row in utilities), overall["finding_count"])
        self.assertEqual(sum(row["finding_count"] for row in stages), overall["finding_count"])
        opportunity = next(row for row in opportunities if row["group_type"] == "overall")
        self.assertEqual(opportunity["candidate_count_with_depth"], 2)

    def test_incomplete_coverage_never_becomes_zero_and_disables_density(self):
        candidates = [
            candidate("candidate-a"),
            candidate(
                "candidate-b", utility="grep", checkpoint="001",
                flawfinder_status="unavailable", descriptor_status="unavailable",
            ),
        ]
        findings = [self.localized_finding("candidate-a", "sort", "000", "one")]
        _, finding_rows, descriptor_rows = aggregate_localization(
            candidates, self.structural(), findings, []
        )
        overall = next(row for row in finding_rows if row["group_type"] == "overall" and row["depth_category"] == "0")
        self.assertEqual(overall["measured_candidate_count"], 1)
        self.assertEqual(overall["eligible_candidate_count"], 2)
        self.assertEqual(overall["measurement_coverage"], 0.5)
        self.assertIsNone(overall["candidate_prevalence"])
        self.assertIsNone(overall["findings_per_KLOC_at_depth"])
        descriptor = next(row for row in descriptor_rows if row["group_type"] == "overall")
        self.assertIsNone(descriptor["candidate_prevalence"])


class IntegrityAndDeterminismTests(unittest.TestCase):
    def test_hash_mismatch_is_rejected_before_localization(self):
        source = b"int main(void) { return 0; }\n"
        candidate_row = {
            "candidate_id": "c", "candidate_source": "candidate.c",
            "candidate_source_sha256": "0" * 64,
        }
        with mock.patch(
            "security.generated_security_depth_localization.repository_candidate_bytes",
            return_value=(source, "filesystem_bytes"),
        ):
            with self.assertRaisesRegex(LocalizationError, "hash mismatch"):
                _analyze_candidate_functions(candidate_row, REPO, [])

    def test_formal_tree_sitter_fallback_is_rejected(self):
        with self.assertRaisesRegex(LocalizationError, "fallback rejected"):
            run_localization({}, REPO, force_fallback=True)

    def test_changed_or_wrong_version_security_configuration_is_rejected(self):
        configuration = default_security_configuration()
        configuration["expected_flawfinder_version"] = "9.9.9"
        with self.assertRaisesRegex(LocalizationError, "frozen security configuration"):
            run_localization({}, REPO, security_configuration=configuration)

    def test_wrong_scanner_version_remains_explicitly_unavailable_in_formal_mode(self):
        source = b"int main(void) { return 0; }\n"
        digest = hashlib.sha256(source).hexdigest()
        frozen_candidate = {
            "candidate_id": "formal/lineage-001/000",
            "formal_run_id": "formal", "lineage_id": "lineage-001",
            "checkpoint_id": "000", "checkpoint_name": "base",
            "utility": "sort", "candidate_source": "candidate.c",
            "candidate_source_sha256": digest,
        }
        manifest = {"candidate_population_sha256": "p" * 64, "candidates": [frozen_candidate]}
        structural = {
            "structural_census_sha256": "s" * 64,
            "scientific_results": {
                "candidate_rows": [{
                    "candidate_id": frozen_candidate["candidate_id"],
                    "analysis_status": "analyzed", "unavailable_reason": None,
                    "analysis_method": "tree_sitter",
                }],
                "function_rows": [],
            },
        }
        unavailable_scan = {
            "status": "unavailable", "reason": "version_mismatch",
            "version": "9.9.9", "expected_version": "2.0.20",
            "executable_path": "/scanner", "executable_identifier": "flawfinder",
            "options": [],
        }
        empty_profile = {field: 0 for field in CONSTRUCT_FIELDS}
        with (
            mock.patch(
                "security.generated_security_depth_localization.run_census",
                return_value=(structural, {}),
            ),
            mock.patch(
                "security.generated_security_depth_localization.flawfinder_provenance",
                return_value=unavailable_scan,
            ),
            mock.patch(
                "security.generated_security_depth_localization._analyze_candidate_functions",
                return_value=(source, []),
            ),
            mock.patch(
                "security.generated_security_depth_localization._localize_descriptors",
                return_value=([], empty_profile),
            ),
            mock.patch(
                "security.generated_security_depth_localization._scan_source_bytes",
                return_value={
                    "status": "unavailable", "reason": "version_mismatch",
                    "findings": None,
                },
            ),
        ):
            summary, _ = run_localization(
                manifest, REPO, formal=True, host_role="vessel"
            )
        row = summary["scientific_results"]["candidate_rows"][0]
        self.assertEqual(row["flawfinder_status"], "unavailable")
        self.assertEqual(row["flawfinder_unavailable_reason"], "version_mismatch")
        self.assertIsNone(row["flawfinder_finding_count"])

    def test_missing_candidate_remains_in_localization_denominator(self):
        frozen_candidate = {
            "candidate_id": "formal/lineage-001/000",
            "formal_run_id": "formal", "lineage_id": "lineage-001",
            "checkpoint_id": "000", "checkpoint_name": "base",
            "utility": "sort", "candidate_source": "missing.c",
            "candidate_source_sha256": "a" * 64,
        }
        manifest = {"candidate_population_sha256": "p" * 64, "candidates": [frozen_candidate]}
        structural = {
            "structural_census_sha256": "s" * 64,
            "scientific_results": {
                "candidate_rows": [{
                    "candidate_id": frozen_candidate["candidate_id"],
                    "analysis_status": "unavailable",
                    "unavailable_reason": "frozen_candidate_source_missing",
                    "analysis_method": None,
                }],
                "function_rows": [],
            },
        }
        with (
            mock.patch(
                "security.generated_security_depth_localization.run_census",
                return_value=(structural, {}),
            ),
            mock.patch(
                "security.generated_security_depth_localization.flawfinder_provenance",
                return_value={
                    "status": "unavailable", "reason": "flawfinder_not_found",
                    "version": None, "executable_path": None,
                },
            ),
        ):
            summary, _ = run_localization(manifest, REPO)
        rows = summary["scientific_results"]["candidate_rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["structural_status"], "unavailable")
        self.assertEqual(
            rows[0]["flawfinder_unavailable_reason"],
            "frozen_candidate_source_missing",
        )

    def test_host_only_provenance_does_not_change_scientific_comparison(self):
        science = {"finding_rows": [], "descriptor_occurrence_rows": []}
        left = {
            "candidate_population_sha256": "p", "structural_census_sha256": "s",
            "security_depth_localization_sha256": content_sha256(science),
            "scientific_results": science,
        }
        right = copy.deepcopy(left)
        result = compare_summaries(
            left, right, {"host_name": "wsl"}, {"host_name": "vessel"}
        )
        self.assertTrue(result["scientific_results_identical"])
        self.assertEqual(len(result["environment_differences"]), 1)
        changed = copy.deepcopy(right)
        changed["scientific_results"]["finding_rows"] = [{"raw_call_depth": 1}]
        changed["security_depth_localization_sha256"] = content_sha256(changed["scientific_results"])
        self.assertFalse(compare_summaries(left, changed)["scientific_results_identical"])

    def test_frozen_structural_population_and_entry_only_candidates_remain_exact(self):
        manifest = load_manifest(REPO / "security/generated_candidate_population.json")
        self.assertEqual(manifest["candidate_population_sha256"], FROZEN_CANDIDATE_POPULATION_SHA256)
        summary, _ = run_census(manifest, REPO, host_role="other")
        self.assertEqual(summary["structural_census_sha256"], FROZEN_STRUCTURAL_CENSUS_SHA256)
        science = summary["scientific_results"]
        overall = science["aggregates"]["overall"][0]
        self.assertEqual(overall["candidate_count"], 140)
        self.assertEqual(sum(row["defined_function_count"] for row in science["candidate_rows"]), 1000)
        self.assertEqual(
            {row["call_depth"]: row["function_count"] for row in science["depth_distribution"]},
            {0: 140, 1: 456, 2: 386, 3: 18},
        )
        self.assertEqual(
            sum(row["entry_point_only_reachable"] for row in science["candidate_rows"]),
            7,
        )


if __name__ == "__main__":
    unittest.main()
