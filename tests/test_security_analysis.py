"""Focused tests for formal RQ3 security measurement."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from analysis import security_diagnostics as sd  # noqa: E402


CSV_HEADER = (
    "File,Line,Column,DefaultLevel,Level,Category,Name,Warning,Suggestion,"
    "Note,CWEs,Context,Fingerprint,ToolVersion,RuleId,HelpUri\n"
)


def test_frozen_security_configuration_matches_code_defaults():
    frozen = json.loads(
        (REPO_ROOT / "scripts" / "security-analysis-config-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert frozen == sd.default_security_configuration()


def finding_row(
    *, run_id: str, level: int, cwes: list[str], fingerprint: str
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "source_identifier": f"{run_id}/candidate.c",
        "reported_filename": "candidate.c",
        "line": 1,
        "column": 1,
        "default_level": level,
        "level": level,
        "category": "buffer",
        "rule_name": "strcpy",
        "warning": "warning",
        "suggestion": "suggestion",
        "note": None,
        "cwe_ids": json.dumps(cwes, separators=(",", ":")),
        "context": "strcpy(a, b);",
        "flawfinder_fingerprint": fingerprint,
        "tool_version": "2.0.20",
        "rule_id": "FF1001",
        "help_uri": "https://example.invalid/CWE-120",
    }


def measured_row(
    run_id: str,
    *,
    findings: list[dict[str, object]],
    loc: int,
    unsafe: int = 0,
) -> dict[str, object]:
    count = len(findings)
    cwes = sorted(
        {cwe for finding in findings for cwe in json.loads(str(finding["cwe_ids"]))}
    )
    return {
        "run_id": run_id,
        "analysis_status": "available",
        "descriptor_status": "available",
        "flawfinder_status": "available",
        "flawfinder_finding_count": count,
        "flawfinder_findings_per_kloc": 1000.0 * count / loc if loc else None,
        "maximum_flawfinder_level": (
            max(int(finding["level"]) for finding in findings) if findings else None
        ),
        "cwe_ids": json.dumps(cwes, separators=(",", ":")),
        "unsafe_call_count": unsafe,
        "bounded_risky_call_count": 0,
        "heap_allocation_deallocation_call_count": 0,
        "fixed_size_stack_buffer_count": 0,
        "indexing_operation_count": 0,
        "_findings": findings,
    }


def test_flawfinder_discovery_preserves_virtual_environment_location(
    monkeypatch, tmp_path: Path
):
    environment_bin = tmp_path / "analysis-environment" / "bin"
    environment_bin.mkdir(parents=True)
    python = environment_bin / "python"
    scanner = environment_bin / "flawfinder"
    python.write_text("", encoding="utf-8")
    scanner.write_text("", encoding="utf-8")
    monkeypatch.setattr(sd.shutil, "which", lambda _: None)
    monkeypatch.setattr(sd.sys, "executable", str(python))

    assert sd.resolve_flawfinder_executable() == scanner.resolve()


def test_security_sensitive_call_and_construct_classification():
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_c")
    source = b"""\
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
void f(const char *src) {
    char fixed[16];
    char *heap = malloc(32);
    strcpy(fixed, src);
    snprintf(fixed, sizeof(fixed), "%s", src);
    fixed[0] = src[0];
    free(heap);
}
"""
    profile = sd.security_profile(source)
    assert profile["unsafe_call_count"] == 1
    assert profile["bounded_risky_call_count"] == 1
    assert profile["heap_allocation_deallocation_call_count"] == 2
    assert profile["fixed_size_stack_buffer_count"] == 1
    assert profile["indexing_operation_count"] == 2


def test_flawfinder_csv_preserves_metadata_and_multiple_cwes():
    text = CSV_HEADER + (
        'candidate.c,7,3,4,3,buffer,strcpy,"warning, text",suggestion,note,'
        '"CWE-120, CWE-20",strcpy(a b),abc123,2.0.20,FF1001,'
        "https://cwe.mitre.org/data/definitions/120.html\n"
    )
    findings = sd.parse_flawfinder_csv(
        text, run_id="run-1", source_identifier="run-1/candidate.c"
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding["run_id"] == "run-1"
    assert finding["reported_filename"] == "candidate.c"
    assert finding["level"] == 3
    assert finding["default_level"] == 4
    assert finding["category"] == "buffer"
    assert finding["rule_name"] == "strcpy"
    assert json.loads(finding["cwe_ids"]) == ["CWE-20", "CWE-120"]
    assert finding["flawfinder_fingerprint"] == "abc123"
    assert finding["tool_version"] == "2.0.20"
    assert finding["rule_id"] == "FF1001"


def test_malformed_flawfinder_csv_is_unavailable_not_zero(monkeypatch, tmp_path: Path):
    source = tmp_path / "candidate.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, "bad,header\n1,2\n", "")

    monkeypatch.setattr(sd.subprocess, "run", fake_run)
    result = sd.flawfinder_crosscheck(
        source,
        run_id="r1",
        configuration=sd.default_security_configuration(),
        provenance={
            "status": "available",
            "reason": None,
            "executable_path": "/scanner/flawfinder",
            "executable_identifier": "flawfinder",
            "options": ["--csv", "--dataonly", "--quiet", "--minlevel=1"],
        },
    )
    assert result["status"] == "unavailable"
    assert result["findings"] is None
    assert result["reason"].startswith("malformed_flawfinder_csv")


def test_flawfinder_timeout_is_recorded(monkeypatch, tmp_path: Path):
    source = tmp_path / "candidate.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 120)

    monkeypatch.setattr(sd.subprocess, "run", timeout)
    result = sd.flawfinder_crosscheck(
        source,
        configuration=sd.default_security_configuration(),
        provenance={
            "status": "available",
            "reason": None,
            "executable_path": "/scanner/flawfinder",
            "executable_identifier": "flawfinder",
            "options": ["--csv", "--dataonly", "--quiet", "--minlevel=1"],
        },
    )
    assert result["status"] == "unavailable"
    assert result["reason"] == "flawfinder_timeout"
    assert result["findings"] is None


def test_unavailable_flawfinder_never_becomes_zero_findings(monkeypatch, tmp_path: Path):
    source = tmp_path / "candidate.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    monkeypatch.setattr(sd, "security_profile", lambda *args: {field: 0 for field in sd.CONSTRUCT_FIELDS})
    row = sd.measure_security_candidate(
        run_id="r1",
        source=source,
        source_identifier="r1/candidate.c",
        configuration=sd.default_security_configuration(),
        provenance={
            "status": "unavailable",
            "reason": "flawfinder_not_found",
            "executable_path": None,
            "executable_identifier": "flawfinder",
            "version": None,
            "expected_version": "2.0.20",
            "options": ["--csv"],
        },
    )
    assert row["flawfinder_status"] == "unavailable"
    assert row["flawfinder_finding_count"] is None
    assert row["analysis_status"] == "unavailable"


def test_population_prevalence_density_severity_cwe_and_construct_aggregation():
    r1_findings = [
        finding_row(run_id="r1", level=3, cwes=["CWE-120", "CWE-20"], fingerprint="a"),
        finding_row(run_id="r1", level=1, cwes=["CWE-20"], fingerprint="b"),
    ]
    r2_findings: list[dict[str, object]] = []
    rows = [
        measured_row("r1", findings=r1_findings, loc=100, unsafe=2),
        measured_row("r2", findings=r2_findings, loc=50, unsafe=0),
    ]
    summary = sd.aggregate_security_population(rows)
    assert summary["population_n"] == 2
    assert summary["security_measurement_coverage"] == 1.0
    assert summary["static_finding_prevalence"] == 0.5
    assert summary["flawfinder_findings"]["mean"] == 1.0
    assert summary["flawfinder_findings"]["median"] == 1.0
    assert summary["flawfinder_findings"]["minimum"] == 0.0
    assert summary["flawfinder_findings"]["maximum"] == 2.0
    assert summary["findings_per_kloc"]["mean"] == 10.0
    assert summary["unsafe_api_prevalence"] == 0.5
    assert summary["mean_unsafe_call_count"] == 1.0
    assert summary["distinct_cwe_count"] == 2
    severity = {row["level"]: row for row in summary["severity_distribution"]}
    assert severity[1]["finding_count"] == 1
    assert severity[3]["implementations_with_finding"] == 1
    assert severity[3]["candidate_prevalence"] == 0.5
    cwes = {row["cwe_id"]: row for row in summary["cwe_distribution"]}
    assert cwes["CWE-20"]["occurrence_count"] == 2
    assert cwes["CWE-20"]["implementations_with_cwe"] == 1
    assert cwes["CWE-120"]["candidate_prevalence"] == 0.5


def test_zero_or_missing_loc_has_null_density(monkeypatch, tmp_path: Path):
    source = tmp_path / "empty.c"
    source.write_text("", encoding="utf-8")
    finding = finding_row(run_id="r1", level=2, cwes=[], fingerprint="a")
    monkeypatch.setattr(sd, "security_profile", lambda *args: {field: 0 for field in sd.CONSTRUCT_FIELDS})
    monkeypatch.setattr(
        sd,
        "flawfinder_crosscheck",
        lambda *args, **kwargs: {
            "status": "available",
            "reason": None,
            "findings": [finding],
            "command": ["flawfinder", "empty.c"],
        },
    )
    row = sd.measure_security_candidate(
        run_id="r1",
        source=source,
        source_identifier="r1/empty.c",
        configuration=sd.default_security_configuration(),
        provenance={"status": "available"},
    )
    assert row["source_line_count"] == 0
    assert row["flawfinder_findings_per_kloc"] is None

    missing = sd.measure_security_candidate(
        run_id="r2",
        source=None,
        source_identifier="r2/missing.c",
        configuration=sd.default_security_configuration(),
        provenance={"status": "available"},
    )
    assert missing["source_line_count"] is None
    assert missing["flawfinder_finding_count"] is None


def test_partial_measurement_has_coverage_and_null_population_prevalence():
    available = measured_row("r1", findings=[], loc=10)
    unavailable = {
        "run_id": "r2",
        "analysis_status": "unavailable",
        "descriptor_status": "available",
        "flawfinder_status": "unavailable",
        "unavailable_reason": "flawfinder_timeout",
        **{field: 0 for field in sd.CONSTRUCT_FIELDS},
        "_findings": [],
    }
    summary = sd.aggregate_security_population([available, unavailable])
    assert summary["security_measurement_coverage"] == 0.5
    assert summary["flawfinder_measurement_coverage"] == 0.5
    assert summary["static_finding_prevalence"] is None
    assert summary["flawfinder_findings"]["mean"] is None
    assert summary["unmeasured_runs"] == [
        {"run_id": "r2", "reason": "flawfinder_timeout"}
    ]


def test_security_measurement_does_not_mutate_success_or_cluster_membership():
    rq2_row = {
        "run_id": "r1",
        "overall_success": True,
        "architecture_cluster_id": 4,
        "strategy_cluster_id": 2,
    }
    before = dict(rq2_row)
    sd.aggregate_security_population(
        [measured_row("r1", findings=[], loc=10, unsafe=0)]
    )
    assert rq2_row == before


def test_formal_missing_scanner_is_marked_unavailable(tmp_path: Path):
    source = tmp_path / "candidate.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    result = sd.analyze_security_population(
        candidates=[
            {
                "run_id": "r1",
                "source": source,
                "source_identifier": "r1/candidate.c",
            }
        ],
        output_dir=tmp_path / "security",
        configuration=sd.default_security_configuration(),
        metadata={},
        formal=True,
        explicit_executable=tmp_path / "missing-flawfinder",
    )
    summary = result["summary"]
    assert summary["status"] == "formally_unavailable"
    assert summary["flawfinder"]["reason"] == "flawfinder_not_found"
    assert summary["static_finding_prevalence"] is None
    with (tmp_path / "security" / "security_per_run.csv").open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["flawfinder_finding_count"] == ""


def test_deterministic_repeated_analysis_outputs(monkeypatch, tmp_path: Path):
    source = tmp_path / "candidate.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    finding = finding_row(run_id="r1", level=2, cwes=["CWE-20"], fingerprint="stable")
    monkeypatch.setattr(sd, "security_profile", lambda *args: {field: 0 for field in sd.CONSTRUCT_FIELDS})
    monkeypatch.setattr(
        sd,
        "flawfinder_provenance",
        lambda *args, **kwargs: {
            "status": "available",
            "reason": None,
            "executable_path": "/scanner/flawfinder",
            "executable_identifier": "flawfinder",
            "version": "2.0.20",
            "expected_version": "2.0.20",
            "options": ["--csv", "--dataonly", "--quiet", "--minlevel=1"],
        },
    )
    monkeypatch.setattr(
        sd,
        "flawfinder_crosscheck",
        lambda *args, **kwargs: {
            "status": "available",
            "reason": None,
            "findings": [finding],
            "command": ["flawfinder", "candidate.c"],
        },
    )
    candidates = [{"run_id": "r1", "source": source, "source_identifier": "r1/candidate.c"}]
    for name in ("first", "second"):
        sd.analyze_security_population(
            candidates=candidates,
            output_dir=tmp_path / name,
            configuration=sd.default_security_configuration(),
            metadata={"issue": "demo"},
            formal=True,
        )
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert sorted(path.name for path in first.iterdir()) == sorted(path.name for path in second.iterdir())
    for path in first.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()
