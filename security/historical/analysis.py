"""Version-specific historical function mapping and coverage metrics."""

from __future__ import annotations

import hashlib
import json
import random
import re
import statistics
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence

from security.common.callgraph import SELECTION_POLICIES, analyze_source_tree, select_functions

SCHEMA_VERSION = 5
ALLOWED_UTILITIES = {"sort", "mkdir", "chmod", "grep"}
ALLOWED_PROJECTS = {"gnu-coreutils", "gnu-grep"}
RECORD_FIELDS = {
    "id": str, "utility": str, "upstream_project": str,
    "affected_version": str, "fixed_version": str, "source_revision": str,
    "vulnerable_functions": list, "patched_functions": list, "cwe": str,
    "bug_type": str, "attacker_input": str, "source_reference": str,
    "patch_reference": str, "notes": str, "verified": bool,
    "source_provenance": str, "upstream_base_version": str,
    "downstream_revision": str,
}
REQUIRED_RECORD_FIELDS = set(RECORD_FIELDS) - {
    "source_provenance", "upstream_base_version", "downstream_revision",
}
MANIFEST_FIELDS = {
    "upstream_project": str, "affected_version": str, "source_revision": str,
    "source_tree": str, "source_tree_sha256": str, "programs": dict,
    "source_provenance": str, "upstream_base_version": str,
    "downstream_revision": str, "downstream_source": dict,
}
REQUIRED_MANIFEST_FIELDS = set(MANIFEST_FIELDS) - {
    "source_provenance", "upstream_base_version", "downstream_revision",
    "downstream_source",
}
DOWNSTREAM_SOURCE_FIELDS = {
    "distribution": str, "source_package": str,
    "packaging_repository": str, "spec_file": str, "spec_sha256": str,
    "security_patch_file": str, "security_patch_sha256": str,
    "security_patch_git_blob": str,
    "upstream_archive_sha256": str, "upstream_signature_sha256": str,
}
PROGRAM_FIELDS = {
    "entry_point": dict, "source_globs": list, "source_files": list,
    "declared_indirect_dispatches": list,
}
ENTRY_POINT_FIELDS = {"source_file": str, "function": str}
INDIRECT_DISPATCH_FIELDS = {
    "caller": dict, "callee_text": str, "possible_target": dict,
}
CENSUS_FIELDS = {
    "id": str, "identifier_type": str,
    "package_project": str, "utility_component": str,
    "target_utility": bool, "provenance": str, "analysis_eligibility": str,
    "disposition_reason": str, "source_patch_verification_status": str,
    "references": list,
}
CENSUS_IDENTIFIER_TYPES = {"cve", "temporary"}
CENSUS_PROVENANCE = {
    "upstream_gnu", "downstream_patch", "predecessor_package",
    "unrelated_implementation",
}
CENSUS_ELIGIBILITY = {"eligible", "excluded", "unresolved"}
CENSUS_VERIFICATION = {"verified", "partially_verified", "unverified"}
MAPPED_STATES = {"mapped_and_reachable", "mapped_without_resolved_static_path"}
HVC_ELIGIBLE_STATE = "mapped_and_reachable"
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class HistoricalDataError(ValueError):
    pass


