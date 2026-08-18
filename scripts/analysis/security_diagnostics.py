"""Formal RQ3 static findings and security-sensitive source descriptors.

Security is post-hoc measurement over an already-selected successful source
population. Nothing in this module determines correctness, population
membership, repair, or structural clustering.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import shutil
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from analysis.diversity_validation import _call_name, parse_source


SECURITY_SCHEMA_VERSION = 1
SECURITY_CONFIGURATION_VERSION = 1
SECURITY_CLASSIFICATION_VERSION = "agentic-cyber-security-sensitive-calls-v1"
PINNED_FLAWFINDER_VERSION = "2.0.20"
FLAWFINDER_TIMEOUT_SECONDS = 120
FLAWFINDER_BASE_OPTIONS = ("--csv", "--dataonly", "--quiet")

UNSAFE_CALLS = frozenset({"strcpy", "strcat", "sprintf", "gets", "vsprintf"})
BOUNDED_RISKY_CALLS = frozenset(
    {"strncpy", "strncat", "snprintf", "memcpy", "memmove", "stpcpy"}
)
HEAP_CALLS = frozenset(
    {"malloc", "calloc", "realloc", "free", "strdup", "reallocarray"}
)

CONSTRUCT_FIELDS = (
    "unsafe_call_count",
    "bounded_risky_call_count",
    "heap_allocation_deallocation_call_count",
    "fixed_size_stack_buffer_count",
    "indexing_operation_count",
)

FLAWFINDER_REQUIRED_COLUMNS = frozenset(
    {
        "File",
        "Line",
        "Column",
        "DefaultLevel",
        "Level",
        "Category",
        "Name",
        "Warning",
        "Suggestion",
        "CWEs",
        "Fingerprint",
        "ToolVersion",
    }
)

FLAWFINDER_FINDING_FIELDS = (
    "run_id",
    "source_identifier",
    "reported_filename",
    "line",
    "column",
    "default_level",
    "level",
    "category",
    "rule_name",
    "warning",
    "suggestion",
    "note",
    "cwe_ids",
    "context",
    "flawfinder_fingerprint",
    "tool_version",
    "rule_id",
    "help_uri",
)

SECURITY_PER_RUN_FIELDS = (
    "run_id",
    "source_identifier",
    "source_line_count",
    "analysis_status",
    "unavailable_reason",
    "descriptor_status",
    "descriptor_unavailable_reason",
    "flawfinder_status",
    "flawfinder_unavailable_reason",
    "flawfinder_command",
    "flawfinder_finding_count",
    "flawfinder_findings_per_kloc",
    "maximum_flawfinder_level",
    "cwe_ids",
    *CONSTRUCT_FIELDS,
)

PAPER_SECURITY_COLUMNS = (
    "Issue",
    "Checkpoint",
    "Model",
    "Temp",
    "Security Population N",
    "Static Finding Prevalence",
    "Mean Flawfinder Findings",
    "Median Flawfinder Findings",
    "SD Flawfinder Findings",
    "Min Flawfinder Findings",
    "Max Flawfinder Findings",
    "Mean Flawfinder Findings per KLOC",
    "Median Flawfinder Findings per KLOC",
    "SD Flawfinder Findings per KLOC",
    "Unsafe API Prevalence",
    "Mean Unsafe API Calls",
    "Distinct CWE Count",
    "Flawfinder Version",
    "Security Measurement Coverage",
)


def default_security_configuration() -> dict[str, Any]:
    return {
        "schema_version": SECURITY_CONFIGURATION_VERSION,
        "security_analysis_enabled": True,
        "security_analyzer": "flawfinder",
        "expected_flawfinder_version": PINNED_FLAWFINDER_VERSION,
        "flawfinder_minimum_level": 1,
        "flawfinder_timeout_seconds": FLAWFINDER_TIMEOUT_SECONDS,
        "classification_version": SECURITY_CLASSIFICATION_VERSION,
        "unsafe_calls": sorted(UNSAFE_CALLS),
        "bounded_risky_calls": sorted(BOUNDED_RISKY_CALLS),
        "heap_calls": sorted(HEAP_CALLS),
        "severity_threshold": None,
    }


def validate_security_configuration(value: Mapping[str, Any]) -> dict[str, Any]:
    required = frozenset(default_security_configuration())
    missing = sorted(required - value.keys())
    if missing:
        raise ValueError("security configuration is incomplete; missing: " + ", ".join(missing))
    configuration = dict(value)
    if configuration.get("schema_version") != SECURITY_CONFIGURATION_VERSION:
        raise ValueError(
            "security configuration schema_version must be "
            f"{SECURITY_CONFIGURATION_VERSION}"
        )
    if configuration.get("security_analysis_enabled") is not True:
        raise ValueError("security_analysis_enabled must be true")
    if configuration.get("security_analyzer") != "flawfinder":
        raise ValueError("security_analyzer must be flawfinder")
    if configuration.get("severity_threshold") is not None:
        raise ValueError("severity_threshold must be null; no cross-level weighting is defined")
    minimum = configuration.get("flawfinder_minimum_level")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or not 0 <= minimum <= 5:
        raise ValueError("flawfinder_minimum_level must be an integer from 0 through 5")
    timeout = configuration.get("flawfinder_timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("flawfinder_timeout_seconds must be a positive integer")
    for key in ("unsafe_calls", "bounded_risky_calls", "heap_calls"):
        entries = configuration.get(key)
        if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
            raise ValueError(f"{key} must be a list of strings")
        configuration[key] = sorted(set(entries))
    return configuration


def security_configuration_fingerprint(configuration: Mapping[str, Any]) -> str:
    material = json.dumps(
        dict(configuration), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(
        ("agentic-cyber.security-configuration.v1\n" + material).encode("utf-8")
    ).hexdigest()


def source_physical_line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def security_profile(
    source: bytes, configuration: Mapping[str, Any] | None = None
) -> dict[str, int]:
    """Count descriptors; none is interpreted as a confirmed vulnerability."""
    resolved = validate_security_configuration(
        configuration or default_security_configuration()
    )
    unsafe_calls = set(resolved["unsafe_calls"])
    bounded_calls = set(resolved["bounded_risky_calls"])
    heap_calls = set(resolved["heap_calls"])
    parsed = parse_source(source)
    counts = {field: 0 for field in CONSTRUCT_FIELDS}
    stack = [(parsed.root, False)]
    while stack:
        node, inside_function = stack.pop()
        inside_function = inside_function or node.type == "function_definition"
        if node.type == "call_expression":
            name = _call_name(node, parsed.data)
            if name in unsafe_calls:
                counts["unsafe_call_count"] += 1
            elif name in bounded_calls:
                counts["bounded_risky_call_count"] += 1
            elif name in heap_calls:
                counts["heap_allocation_deallocation_call_count"] += 1
        elif inside_function and node.type == "array_declarator":
            size = node.child_by_field_name("size")
            if size is not None and size.type in {"number_literal", "identifier"}:
                counts["fixed_size_stack_buffer_count"] += 1
        elif node.type == "subscript_expression":
            counts["indexing_operation_count"] += 1
        stack.extend((child, inside_function) for child in reversed(node.children))
    return counts


def resolve_flawfinder_executable(explicit: str | Path | None = None) -> Path | None:
    if explicit is not None:
        candidate = Path(explicit)
        return candidate.resolve() if candidate.is_file() else None
    discovered = shutil.which("flawfinder")
    if discovered:
        return Path(discovered).resolve()
    # Preserve the virtual-environment location.  Resolving the Python symlink
    # first would move this lookup to /usr/bin and miss a Flawfinder console
    # script installed beside the active environment's interpreter.
    python = Path(sys.executable)
    names = ("flawfinder.exe", "flawfinder") if sys.platform == "win32" else ("flawfinder",)
    for name in names:
        candidate = python.with_name(name)
        if candidate.is_file():
            return candidate
    return None


def flawfinder_version(executable: Path) -> tuple[str | None, str | None]:
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    if completed.returncode != 0:
        return None, completed.stderr.strip() or f"exit_status_{completed.returncode}"
    output = (completed.stdout or completed.stderr).strip()
    for token in output.split():
        if token and token[0].isdigit() and all(part.isdigit() for part in token.split(".")):
            return token, None
    return None, f"unrecognized version output: {output!r}"


def flawfinder_provenance(
    configuration: Mapping[str, Any], explicit_executable: str | Path | None = None
) -> dict[str, Any]:
    executable = resolve_flawfinder_executable(explicit_executable)
    options = [
        *FLAWFINDER_BASE_OPTIONS,
        f"--minlevel={configuration['flawfinder_minimum_level']}",
    ]
    if executable is None:
        return {
            "status": "unavailable",
            "reason": "flawfinder_not_found",
            "executable_path": None,
            "executable_identifier": "flawfinder",
            "version": None,
            "expected_version": configuration["expected_flawfinder_version"],
            "options": options,
        }
    version, error = flawfinder_version(executable)
    status = "available"
    reason = error
    if error is not None:
        status = "unavailable"
    elif version != configuration["expected_flawfinder_version"]:
        status = "unavailable"
        reason = "version_mismatch"
    return {
        "status": status,
        "reason": reason,
        "executable_path": str(executable),
        "executable_identifier": executable.name,
        "version": version,
        "expected_version": configuration["expected_flawfinder_version"],
        "options": options,
    }


def parse_cwe_ids(value: str | None) -> list[str]:
    if not value:
        return []
    identifiers = {
        token.rstrip(".,);]")
        for token in value.replace("(", " ").replace(",", " ").split()
        if token.startswith("CWE-") and token.rstrip(".,);]")[4:].isdigit()
    }
    return sorted(identifiers, key=lambda item: int(item.split("-", 1)[1]))


def _required_integer(row: Mapping[str, Any], field: str) -> int:
    value = str(row.get(field, ""))
    if not value.isdigit():
        raise ValueError(f"Flawfinder CSV field {field} is not a non-negative integer")
    return int(value)


def parse_flawfinder_csv(
    output: str, *, run_id: str, source_identifier: str
) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(output))
    fields = set(reader.fieldnames or [])
    missing = sorted(FLAWFINDER_REQUIRED_COLUMNS - fields)
    if missing:
        raise ValueError("Flawfinder CSV missing columns: " + ", ".join(missing))
    findings: list[dict[str, Any]] = []
    for row in reader:
        if None in row:
            raise ValueError("Flawfinder CSV row has unexpected extra columns")
        cwes = parse_cwe_ids(row.get("CWEs"))
        finding = {
            "run_id": run_id,
            "source_identifier": source_identifier,
            "reported_filename": Path(str(row.get("File", ""))).name,
            "line": _required_integer(row, "Line"),
            "column": _required_integer(row, "Column"),
            "default_level": _required_integer(row, "DefaultLevel"),
            "level": _required_integer(row, "Level"),
            "category": row.get("Category") or None,
            "rule_name": row.get("Name") or None,
            "warning": row.get("Warning") or None,
            "suggestion": row.get("Suggestion") or None,
            "note": row.get("Note") or None,
            "cwe_ids": json.dumps(cwes, separators=(",", ":")),
            "context": row.get("Context") or None,
            "flawfinder_fingerprint": row.get("Fingerprint") or None,
            "tool_version": row.get("ToolVersion") or None,
            "rule_id": row.get("RuleId") or None,
            "help_uri": row.get("HelpUri") or None,
        }
        findings.append(finding)
    return sorted(
        findings,
        key=lambda row: (
            row["source_identifier"],
            row["line"],
            row["column"],
            row["flawfinder_fingerprint"] or "",
        ),
    )


def flawfinder_crosscheck(
    path: Path,
    *,
    run_id: str = "candidate",
    source_identifier: str | None = None,
    configuration: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = validate_security_configuration(
        configuration or default_security_configuration()
    )
    scanner = dict(provenance or flawfinder_provenance(resolved))
    stable_source = source_identifier or path.name
    command = [
        scanner.get("executable_identifier") or "flawfinder",
        *scanner.get("options", []),
        path.name,
    ]
    if scanner.get("status") != "available":
        return {
            "status": "unavailable",
            "reason": scanner.get("reason") or "flawfinder_unavailable",
            "findings": None,
            "command": command,
        }
    executable = scanner.get("executable_path")
    try:
        completed = subprocess.run(
            [str(executable), *scanner["options"], path.name],
            cwd=path.parent,
            capture_output=True,
            text=True,
            timeout=resolved["flawfinder_timeout_seconds"],
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "reason": "flawfinder_timeout", "findings": None, "command": command}
    except OSError as error:
        return {"status": "unavailable", "reason": f"flawfinder_execution_failed: {error}", "findings": None, "command": command}
    if completed.returncode != 0:
        reason = completed.stderr.strip() or f"flawfinder_exit_status_{completed.returncode}"
        return {"status": "unavailable", "reason": reason, "findings": None, "command": command}
    try:
        findings = parse_flawfinder_csv(
            completed.stdout, run_id=run_id, source_identifier=stable_source
        )
    except ValueError as error:
        return {
            "status": "unavailable",
            "reason": f"malformed_flawfinder_csv: {error}",
            "findings": None,
            "command": command,
        }
    return {"status": "available", "reason": None, "findings": findings, "command": command}


def measure_security_candidate(
    *,
    run_id: str,
    source: Path | None,
    source_identifier: str,
    configuration: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": run_id,
        "source_identifier": source_identifier,
        "source_line_count": None,
        "descriptor_status": "unavailable",
        "descriptor_unavailable_reason": None,
        "flawfinder_status": "unavailable",
        "flawfinder_unavailable_reason": None,
        "flawfinder_command": None,
        "flawfinder_finding_count": None,
        "flawfinder_findings_per_kloc": None,
        "maximum_flawfinder_level": None,
        "cwe_ids": None,
        **{field: None for field in CONSTRUCT_FIELDS},
        "_findings": [],
    }
    if source is None or not source.is_file():
        row["descriptor_unavailable_reason"] = "candidate_source_missing"
        row["flawfinder_unavailable_reason"] = "candidate_source_missing"
    else:
        row["source_line_count"] = source_physical_line_count(source)
        try:
            row.update(security_profile(source.read_bytes(), configuration))
        except Exception as error:
            row["descriptor_unavailable_reason"] = f"source_parser_failure: {error}"
        else:
            row["descriptor_status"] = "available"
        scan = flawfinder_crosscheck(
            source,
            run_id=run_id,
            source_identifier=source_identifier,
            configuration=configuration,
            provenance=provenance,
        )
        row["flawfinder_status"] = scan["status"]
        row["flawfinder_unavailable_reason"] = scan["reason"]
        row["flawfinder_command"] = json.dumps(
            scan["command"], separators=(",", ":")
        )
        if scan["status"] == "available":
            findings = list(scan["findings"] or [])
            row["_findings"] = findings
            row["flawfinder_finding_count"] = len(findings)
            loc = row["source_line_count"]
            row["flawfinder_findings_per_kloc"] = (
                1000.0 * len(findings) / loc
                if isinstance(loc, int) and loc > 0
                else None
            )
            levels = [int(finding["level"]) for finding in findings]
            row["maximum_flawfinder_level"] = max(levels) if levels else None
            cwes = sorted(
                {
                    cwe
                    for finding in findings
                    for cwe in json.loads(finding["cwe_ids"])
                }
            )
            row["cwe_ids"] = json.dumps(cwes, separators=(",", ":"))
    unavailable = []
    if row["descriptor_status"] != "available":
        unavailable.append(str(row["descriptor_unavailable_reason"]))
    if row["flawfinder_status"] != "available":
        unavailable.append(str(row["flawfinder_unavailable_reason"]))
    row["analysis_status"] = "available" if not unavailable else "unavailable"
    row["unavailable_reason"] = "; ".join(unavailable) if unavailable else None
    return row


def _summary(values: Iterable[Any]) -> dict[str, Any]:
    numbers = [
        float(value)
        for value in values
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ]
    return {
        "n": len(numbers),
        "mean": statistics.fmean(numbers) if numbers else None,
        "median": statistics.median(numbers) if numbers else None,
        "sample_sd": statistics.stdev(numbers) if len(numbers) >= 2 else None,
        "minimum": min(numbers) if numbers else None,
        "maximum": max(numbers) if numbers else None,
    }


def aggregate_security_population(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    population_n = len(rows)
    fully_measured = [row for row in rows if row.get("analysis_status") == "available"]
    scanner_measured = [row for row in rows if row.get("flawfinder_status") == "available"]
    descriptor_measured = [row for row in rows if row.get("descriptor_status") == "available"]
    scanner_complete = len(scanner_measured) == population_n
    descriptor_complete = len(descriptor_measured) == population_n
    finding_counts = _summary(row.get("flawfinder_finding_count") for row in scanner_measured)
    densities = _summary(row.get("flawfinder_findings_per_kloc") for row in scanner_measured)
    all_findings = [finding for row in scanner_measured for finding in row.get("_findings", [])]

    level_findings = Counter(int(finding["level"]) for finding in all_findings)
    level_runs: dict[int, set[str]] = defaultdict(set)
    cwe_findings: Counter[str] = Counter()
    cwe_runs: dict[str, set[str]] = defaultdict(set)
    max_levels = Counter()
    for row in scanner_measured:
        run_id = str(row["run_id"])
        levels = {int(finding["level"]) for finding in row.get("_findings", [])}
        for level in levels:
            level_runs[level].add(run_id)
        cwes = set(json.loads(row.get("cwe_ids") or "[]"))
        for cwe in cwes:
            cwe_runs[cwe].add(run_id)
        maximum = row.get("maximum_flawfinder_level")
        max_levels["none" if maximum is None else str(maximum)] += 1
        for finding in row.get("_findings", []):
            cwe_findings.update(json.loads(finding["cwe_ids"]))

    severity_rows = [
        {
            "level": level,
            "finding_count": level_findings[level],
            "implementations_with_finding": len(level_runs[level]),
            "candidate_prevalence": (
                len(level_runs[level]) / population_n
                if scanner_complete and population_n
                else None
            ),
        }
        for level in sorted(level_findings)
    ]
    maximum_level_rows = [
        {
            "maximum_level": level,
            "implementation_count": count,
            "proportion": (
                count / population_n if scanner_complete and population_n else None
            ),
        }
        for level, count in sorted(
            max_levels.items(), key=lambda item: (-1 if item[0] == "none" else int(item[0]))
        )
    ]
    cwe_rows = [
        {
            "cwe_id": cwe,
            "occurrence_count": cwe_findings[cwe],
            "implementations_with_cwe": len(cwe_runs[cwe]),
            "candidate_prevalence": (
                len(cwe_runs[cwe]) / population_n
                if scanner_complete and population_n
                else None
            ),
        }
        for cwe in sorted(cwe_findings, key=lambda item: int(item.split("-", 1)[1]))
    ]
    construct_rows = []
    for field in CONSTRUCT_FIELDS:
        values = _summary(row.get(field) for row in descriptor_measured)
        construct_rows.append(
            {
                "descriptor": field,
                "mean_count": values["mean"] if descriptor_complete else None,
                "median_count": values["median"] if descriptor_complete else None,
                "implementations_with_occurrence": sum(
                    (row.get(field) or 0) > 0 for row in descriptor_measured
                ),
                "prevalence": (
                    sum((row.get(field) or 0) > 0 for row in descriptor_measured)
                    / population_n
                    if descriptor_complete and population_n
                    else None
                ),
            }
        )
    unsafe = next(row for row in construct_rows if row["descriptor"] == "unsafe_call_count")
    complete_finding_counts = finding_counts if scanner_complete else {key: None for key in finding_counts}
    positive = sum((row.get("flawfinder_finding_count") or 0) > 0 for row in scanner_measured)
    return {
        "population_n": population_n,
        "security_measured_n": len(fully_measured),
        "security_measurement_coverage": (
            len(fully_measured) / population_n if population_n else None
        ),
        "flawfinder_measured_n": len(scanner_measured),
        "flawfinder_measurement_coverage": (
            len(scanner_measured) / population_n if population_n else None
        ),
        "descriptor_measured_n": len(descriptor_measured),
        "descriptor_measurement_coverage": (
            len(descriptor_measured) / population_n if population_n else None
        ),
        "static_finding_prevalence": (
            positive / population_n if scanner_complete and population_n else None
        ),
        "flawfinder_findings": complete_finding_counts,
        "findings_per_kloc": densities if scanner_complete else {key: None for key in densities},
        "unsafe_api_prevalence": unsafe["prevalence"],
        "mean_unsafe_call_count": unsafe["mean_count"],
        "distinct_cwe_count": len(cwe_findings) if scanner_complete else None,
        "severity_distribution": severity_rows,
        "maximum_level_distribution": maximum_level_rows,
        "cwe_distribution": cwe_rows,
        "construct_profile": construct_rows,
        "unmeasured_runs": [
            {"run_id": row["run_id"], "reason": row.get("unavailable_reason")}
            for row in rows
            if row.get("analysis_status") != "available"
        ],
    }


def paper_security_row(
    summary: Mapping[str, Any], metadata: Mapping[str, Any]
) -> dict[str, Any]:
    findings = summary["flawfinder_findings"]
    density = summary["findings_per_kloc"]
    return {
        "Issue": metadata.get("issue"),
        "Checkpoint": metadata.get("checkpoint"),
        "Model": metadata.get("model"),
        "Temp": metadata.get("temperature"),
        "Security Population N": summary["population_n"],
        "Static Finding Prevalence": summary["static_finding_prevalence"],
        "Mean Flawfinder Findings": findings["mean"],
        "Median Flawfinder Findings": findings["median"],
        "SD Flawfinder Findings": findings["sample_sd"],
        "Min Flawfinder Findings": findings["minimum"],
        "Max Flawfinder Findings": findings["maximum"],
        "Mean Flawfinder Findings per KLOC": density["mean"],
        "Median Flawfinder Findings per KLOC": density["median"],
        "SD Flawfinder Findings per KLOC": density["sample_sd"],
        "Unsafe API Prevalence": summary["unsafe_api_prevalence"],
        "Mean Unsafe API Calls": summary["mean_unsafe_call_count"],
        "Distinct CWE Count": summary["distinct_cwe_count"],
        "Flawfinder Version": summary.get("flawfinder", {}).get("version"),
        "Security Measurement Coverage": summary["security_measurement_coverage"],
    }


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def analyze_security_population(
    *,
    candidates: Sequence[Mapping[str, Any]],
    output_dir: Path,
    configuration: Mapping[str, Any],
    metadata: Mapping[str, Any],
    formal: bool,
    explicit_executable: str | Path | None = None,
) -> dict[str, Any]:
    resolved = validate_security_configuration(configuration)
    fingerprint = security_configuration_fingerprint(resolved)
    provenance = flawfinder_provenance(resolved, explicit_executable)
    rows = [
        measure_security_candidate(
            run_id=str(candidate["run_id"]),
            source=(Path(candidate["source"]) if candidate.get("source") else None),
            source_identifier=str(candidate["source_identifier"]),
            configuration=resolved,
            provenance=provenance,
        )
        for candidate in sorted(candidates, key=lambda item: str(item["run_id"]))
    ]
    aggregate = aggregate_security_population(rows)
    aggregate.update(
        {
            "schema_version": SECURITY_SCHEMA_VERSION,
            "role": "formal_rq3_security" if formal else "rq3_security",
            "formal_analysis": formal,
            "status": (
                "formally_unavailable"
                if formal and aggregate["security_measurement_coverage"] != 1.0
                else "completed"
                if aggregate["security_measurement_coverage"] == 1.0
                else "partially_available"
            ),
            "terminology": "static findings and risk descriptors are not confirmed vulnerabilities",
            "security_configuration": resolved,
            "security_configuration_fingerprint": fingerprint,
            "flawfinder": {
                **provenance,
                "command_template": [
                    provenance["executable_identifier"],
                    *provenance["options"],
                    "<candidate-source-basename>",
                ],
                "analyzed_candidates": aggregate["flawfinder_measured_n"],
                "unavailable_or_failed_candidates": (
                    aggregate["population_n"] - aggregate["flawfinder_measured_n"]
                ),
            },
        }
    )
    findings = [finding for row in rows for finding in row["_findings"]]
    serializable_rows = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in rows
    ]
    write_csv(output_dir / "security_per_run.csv", serializable_rows, SECURITY_PER_RUN_FIELDS)
    write_csv(output_dir / "flawfinder_findings.csv", findings, FLAWFINDER_FINDING_FIELDS)
    write_csv(
        output_dir / "security_severity_distribution.csv",
        aggregate["severity_distribution"],
        ("level", "finding_count", "implementations_with_finding", "candidate_prevalence"),
    )
    write_csv(
        output_dir / "security_max_level_distribution.csv",
        aggregate["maximum_level_distribution"],
        ("maximum_level", "implementation_count", "proportion"),
    )
    write_csv(
        output_dir / "security_cwe_distribution.csv",
        aggregate["cwe_distribution"],
        ("cwe_id", "occurrence_count", "implementations_with_cwe", "candidate_prevalence"),
    )
    write_csv(
        output_dir / "security_construct_profile.csv",
        aggregate["construct_profile"],
        ("descriptor", "mean_count", "median_count", "implementations_with_occurrence", "prevalence"),
    )
    paper_row = paper_security_row(aggregate, metadata)
    write_csv(output_dir / "paper_security_metrics.csv", [paper_row], PAPER_SECURITY_COLUMNS)
    write_json(
        output_dir / "paper_security_schema.json",
        {
            "schema_version": SECURITY_SCHEMA_VERSION,
            "columns": PAPER_SECURITY_COLUMNS,
            "population": "the same retained successful implementation population as RQ2",
            "primary_external_analyzer": "Flawfinder findings",
            "supporting_descriptors": list(CONSTRUCT_FIELDS),
            "missing_values": "Unavailable values are null in JSON and blank in CSV.",
            "terminology": "Static findings and descriptors are not confirmed vulnerabilities.",
        },
    )
    write_json(output_dir / "security_summary.json", aggregate)
    return {"summary": aggregate, "rows": rows, "paper_row": paper_row}
