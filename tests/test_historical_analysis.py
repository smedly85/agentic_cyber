from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from security.common.callgraph import analyze_source_bytes, analyze_sources
from security.historical.analysis import (
    HistoricalDataError,
    ProgramAnalysisError,
    _resolve_program_scope,
    analyze_versioned_records,
    load_census,
    load_records,
    load_source_manifest,
    map_record_to_graph,
    summarize_census,
    summarize_historical_analysis,
    source_tree_sha256,
    validate_record,
    validate_source_manifest,
    verify_source_tree_sha256,
    version_specific_hvc,
)
from security.historical.downstream import (
    DownstreamSourceError,
    file_sha256,
    rpm_patch_sequence,
    verify_packaging_components,
)
from security.historical.derive_coreutils_mkdir_scope import verify_frozen_source_files
from security.historical.run_historical_analysis import parse_args


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "historical"
SCHEMA = json.loads((REPO / "security" / "historical" / "schema.json").read_text())
GREP_REVISION = next(
    item["source_revision"]
    for item in json.loads(
        (REPO / "security" / "historical" / "source_manifest.json").read_text()
    )
    if item["upstream_project"] == "gnu-grep"
    and item["affected_version"] == "2.21"
)
GREP_210_REVISION = next(
    item["source_revision"]
    for item in json.loads(
        (REPO / "security" / "historical" / "source_manifest.json").read_text()
    )
    if item["upstream_project"] == "gnu-grep"
    and item["affected_version"] == "2.10"
)
MKDIR_REVISION = next(
    item["source_revision"]
    for item in json.loads(
        (REPO / "security" / "historical" / "source_manifest.json").read_text()
    )
    if item["upstream_project"] == "gnu-coreutils"
    and item["affected_version"] == "5.2.1"
)
FEDORA_REVISION = next(
    item["downstream_revision"]
    for item in json.loads(
        (REPO / "security" / "historical" / "source_manifest.json").read_text()
    )
    if item.get("source_provenance") == "downstream_patch"
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


def mkdir_fixture():
    record = copy.deepcopy(fixture_records()[1])
    record.update({
        "id": "SYNTHETIC-MKDIR",
        "utility": "mkdir",
        "upstream_project": "gnu-coreutils",
        "affected_version": "fixture-mkdir",
        "source_revision": "c" * 40,
    })
    manifest = copy.deepcopy(fixture_manifest()[1])
    manifest.update({
        "upstream_project": "gnu-coreutils",
        "affected_version": "fixture-mkdir",
        "source_revision": "c" * 40,
    })
    manifest["programs"] = {"mkdir": manifest["programs"].pop("sort")}
    return record, manifest


def grep_210_fixture():
    record = copy.deepcopy(fixture_records()[0])
    record.update({
        "id": "SYNTHETIC-GREP-210",
        "utility": "grep",
        "upstream_project": "gnu-grep",
        "affected_version": "fixture-grep-2.10",
        "source_revision": "e" * 40,
    })
    manifest = copy.deepcopy(fixture_manifest()[0])
    manifest.update({
        "upstream_project": "gnu-grep",
        "affected_version": "fixture-grep-2.10",
        "source_revision": "e" * 40,
    })
    manifest["programs"] = {"grep": manifest["programs"].pop("sort")}
    return record, manifest


def downstream_sort_fixture():
    record = copy.deepcopy(fixture_records()[0])
    record.update({
        "id": "SYNTHETIC-DOWNSTREAM-A",
        "affected_version": "fixture-1.fc",
        "fixed_version": "fixture-2.fc",
        "source_provenance": "downstream_patch",
        "upstream_base_version": "fixture-upstream",
        "downstream_revision": "f" * 40,
    })
    manifest = copy.deepcopy(fixture_manifest()[0])
    manifest["source_tree"] = manifest.pop("resolved_source_tree")
    manifest.update({
        "affected_version": "fixture-1.fc",
        "source_provenance": "downstream_patch",
        "upstream_base_version": "fixture-upstream",
        "downstream_revision": "f" * 40,
        "downstream_source": {
            "distribution": "Fixture Linux",
            "source_package": "fixture.src.rpm",
            "packaging_repository": "https://example.invalid/fixture.git",
            "spec_file": "fixture.spec",
            "spec_sha256": "1" * 64,
            "security_patch_file": "security.patch",
            "security_patch_sha256": "2" * 64,
            "security_patch_git_blob": "3" * 40,
            "upstream_archive_sha256": "4" * 64,
            "upstream_signature_sha256": "5" * 64,
        },
    })
    return record, manifest


def cve_2012_graph_and_record():
    analyzed = analyze_sources([
        (
            "src/main.c",
            b"static void (*compile)(void); static void (*execute)(void);\n"
            b"static void prtext(void) {}\n"
            b"static void do_execute(void) { execute(); }\n"
            b"static void grepbuf(void) { do_execute(); prtext(); }\n"
            b"static void grep(void) { grepbuf(); }\n"
            b"static void grepfile(void) { grep(); }\n"
            b"static void prepend_args(void) {}\n"
            b"static void prepend_default_options(void) { prepend_args(); }\n"
            b"int main(void) { compile(); prepend_default_options(); grepfile(); return 0; }\n",
        ),
        (
            "src/dfa.c",
            b"static void lex(void) {}\n"
            b"void dfaparse(void) { lex(); }\n",
        ),
        (
            "src/grep.c",
            b"void dfaparse(void);\n"
            b"void Gcompile(void) { dfaparse(); }\n",
        ),
        ("src/dfasearch.c", b"void EGexecute(void) {}\n"),
        ("lib/argmatch.c", b"int main(void) { return 0; }\n"),
    ], entry_points=("src/main.c::main",), force_fallback=True)
    record = sample_record(["EGexecute"])
    record.update({
        "id": "CVE-2012-5667",
        "utility": "grep",
        "upstream_project": "gnu-grep",
        "patched_functions": [
            "lex", "EGexecute", "prtext", "grepbuf", "grep", "prepend_args",
            "prepend_default_options", "main",
        ],
    })
    dispatches = [
        {
            "caller": {"source_file": "src/main.c", "function": "main"},
            "callee_text": "compile",
            "possible_target": {
                "source_file": "src/grep.c", "function": "Gcompile",
            },
        },
        {
            "caller": {"source_file": "src/main.c", "function": "do_execute"},
            "callee_text": "execute",
            "possible_target": {
                "source_file": "src/dfasearch.c", "function": "EGexecute",
            },
        },
    ]
    return analyzed, record, dispatches


def graph(source):
    return analyze_source_bytes(source.replace("} ", "}\n"), force_fallback=True)


def symlink_or_skip(test: unittest.TestCase, target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            test.skipTest("Windows symlink privilege is unavailable")
        raise


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
            "CVE-2025-5278", "CVE-2015-1345", "CVE-2005-1039",
            "CVE-2012-5667", "CVE-2015-4041", "CVE-2015-4042",
        ])
        self.assertEqual([item["id"] for item in census], [
            "CVE-2025-5278", "CVE-2015-1345", "CVE-2005-1039",
            "CVE-2012-5667", "CVE-2015-4041", "CVE-2015-4042",
            "CVE-2013-0221", "TEMP-0306076-4B7D89", "CVE-2026-35338",
            "CVE-2026-35339", "CVE-2026-35348", "CVE-2026-35353",
        ])
        self.assertEqual(
            [(item["upstream_project"], item["affected_version"]) for item in manifest],
            [
                ("gnu-coreutils", "9.7"),
                ("gnu-grep", "2.21"),
                ("gnu-coreutils", "5.2.1"),
                ("gnu-grep", "2.10"),
                ("gnu-coreutils", "8.23-9.fc22"),
            ],
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
        self.assertEqual(
            grep_source["programs"]["grep"]["declared_indirect_dispatches"],
            [{
                "caller": {"source_file": "src/grep.c", "function": "grepbuf"},
                "callee_text": "execute",
                "possible_target": {
                    "source_file": "src/kwsearch.c", "function": "Fexecute",
                },
            }],
        )
        mkdir_record = next(item for item in records if item["id"] == "CVE-2005-1039")
        mkdir_source = next(
            item for item in manifest
            if item["upstream_project"] == "gnu-coreutils"
            and item["affected_version"] == "5.2.1"
        )
        self.assertEqual(mkdir_record["vulnerable_functions"], ["main", "make_path"])
        self.assertEqual(mkdir_record["fixed_version"], "6.0")
        self.assertEqual(mkdir_source["programs"]["mkdir"]["entry_point"], {
            "source_file": "src/mkdir.c", "function": "main",
        })
        self.assertEqual(len(mkdir_source["programs"]["mkdir"]["source_files"]), 14)
        self.assertIn(
            "lib/makepath.c", mkdir_source["programs"]["mkdir"]["source_files"]
        )
        grep_210_record = next(
            item for item in records if item["id"] == "CVE-2012-5667"
        )
        grep_210_source = next(
            item for item in manifest
            if item["upstream_project"] == "gnu-grep"
            and item["affected_version"] == "2.10"
        )
        self.assertEqual(grep_210_record["vulnerable_functions"], ["EGexecute"])
        formerly_declared = {
            "lex", "prtext", "grepbuf", "grep", "prepend_args",
            "prepend_default_options", "main",
        }
        self.assertTrue(formerly_declared.issubset(
            set(grep_210_record["patched_functions"])
        ))
        self.assertTrue(formerly_declared.isdisjoint(
            grep_210_record["vulnerable_functions"]
        ))
        self.assertEqual(grep_210_record["fixed_version"], "2.11")
        self.assertEqual(grep_210_source["programs"]["grep"]["entry_point"], {
            "source_file": "src/main.c", "function": "main",
        })
        self.assertEqual(len(
            grep_210_source["programs"]["grep"]["source_files"]
        ), 33)
        self.assertEqual(
            grep_210_source["source_revision"], GREP_210_REVISION
        )
        downstream_records = [
            item for item in records
            if item["id"] in {"CVE-2015-4041", "CVE-2015-4042"}
        ]
        self.assertEqual(
            [item["vulnerable_functions"] for item in downstream_records],
            [["keycompare_mb"], ["keycompare_mb"]],
        )
        downstream_source = next(
            item for item in manifest
            if item.get("source_provenance") == "downstream_patch"
        )
        self.assertEqual(downstream_source["downstream_revision"], FEDORA_REVISION)
        self.assertEqual(
            len(downstream_source["programs"]["sort"]["source_files"]), 46
        )
        self.assertEqual(downstream_source["programs"]["sort"]["entry_point"], {
            "source_file": "src/sort.c", "function": "main",
        })
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

    def test_duplicate_source_manifest_identity_is_rejected(self):
        entry = json.loads((FIXTURES / "source_manifest.json").read_text())[0]
        errors = validate_source_manifest([entry, copy.deepcopy(entry)])
        self.assertEqual(errors, [
            "source 1: duplicate source identity: "
            f"{entry['upstream_project']}/{entry['affected_version']}/"
            f"{entry['source_revision']}"
        ])

    def test_discovery_dispositions_do_not_leak_into_analysis_records(self):
        census = load_census(REPO / "security/historical/cve_census.json")
        records = load_records(REPO / "security/historical/records.json")
        analysis_ids = {item["id"] for item in records}
        noneligible = {
            item["id"] for item in census
            if item["analysis_eligibility"] != "eligible"
        }
        self.assertTrue(noneligible)
        self.assertTrue(noneligible.isdisjoint(analysis_ids))
        self.assertIn("CVE-2013-0221", noneligible)
        self.assertIn("TEMP-0306076-4B7D89", noneligible)

    def test_temporary_identifier_is_outside_cve_denominator(self):
        summary = summarize_census(
            load_census(REPO / "security/historical/cve_census.json")
        )
        self.assertEqual(summary["discovery_entry_count"], 12)
        self.assertEqual(summary["cve_identifier_count"], 11)
        self.assertEqual(summary["temporary_identifier_count"], 1)
        self.assertEqual(summary["eligibility_counts"], {
            "eligible": 6, "excluded": 5, "unresolved": 1,
        })

    def test_downstream_schema_requires_complete_separate_identity(self):
        record, manifest = downstream_sort_fixture()
        self.assertEqual(validate_record(record), [])
        self.assertEqual(validate_source_manifest([manifest]), [])
        del record["downstream_revision"]
        self.assertIn(
            "downstream_revision is required for downstream_patch provenance",
            validate_record(record),
        )

    def test_checked_in_upstream_identities_declare_provenance_explicitly(self):
        records = load_records(REPO / "security/historical/records.json")
        manifest = load_source_manifest(
            REPO / "security/historical/source_manifest.json"
        )
        for collection in (records, manifest):
            upstream = [
                item for item in collection
                if item.get("source_provenance") != "downstream_patch"
            ]
            self.assertTrue(upstream)
            self.assertTrue(all(
                item.get("source_provenance") == "upstream_gnu"
                for item in upstream
            ))


class MultiFunctionMappingTests(unittest.TestCase):
    def test_program_scope_rejects_parent_traversal_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_tree = base / "source"
            source_tree.mkdir()
            (source_tree / "entry.c").write_text("int main(void) { return 0; }\n")
            outside = base / "outside.c"
            outside.write_text("void outside(void) {}\n")
            with self.assertRaises(ProgramAnalysisError) as raised:
                _resolve_program_scope(source_tree, {
                    "entry_point": {
                        "source_file": "entry.c", "function": "main",
                    },
                    "source_files": ["../outside.c"],
                })
            self.assertEqual(raised.exception.status, "analysis_scope_invalid")

            escaped = source_tree / "escaped.c"
            symlink_or_skip(self, outside, escaped)
            with self.assertRaises(ProgramAnalysisError) as raised:
                _resolve_program_scope(source_tree, {
                    "entry_point": {
                        "source_file": "entry.c", "function": "main",
                    },
                    "source_files": ["entry.c", "escaped.c"],
                })
            self.assertEqual(raised.exception.status, "analysis_scope_invalid")

    def test_same_file_fallback_is_explicit_for_duplicate_function_names(self):
        analyzed = analyze_sources([
            (
                "caller.c",
                b"static void duplicate(void) {}\n"
                b"static void caller(void) { duplicate(); }\n"
                b"int main(void) { caller(); return 0; }\n",
            ),
            ("other.c", b"static void duplicate(void) {}\n"),
        ], entry_points=("caller.c::main",), force_fallback=True)
        caller = next(
            item for item in analyzed["function_reachability"]
            if item["function"] == "caller"
        )
        self.assertEqual(caller["direct_callees"], ["caller.c::duplicate"])
        self.assertNotIn({
            "caller": "caller",
            "callee_text": "duplicate",
            "reason": "ambiguous_target",
        }, analyzed["unresolved_direct_calls"])

    def test_two_coreutils_versions_and_grep_resolve_independently(self):
        coreutils_record = fixture_records()[0]
        coreutils_manifest = fixture_manifest()[0]
        grep_record, grep_manifest = grep_fixture()
        mkdir_record, mkdir_manifest = mkdir_fixture()
        combined = analyze_versioned_records(
            [coreutils_record, grep_record, mkdir_record],
            [coreutils_manifest, grep_manifest, mkdir_manifest],
            force_fallback=True,
        )
        rows = {
            item["vulnerability_id"]: item
            for item in combined["historical_function_mappings"]
        }
        self.assertEqual(combined["call_graphs_constructed"], 3)
        self.assertEqual(rows["SYNTHETIC-A"]["call_depth"], 1)
        self.assertEqual(rows["SYNTHETIC-GREP"]["call_depth"], 2)
        self.assertEqual(rows["SYNTHETIC-GREP"]["mapped_source_file"], "program.c")
        self.assertEqual(rows["SYNTHETIC-MKDIR"]["call_depth"], 2)

    def test_grep_210_and_221_identities_and_graph_caches_are_independent(self):
        grep_221_record, grep_221_manifest = grep_fixture()
        grep_210_record, grep_210_manifest = grep_210_fixture()
        combined = analyze_versioned_records(
            [grep_210_record, grep_221_record],
            [grep_221_manifest, grep_210_manifest],
            force_fallback=True,
        )
        rows = {
            item["vulnerability_id"]: item
            for item in combined["historical_function_mappings"]
        }
        self.assertEqual(combined["call_graphs_constructed"], 2)
        self.assertEqual(combined["call_graph_cache_hits"], 0)
        self.assertNotEqual(
            rows["SYNTHETIC-GREP-210"]["source_analysis_id"],
            rows["SYNTHETIC-GREP"]["source_analysis_id"],
        )
        self.assertNotEqual(
            rows["SYNTHETIC-GREP-210"]["source_tree"],
            rows["SYNTHETIC-GREP"]["source_tree"],
        )
        self.assertEqual(rows["SYNTHETIC-GREP-210"]["affected_version"],
                         "fixture-grep-2.10")

        wrong_manifest = copy.deepcopy(grep_221_manifest)
        wrong_manifest["affected_version"] = "fixture-grep-2.10"
        mismatch = analyze_versioned_records(
            [grep_210_record], [wrong_manifest], force_fallback=True
        )
        self.assertEqual(
            mismatch["historical_function_mappings"][0]["source_version_status"],
            "source_version_mismatch",
        )
        self.assertEqual(mismatch["call_graphs_constructed"], 0)

    def test_downstream_and_upstream_source_identities_coexist(self):
        upstream_record = fixture_records()[0]
        upstream_manifest = fixture_manifest()[0]
        downstream_record, downstream_manifest = downstream_sort_fixture()
        result = analyze_versioned_records(
            [upstream_record, downstream_record],
            [upstream_manifest, downstream_manifest],
            force_fallback=True,
        )
        self.assertEqual(result["call_graphs_constructed"], 2)
        self.assertEqual(result["call_graph_cache_hits"], 0)
        rows = result["historical_function_mappings"]
        self.assertNotEqual(rows[0]["source_analysis_id"], rows[1]["source_analysis_id"])

    def test_downstream_identity_matching_includes_packaging_revision(self):
        record, manifest = downstream_sort_fixture()
        changed = copy.deepcopy(record)
        changed["downstream_revision"] = "a" * 40
        result = analyze_versioned_records([changed], [manifest], force_fallback=True)
        row = result["historical_function_mappings"][0]
        self.assertEqual(row["source_version_status"], "source_version_mismatch")
        self.assertEqual(result["call_graphs_constructed"], 0)

    def test_distinct_downstream_revisions_do_not_share_graph_cache(self):
        first_record, first_manifest = downstream_sort_fixture()
        second_record = copy.deepcopy(first_record)
        second_manifest = copy.deepcopy(first_manifest)
        second_record.update({
            "id": "SYNTHETIC-DOWNSTREAM-B",
            "affected_version": "fixture-2.fc",
            "downstream_revision": "a" * 40,
        })
        second_manifest.update({
            "affected_version": "fixture-2.fc",
            "downstream_revision": "a" * 40,
        })
        result = analyze_versioned_records(
            [first_record, second_record], [first_manifest, second_manifest],
            force_fallback=True,
        )
        self.assertEqual(result["call_graphs_constructed"], 2)
        self.assertEqual(result["call_graph_cache_hits"], 0)

    def test_two_cves_at_same_downstream_function_are_not_collapsed(self):
        first, manifest = downstream_sort_fixture()
        second = copy.deepcopy(first)
        second["id"] = "SYNTHETIC-DOWNSTREAM-B"
        result = analyze_versioned_records(
            [first, second], [manifest], force_fallback=True
        )
        self.assertEqual(result["call_graphs_constructed"], 1)
        self.assertEqual(result["call_graph_cache_hits"], 1)
        rows = result["historical_function_mappings"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [item["vulnerability_id"] for item in rows],
            ["SYNTHETIC-DOWNSTREAM-A", "SYNTHETIC-DOWNSTREAM-B"],
        )
        self.assertEqual(len({item["mapped_function_id"] for item in rows}), 1)
        self.assertEqual(len(result["historical_record_mappings"]), 2)
        summary = summarize_historical_analysis(
            rows, result["historical_record_mappings"]
        )
        self.assertEqual(summary["historical_record_count"], 2)
        self.assertEqual(summary["historical_function_location_count"], 2)

    def test_analyzer_serializes_complete_downstream_provenance(self):
        record, manifest = downstream_sort_fixture()
        result = analyze_versioned_records(
            [record], [manifest], force_fallback=True
        )
        function_row = result["historical_function_mappings"][0]
        record_row = result["historical_record_mappings"][0]
        program_scope = next(iter(result["call_graphs"].values()))[
            "historical_program_scope"
        ]
        for row in (function_row, record_row, program_scope):
            with self.subTest(row_type=row.get("vulnerability_id", "scope")):
                self.assertEqual(row["source_provenance"], "downstream_patch")
                self.assertEqual(row["upstream_base_version"], "fixture-upstream")
                self.assertEqual(row["downstream_revision"], "f" * 40)
                self.assertEqual(
                    row["downstream_source"], manifest["downstream_source"]
                )
                self.assertEqual(
                    row["source_tree_sha256"], manifest["source_tree_sha256"]
                )
        self.assertEqual(function_row["source_revision"], record["source_revision"])
        self.assertNotEqual(
            function_row["source_revision"], function_row["downstream_revision"]
        )

    def test_hvc_detail_serializes_downstream_source_identity(self):
        record, manifest = downstream_sort_fixture()
        versioned = analyze_versioned_records(
            [record], [manifest], force_fallback=True
        )
        hvc = version_specific_hvc(versioned, policy="SHALLOW", k=1)
        detail = hvc["per_vulnerability_selections"][0]
        self.assertEqual(detail["source_provenance"], "downstream_patch")
        self.assertEqual(detail["upstream_base_version"], "fixture-upstream")
        self.assertEqual(detail["downstream_revision"], "f" * 40)
        self.assertEqual(detail["downstream_source"], manifest["downstream_source"])
        self.assertEqual(
            detail["source_tree_sha256"], manifest["source_tree_sha256"]
        )

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

    def test_downstream_source_fingerprint_mismatch_fails_closed(self):
        record, manifest = downstream_sort_fixture()
        manifest["source_tree_sha256"] = "0" * 64
        result = analyze_versioned_records([record], [manifest], force_fallback=True)
        row = result["historical_function_mappings"][0]
        self.assertEqual(row["source_version_status"], "source_version_mismatch")
        self.assertEqual(row["mapping_status"], "source_version_mismatch")
        self.assertEqual(result["call_graphs_constructed"], 0)

    def test_grep_210_fingerprint_mismatch_fails_closed(self):
        record, manifest = grep_210_fixture()
        manifest["source_tree_sha256"] = "0" * 64
        result = analyze_versioned_records([record], [manifest], force_fallback=True)
        row = result["historical_function_mappings"][0]
        self.assertEqual(row["source_version_status"], "source_version_mismatch")
        self.assertEqual(row["mapping_status"], "source_version_mismatch")
        self.assertEqual(result["call_graphs_constructed"], 0)

    def test_mkdir_source_fingerprint_mismatch_fails_closed(self):
        record, manifest = mkdir_fixture()
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

    def test_missing_exact_downstream_source_file_fails_closed(self):
        record, manifest = downstream_sort_fixture()
        program = manifest["programs"]["sort"]
        program["source_files"] = [program.pop("source_globs")[0], "missing.c"]
        result = analyze_versioned_records([record], [manifest], force_fallback=True)
        row = result["historical_function_mappings"][0]
        self.assertEqual(row["mapping_status"], "analysis_scope_invalid")
        self.assertEqual(result["call_graphs_constructed"], 0)

    def test_missing_exact_grep_210_source_file_fails_closed(self):
        record, manifest = grep_210_fixture()
        program = manifest["programs"]["grep"]
        program["source_files"] = [program.pop("source_globs")[0], "missing.c"]
        result = analyze_versioned_records([record], [manifest], force_fallback=True)
        row = result["historical_function_mappings"][0]
        self.assertEqual(row["mapping_status"], "analysis_scope_invalid")
        self.assertEqual(result["call_graphs_constructed"], 0)

    def test_missing_exact_mkdir_source_file_fails_closed(self):
        record, manifest = mkdir_fixture()
        program = manifest["programs"]["mkdir"]
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

    def test_cve_2012_zero_numeric_depth_remains_explicitly_represented(self):
        analyzed, record, dispatches = cve_2012_graph_and_record()
        result = map_record_to_graph(
            record, analyzed, declared_indirect_dispatches=dispatches
        )
        rows = {
            item["vulnerable_function"]: item
            for item in result["function_mappings"]
        }
        self.assertEqual(list(rows), record["vulnerable_functions"])
        self.assertEqual(result["successfully_mapped_function_count"], 1)
        self.assertEqual(result["reachable_vulnerable_function_count"], 0)
        self.assertIsNone(result["minimum_reachable_call_depth"])
        self.assertIsNone(result["maximum_reachable_call_depth"])
        self.assertEqual(result["mapping_status"],
                         "mapped_without_resolved_static_path")
        self.assertEqual(rows["EGexecute"]["mapping_status"],
                         "mapped_without_resolved_static_path")
        self.assertEqual(rows["EGexecute"]["call_depth_status"],
                         "unresolved_indirect_dispatch")
        self.assertIsNone(rows["EGexecute"]["call_depth"])

        summary = summarize_historical_analysis(
            result["function_mappings"], [result]
        )
        self.assertEqual(
            summary["vulnerable_function_location_depth_distribution"],
            {},
        )
        self.assertEqual(
            summary["per_cve_shallowest_reachable_depth_distribution"],
            {},
        )
        self.assertEqual(summary["historical_record_count"], 1)
        self.assertEqual(summary["historical_function_location_count"], 1)
        self.assertEqual(summary["cve_mapping_status_counts"], {
            "mapped_without_resolved_static_path": 1,
        })
        self.assertEqual(summary["function_mapping_status_counts"], {
            "mapped_without_resolved_static_path": 1,
        })
        self.assertEqual(summary["function_call_depth_status_counts"], {
            "unresolved_indirect_dispatch": 1,
        })
        self.assertEqual(summary["reachable_mapped_vulnerability_count"], 0)

        # Reachable functions that are merely patch provenance do not enter
        # either depth distribution.
        for patched_only in (
            "lex", "prtext", "grepbuf", "grep", "prepend_args",
            "prepend_default_options", "main",
        ):
            self.assertIn(patched_only, record["patched_functions"])
            self.assertNotIn(patched_only, rows)

    def test_cve_2012_missing_or_ambiguous_sibling_does_not_erase_mappings(self):
        analyzed, record, dispatches = cve_2012_graph_and_record()
        missing_record = copy.deepcopy(record)
        missing_record["vulnerable_functions"] = [
            *missing_record["vulnerable_functions"], "missing",
        ]
        missing = map_record_to_graph(
            missing_record, analyzed, declared_indirect_dispatches=dispatches
        )
        self.assertEqual(missing["successfully_mapped_function_count"], 1)
        self.assertEqual(missing["function_mappings"][-1]["mapping_status"],
                         "function_not_found")
        self.assertEqual(
            missing["function_mappings"][0]["mapping_status"],
            "mapped_without_resolved_static_path",
        )
        self.assertIsNone(missing["function_mappings"][0]["call_depth"])

        ambiguous_graph = analyze_sources([
            ("first.c", b"static void EGexecute(void) {}\n"),
            ("second.c", b"static void EGexecute(void) {}\n"),
            ("main.c", b"int main(void) { return 0; }\n"),
        ], force_fallback=True)
        ambiguous = map_record_to_graph(
            sample_record(["EGexecute"]), ambiguous_graph
        )["function_mappings"][0]
        self.assertEqual(ambiguous["mapping_status"], "ambiguous_function_name")
        self.assertIsNone(ambiguous["mapped_function_id"])

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

    def test_resolved_and_missing_static_paths_remain_distinguishable(self):
        result = map_record_to_graph(
            sample_record(["reached", "orphan"]),
            graph("static void reached(void) {} static void orphan(void) {} "
                  "int main(void) { reached(); return 0; }"),
        )
        rows = {item["vulnerable_function"]: item for item in result["function_mappings"]}
        self.assertIs(rows["reached"]["reachable_from_entry"], True)
        self.assertIs(rows["orphan"]["reachable_from_entry"], False)
        self.assertEqual(
            rows["orphan"]["mapping_status"],
            "mapped_without_resolved_static_path",
        )
        self.assertEqual(rows["orphan"]["call_depth_status"], "no_resolved_static_path")
        self.assertEqual(result["mapping_status"], "mapped_with_mixed_path_resolution")

    def test_unresolved_indirect_dispatch_is_explicit_without_inventing_depth(self):
        analyzed = analyze_sources([
            (
                "grep.c",
                b"static void (*execute)(void);\n"
                b"static void grepbuf(void) { execute(); }\n"
                b"int main(void) { grepbuf(); return 0; }\n",
            ),
            (
                "kwsearch.c",
                b"static void bmexec_trans(void) {}\n"
                b"static void bmexec(void) { bmexec_trans(); }\n"
                b"static void kwsexec(void) { bmexec(); }\n"
                b"static void Fexecute(void) { kwsexec(); }\n",
            ),
        ], entry_points=("grep.c::main",), force_fallback=True)
        result = map_record_to_graph(
            sample_record(["bmexec_trans"]),
            analyzed,
            declared_indirect_dispatches=[{
                "caller": {"source_file": "grep.c", "function": "grepbuf"},
                "callee_text": "execute",
                "possible_target": {
                    "source_file": "kwsearch.c", "function": "Fexecute",
                },
            }],
        )
        row = result["function_mappings"][0]
        self.assertEqual(
            row["mapping_status"], "mapped_without_resolved_static_path"
        )
        self.assertEqual(row["call_depth_status"], "unresolved_indirect_dispatch")
        self.assertIsNone(row["call_depth"])
        self.assertIsNone(row["shortest_call_path"])
        self.assertIsNone(row["normalized_depth"])
        self.assertEqual(len(row["unresolved_indirect_dispatches"]), 1)
        evidence = row["unresolved_indirect_dispatches"][0]
        self.assertEqual(
            evidence["resolved_path_to_dispatch_caller"], ["main", "grepbuf"]
        )
        self.assertEqual(evidence["callee_text"], "execute")
        self.assertEqual(evidence["resolved_static_suffix"], [
            "Fexecute", "kwsexec", "bmexec", "bmexec_trans",
        ])
        summary = summarize_historical_analysis(
            result["function_mappings"], [result]
        )
        self.assertEqual(summary["function_call_depth_status_counts"], {
            "unresolved_indirect_dispatch": 1,
        })
        unobserved = map_record_to_graph(
            sample_record(["bmexec_trans"]),
            analyzed,
            declared_indirect_dispatches=[{
                "caller": {"source_file": "grep.c", "function": "grepbuf"},
                "callee_text": "not_the_observed_call",
                "possible_target": {
                    "source_file": "kwsearch.c", "function": "Fexecute",
                },
            }],
        )["function_mappings"][0]
        self.assertEqual(unobserved["call_depth_status"], "no_resolved_static_path")
        self.assertEqual(unobserved["unresolved_indirect_dispatches"], [])

    def test_indirect_dispatch_manifest_endpoints_must_be_in_exact_scope(self):
        manifest = fixture_manifest()[0]
        program = manifest["programs"]["sort"]
        program["source_files"] = program.pop("source_globs")
        program["declared_indirect_dispatches"] = [{
            "caller": {"source_file": "outside.c", "function": "caller"},
            "callee_text": "dispatch",
            "possible_target": {
                "source_file": "program.c", "function": "target",
            },
        }]
        self.assertTrue(any(
            "caller.source_file must be in source_files" in error
            for error in validate_source_manifest([manifest])
        ))

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
        self.assertEqual(row["call_depth_status"], "resolved_numeric_depth")
        self.assertEqual(row["mapped_source_file"], "grep.c")
        self.assertEqual(row["call_depth"], 5)
        self.assertEqual(row["shortest_call_path"], [
            "main", "grepbuf", "Fexecute", "kwsexec", "bmexec", "bmexec_trans",
        ])

    def test_mkdir_locations_resolve_uniquely_with_frozen_depths(self):
        analyzed = analyze_sources([
            (
                "lib/makepath.c",
                b"void make_path(void) {}\n",
            ),
            (
                "src/mkdir.c",
                b"void make_path(void);\nint main(void) { make_path(); return 0; }\n",
            ),
        ], entry_points=("src/mkdir.c::main",), force_fallback=True)
        result = map_record_to_graph(sample_record(["main", "make_path"]), analyzed)
        rows = {item["vulnerable_function"]: item for item in result["function_mappings"]}
        self.assertEqual(rows["main"]["mapping_status"], "mapped_and_reachable")
        self.assertEqual(rows["main"]["mapped_source_file"], "src/mkdir.c")
        self.assertEqual(rows["main"]["call_depth"], 0)
        self.assertEqual(rows["main"]["shortest_call_path"], ["main"])
        self.assertEqual(rows["make_path"]["mapping_status"], "mapped_and_reachable")
        self.assertEqual(rows["make_path"]["mapped_source_file"], "lib/makepath.c")
        self.assertEqual(rows["make_path"]["call_depth"], 1)
        self.assertEqual(rows["make_path"]["shortest_call_path"], ["main", "make_path"])

    def test_existing_sort_depth_three_regression_shape(self):
        analyzed = graph(
            "static void begfield(void) {} "
            "static void fillbuf(void) { begfield(); } "
            "static void check(void) { fillbuf(); } "
            "int main(void) { check(); return 0; }"
        )
        row = map_record_to_graph(
            sample_record(["begfield"]), analyzed
        )["function_mappings"][0]
        self.assertEqual(row["mapping_status"], "mapped_and_reachable")
        self.assertEqual(row["call_depth"], 3)
        self.assertEqual(row["shortest_call_path"], [
            "main", "check", "fillbuf", "begfield",
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

    def test_third_record_does_not_change_existing_project_results(self):
        coreutils_record = fixture_records()[0]
        coreutils_manifest = fixture_manifest()[0]
        grep_record, grep_manifest = grep_fixture()
        baseline = analyze_versioned_records(
            [coreutils_record, grep_record],
            [coreutils_manifest, grep_manifest],
            force_fallback=True,
        )["historical_function_mappings"]
        mkdir_record, mkdir_manifest = mkdir_fixture()
        combined = analyze_versioned_records(
            [coreutils_record, grep_record, mkdir_record],
            [coreutils_manifest, grep_manifest, mkdir_manifest],
            force_fallback=True,
        )["historical_function_mappings"]
        stable_fields = (
            "vulnerability_id", "mapping_status", "mapped_function_id",
            "mapped_source_file", "call_depth", "shortest_call_path",
            "direct_callers", "direct_callees",
        )
        self.assertEqual(
            [{field: row[field] for field in stable_fields} for row in baseline],
            [{field: row[field] for field in stable_fields} for row in combined[:2]],
        )

    def test_fourth_grep_version_does_not_change_prior_three_results(self):
        coreutils_record = fixture_records()[0]
        coreutils_manifest = fixture_manifest()[0]
        grep_record, grep_manifest = grep_fixture()
        mkdir_record, mkdir_manifest = mkdir_fixture()
        prior_records = [coreutils_record, grep_record, mkdir_record]
        prior_manifest = [coreutils_manifest, grep_manifest, mkdir_manifest]
        baseline = analyze_versioned_records(
            prior_records, prior_manifest, force_fallback=True
        )["historical_function_mappings"]
        grep_210_record, grep_210_manifest = grep_210_fixture()
        combined = analyze_versioned_records(
            [*prior_records, grep_210_record],
            [*prior_manifest, grep_210_manifest],
            force_fallback=True,
        )["historical_function_mappings"]
        stable_fields = (
            "vulnerability_id", "mapping_status", "mapped_function_id",
            "mapped_source_file", "call_depth", "shortest_call_path",
            "direct_callers", "direct_callees",
        )
        self.assertEqual(
            [{field: row[field] for field in stable_fields} for row in baseline],
            [{field: row[field] for field in stable_fields} for row in combined[:3]],
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
    def _write_mkdir_manifest(self, path, source_tree, source_files):
        path.write_text(json.dumps([{
            "upstream_project": "gnu-coreutils",
            "affected_version": "fixture",
            "source_revision": "d" * 40,
            "source_tree": str(source_tree),
            "source_tree_sha256": "0" * 64,
            "programs": {
                "mkdir": {
                    "entry_point": {
                        "source_file": "entry.c", "function": "main",
                    },
                    "source_files": source_files,
                },
            },
        }]))

    def test_frozen_file_verifier_rejects_traversal_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_tree = base / "source"
            source_tree.mkdir()
            (source_tree / "entry.c").write_text("int main(void) { return 0; }\n")
            outside = base / "outside.c"
            outside.write_text("void outside(void) {}\n")
            manifest = base / "manifest.json"

            self._write_mkdir_manifest(manifest, source_tree, ["../outside.c"])
            with self.assertRaises(HistoricalDataError):
                verify_frozen_source_files(source_tree, manifest)

            symlink_or_skip(self, outside, source_tree / "escaped.c")
            self._write_mkdir_manifest(
                manifest, source_tree, ["entry.c", "escaped.c"]
            )
            with self.assertRaisesRegex(RuntimeError, "escapes source tree"):
                verify_frozen_source_files(source_tree, manifest)

    def test_partial_existing_source_tree_fails_preparation_fingerprint_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            source_tree = Path(directory)
            (source_tree / "one.c").write_text("void one(void) {}\n")
            (source_tree / "two.h").write_text("void two(void);\n")
            expected = source_tree_sha256(source_tree)
            (source_tree / "two.h").unlink()
            with self.assertRaisesRegex(
                HistoricalDataError, "source-tree fingerprint mismatch"
            ):
                verify_source_tree_sha256(source_tree, expected)

            script = (
                REPO / "security/historical/prepare_coreutils_5_2_1.sh"
            ).read_text()
            self.assertIn("verify_source_tree_sha256", script)
            self.assertIn(
                'if test "$observed_tree_sha256" != "$source_tree_sha256"; then',
                script,
            )

    def test_downstream_packaging_components_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            spec = checkout / "fixture.spec"
            patch = checkout / "security.patch"
            spec.write_text("Name: fixture\n")
            patch.write_text("diff --git a/a b/a\n")
            metadata = {
                "spec_file": spec.name,
                "spec_sha256": file_sha256(spec),
                "security_patch_file": patch.name,
                "security_patch_sha256": file_sha256(patch),
            }
            verified = verify_packaging_components(checkout, metadata)
            self.assertEqual(set(verified), {"spec", "security_patch"})

            patch.unlink()
            with self.assertRaisesRegex(
                DownstreamSourceError, "packaging component is missing"
            ):
                verify_packaging_components(checkout, metadata)

            patch.write_text("corrupted\n")
            with self.assertRaisesRegex(
                DownstreamSourceError, "security_patch checksum mismatch"
            ):
                verify_packaging_components(checkout, metadata)

    def test_downstream_packaging_component_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = base / "checkout"
            checkout.mkdir()
            outside = base / "outside.patch"
            outside.write_text("outside\n")
            spec = checkout / "fixture.spec"
            spec.write_text("Name: fixture\n")
            symlink_or_skip(self, outside, checkout / "security.patch")
            metadata = {
                "spec_file": spec.name,
                "spec_sha256": file_sha256(spec),
                "security_patch_file": "security.patch",
                "security_patch_sha256": file_sha256(outside),
            }
            with self.assertRaisesRegex(
                DownstreamSourceError, "escapes checkout"
            ):
                verify_packaging_components(checkout, metadata)

    def test_rpm_patch_parser_supports_bare_numbered_and_strip_levels(self):
        bare = rpm_patch_sequence("Patch: zero.patch\n%prep\n%patch\n%build\n")
        self.assertEqual(
            [(item.number, item.path, item.strip_level) for item in bare],
            [(0, "zero.patch", 0)],
        )
        numbered = rpm_patch_sequence(
            "Patch7: seven.patch\nPatch8: eight.patch\n%prep\n"
            "%patch7 -p1 -b .seven\n%patch -P 8 -p2\n%build\n"
        )
        self.assertEqual(
            [(item.number, item.path, item.strip_level) for item in numbered],
            [(7, "seven.patch", 1), (8, "eight.patch", 2)],
        )

    def test_rpm_patch_parser_rejects_conditionals_and_macro_sequences(self):
        guarded = (
            "Patch0: zero.patch\n%prep\n%if 0%{?fedora}\n"
            "%patch0 -p1\n%endif\n%build\n"
        )
        with self.assertRaisesRegex(
            DownstreamSourceError, "conditional %prep sequencing"
        ):
            rpm_patch_sequence(guarded)
        macro_guarded = (
            "Patch0: zero.patch\n%prep\n%{?apply_zero:%patch0 -p1}\n%build\n"
        )
        with self.assertRaisesRegex(
            DownstreamSourceError, "macro-dependent RPM patch sequencing"
        ):
            rpm_patch_sequence(macro_guarded)
        conditional_declaration = (
            "%if 0%{?fedora}\nPatch0: zero.patch\n%endif\n"
            "%prep\n%patch0 -p1\n%build\n"
        )
        with self.assertRaisesRegex(
            DownstreamSourceError, "conditional Patch0 declaration"
        ):
            rpm_patch_sequence(conditional_declaration)

    def test_rpm_patch_parser_rejects_malformed_conditionals(self):
        with self.assertRaisesRegex(
            DownstreamSourceError, "malformed RPM conditional %else"
        ):
            rpm_patch_sequence(
                "Patch0: zero.patch\n%prep\n%else\n%patch0\n%build\n"
            )
        with self.assertRaisesRegex(
            DownstreamSourceError, "unterminated RPM conditional structure"
        ):
            rpm_patch_sequence(
                "Patch0: zero.patch\n%if 1\n%endif\n%prep\n%patch0\n"
                "%build\n%if 1\n"
            )

    def test_fedora_8_23_9_patch_sequence_and_strip_levels_are_frozen(self):
        names = [
            "coreutils-8.23-chroot-chdir.patch",
            "coreutils-6.10-configuration.patch",
            "coreutils-6.10-manpages.patch",
            "coreutils-7.4-sttytcsadrain.patch",
            "coreutils-8.2-uname-processortype.patch",
            "coreutils-df-direct.patch",
            "coreutils-8.4-mkdir-modenote.patch",
            "sh-utils-2.0.11-dateman.patch",
            "coreutils-4.5.3-langinfo.patch",
            "coreutils-i18n.patch",
            "coreutils-getgrouplist.patch",
            "coreutils-overflow.patch",
            "coreutils-8.22-temporarytestoff.patch",
            "coreutils-selinux.patch",
            "coreutils-selinuxmanpages.patch",
        ]
        numbers = [1, 100, 101, 102, 103, 104, 107, 703, 713, 800,
                   908, 912, 913, 950, 951]
        spec = "\n".join(
            [*(f"Patch{number}: {name}" for number, name in zip(numbers, names)),
             "%prep", "%setup -q",
             *(f"%patch{number} -p1 -b .fixture" for number in numbers),
             "%build"]
        )
        sequence = rpm_patch_sequence(spec)
        self.assertEqual(len(sequence), 15)
        self.assertEqual([item.path for item in sequence], names)
        self.assertEqual([item.strip_level for item in sequence], [1] * 15)

        script = (
            REPO / "security/historical/prepare_coreutils_8_23_fedora.sh"
        ).read_text()
        self.assertIn("application.strip_level", script)
        self.assertIn('"-p$strip_level"', script)
        self.assertNotIn('patch --directory "$working_tree" --batch --forward -p1', script)

    def test_preparation_scripts_use_portable_python_sha256(self):
        historical = REPO / "security" / "historical"
        for name in (
            "prepare_coreutils_9_7.sh",
            "prepare_grep_2_21.sh",
            "prepare_coreutils_5_2_1.sh",
            "prepare_grep_2_10.sh",
            "prepare_coreutils_8_23_fedora.sh",
        ):
            with self.subTest(script=name):
                text = (historical / name).read_text()
                self.assertIn("hashlib.sha256", text)
                self.assertNotIn("sha256sum", text)
                self.assertNotIn("sha1sum", text)
                self.assertNotIn("shasum", text)
        self.assertIn(
            "hashlib.sha1",
            (historical / "prepare_coreutils_5_2_1.sh").read_text(),
        )

    def test_grep_scripts_do_not_duplicate_frozen_revision(self):
        historical = REPO / "security" / "historical"
        for name in (
            "prepare_grep_2_21.sh",
            "prepare_grep_2_21_scope.sh",
            "derive_grep_scope.py",
            "prepare_grep_2_10.sh",
            "prepare_grep_2_10_scope.sh",
            "derive_grep_2_10_scope.py",
            "check_grep_2_10_scope_sensitivity.py",
        ):
            with self.subTest(script=name):
                text = (historical / name).read_text()
                self.assertNotIn(GREP_REVISION, text)
                self.assertNotIn(GREP_210_REVISION, text)

    def test_grep_preparation_is_version_specific_and_cannot_cross_satisfy(self):
        historical = REPO / "security" / "historical"
        old = (historical / "prepare_grep_2_10.sh").read_text()
        recent = (historical / "prepare_grep_2_21.sh").read_text()
        self.assertIn("requested_version=2.10", old)
        self.assertIn("requested_version=2.21", recent)
        self.assertIn('grep-$release_version.tar.xz', old)
        self.assertIn('grep-$release_version.tar.xz', recent)
        self.assertIn('Path(sys.argv[1]).parent / entry["source_tree"]', old)
        self.assertIn('Path(sys.argv[1]).parent / entry["source_tree"]', recent)

    def test_grep_210_preparation_rechecks_release_git_correspondence(self):
        script = (
            REPO / "security/historical/prepare_grep_2_10.sh"
        ).read_text()
        for relative_file in (
            "src/main.c", "src/dfa.c", "src/dfa.h", "src/dfasearch.c",
            "src/kwset.c", "src/kwset.h", "src/Makefile.am",
            "lib/Makefile.am", "configure.ac",
        ):
            with self.subTest(relative_file=relative_file):
                self.assertIn(relative_file, script)
        self.assertIn('git hash-object "$release_file"', script)
        self.assertIn('"$release_revision:$relative_file"', script)
        self.assertIn("release_git_correspondence=%s", script)

    def test_partial_grep_210_tree_cannot_bypass_fingerprint_gate(self):
        script = (
            REPO / "security/historical/prepare_grep_2_10.sh"
        ).read_text()
        self.assertIn('if ! test -d "$source_tree"; then', script)
        self.assertIn("verify_source_tree_sha256", script)
        self.assertIn(
            'if test "$observed_tree_sha256" != "$source_tree_sha256"; then',
            script,
        )

    def test_mkdir_scripts_do_not_duplicate_frozen_revision(self):
        historical = REPO / "security" / "historical"
        for name in (
            "prepare_coreutils_5_2_1.sh",
            "prepare_coreutils_5_2_1_mkdir_scope.sh",
            "derive_coreutils_mkdir_scope.py",
            "check_coreutils_mkdir_scope_sensitivity.py",
        ):
            with self.subTest(script=name):
                self.assertNotIn(MKDIR_REVISION, (historical / name).read_text())

    def test_fedora_scripts_do_not_duplicate_frozen_revisions(self):
        historical = REPO / "security" / "historical"
        upstream_revision = next(
            item["source_revision"]
            for item in json.loads(
                (historical / "source_manifest.json").read_text()
            )
            if item.get("source_provenance") == "downstream_patch"
        )
        for name in (
            "prepare_coreutils_8_23_fedora.sh",
            "prepare_coreutils_8_23_fedora_sort_scope.sh",
            "derive_coreutils_8_23_sort_scope.py",
            "check_coreutils_8_23_sort_scope_sensitivity.py",
        ):
            with self.subTest(script=name):
                text = (historical / name).read_text()
                self.assertNotIn(upstream_revision, text)
                self.assertNotIn(FEDORA_REVISION, text)

    def test_fedora_preparation_rechecks_full_downstream_identity(self):
        script = (
            REPO / "security/historical/prepare_coreutils_8_23_fedora.sh"
        ).read_text()
        self.assertIn("verify_packaging_components", script)
        self.assertIn("rpm_patch_sequence", script)
        self.assertIn("security patch Git blob mismatch", script)
        self.assertIn("verify_source_tree_sha256", script)
        self.assertIn("source_package_identity=%s", script)
        self.assertIn(
            "srpm_authentication_status=%s", script
        )
        self.assertIn("not_downloaded_or_authenticated", script)
        for relative_file in (
            "src/sort.c", "src/local.mk", "lib/local.mk", "Makefile.am",
            "configure.ac",
        ):
            with self.subTest(relative_file=relative_file):
                self.assertIn(relative_file, script)

    def test_mkdir_preparation_rechecks_release_git_blob_correspondence(self):
        script = (
            REPO / "security/historical/prepare_coreutils_5_2_1.sh"
        ).read_text()
        for relative_file in (
            "src/mkdir.c", "lib/makepath.c", "src/Makefile.am",
            "lib/Makefile.am", "configure",
        ):
            with self.subTest(relative_file=relative_file):
                self.assertIn(relative_file, script)
        self.assertIn('git hash-object "$release_file"', script)
        self.assertIn('"$release_revision:$relative_file"', script)
        self.assertIn("release_git_correspondence=%s", script)

    def test_historical_analysis_does_not_run_hvc_without_opt_in(self):
        arguments = parse_args([
            "--source-manifest", str(REPO / "security/historical/source_manifest.json"),
            "--records", str(REPO / "security/historical/records.json"),
            "--output", str(REPO / "build/unused-historical-test-output.json"),
        ])
        self.assertIs(arguments.coverage_study, False)


if __name__ == "__main__":
    unittest.main()