class ProgramAnalysisError(ValueError):
    def __init__(
        self, status: str, message: str, *,
        source_qualified_entry_point: str | None = None,
        resolved_source_files: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.status = status
        self.source_qualified_entry_point = source_qualified_entry_point
        self.resolved_source_files = list(resolved_source_files)


def _is_commit_sha(value: Any) -> bool:
    return isinstance(value, str) and COMMIT_SHA_PATTERN.fullmatch(value) is not None


def _validate_fields(
    value: Mapping[str, Any], fields: Mapping[str, type], *,
    required_fields: Iterable[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(value) - set(fields))
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    required = set(fields) if required_fields is None else set(required_fields)
    for field, expected in fields.items():
        if field not in value:
            if field in required:
                errors.append(f"missing field: {field}")
        elif not isinstance(value[field], expected) or (
            expected is bool and type(value[field]) is not bool
        ):
            errors.append(f"{field} must be {expected.__name__}")
    return errors


def validate_record(record: Mapping[str, Any]) -> list[str]:
    errors = _validate_fields(
        record, RECORD_FIELDS, required_fields=REQUIRED_RECORD_FIELDS
    )
    for field in ("id", "source_revision"):
        if isinstance(record.get(field), str) and not record[field].strip():
            errors.append(f"{field} must not be empty")
    revision = record.get("source_revision")
    if isinstance(revision, str) and not _is_commit_sha(revision):
        errors.append("source_revision must be a lowercase 40-character Git commit SHA")
    errors.extend(_validate_downstream_identity(record))
    if record.get("utility") not in ALLOWED_UTILITIES:
        errors.append("utility must be sort, mkdir, chmod, or grep")
    if record.get("upstream_project") not in ALLOWED_PROJECTS:
        errors.append("upstream_project must be gnu-coreutils or gnu-grep")
    for field, require_nonempty in (("vulnerable_functions", True), ("patched_functions", False)):
        values = record.get(field)
        if not isinstance(values, list):
            continue
        if require_nonempty and not values:
            errors.append(f"{field} must not be empty")
        strings = [item for item in values if isinstance(item, str)]
        if len(strings) != len(values):
            errors.append(f"{field} entries must be strings")
        if any(not item.strip() for item in strings):
            errors.append(f"{field} entries must not be empty")
        if len(set(strings)) != len(values):
            errors.append(f"{field} entries must be unique")
    return errors


def validate_records(records: Any) -> list[str]:
    if not isinstance(records, list):
        return ["dataset root must be an array"]
    errors: list[str] = []
    identifiers: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            errors.append(f"record {index}: must be an object")
            continue
        errors.extend(f"record {index}: {error}" for error in validate_record(record))
        identifier = record.get("id")
        if isinstance(identifier, str):
            if identifier in identifiers:
                errors.append(f"record {index}: duplicate id: {identifier}")
            identifiers.add(identifier)
    return errors


def validate_census(records: Any) -> list[str]:
    if not isinstance(records, list):
        return ["census root must be an array"]
    errors: list[str] = []
    identifiers: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"record {index}: "
        if not isinstance(record, Mapping):
            errors.append(prefix + "must be an object")
            continue
        errors.extend(prefix + error for error in _validate_fields(record, CENSUS_FIELDS))
        for field in ("id", "package_project", "utility_component", "disposition_reason"):
            if isinstance(record.get(field), str) and not record[field].strip():
                errors.append(prefix + f"{field} must not be empty")
        if record.get("identifier_type") not in CENSUS_IDENTIFIER_TYPES:
            errors.append(prefix + "invalid identifier_type")
        identifier = record.get("id")
        identifier_type = record.get("identifier_type")
        if isinstance(identifier, str):
            is_cve = re.fullmatch(r"CVE-\d{4}-\d{4,}", identifier) is not None
            if identifier_type == "cve" and not is_cve:
                errors.append(prefix + "cve identifier_type requires a CVE identifier")
            if identifier_type == "temporary" and is_cve:
                errors.append(prefix + "temporary identifier_type cannot use a CVE identifier")
        if record.get("provenance") not in CENSUS_PROVENANCE:
            errors.append(prefix + "invalid provenance")
        if record.get("analysis_eligibility") not in CENSUS_ELIGIBILITY:
            errors.append(prefix + "invalid analysis_eligibility")
        if record.get("source_patch_verification_status") not in CENSUS_VERIFICATION:
            errors.append(prefix + "invalid source_patch_verification_status")
        references = record.get("references")
        if isinstance(references, list):
            strings = [item for item in references if isinstance(item, str)]
            if not references:
                errors.append(prefix + "references must not be empty")
            if len(strings) != len(references) or any(not item.strip() for item in strings):
                errors.append(prefix + "references entries must be non-empty strings")
            if len(set(strings)) != len(references):
                errors.append(prefix + "references entries must be unique")
        if isinstance(identifier, str):
            if identifier in identifiers:
                errors.append(prefix + f"duplicate id: {identifier}")
            identifiers.add(identifier)
    return errors


def summarize_census(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize discovery dispositions without treating temporary IDs as CVEs."""
    return {
        "discovery_entry_count": len(records),
        "cve_identifier_count": sum(
            item.get("identifier_type") == "cve" for item in records
        ),
        "temporary_identifier_count": sum(
            item.get("identifier_type") == "temporary" for item in records
        ),
        "eligibility_counts": dict(sorted(Counter(
            str(item.get("analysis_eligibility")) for item in records
        ).items())),
        "provenance_counts": dict(sorted(Counter(
            str(item.get("provenance")) for item in records
        ).items())),
    }


def _validate_downstream_identity(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    provenance = value.get("source_provenance")
    downstream_fields = (
        "upstream_base_version", "downstream_revision",
    )
    if provenance is not None and provenance not in {"upstream_gnu", "downstream_patch"}:
        errors.append("source_provenance must be upstream_gnu or downstream_patch")
    if provenance == "downstream_patch":
        for field in downstream_fields:
            if not isinstance(value.get(field), str) or not value[field].strip():
                errors.append(f"{field} is required for downstream_patch provenance")
        revision = value.get("downstream_revision")
        if isinstance(revision, str) and not _is_commit_sha(revision):
            errors.append(
                "downstream_revision must be a lowercase 40-character Git commit SHA"
            )
    elif any(field in value for field in downstream_fields):
        errors.append(
            "downstream identity fields require source_provenance=downstream_patch"
        )
    return errors


def _validate_downstream_source(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return ["downstream_source must be an object"]
    errors = _validate_fields(value, DOWNSTREAM_SOURCE_FIELDS)
    for field, item in value.items():
        if isinstance(item, str) and not item.strip():
            errors.append(f"downstream_source.{field} must not be empty")
    for field in (
        "spec_sha256", "security_patch_sha256", "upstream_archive_sha256",
        "upstream_signature_sha256",
    ):
        digest = value.get(field)
        if isinstance(digest, str) and not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"downstream_source.{field} must be a lowercase SHA-256")
    blob = value.get("security_patch_git_blob")
    if isinstance(blob, str) and not _is_commit_sha(blob):
        errors.append(
            "downstream_source.security_patch_git_blob must be a lowercase Git object id"
        )
    for field in ("spec_file", "security_patch_file"):
        item = value.get(field)
        if isinstance(item, str):
            path_error = _relative_scope_path_error(item, allow_glob=False)
            if path_error:
                errors.append(f"downstream_source.{field}: {path_error}")
    return errors


def _relative_scope_path_error(value: str, *, allow_glob: bool) -> str | None:
    if not value.strip():
        return "must not be empty"
    if "\\" in value:
        return "must use forward slashes"
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive:
        return "must be relative to the source tree"
    if ".." in path.parts:
        return "must not escape the source tree"
    if not allow_glob and any(character in value for character in "*?["):
        return "must be an exact path, not a glob"
    return None


def validate_manifest_entry(entry: Mapping[str, Any]) -> list[str]:
    errors = _validate_fields(
        entry, MANIFEST_FIELDS, required_fields=REQUIRED_MANIFEST_FIELDS
    )
    for field in ("affected_version", "source_revision", "source_tree"):
        if isinstance(entry.get(field), str) and not entry[field].strip():
            errors.append(f"{field} must not be empty")
    revision = entry.get("source_revision")
    if isinstance(revision, str) and not _is_commit_sha(revision):
        errors.append("source_revision must be a lowercase 40-character Git commit SHA")
    if entry.get("upstream_project") not in ALLOWED_PROJECTS:
        errors.append("upstream_project must be gnu-coreutils or gnu-grep")
    errors.extend(_validate_downstream_identity(entry))
    if entry.get("source_provenance") == "downstream_patch":
        if "downstream_source" not in entry:
            errors.append("downstream_source is required for downstream_patch provenance")
        else:
            errors.extend(_validate_downstream_source(entry.get("downstream_source")))
    elif "downstream_source" in entry:
        errors.append(
            "downstream_source requires source_provenance=downstream_patch"
        )
    fingerprint = entry.get("source_tree_sha256")
    if isinstance(fingerprint, str) and not (
        len(fingerprint) == 64
        and all(character in "0123456789abcdef" for character in fingerprint.lower())
    ):
        errors.append("source_tree_sha256 must be a 64-character hexadecimal digest")
    programs = entry.get("programs")
    if isinstance(programs, dict):
        if not programs:
            errors.append("programs must contain at least one utility")
        for utility, program in programs.items():
            prefix = f"programs.{utility}"
            if utility not in ALLOWED_UTILITIES:
                errors.append(f"{prefix}: unsupported utility")
            if not isinstance(program, Mapping):
                errors.append(f"{prefix}: must be an object")
                continue
            errors.extend(
                f"{prefix}: {error}"
                for error in _validate_fields(
                    program, PROGRAM_FIELDS, required_fields=("entry_point",)
                )
            )
            scope_fields = [
                field for field in ("source_globs", "source_files")
                if field in program
            ]
            if len(scope_fields) != 1:
                errors.append(
                    f"{prefix}: exactly one of source_globs or source_files is required"
                )
            entry_point = program.get("entry_point")
            if isinstance(entry_point, Mapping):
                errors.extend(
                    f"{prefix}.entry_point: {error}"
                    for error in _validate_fields(entry_point, ENTRY_POINT_FIELDS)
                )
                source_file = entry_point.get("source_file")
                function = entry_point.get("function")
                if isinstance(source_file, str):
                    path_error = _relative_scope_path_error(source_file, allow_glob=False)
                    if path_error:
                        errors.append(f"{prefix}.entry_point.source_file: {path_error}")
                if isinstance(function, str) and not function.strip():
                    errors.append(f"{prefix}.entry_point.function must not be empty")
            globs = program.get("source_globs")
            if isinstance(globs, list):
                if not globs:
                    errors.append(f"{prefix}.source_globs must not be empty")
                if any(not isinstance(pattern, str) for pattern in globs):
                    errors.append(f"{prefix}.source_globs entries must be strings")
                strings = [pattern for pattern in globs if isinstance(pattern, str)]
                if len(set(strings)) != len(strings):
                    errors.append(f"{prefix}.source_globs entries must be unique")
                for pattern in strings:
                    path_error = _relative_scope_path_error(pattern, allow_glob=True)
                    if path_error:
                        errors.append(f"{prefix}.source_globs: {path_error}: {pattern}")
            source_files = program.get("source_files")
            if isinstance(source_files, list):
                if not source_files:
                    errors.append(f"{prefix}.source_files must not be empty")
                if any(not isinstance(path, str) for path in source_files):
                    errors.append(f"{prefix}.source_files entries must be strings")
                strings = [path for path in source_files if isinstance(path, str)]
                if len(set(strings)) != len(strings):
                    errors.append(f"{prefix}.source_files entries must be unique")
                for path in strings:
                    path_error = _relative_scope_path_error(path, allow_glob=False)
                    if path_error:
                        errors.append(f"{prefix}.source_files: {path_error}: {path}")
                    elif not path.endswith(".c"):
                        errors.append(
                            f"{prefix}.source_files entries must name C files: {path}"
                        )
            dispatches = program.get("declared_indirect_dispatches")
            if isinstance(dispatches, list):
                if not dispatches:
                    errors.append(
                        f"{prefix}.declared_indirect_dispatches must not be empty"
                    )
                for index, dispatch in enumerate(dispatches):
                    dispatch_prefix = (
                        f"{prefix}.declared_indirect_dispatches[{index}]"
                    )
                    if not isinstance(dispatch, Mapping):
                        errors.append(f"{dispatch_prefix}: must be an object")
                        continue
                    errors.extend(
                        f"{dispatch_prefix}: {error}"
                        for error in _validate_fields(
                            dispatch, INDIRECT_DISPATCH_FIELDS
                        )
                    )
                    for endpoint_name in ("caller", "possible_target"):
                        endpoint = dispatch.get(endpoint_name)
                        if not isinstance(endpoint, Mapping):
                            continue
                        errors.extend(
                            f"{dispatch_prefix}.{endpoint_name}: {error}"
                            for error in _validate_fields(
                                endpoint, ENTRY_POINT_FIELDS
                            )
                        )
                        endpoint_file = endpoint.get("source_file")
                        endpoint_function = endpoint.get("function")
                        if isinstance(endpoint_file, str):
                            path_error = _relative_scope_path_error(
                                endpoint_file, allow_glob=False
                            )
                            if path_error:
                                errors.append(
                                    f"{dispatch_prefix}.{endpoint_name}.source_file: "
                                    f"{path_error}"
                                )
                            elif (
                                isinstance(source_files, list)
                                and endpoint_file not in source_files
                            ):
                                errors.append(
                                    f"{dispatch_prefix}.{endpoint_name}.source_file "
                                    "must be in source_files"
                                )
                        if (
                            isinstance(endpoint_function, str)
                            and not endpoint_function.strip()
                        ):
                            errors.append(
                                f"{dispatch_prefix}.{endpoint_name}.function "
                                "must not be empty"
                            )
                    callee_text = dispatch.get("callee_text")
                    if isinstance(callee_text, str) and not callee_text.strip():
                        errors.append(
                            f"{dispatch_prefix}.callee_text must not be empty"
                        )
    return errors


def validate_source_manifest(entries: Any) -> list[str]:
    if not isinstance(entries, list):
        return ["source manifest root must be an array"]
    errors: list[str] = []
    identities: set[tuple[str, str, str]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            errors.append(f"source {index}: must be an object")
            continue
        errors.extend(f"source {index}: {error}" for error in validate_manifest_entry(entry))
        identity = tuple(str(entry.get(field, "")) for field in (
            "upstream_project", "affected_version", "source_revision"
        ))
        if identity in identities:
            errors.append(f"source {index}: duplicate source identity: {'/'.join(identity)}")
        identities.add(identity)
    return errors


def _load_array(path: Path, validator: Any, label: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HistoricalDataError(f"cannot read {label}: {error}") from error
    errors = validator(raw)
    if errors:
        raise HistoricalDataError("; ".join(errors))
    return [dict(item) for item in raw]


def load_records(path: Path) -> list[dict[str, Any]]:
    return _load_array(path, validate_records, "historical dataset")


def load_census(path: Path) -> list[dict[str, Any]]:
    return _load_array(path, validate_census, "historical CVE census")


def load_source_manifest(path: Path) -> list[dict[str, Any]]:
    entries = _load_array(path, validate_source_manifest, "source manifest")
    for entry in entries:
        candidate = Path(entry["source_tree"])
        entry["resolved_source_tree"] = str(
            candidate.resolve() if candidate.is_absolute()
            else (path.parent / candidate).resolve()
        )
    return entries


def source_tree_sha256(source_tree: Path) -> str:
    """Fingerprint the C inputs used to construct a historical call graph."""
    digest = hashlib.sha256()
    for source in sorted(
        path for path in source_tree.rglob("*")
        if path.is_file() and path.suffix in {".c", ".h"}
    ):
        relative = source.relative_to(source_tree).as_posix().encode()
        contents = source.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def verify_source_tree_sha256(source_tree: Path, expected: str) -> str:
    """Return the C/H fingerprint or fail closed when it is not the frozen value."""
    observed = source_tree_sha256(source_tree)
    if observed.lower() != expected.lower():
        raise HistoricalDataError(
            f"source-tree fingerprint mismatch: observed {observed}, expected {expected}"
        )
    return observed


def _identity(record: Mapping[str, Any]) -> tuple[str, ...]:
    identity = (
        str(record["upstream_project"]), str(record["affected_version"]),
        str(record["source_revision"]),
    )
    if record.get("source_provenance") == "downstream_patch":
        return (*identity, "downstream_patch", str(record["upstream_base_version"]),
                str(record["downstream_revision"]))
    return identity


def _emitted_source_identity(
    record: Mapping[str, Any], source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize provenance without conflating upstream and downstream revisions."""
    manifest_source = source or {}
    provenance = str(
        manifest_source.get(
            "source_provenance", record.get("source_provenance", "upstream_gnu")
        )
    )
    identity: dict[str, Any] = {"source_provenance": provenance}
    if provenance != "downstream_patch":
        return identity
    for field in ("upstream_base_version", "downstream_revision"):
        value = manifest_source.get(field, record.get(field))
        if value is not None:
            identity[field] = value
    downstream_source = manifest_source.get(
        "downstream_source", record.get("downstream_source")
    )
    if isinstance(downstream_source, Mapping):
        identity["downstream_source"] = dict(downstream_source)
    return identity


def _source_resolution(
    record: Mapping[str, Any], manifest: Sequence[Mapping[str, Any]],
) -> tuple[str, Mapping[str, Any] | None, str | None]:
    project_version = [
        item for item in manifest
        if item.get("upstream_project") == record["upstream_project"]
        and item.get("affected_version") == record["affected_version"]
    ]
    exact = [item for item in project_version if item.get("source_revision") == record["source_revision"]]
    if not exact:
        return (
            "source_version_mismatch" if project_version else "source_version_unavailable",
            None,
            "no manifest entry matches the record's exact source revision"
            if project_version else "no manifest entry matches the project and affected version",
        )
    if len(exact) != 1:
        return "source_version_mismatch", None, "source identity is not unique in the manifest"
    entry = exact[0]
    record_downstream = record.get("source_provenance") == "downstream_patch"
    entry_downstream = entry.get("source_provenance") == "downstream_patch"
    if record_downstream != entry_downstream:
        return (
            "source_version_mismatch", entry,
            "record and manifest disagree about downstream-patch provenance",
        )
    if record_downstream and any(
        entry.get(field) != record.get(field)
        for field in ("upstream_base_version", "downstream_revision")
    ):
        return (
            "source_version_mismatch", entry,
            "no manifest entry matches the record's exact downstream source identity",
        )
    source_tree = Path(str(entry.get("resolved_source_tree", entry["source_tree"])))
    if not source_tree.is_dir():
        return "source_version_unavailable", entry, f"source tree is unavailable: {source_tree}"
    observed = source_tree_sha256(source_tree)
    if observed.lower() != str(entry["source_tree_sha256"]).lower():
        return "source_version_mismatch", entry, "source tree fingerprint does not match manifest metadata"
    return "source_version_matched", entry, None


def _resolve_program_scope(
    source_tree: Path, program: Mapping[str, Any],
) -> tuple[str, list[str]]:
    """Resolve one manifest program scope to a stable, contained C-file list."""
    root = source_tree.resolve()
    entry_point = program.get("entry_point")
    globs = program.get("source_globs")
    source_files = program.get("source_files")
    if (
        not isinstance(entry_point, Mapping)
        or (isinstance(globs, list) == isinstance(source_files, list))
    ):
        raise ProgramAnalysisError(
            "analysis_scope_invalid", "program scope metadata is incomplete"
        )
    source_file = entry_point.get("source_file")
    function = entry_point.get("function")
    if not isinstance(source_file, str) or not isinstance(function, str):
        raise ProgramAnalysisError(
            "analysis_scope_invalid", "program entry point metadata is invalid"
        )
    qualified_entry = f"{PurePosixPath(source_file).as_posix()}::{function}"
    scope_values = globs if isinstance(globs, list) else source_files
    assert isinstance(scope_values, list)
    allow_scope_glob = isinstance(globs, list)
    for value, allow_glob in (
        (source_file, False),
        *((item, allow_scope_glob) for item in scope_values),
    ):
        if not isinstance(value, str):
            raise ProgramAnalysisError(
                "analysis_scope_invalid", "program source paths must be strings"
            )
        path_error = _relative_scope_path_error(value, allow_glob=allow_glob)
        if path_error:
            raise ProgramAnalysisError(
                "analysis_scope_invalid", f"{path_error}: {value}",
                source_qualified_entry_point=qualified_entry,
            )

    matched: dict[str, Path] = {}
    try:
        for pattern in scope_values:
            candidates = root.glob(pattern) if allow_scope_glob else (
                root.joinpath(*PurePosixPath(pattern).parts),
            )
            for candidate in candidates:
                resolved = candidate.resolve()
                try:
                    relative = resolved.relative_to(root).as_posix()
                except ValueError as error:
                    raise ProgramAnalysisError(
                        "analysis_scope_invalid",
                        f"source path resolves outside the source tree: {pattern}",
                        source_qualified_entry_point=qualified_entry,
                        resolved_source_files=sorted(matched),
                    ) from error
                if resolved.is_file() and resolved.suffix.lower() == ".c":
                    matched[relative] = resolved
    except (OSError, ValueError) as error:
        if isinstance(error, ProgramAnalysisError):
            raise
        raise ProgramAnalysisError(
            "analysis_scope_invalid", f"cannot resolve program source paths: {error}",
            source_qualified_entry_point=qualified_entry,
            resolved_source_files=sorted(matched),
        ) from error
    resolved_files = sorted(matched)
    if not resolved_files:
        raise ProgramAnalysisError(
            "analysis_scope_empty", "program source scope matched no C files",
            source_qualified_entry_point=qualified_entry,
        )
    if isinstance(source_files, list) and len(resolved_files) != len(source_files):
        missing = sorted(set(source_files) - set(resolved_files))
        raise ProgramAnalysisError(
            "analysis_scope_invalid",
            f"exact program source files are missing or not C files: {', '.join(missing)}",
            source_qualified_entry_point=qualified_entry,
            resolved_source_files=resolved_files,
        )
    normalized_entry_file = PurePosixPath(source_file).as_posix()
    if normalized_entry_file not in matched:
        raise ProgramAnalysisError(
            "entry_point_outside_scope",
            "configured entry-point source file is outside the resolved program scope",
            source_qualified_entry_point=qualified_entry,
            resolved_source_files=resolved_files,
        )
    return qualified_entry, resolved_files


def _source_qualified_function(
    analysis: Mapping[str, Any], endpoint: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    matches = [
        item for item in analysis.get("function_reachability", [])
        if item.get("source_file") == endpoint.get("source_file")
        and item.get("function") == endpoint.get("function")
    ]
    return matches[0] if len(matches) == 1 else None


def _shortest_resolved_suffix(
    analysis: Mapping[str, Any], start: str, target: str,
) -> list[str] | None:
    rows = {
        str(item.get("function_id")): item
        for item in analysis.get("function_reachability", [])
    }
    if start not in rows or target not in rows:
        return None
    pending: list[tuple[str, list[str]]] = [(start, [start])]
    visited: set[str] = set()
    while pending:
        current, path = pending.pop(0)
        if current == target:
            return path
        if current in visited:
            continue
        visited.add(current)
        row = rows[current]
        callees = sorted(set(row.get("direct_callees", [])) | set(
            row.get("callback_callees", [])
        ))
        pending.extend(
            (str(callee), [*path, str(callee)])
            for callee in callees if str(callee) not in visited
        )
    return None


def _unresolved_indirect_dispatch_evidence(
    analysis: Mapping[str, Any], target_function_id: str,
    dispatches: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Find predeclared indirect boundaries without converting them to edges."""
    unresolved = analysis.get("unresolved_direct_calls", [])
    evidence: list[dict[str, Any]] = []
    for dispatch in dispatches:
        caller_spec = dispatch.get("caller")
        possible_target_spec = dispatch.get("possible_target")
        if not isinstance(caller_spec, Mapping) or not isinstance(
            possible_target_spec, Mapping
        ):
            continue
        caller = _source_qualified_function(analysis, caller_spec)
        possible_target = _source_qualified_function(analysis, possible_target_spec)
        if caller is None or possible_target is None:
            continue
        caller_id = str(caller["function_id"])
        callee_text = dispatch.get("callee_text")
        unresolved_call = next((
            item for item in unresolved
            if item.get("caller") == caller_id
            and item.get("callee_text") == callee_text
        ), None)
        suffix = _shortest_resolved_suffix(
            analysis, str(possible_target["function_id"]), target_function_id
        )
        if (
            caller.get("reachable_from_entry") is not True
            or unresolved_call is None
            or suffix is None
        ):
            continue
        evidence.append({
            "caller_function_id": caller_id,
            "caller_source_file": caller.get("source_file"),
            "callee_text": callee_text,
            "unresolved_reason": unresolved_call.get("reason"),
            "possible_target_function_id": possible_target.get("function_id"),
            "possible_target_source_file": possible_target.get("source_file"),
            "resolved_path_to_dispatch_caller": list(
                caller.get("shortest_call_path", [])
            ),
            "resolved_static_suffix": suffix,
        })
    return sorted(
        evidence,
        key=lambda item: (
            str(item["caller_source_file"]), str(item["caller_function_id"]),
            str(item["callee_text"]), str(item["possible_target_function_id"]),
        ),
    )


def map_record_to_graph(
    record: Mapping[str, Any], analysis: Mapping[str, Any], *,
    source_analysis_id: str | None = None,
    source_qualified_entry_point: str | None = None,
    resolved_source_files: Sequence[str] = (),
    declared_indirect_dispatches: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Map every declared vulnerable function and retain a CVE-level aggregate."""
    function_mappings = [
        _map_function_to_graph(
            record, target, analysis,
            source_analysis_id=source_analysis_id,
            source_qualified_entry_point=source_qualified_entry_point,
            resolved_source_files=resolved_source_files,
            declared_indirect_dispatches=declared_indirect_dispatches,
        )
        for target in record["vulnerable_functions"]
    ]
    return _aggregate_record_mapping(record, function_mappings)


def _map_function_to_graph(
    record: Mapping[str, Any], target: str, analysis: Mapping[str, Any], *,
    source_analysis_id: str | None = None,
    source_qualified_entry_point: str | None = None,
    resolved_source_files: Sequence[str] = (),
    declared_indirect_dispatches: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    matches = [
        item for item in analysis.get("function_reachability", [])
        if item.get("function") == target or item.get("function_id") == target
    ]
    unique = {str(item.get("function_id")): item for item in matches}
    if not unique:
        status, matched = "function_not_found", None
    elif len(unique) > 1:
        status, matched = "ambiguous_function_name", None
    else:
        matched = next(iter(unique.values()))
        status = (
            "mapped_and_reachable"
            if matched.get("reachable_from_entry") is True
            else "mapped_without_resolved_static_path"
        )
    depth = matched.get("call_depth") if matched else None
    indirect_dispatch_evidence = (
        _unresolved_indirect_dispatch_evidence(
            analysis, str(matched["function_id"]), declared_indirect_dispatches
        )
        if matched and matched.get("reachable_from_entry") is not True
        else []
    )
    call_depth_status = (
        "resolved_numeric_depth"
        if isinstance(depth, int)
        else "unresolved_indirect_dispatch"
        if indirect_dispatch_evidence
        else "no_resolved_static_path"
        if matched
        else "mapping_unresolved"
    )
    maximum = analysis.get("max_reachable_call_depth")
    normalized = (
        depth / maximum
        if isinstance(depth, int) and isinstance(maximum, int) and maximum > 0
        else None
    )
    return {
        "vulnerability_id": record["id"], "utility": record["utility"],
        "upstream_project": record["upstream_project"],
        "affected_version": record["affected_version"],
        "source_revision": record["source_revision"],
        **_emitted_source_identity(record),
        "vulnerable_function": target,
        "source_version_status": "source_version_matched",
        "source_version_error": None, "analysis_error": None,
        "mapping_status": status, "verified": record["verified"],
        "eligible_for_hvc": record["verified"] is True and status == HVC_ELIGIBLE_STATE,
        "source_analysis_id": source_analysis_id,
        "source_qualified_entry_point": source_qualified_entry_point,
        "resolved_source_files": list(resolved_source_files),
        "mapped_function_id": matched.get("function_id") if matched else None,
        "mapped_source_file": matched.get("source_file") if matched else None,
        "call_depth_status": call_depth_status,
        "unresolved_indirect_dispatches": indirect_dispatch_evidence,
        "call_depth": depth,
        "shortest_call_path": (
            list(matched.get("shortest_call_path", []))
            if matched and matched.get("shortest_call_path") is not None
            else None
        ),
        "direct_callers": list(matched.get("direct_callers", [])) if matched else [],
        "direct_callees": list(matched.get("direct_callees", [])) if matched else [],
        "reachable_from_entry": matched.get("reachable_from_entry") if matched else None,
        "reachable_from_main": matched.get("reachable_from_entry") if matched else None,
        "total_reachable_functions": analysis.get("reachable_function_count"),
        "diversification_eligible_function_count": analysis.get("diversification_eligible_function_count"),
        "maximum_reachable_depth": maximum,
        "normalized_depth": normalized,
    }


def _overall_mapping_status(function_mappings: Sequence[Mapping[str, Any]]) -> str:
    states = {str(item.get("mapping_status")) for item in function_mappings}
    if len(states) == 1:
        return next(iter(states))
    mapped = sum(item.get("mapping_status") in MAPPED_STATES for item in function_mappings)
    if mapped == len(function_mappings):
        return "mapped_with_mixed_path_resolution"
    if mapped:
        return "partial_mapping"
    return "unmapped_functions"


def _aggregate_record_mapping(
    record: Mapping[str, Any], function_mappings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    mappings = [dict(item) for item in function_mappings]
    mapped_count = sum(item.get("mapping_status") in MAPPED_STATES for item in mappings)
    reachable = [
        item for item in mappings
        if item.get("mapping_status") == HVC_ELIGIBLE_STATE
        and isinstance(item.get("call_depth"), int)
    ]
    depths = [int(item["call_depth"]) for item in reachable]
    first = mappings[0]
    return {
        "vulnerability_id": record["id"],
        "utility": record["utility"],
        "upstream_project": record["upstream_project"],
        "affected_version": record["affected_version"],
        "source_revision": record["source_revision"],
        **_emitted_source_identity(record),
        "vulnerable_functions": list(record["vulnerable_functions"]),
        "declared_vulnerable_function_count": len(mappings),
        "successfully_mapped_function_count": mapped_count,
        "reachable_vulnerable_function_count": len(reachable),
        "function_mappings": mappings,
        "minimum_reachable_call_depth": min(depths) if depths else None,
        "maximum_reachable_call_depth": max(depths) if depths else None,
        "mapping_status": _overall_mapping_status(mappings),
        "verified": record["verified"],
        "eligible_for_hvc": record["verified"] is True and bool(reachable),
        "source_version_status": first.get("source_version_status"),
        "source_version_error": first.get("source_version_error"),
        "analysis_error": first.get("analysis_error"),
        "source_analysis_id": first.get("source_analysis_id"),
        "source_qualified_entry_point": first.get("source_qualified_entry_point"),
        "resolved_source_files": list(first.get("resolved_source_files", [])),
        "call_depth_status_counts": dict(sorted(Counter(
            str(item.get("call_depth_status")) for item in mappings
        ).items())),
        "total_reachable_functions": first.get("total_reachable_functions"),
        "diversification_eligible_function_count": first.get(
            "diversification_eligible_function_count"
        ),
        "maximum_program_call_depth": first.get("maximum_reachable_depth"),
    }


def _unevaluable_function_mapping(
    record: Mapping[str, Any], target: str, status: str, reason: str | None, *,
    source_version_status: str | None = None,
    source_analysis_id: str | None = None,
    source_qualified_entry_point: str | None = None,
    resolved_source_files: Sequence[str] = (),
) -> dict[str, Any]:
    source_error = source_version_status is None
    return {
        "vulnerability_id": record["id"], "utility": record["utility"],
        "upstream_project": record["upstream_project"],
        "affected_version": record["affected_version"],
        "source_revision": record["source_revision"],
        **_emitted_source_identity(record),
        "vulnerable_function": target,
        "source_version_status": source_version_status or status,
        "source_version_error": reason if source_error else None,
        "analysis_error": None if source_error else reason,
        "mapping_status": status, "verified": record["verified"],
        "eligible_for_hvc": False, "source_analysis_id": source_analysis_id,
        "source_qualified_entry_point": source_qualified_entry_point,
        "resolved_source_files": list(resolved_source_files),
        "mapped_function_id": None, "mapped_source_file": None, "call_depth": None,
        "call_depth_status": "analysis_unavailable",
        "unresolved_indirect_dispatches": [],
        "shortest_call_path": None,
        "direct_callers": [], "direct_callees": [],
        "reachable_from_entry": None,
        "reachable_from_main": None, "total_reachable_functions": None,
        "diversification_eligible_function_count": None,
        "maximum_reachable_depth": None, "normalized_depth": None,
    }


def _unevaluable_record_mapping(
    record: Mapping[str, Any], status: str, reason: str | None, *,
    source_version_status: str | None = None,
    source_analysis_id: str | None = None,
    source_qualified_entry_point: str | None = None,
    resolved_source_files: Sequence[str] = (),
) -> dict[str, Any]:
    return _aggregate_record_mapping(record, [
        _unevaluable_function_mapping(
            record, target, status, reason,
            source_version_status=source_version_status,
            source_analysis_id=source_analysis_id,
            source_qualified_entry_point=source_qualified_entry_point,
            resolved_source_files=resolved_source_files,
        )
        for target in record["vulnerable_functions"]
    ])


def analyze_versioned_records(
    records: Sequence[Mapping[str, Any]], manifest: Sequence[Mapping[str, Any]], *,
    force_fallback: bool = False,
) -> dict[str, Any]:
    """Analyze every record against its exact vulnerable source identity."""
    # Upstream identities have three components; authenticated downstream
    # identities add provenance, base-version, and packaging-revision fields.
    cache: dict[tuple[Any, ...], tuple[str, dict[str, Any]]] = {}
    function_mappings: list[dict[str, Any]] = []
    record_mappings: list[dict[str, Any]] = []
    graphs: dict[str, dict[str, Any]] = {}
    hits = 0
    for record in records:
        source_status, source, reason = _source_resolution(record, manifest)
        if source_status != "source_version_matched" or source is None:
            record_mapping = _unevaluable_record_mapping(record, source_status, reason)
            record_mappings.append(record_mapping)
            function_mappings.extend(record_mapping["function_mappings"])
            continue
        source_tree = Path(str(source.get("resolved_source_tree", source["source_tree"])))
        programs = source.get("programs")
        program = programs.get(record["utility"]) if isinstance(programs, Mapping) else None
        if not isinstance(program, Mapping):
            record_mapping = _unevaluable_record_mapping(
                record,
                "program_scope_unavailable",
                f"source manifest has no program scope for utility: {record['utility']}",
                source_version_status="source_version_matched",
            )
            record_mappings.append(record_mapping)
            function_mappings.extend(record_mapping["function_mappings"])
            continue
        try:
            qualified_entry, resolved_files = _resolve_program_scope(source_tree, program)
        except ProgramAnalysisError as error:
            record_mapping = _unevaluable_record_mapping(
                record, error.status, str(error),
                source_version_status="source_version_matched",
                source_qualified_entry_point=error.source_qualified_entry_point,
                resolved_source_files=error.resolved_source_files,
            )
            record_mappings.append(record_mapping)
            function_mappings.extend(record_mapping["function_mappings"])
            continue
        cache_key = (
            *_identity(record), str(source_tree), str(record["utility"]),
            qualified_entry, tuple(resolved_files),
        )
        if cache_key in cache:
            analysis_id, graph = cache[cache_key]
            hits += 1
        else:
            analysis_id = hashlib.sha256(json.dumps({
                "identity": _identity(record), "source_tree": str(source_tree),
                "source_tree_sha256": source["source_tree_sha256"],
                "utility": record["utility"],
                "source_qualified_entry_point": qualified_entry,
                "resolved_source_files": resolved_files,
                "declared_indirect_dispatches": program.get(
                    "declared_indirect_dispatches", []
                ),
            }, sort_keys=True).encode()).hexdigest()
            try:
                graph = analyze_source_tree(
                    source_tree, entry_points=(qualified_entry,),
                    source_files=resolved_files, force_fallback=force_fallback,
                )
            except (OSError, ValueError) as error:
                record_mapping = _unevaluable_record_mapping(
                    record, "analysis_scope_invalid",
                    f"cannot analyze resolved program source scope: {error}",
                    source_version_status="source_version_matched",
                    source_qualified_entry_point=qualified_entry,
                    resolved_source_files=resolved_files,
                )
                record_mappings.append(record_mapping)
                function_mappings.extend(record_mapping["function_mappings"])
                continue
            graph["historical_program_scope"] = {
                "utility": record["utility"],
                "upstream_project": record["upstream_project"],
                "affected_version": record["affected_version"],
                "source_revision": record["source_revision"],
                **_emitted_source_identity(record, source),
                "source_tree": str(source_tree),
                "source_tree_sha256": source["source_tree_sha256"],
                "source_qualified_entry_point": qualified_entry,
                "resolved_source_files": resolved_files,
                "declared_indirect_dispatches": list(program.get(
                    "declared_indirect_dispatches", []
                )),
            }
            cache[cache_key] = (analysis_id, graph)
            graphs[analysis_id] = graph
        resolution = graph.get("entry_point_resolutions", [{}])[0]
        entry_status = resolution.get("status")
        if entry_status != "resolved":
            status = {
                "not_found": "entry_point_not_found",
                "ambiguous": "entry_point_ambiguous",
            }.get(str(entry_status), "entry_point_unresolved")
            record_mapping = _unevaluable_record_mapping(
                record, status,
                f"configured source-qualified entry point is {entry_status}",
                source_version_status="source_version_matched",
                source_analysis_id=analysis_id,
                source_qualified_entry_point=qualified_entry,
                resolved_source_files=resolved_files,
            )
        else:
            record_mapping = map_record_to_graph(
                record, graph, source_analysis_id=analysis_id,
                source_qualified_entry_point=qualified_entry,
                resolved_source_files=resolved_files,
                declared_indirect_dispatches=program.get(
                    "declared_indirect_dispatches", []
                ),
            )
        emitted_identity = _emitted_source_identity(record, source)
        record_mapping.update(emitted_identity)
        record_mapping["source_tree"] = str(source_tree)
        record_mapping["source_tree_sha256"] = source["source_tree_sha256"]
        for mapping in record_mapping["function_mappings"]:
            mapping.update(emitted_identity)
            mapping["source_tree"] = str(source_tree)
            mapping["source_tree_sha256"] = source["source_tree_sha256"]
        record_mappings.append(record_mapping)
        function_mappings.extend(record_mapping["function_mappings"])
    return {
        "schema_version": SCHEMA_VERSION,
        "historical_function_mappings": function_mappings,
        "historical_record_mappings": record_mappings,
        "call_graphs": graphs,
        "call_graphs_constructed": len(graphs), "call_graph_cache_hits": hits,
    }


def version_specific_hvc(
    versioned: Mapping[str, Any], *, policy: str, k: int | None = None,
    percent: float | None = None, seed: int = 1,
    include_entry_points: bool = False,
) -> dict[str, Any]:
    records = list(versioned.get("historical_record_mappings", []))
    graphs = versioned.get("call_graphs", {})
    valid = [item for item in records if item.get("eligible_for_hvc") is True]
    details: list[dict[str, Any]] = []
    eligible_vulnerability_ids = {
        str(record["vulnerability_id"]) for record in valid
    }
    covered_vulnerability_ids: set[str] = set()
    for record in valid:
        selection = select_functions(
            graphs[record["source_analysis_id"]], policy=policy, k=k,
            percent=percent, seed=seed, include_entry_points=include_entry_points,
        )
        selected = set(selection["selected_functions"])
        location_coverage = [
            {
                "vulnerable_function": mapping["vulnerable_function"],
                "mapping_status": mapping["mapping_status"],
                "mapped_function_id": mapping["mapped_function_id"],
                "reachable_from_entry": mapping["reachable_from_entry"],
                "call_depth": mapping["call_depth"],
                "selected": (
                    mapping.get("eligible_for_hvc") is True
                    and mapping.get("mapped_function_id") in selected
                ),
            }
            for mapping in record["function_mappings"]
        ]
        is_covered = any(item["selected"] for item in location_coverage)
        if is_covered:
            covered_vulnerability_ids.add(str(record["vulnerability_id"]))
        details.append({
            "vulnerability_id": record["vulnerability_id"],
            "utility": record["utility"],
            "source_revision": record["source_revision"],
            **_emitted_source_identity(record),
            "source_tree": record.get("source_tree"),
            "source_tree_sha256": record.get("source_tree_sha256"),
            "source_analysis_id": record["source_analysis_id"],
            "source_qualified_entry_point": record["source_qualified_entry_point"],
            "resolved_source_files": list(record["resolved_source_files"]),
            "reachable_function_count": record["total_reachable_functions"],
            "diversification_eligible_function_count": record[
                "diversification_eligible_function_count"
            ],
            "declared_vulnerable_function_count": record[
                "declared_vulnerable_function_count"
            ],
            "function_location_coverage": location_coverage,
            "covered": is_covered, **selection,
        })
    denominator = len(eligible_vulnerability_ids)
    covered_count = len(covered_vulnerability_ids)
    return {
        "selection_policy": policy.upper(),
        "selection_seed": seed if policy.upper() == "RANDOM" else None,
        "include_entry_points": include_entry_points,
        "selection_budget": {"k": k, "percent": percent},
        "selection_budget_unit": "function_count",
        "historical_vulnerabilities_with_valid_version_specific_mappings": denominator,
        "historical_vulnerabilities_covered": covered_count,
        "covered_vulnerability_ids": sorted(covered_vulnerability_ids),
        "historical_vulnerability_coverage_at_budget": (
            covered_count / denominator if denominator else None
        ),
        "per_vulnerability_selections": details,
    }


def _percentile_bootstrap_ci(
    values: Sequence[float], *, seed: int = 0, replicates: int = 2000,
) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    means = sorted(
        statistics.fmean(rng.choice(values) for _ in values)
        for _ in range(replicates)
    )
    return [
        means[int(0.025 * (replicates - 1))],
        means[int(0.975 * (replicates - 1))],
    ]


def coverage_study(
    versioned: Mapping[str, Any], *, k_values: Iterable[int] = (),
    percent_values: Iterable[float] = (10, 25, 50, 100),
    random_seeds: Iterable[int] = (1,), include_entry_points: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seeds = list(random_seeds)
    if not seeds:
        raise ValueError("at least one random seed is required")
    budgets = [("k", value) for value in k_values] + [("percent", value) for value in percent_values]
    for kind, value in budgets:
        for policy in SELECTION_POLICIES:
            for policy_seed in (seeds if policy == "RANDOM" else [1]):
                rows.append(version_specific_hvc(
                    versioned, policy=policy, seed=policy_seed,
                    include_entry_points=include_entry_points, **{kind: value},
                ))
    aggregates: list[dict[str, Any]] = []
    random_groups: dict[tuple[Any, Any], list[float]] = {}
    for row in rows:
        value = row["historical_vulnerability_coverage_at_budget"]
        if row["selection_policy"] == "RANDOM" and value is not None:
            budget = row["selection_budget"]
            random_groups.setdefault((budget["k"], budget["percent"]), []).append(value)
    for (k_value, percent_value), values in random_groups.items():
        aggregates.append({
            "selection_policy": "RANDOM",
            "selection_budget": {"k": k_value, "percent": percent_value},
            "selection_budget_unit": "function_count", "repetitions": len(values),
            "mean_historical_vulnerability_coverage": statistics.fmean(values),
            "percentile_bootstrap_95pct_ci": _percentile_bootstrap_ci(values),
            "bootstrap_seed": 0, "bootstrap_replicates": 2000,
        })
    return {"coverage_rows": rows, "random_coverage_aggregates": aggregates}


def summarize_historical_analysis(
    mappings: Sequence[Mapping[str, Any]],
    record_mappings: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize location depths and each CVE's shallowest reachable location."""
    if record_mappings is None:
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for mapping in mappings:
            grouped.setdefault(str(mapping.get("vulnerability_id")), []).append(mapping)
        records = []
        for vulnerability_id, locations in grouped.items():
            depths = [
                item["call_depth"] for item in locations
                if item.get("mapping_status") == HVC_ELIGIBLE_STATE
                and isinstance(item.get("call_depth"), int)
            ]
            records.append({
                "vulnerability_id": vulnerability_id,
                "mapping_status": _overall_mapping_status(locations),
                "verified": locations[0].get("verified") is True,
                "eligible_for_hvc": locations[0].get("verified") is True and bool(depths),
                "minimum_reachable_call_depth": min(depths) if depths else None,
            })
    else:
        records = list(record_mappings)
    location_status_counts = Counter(str(item.get("mapping_status")) for item in mappings)
    call_depth_status_counts = Counter(
        str(item.get("call_depth_status")) for item in mappings
    )
    record_status_counts = Counter(str(item.get("mapping_status")) for item in records)
    valid_locations = [item for item in mappings if item.get("eligible_for_hvc") is True]
    location_depths = [
        item["call_depth"] for item in valid_locations
        if isinstance(item.get("call_depth"), int)
    ]
    cve_depths = [
        item["minimum_reachable_call_depth"] for item in records
        if item.get("verified") is True
        and isinstance(item.get("minimum_reachable_call_depth"), int)
    ]
    record_count = len(records)
    return {
        "historical_record_count": record_count,
        "historical_function_location_count": len(mappings),
        "function_mapping_status_counts": dict(sorted(location_status_counts.items())),
        "function_call_depth_status_counts": dict(
            sorted(call_depth_status_counts.items())
        ),
        "cve_mapping_status_counts": dict(sorted(record_status_counts.items())),
        "valid_version_specific_mapping_count": sum(
            item.get("eligible_for_hvc") is True for item in records
        ),
        "unverified_record_count": sum(
            item.get("verified") is not True for item in records
        ),
        "reachable_mapped_vulnerability_count": len(cve_depths),
        "reachable_vulnerable_function_location_count": len(location_depths),
        "vulnerable_function_location_depth_distribution": {
            str(depth): location_depths.count(depth)
            for depth in sorted(set(location_depths))
        },
        "per_cve_shallowest_reachable_depth_distribution": {
            str(depth): cve_depths.count(depth) for depth in sorted(set(cve_depths))
        },
        "mean_vulnerable_function_location_depth": (
            statistics.fmean(location_depths) if location_depths else None
        ),
        "median_vulnerable_function_location_depth": (
            statistics.median(location_depths) if location_depths else None
        ),
        "mean_per_cve_shallowest_reachable_depth": (
            statistics.fmean(cve_depths) if cve_depths else None
        ),
        "median_per_cve_shallowest_reachable_depth": (
            statistics.median(cve_depths) if cve_depths else None
        ),
    }
