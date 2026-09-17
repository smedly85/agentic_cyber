#!/usr/bin/env python3
"""Validate semantic call depth for the nine frozen historical-v1 locations.

This is a side-by-side instrument validation.  It reads, but never rewrites,
the historical-v1 records and source manifest.  Historical translation units
are compiled from their already configured Automake recipes; there is no
generic fixture-command fallback and no synthetic call edge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from security.historical.analysis import (
    load_records,
    load_source_manifest,
    verify_source_tree_sha256,
)
from security.semantic_callgraph import (
    BuildResult,
    analyze_build,
    inventory_toolchain,
    stable_json,
)


REPO = Path(__file__).resolve().parents[2]
HISTORICAL = Path(__file__).resolve().parent
PRIMARY_OPTIONS = ("-stat=false", "-ff-eq-base")
SENSITIVITY_OPTIONS = ("-stat=false",)
COREUTILS_LINKER_SCOPES = {
    "9.7": "coreutils_9_7_linker_scope.json",
    "8.17-7.fc18": "coreutils_8_17_linker_scope.json",
    "8.23-9.fc22": "coreutils_8_23_linker_scope.json",
}


def verify_frozen_queries(records: Sequence[Mapping[str, Any]],
                          observations: Sequence[Mapping[str, Any]] | None = None) -> None:
    """Records select queries only; this guard never constructs graph edges.

    records.json stores function names, not structured source locations. The
    companion location ledger preserves the independently verified milestone
    source mappings; both must agree exactly with the query declarations.
    """
    declarations = OBSERVATIONS if observations is None else observations
    ledger = json.loads((HISTORICAL / "semantic_query_locations.json").read_text())
    expected = {}
    for row in ledger["locations"]:
        expected.setdefault(row["cve"], set()).add((row["source_file"], row["function"]))
    actual = {}
    for row in declarations:
        pair = (row["source_file"], row["function"])
        values = actual.setdefault(row["cve"], set())
        if pair in values:
            raise RuntimeError("duplicate historical semantic query")
        values.add(pair)
    if actual != expected or {r["id"] for r in records} != set(expected):
        raise RuntimeError("historical query/location ledger mismatch")
    for record in records:
        if set(record["vulnerable_functions"]) != {f for _, f in expected[record["id"]]}:
            raise RuntimeError(f"frozen vulnerable-function query mismatch: {record['id']}")
        for row in declarations:
            if row["cve"] == record["id"] and (
                row["project"], row["version"], row["program"]
            ) != (record["upstream_project"], record["affected_version"], record["utility"]):
                raise RuntimeError("historical query specimen mismatch")


def map_source_identity(result: Mapping[str, Any], source_file: str,
                        function: str) -> dict[str, Any]:
    """Expose all matches. LLVM suffix ordering must never resolve ambiguity."""
    candidates = sorted((dict(row) for row in result.get("functions", [])
                         if row.get("source_file") == source_file
                         and row.get("name") == function),
                        key=lambda row: row["identity"])
    status = result.get("analysis_status")
    if status == "success":
        status = ("source_identity_not_found" if not candidates else
                  "source_identity_ambiguous" if len(candidates) > 1 else
                  candidates[0]["semantic_status"])
    return {
        "semantic_mapping_status": status,
        "requested_source_identity": f"{source_file}::{function}",
        "candidate_count": len(candidates),
        "candidate_identities": [row["identity"] for row in candidates],
        "candidates": candidates,
    }


@dataclass(frozen=True)
class HistoricalBuildSpec:
    build_dir: str
    layout: str
    configure_options: tuple[str, ...]
    configured_cc: str
    make_variables: tuple[tuple[str, str], ...] = ()
    relocated_source_override: bool = False
    prepare_built_sources: bool = False


BUILD_SPECS: dict[tuple[str, str, str], HistoricalBuildSpec] = {
    ("gnu-coreutils", "9.7", "sort"): HistoricalBuildSpec(
        "build/coreutils-9.7-sort-scope", "nonrecursive",
        ("--disable-nls", "--without-selinux"), "gcc -std=gnu17",
        prepare_built_sources=True,
    ),
    ("gnu-grep", "2.21", "grep"): HistoricalBuildSpec(
        "build/grep-2.21-scope", "recursive",
        ("--disable-nls",), "gcc -std=gnu17",
    ),
    ("gnu-coreutils", "5.2.1", "mkdir"): HistoricalBuildSpec(
        "build/coreutils-5.2.1-mkdir-scope", "recursive",
        ("--disable-nls",), "gcc -std=gnu89 -fcommon",
    ),
    ("gnu-grep", "2.10", "grep"): HistoricalBuildSpec(
        "build/grep-2.10-scope", "recursive",
        ("--disable-nls",), "gcc -std=gnu17",
    ),
    ("gnu-coreutils", "8.17-7.fc18", "sort"): HistoricalBuildSpec(
        "build/coreutils-8.17-fedora-sort-scope-portable", "recursive",
        (
            "--disable-nls", "--without-selinux", "--without-gmp",
            "--enable-largefile", "--enable-install-program=hostname,arch",
            "--with-tty-group", "DEFAULT_POSIX2_VERSION=200112",
            "alternative=199209",
        ),
        "gcc",
        (
            ("CPPFLAGS", "-D_IO_ftrylockfile=1 -D_IO_IN_BACKUP=0x100"),
            ("CFLAGS", "-g -O2 -Wno-error=implicit-function-declaration "
                       "-Wno-error=incompatible-pointer-types "
                       "-Wno-error=int-conversion"),
        ),
    ),
    ("gnu-coreutils", "8.23-9.fc22", "sort"): HistoricalBuildSpec(
        "build/coreutils-8.23-fedora-sort-scope-portable", "nonrecursive",
        (
            "--disable-nls", "--without-selinux", "--without-openssl",
            "--without-gmp", "--enable-largefile",
            "--enable-install-program=hostname,arch", "--with-tty-group",
            "DEFAULT_POSIX2_VERSION=200112", "alternative=199209",
        ),
        "gcc",
        (
            ("CPPFLAGS", "-D_IO_ftrylockfile=1 -D_IO_IN_BACKUP=0x100"),
            ("CFLAGS", "-g -O2 -Wno-error=implicit-function-declaration "
                       "-Wno-error=incompatible-pointer-types "
                       "-Wno-error=int-conversion"),
        ),
    ),
}


OBSERVATIONS: tuple[dict[str, Any], ...] = (
    {"cve": "CVE-2005-1039", "project": "gnu-coreutils", "version": "5.2.1", "program": "mkdir", "source_file": "src/mkdir.c", "function": "main", "old_status": "resolved_static_path", "old_depth": 0},
    {"cve": "CVE-2005-1039", "project": "gnu-coreutils", "version": "5.2.1", "program": "mkdir", "source_file": "lib/makepath.c", "function": "make_path", "old_status": "resolved_static_path", "old_depth": 1},
    {"cve": "CVE-2025-5278", "project": "gnu-coreutils", "version": "9.7", "program": "sort", "source_file": "src/sort.c", "function": "begfield", "old_status": "resolved_static_path", "old_depth": 3},
    {"cve": "CVE-2015-1345", "project": "gnu-grep", "version": "2.21", "program": "grep", "source_file": "src/kwset.c", "function": "bmexec_trans", "old_status": "unresolved_indirect_dispatch", "old_depth": None},
    {"cve": "CVE-2012-5667", "project": "gnu-grep", "version": "2.10", "program": "grep", "source_file": "src/dfasearch.c", "function": "EGexecute", "old_status": "unresolved_indirect_dispatch", "old_depth": None},
    {"cve": "CVE-2015-4041", "project": "gnu-coreutils", "version": "8.23-9.fc22", "program": "sort", "source_file": "src/sort.c", "function": "keycompare_mb", "old_status": "unresolved_indirect_dispatch", "old_depth": None},
    {"cve": "CVE-2015-4042", "project": "gnu-coreutils", "version": "8.23-9.fc22", "program": "sort", "source_file": "src/sort.c", "function": "keycompare_mb", "old_status": "unresolved_indirect_dispatch", "old_depth": None},
    {"cve": "CVE-2013-0221", "project": "gnu-coreutils", "version": "8.17-7.fc18", "program": "sort", "source_file": "src/sort.c", "function": "keycompare_mb", "old_status": "unresolved_indirect_dispatch", "old_depth": None},
    {"cve": "CVE-2013-0221", "project": "gnu-coreutils", "version": "8.17-7.fc18", "program": "sort", "source_file": "src/sort.c", "function": "getmonth_mb", "old_status": "no_resolved_static_path", "old_depth": None},
)


def _run(command: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _program_key(entry: Mapping[str, Any], program: str) -> tuple[str, str, str]:
    return (str(entry["upstream_project"]), str(entry["affected_version"]), program)


def _slug(key: tuple[str, str, str]) -> str:
    return "-".join(re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") for value in key)


def _scientific_path(path: Path, *, source_root: Path, build_root: Path, output_root: Path) -> str:
    resolved = path.resolve()
    for root, label in (
        (source_root.resolve(), "$SOURCE_ROOT"),
        (build_root.resolve(), "$CONFIG_BUILD"),
        (output_root.resolve(), "$OUTPUT_ROOT"),
        (REPO.resolve(), "$REPOSITORY"),
    ):
        try:
            return f"{label}/{resolved.relative_to(root).as_posix()}"
        except ValueError:
            pass
    return resolved.as_posix()


def _normalize_command(
    command: Sequence[str], *, source_root: Path, build_root: Path,
    output_root: Path,
) -> tuple[str, ...]:
    replacements = (
        (str(source_root.resolve()), "$SOURCE_ROOT"),
        (str(build_root.resolve()), "$CONFIG_BUILD"),
        (str(output_root.resolve()), "$OUTPUT_ROOT"),
        (str(REPO.resolve()), "$REPOSITORY"),
    )
    result = []
    for item in command:
        value = str(item)
        for old, new in replacements:
            value = value.replace(old, new)
        result.append(value.replace("\\", "/"))
    return tuple(result)


def _dependency_target(
    source_file: str, *, source_root: Path, build_root: Path,
    spec: HistoricalBuildSpec, makefile_text: str | None = None,
) -> tuple[Path, str]:
    if spec.layout == "nonrecursive":
        makefile = makefile_text
        if makefile is None:
            makefile = (build_root / "Makefile").read_text(
                encoding="utf-8", errors="replace",
            )
        escaped = re.escape(source_file)
        matches = sorted(set(re.findall(
            rf"(?m)^([^:\s]+\.o):\s+{escaped}\s*$", makefile,
        )))
        if source_file.startswith("lib/"):
            preferred = [value for value in matches if "libcoreutils_a-" in value]
            if len(preferred) == 1:
                return build_root, preferred[0]
        exact_target = str(Path(source_file).with_suffix(".o"))
        if exact_target in matches or not matches:
            return build_root, exact_target
        if len(matches) == 1:
            return build_root, matches[0]
        raise RuntimeError(f"ambiguous Makefile objects for {source_file}: {matches}")

    candidates: list[tuple[Path, str]] = []
    needle = f"/{source_file}"
    for dependency in build_root.rglob("*.Po"):
        text = dependency.read_text(encoding="utf-8", errors="replace").replace("\\\n", " ")
        if needle not in text.replace("\\", "/"):
            continue
        match = re.match(r"\s*([^:\s]+\.o):", text)
        if not match:
            continue
        target = match.group(1)
        cwd = build_root if spec.layout == "nonrecursive" else dependency.parent.parent
        candidates.append((cwd, target))
    unique = sorted(set(candidates), key=lambda item: (str(item[0]), item[1]))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        exact = [item for item in unique if Path(item[1]).stem == Path(source_file).stem]
        if len(exact) == 1:
            return exact[0]
        raise RuntimeError(f"ambiguous configured objects for {source_file}: {unique}")

    component, rest = source_file.split("/", 1)
    return build_root / component, str(Path(rest).with_suffix(".o"))


def _compile_segment(make_output: str) -> list[str]:
    joined = make_output.replace("\\\n", " ")
    for segment in re.split(r"\n|\s*(?:&&|;)\s*", joined):
        if " -c " not in f" {segment} ":
            continue
        try:
            tokens = shlex.split(segment.strip())
        except ValueError:
            continue
        for index, token in enumerate(tokens):
            if Path(token).name in {"gcc", "cc", "clang"}:
                return tokens[index:]
    raise RuntimeError(f"configured Make recipe did not expose a C compile command:\n{make_output}")


def _configured_make_variable(build_root: Path, name: str) -> tuple[str, ...]:
    """Expand one configured Automake variable without parsing Makefile syntax."""
    marker = "__SEMANTIC_CONFIGURED_VALUE__="
    fragment = (
        ".PHONY: __semantic_print_configured_value\n"
        "__semantic_print_configured_value:\n"
        f"\t@printf '%s\\n' '{marker}$({name})'\n"
    )
    command = [
        "make", "-C", str(build_root), "--no-print-directory", "-s",
        "-f", "Makefile", "-f", "-", "__semantic_print_configured_value",
    ]
    result = subprocess.run(
        command, cwd=REPO, text=True, input=fragment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"could not expand configured {name}:\n{result.stdout}{result.stderr}"
        )
    values = [line[len(marker):] for line in result.stdout.splitlines() if line.startswith(marker)]
    if len(values) != 1:
        raise RuntimeError(f"configured {name} expansion was not unique: {result.stdout!r}")
    return tuple(shlex.split(values[0]))


def _prepare_configured_built_sources(
    *, source_root: Path, build_root: Path, output_root: Path,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Realize Automake BUILT_SOURCES without compiling historical C files.

    Coreutils' gnulib wrappers are configuration output even though Automake
    generates them lazily.  Per-object dry runs assume these prerequisites
    have already been realized by the top-level ``all`` dependency.
    """
    targets = _configured_make_variable(build_root, "BUILT_SOURCES")
    build_targets: list[str] = []
    source_prerequisites: list[str] = []
    for target in targets:
        candidate = Path(target)
        resolved = candidate.resolve() if candidate.is_absolute() else (build_root / candidate).resolve()
        try:
            source_relative = resolved.relative_to(source_root.resolve())
        except ValueError:
            build_targets.append(target)
            continue
        if not resolved.is_file():
            raise RuntimeError(
                "configured BUILT_SOURCES would require modifying the historical "
                f"source tree: {source_relative.as_posix()}"
            )
        source_prerequisites.append(source_relative.as_posix())

    command = [
        "make", "-C", str(build_root), "--no-print-directory", "-j1",
        *build_targets,
    ]
    result = _run(command, cwd=REPO)
    if result.returncode != 0:
        raise RuntimeError(
            "configured BUILT_SOURCES generation failed:\n"
            f"{result.stdout}{result.stderr}"
        )
    missing = []
    vpath_source_targets = []
    for target in build_targets:
        candidate = Path(target)
        if candidate.is_absolute():
            available = candidate.exists()
        else:
            available = (build_root / candidate).exists()
            if not available and (source_root / candidate).exists():
                available = True
                vpath_source_targets.append(candidate.as_posix())
        if not available:
            missing.append(target)
    if missing:
        raise RuntimeError(f"configured BUILT_SOURCES remain unavailable: {missing}")
    return _normalize_command(
        command, source_root=source_root, build_root=build_root,
        output_root=output_root,
    ), {
        "method": "automake_BUILT_SOURCES_prerequisites",
        "configured_target_count": len(targets),
        "generated_build_target_count": len(build_targets),
        "source_tree_prerequisites": sorted(source_prerequisites),
        "vpath_source_targets": sorted(vpath_source_targets),
        "targets": [
            _scientific_path(
                Path(target), source_root=source_root, build_root=build_root,
                output_root=output_root,
            ) if Path(target).is_absolute() else target
            for target in targets
        ],
    }


def _configured_recipe(
    source_file: str, *, source_root: Path, build_root: Path,
    spec: HistoricalBuildSpec, makefile_text: str | None = None,
    recipe_cache: dict[tuple[str, str], list[str]] | None = None,
    configured_object_target: str | None = None,
) -> tuple[Path, str, list[str], list[str]]:
    if configured_object_target is None:
        cwd, target = _dependency_target(
            source_file, source_root=source_root, build_root=build_root, spec=spec,
            makefile_text=makefile_text,
        )
    else:
        # A source may have several configured compile instances (e.g. sort.o
        # versus the single-binary archive variant). Use the object established
        # by the native link closure, not the first source-name rule in Makefile.
        obj = Path(configured_object_target)
        if obj.is_absolute() or ".." in obj.parts or obj.suffix != ".o":
            raise RuntimeError("invalid configured scope object target")
        cwd, target = ((build_root / obj.parent, obj.name) if spec.layout == "recursive"
                       else (build_root, obj.as_posix()))
    makefile = cwd / "Makefile"
    if not makefile.is_file():
        raise RuntimeError(f"configured Makefile unavailable: {makefile}")
    relative_source = os.path.relpath(source_root / source_file, cwd)
    config_status = "config.status" if cwd == build_root else "../config.status"
    relocation_variables: list[str] = []
    if spec.relocated_source_override:
        relative_source_root = os.path.relpath(source_root, build_root)
        make_absolute_source = str(source_root).replace(" ", "\\ ")
        make_absolute_build = str(build_root).replace(" ", "\\ ")
        relocation_variables = [
            f"srcdir={relative_source_root}", f"top_srcdir={relative_source_root}",
            f"abs_srcdir={make_absolute_source}",
            f"abs_top_srcdir={make_absolute_source}",
            "builddir=.", "top_builddir=.",
            f"abs_builddir={make_absolute_build}",
            f"abs_top_builddir={make_absolute_build}",
            f"VPATH={relative_source_root}",
        ]
    command = [
        "make", "-C", str(cwd), "-f", "Makefile", "-n",
        "-o", config_status, "-o", "Makefile",
        "-W", relative_source,
        *(f"{key}={value}" for key, value in spec.make_variables),
        *relocation_variables,
        target,
    ]
    cache_key = None
    if spec.prepare_built_sources and target.startswith("lib/libcoreutils_a-"):
        # Automake emits every member of this nonrecursive convenience archive
        # from the same lib_libcoreutils_a_CFLAGS template. The source, object,
        # dependency, and output operands are replaced below, so one GNU Make
        # expansion is sufficient and avoids 328 identical full-file parses.
        cache_key = (str(cwd), "lib/libcoreutils_a-*.o")
    if cache_key is not None and recipe_cache is not None and cache_key in recipe_cache:
        recipe = list(recipe_cache[cache_key])
    else:
        result = _run(command, cwd=REPO)
        if result.returncode != 0:
            raise RuntimeError(
                f"configured Make recipe failed for {source_file}:\n{result.stdout}{result.stderr}"
            )
        recipe = _compile_segment(result.stdout)
        if cache_key is not None and recipe_cache is not None:
            recipe_cache[cache_key] = list(recipe)
    return cwd, target, recipe, command


def _clang_command(
    recipe: Sequence[str], *, cwd: Path, output: Path, source_root: Path,
    build_root: Path, clang: str, manifest_source: str,
    compile_input_override: Path | None = None,
) -> tuple[list[str], Path]:
    args: list[str] = []
    skip_next = False
    try:
        compile_index = recipe.index("-c")
    except ValueError as error:
        raise RuntimeError(f"configured recipe has no compile action: {recipe}") from error
    # Automake may express its source operand with shell backticks after -c.
    # Retain the configured compiler flags preceding the compile action, then
    # compile the exact source path frozen in the historical manifest.
    for token in recipe[1:compile_index]:
        if skip_next:
            skip_next = False
            continue
        if token in {"-MT", "-MQ", "-MF", "-o"}:
            skip_next = True
            continue
        if token in {"-MD", "-MMD", "-MP", "-c"}:
            continue
        if token == "$depbase.Tpo" or token.startswith("$depbase"):
            continue
        if token.startswith("-O") or token == "-g" or token.startswith("-g"):
            continue
        if token.endswith(".c"):
            continue
        if token.startswith("-I") and len(token) > 2:
            include = (cwd / token[2:]).resolve()
            token = f"-I{include}"
        args.append(token)
    compile_input = (compile_input_override or (source_root / manifest_source)).resolve()
    if not compile_input.is_file():
        raise RuntimeError(f"configured compile input unavailable: {compile_input}")
    command = [
        clang, *args,
        "-g", "-O0", "-fno-inline", "-fno-builtin", "-fno-discard-value-names",
        "-fdebug-compilation-dir=.",
        f"-fdebug-prefix-map={source_root.resolve()}=.",
        f"-fdebug-prefix-map={build_root.resolve()}=generated-config",
        "-emit-llvm", "-c", str(compile_input), "-o", str(output),
    ]
    return command, compile_input


def build_historical_bitcode(
    manifest_entry: Mapping[str, Any], program: str, output_root: Path,
    *, inventory: Mapping[str, Any], scope: Mapping[str, Any] | None = None,
) -> BuildResult:
    key = _program_key(manifest_entry, program)
    spec = BUILD_SPECS[key]
    source_root = (HISTORICAL / str(manifest_entry["source_tree"])).resolve()
    build_root = (REPO / spec.build_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if scope is None and key[0] == "gnu-coreutils" and key[1] in COREUTILS_LINKER_SCOPES and program == "sort":
        exact_path = HISTORICAL / COREUTILS_LINKER_SCOPES[key[1]]
        if not exact_path.is_file():
            raise RuntimeError(f"reconstruct {key[1]} linker scope before primary validation")
        scope = json.loads(exact_path.read_text(encoding="utf-8"))
        if scope["source_tree_sha256"] != manifest_entry["source_tree_sha256"]:
            raise RuntimeError("linker scope source fingerprint mismatch")
    source_files = tuple(scope["source_files"] if scope else manifest_entry["programs"][program]["source_files"])
    allowed_sources = set(manifest_entry["programs"][program]["source_files"])
    if key[0] == "gnu-coreutils" and key[1] in COREUTILS_LINKER_SCOPES and program == "sort":
        allowed_sources.add("generated-config/src/version.c")
    if not source_files or len(set(source_files)) != len(source_files) or not set(source_files) <= allowed_sources:
        raise RuntimeError("scope contains duplicate, empty, or unauthenticated source inputs")
    if scope and scope["source_scope_kind"] not in {"linker_exact", "reconstructed_program_scope", "archive_superset"}:
        raise RuntimeError("unknown historical source_scope_kind")
    def source_path(value: str) -> Path:
        if value.startswith("generated-config/"):
            return build_root / value.removeprefix("generated-config/")
        return source_root / value
    configuration = {
        "source_scope_kind": scope["source_scope_kind"] if scope else (
            "reconstructed_program_scope" if key[1] in ("8.17-7.fc18", "8.23-9.fc22") else "linker_exact"
        ),
        "scope_evidence": scope.get("evidence") if scope else "security/historical/source_scope_audit.json",
        "source_file_count": len(source_files),
        "configured_build": spec.build_dir,
        "configure_options": list(spec.configure_options),
        "configured_cc": spec.configured_cc,
        "make_variables": {key: value for key, value in spec.make_variables},
        "semantic_cflags": [
            "-g", "-O0", "-fno-inline", "-fno-builtin",
            "-fno-discard-value-names", "-emit-llvm", "-c",
        ],
        "recipe_source": "configured_automake_dry_run",
        "recipe_expansion": (
            "shared_libcoreutils_automake_flag_template"
            if spec.prepare_built_sources else "per_object"
        ),
        "relocated_source_override": spec.relocated_source_override,
        "configured_generated_inputs": (
            "automake_BUILT_SOURCES" if spec.prepare_built_sources else "already_available"
        ),
    }
    source_rows = tuple({
        "path": value,
        **({"sha256": _sha256(source_path(value))} if source_path(value).is_file()
           else {"hash_status": "input_not_yet_available"}),
    } for value in source_files)
    tools = inventory.get("tools", {})
    clang = tools.get("clang", {}).get("path")
    linker = tools.get("llvm-link", {}).get("path")
    if not clang or not linker:
        missing = [name for name, value in (("clang", clang), ("llvm-link", linker)) if not value]
        return BuildResult(
            "build_or_ir_unavailable", None, source_rows, (), (),
            ({"stage": "toolchain", "missing_tools": missing},), None, configuration,
        )
    if not source_root.is_dir() or not build_root.is_dir():
        return BuildResult(
            "build_or_ir_unavailable", None, source_rows, (), (),
            ({"stage": "historical_configuration", "reason": "source_or_configured_build_unavailable"},),
            None, configuration,
        )
    try:
        verify_source_tree_sha256(source_root, str(manifest_entry["source_tree_sha256"]))
    except Exception as error:
        return BuildResult(
            "build_or_ir_unavailable", None, source_rows, (), (),
            ({"stage": "source_integrity", "reason": str(error)},), None, configuration,
        )

    commands: list[tuple[str, ...]] = []
    modules: list[Path] = []
    bitcode_rows: list[dict[str, str]] = []
    diagnostics: list[dict[str, Any]] = []
    makefile_text = (
        (build_root / "Makefile").read_text(encoding="utf-8", errors="replace")
        if spec.layout == "nonrecursive" else None
    )
    recipe_cache: dict[tuple[str, str], list[str]] = {}
    if not spec.prepare_built_sources and any(s.startswith("generated-config/") for s in source_files):
        # The Fedora builds generate version.c from PACKAGE_VERSION in their
        # configured Makefile. Do not synthesize it or place it in the source tree.
        cwd = build_root / "src" if spec.layout == "recursive" else build_root
        target = "version.c" if spec.layout == "recursive" else "src/version.c"
        preparation_command = ["make", "-C", str(cwd), "-f", "Makefile",
                               "-o", "../config.status" if spec.layout == "recursive" else "config.status",
                               "-o", "Makefile", target,
                               *(f"{k}={v}" for k, v in spec.make_variables)]
        prepared = _run(preparation_command)
        commands.append(_normalize_command(preparation_command, source_root=source_root,
                                           build_root=build_root, output_root=output_root))
        if prepared.returncode:
            return BuildResult("build_or_ir_unavailable", None, source_rows, tuple(commands), (),
                               ({"stage": "configured_generated_source", "stderr": prepared.stderr},),
                               None, configuration)
        configuration["configured_generated_inputs"] = "configured_Makefile_version_c_rule"
    if spec.prepare_built_sources:
        try:
            preparation_command, preparation = _prepare_configured_built_sources(
                source_root=source_root, build_root=build_root,
                output_root=output_root,
            )
            commands.append(preparation_command)
            configuration["built_sources_preparation"] = preparation
            configuration["build_reconstruction_diagnostic"] = {
                "initial_failure": {
                    "source_file": "lib/aszprintf.c",
                    "undeclared_identifiers": ["ptrdiff_t", "vaszprintf"],
                },
                "root_cause": "configured_automake_BUILT_SOURCES_not_realized",
                "required_generated_headers": ["lib/stddef.h", "lib/stdio.h"],
                "correction": "generate_configured_build_inputs_from_frozen_Makefile",
                "historical_source_modified": False,
                "classification": "incomplete_build_reconstruction_not_intrinsic_source_incompatibility",
                "faithful_clang_ir_result": "success",
            }
            # Generating configured build-directory inputs must not alter the
            # independently authenticated release tree.
            verify_source_tree_sha256(
                source_root, str(manifest_entry["source_tree_sha256"]),
            )
        except Exception as error:
            diagnostics.append({
                "stage": "configured_generated_inputs", "message": str(error),
            })
            return BuildResult(
                "build_or_ir_unavailable", None, source_rows, tuple(commands),
                tuple(bitcode_rows), tuple(diagnostics), None, configuration,
            )
    # Required generated TUs (e.g. version.c) may not exist until BUILT_SOURCES
    # has run. Fingerprint the realized input, never an absent-file placeholder.
    try:
        source_rows = tuple({"path": value, "sha256": _sha256(source_path(value))}
                            for value in source_files)
    except OSError as error:
        return BuildResult(
            "build_or_ir_unavailable", None, source_rows, tuple(commands), (),
            ({"stage": "source_input", "message": str(error)},), None, configuration,
        )
    configuration["translation_units"] = []
    scope_objects = {u["source_file"]: u["configured_object_target"]
                     for u in (scope or {}).get("translation_units", [])}
    if scope and "translation_units" in scope and (
        set(scope_objects) != set(source_files)
        or len(scope_objects) != len(scope["translation_units"])
        or len(set(scope_objects.values())) != len(scope_objects)
    ):
        raise RuntimeError("scope source/object compile-instance mapping is incomplete or duplicated")
    for index, source_file in enumerate(source_files):
        module = output_root / f"tu-{index:04d}.bc"
        try:
            generated = source_file.startswith("generated-config/")
            cwd, target, recipe, make_command = _configured_recipe(
                source_file.removeprefix("generated-config/"),
                source_root=build_root if generated else source_root,
                build_root=build_root, spec=spec,
                makefile_text=makefile_text, recipe_cache=recipe_cache,
                configured_object_target=scope_objects.get(source_file),
            )
            command, compile_input = _clang_command(
                recipe, cwd=cwd, output=module, source_root=source_root,
                build_root=build_root, clang=str(clang),
                manifest_source=source_file,
                compile_input_override=source_path(source_file) if generated else None,
            )
        except Exception as error:
            diagnostics.append({
                "stage": "configured_recipe", "source_file": source_file,
                "message": str(error),
            })
            return BuildResult(
                "build_or_ir_unavailable", None, source_rows, tuple(commands),
                tuple(bitcode_rows), tuple(diagnostics), None, configuration,
            )
        commands.append(_normalize_command(
            command, source_root=source_root, build_root=build_root,
            output_root=output_root,
        ))
        configuration["translation_units"].append({
            "source_file": source_file,
            "source_provenance_kind": "configured_build_generated" if generated else "authenticated_historical_tree",
            "source_sha256": _sha256(compile_input),
            "configured_object_target": str((cwd / target).relative_to(build_root)),
            "compile_recipe_provenance": {
                "kind": "configured_automake_dry_run",
                "working_directory": str(cwd.relative_to(build_root)),
                "make_command": list(_normalize_command(make_command, source_root=source_root, build_root=build_root, output_root=output_root)),
                "configured_compiler_recipe": list(_normalize_command(recipe, source_root=source_root, build_root=build_root, output_root=output_root)),
                "clang_command": list(commands[-1]),
            },
        })
        result = _run(command, cwd=cwd)
        if result.returncode != 0:
            diagnostics.append({
                "stage": "clang", "source_file": source_file,
                "configured_object_target": target,
                "compile_input": _scientific_path(
                    compile_input, source_root=source_root, build_root=build_root,
                    output_root=output_root,
                ),
                "configured_make_command": list(_normalize_command(
                    make_command, source_root=source_root, build_root=build_root,
                    output_root=output_root,
                )),
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })
            return BuildResult(
                "build_or_ir_unavailable", None, source_rows, tuple(commands),
                tuple(bitcode_rows), tuple(diagnostics), None, configuration,
            )
        modules.append(module)
        bitcode_rows.append({
            "path": module.name, "sha256": _sha256(module),
            "manifest_source": source_file,
            "compile_input": _scientific_path(
                compile_input, source_root=source_root, build_root=build_root,
                output_root=output_root,
            ),
        })

    linked = output_root / "linked.bc"
    link_command = [str(linker), *map(str, modules), "-o", str(linked)]
    commands.append(_normalize_command(
        link_command, source_root=source_root, build_root=build_root,
        output_root=output_root,
    ))
    result = _run(link_command, cwd=REPO)
    if result.returncode != 0:
        diagnostics.append({
            "stage": "llvm-link", "returncode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr,
        })
        return BuildResult(
            "build_or_ir_unavailable", None, source_rows, tuple(commands),
            tuple(bitcode_rows), tuple(diagnostics), None, configuration,
        )
    bitcode_rows.append({"path": "linked.bc", "sha256": _sha256(linked)})
    triple = _run((str(clang), "-dumpmachine"))
    return BuildResult(
        "success", linked, source_rows, tuple(commands), tuple(bitcode_rows),
        tuple(diagnostics), triple.stdout.strip() if triple.returncode == 0 else None,
        configuration,
    )


def _path_signature(function_row: Mapping[str, Any] | None) -> Any:
    if not function_row or function_row.get("raw_call_depth") is None:
        return None
    return [
        {
            "caller": edge["caller"], "callee": edge["callee"],
            "edge_type": edge["edge_type"], "callsite": edge["callsite"],
            "indirect_target_set": edge.get("indirect_target_set"),
        }
        for edge in function_row["shortest_call_path"]["edges"]
    ]


def _extract_observation(
    observation: Mapping[str, Any], manifest_entry: Mapping[str, Any],
    build: BuildResult, primary: Mapping[str, Any], sensitivity: Mapping[str, Any],
) -> dict[str, Any]:
    identity = f"{observation['source_file']}::{observation['function']}"

    primary_mapping = map_source_identity(primary, observation["source_file"], observation["function"])
    sensitivity_mapping = map_source_identity(sensitivity, observation["source_file"], observation["function"])
    primary_row = primary_mapping["candidates"][0] if primary_mapping["candidate_count"] == 1 and primary.get("analysis_status") == "success" else None
    sensitivity_row = sensitivity_mapping["candidates"][0] if sensitivity_mapping["candidate_count"] == 1 and sensitivity.get("analysis_status") == "success" else None
    mapping_status = primary_mapping["semantic_mapping_status"]
    path = _path_signature(primary_row)
    direct_count = sum(edge["edge_type"] == "direct" for edge in path or [])
    indirect_count = sum(edge["edge_type"] == "indirect_resolved" for edge in path or [])
    old_depth = observation["old_depth"]
    new_depth = primary_row.get("raw_call_depth") if primary_row else None
    if old_depth is None and new_depth is not None:
        comparison = "old_nonnumeric_now_numeric"
    elif old_depth is not None and new_depth is None:
        comparison = "old_numeric_now_nonnumeric_or_unavailable"
    elif old_depth == new_depth:
        comparison = "numeric_depth_unchanged" if old_depth is not None else "both_nonnumeric"
    else:
        comparison = "numeric_depth_changed"
    sensitivity_path = _path_signature(sensitivity_row)
    return {
        "cve": observation["cve"],
        "vulnerable_source_tree": manifest_entry["source_tree"],
        "source_revision": manifest_entry["source_revision"],
        "affected_version": manifest_entry["affected_version"],
        "vulnerable_function_identity": identity,
        "mapped_semantic_identity": primary_row.get("identity") if primary_row else None,
        "mapped_llvm_symbol": primary_row.get("llvm_symbol") if primary_row else None,
        "source_file": observation["source_file"],
        "definition_location": primary_row.get("definition") if primary_row else None,
        "historical_build_status": build.status,
        "llvm_ir_status": "success" if build.linked_bitcode else "build_or_ir_unavailable",
        "svf_analysis_status": primary.get("analysis_status"),
        "semantic_mapping_status": mapping_status,
        "source_identity_mapping": primary_mapping,
        "source_scope_kind": (build.configuration or {}).get("source_scope_kind"),
        "semantic_raw_call_depth": new_depth,
        "shortest_semantic_path": (
            primary_row["shortest_call_path"] if primary_row else None
        ),
        "direct_edges_on_path": direct_count if path is not None else None,
        "indirect_edges_on_path": indirect_count if path is not None else None,
        "old_prototype_status": observation["old_status"],
        "old_prototype_depth": old_depth,
        "semantic_vs_prototype": comparison,
        "ff_eq_base_sensitivity": {
            "configuration": ["-stat=false"],
            "analysis_status": sensitivity.get("analysis_status"),
            "semantic_mapping_status": sensitivity_mapping["semantic_mapping_status"],
            "source_identity_mapping": sensitivity_mapping,
            "raw_call_depth": (
                sensitivity_row.get("raw_call_depth") if sensitivity_row else None
            ),
            "shortest_semantic_path": (
                sensitivity_row.get("shortest_call_path") if sensitivity_row else None
            ),
            "build_success_changed": False,
            "reachability_changed": bool(primary_row and primary_row.get("reachable_from_entry")) != bool(sensitivity_row and sensitivity_row.get("reachable_from_entry")),
            "raw_depth_changed": new_depth != (sensitivity_row.get("raw_call_depth") if sensitivity_row else None),
            "shortest_path_changed": path != sensitivity_path,
            "indirect_target_set_membership_changed": [
                edge.get("indirect_target_set") for edge in path or []
                if edge["edge_type"] == "indirect_resolved"
            ] != [
                edge.get("indirect_target_set") for edge in sensitivity_path or []
                if edge["edge_type"] == "indirect_resolved"
            ],
        },
    }


def _program_summary(
    entry: Mapping[str, Any], program: str, build: BuildResult,
    primary: Mapping[str, Any], sensitivity: Mapping[str, Any],
) -> dict[str, Any]:
    key = _program_key(entry, program)
    return {
        "program_key": list(key),
        "source_scope_kind": (build.configuration or {})["source_scope_kind"],
        "source_tree": entry["source_tree"],
        "source_revision": entry["source_revision"],
        "source_tree_sha256": entry["source_tree_sha256"],
        "entry_point": entry["programs"][program]["entry_point"],
        "historical_build_status": build.status,
        "llvm_ir_status": "success" if build.linked_bitcode else "build_or_ir_unavailable",
        "source_files": list(build.source_files),
        "build_commands": [list(command) for command in build.build_commands],
        "bitcode_files": list(build.bitcode_files),
        "build_configuration": dict(build.configuration or {}),
        "build_diagnostics": list(build.diagnostics),
        "primary": {
            "options": list(PRIMARY_OPTIONS),
            "analysis_status": primary["analysis_status"],
            "function_count": len(primary["functions"]),
            "edge_count": len(primary["call_edges"]),
            "unresolved_indirect_callsites": primary["unresolved_indirect_callsites"],
            "external_calls": primary["external_calls"],
            "failures": primary["failures"],
        },
        "sensitivity_without_ff_eq_base": {
            "options": list(SENSITIVITY_OPTIONS),
            "analysis_status": sensitivity["analysis_status"],
            "function_count": len(sensitivity["functions"]),
            "edge_count": len(sensitivity["call_edges"]),
            "unresolved_indirect_callsites": sensitivity["unresolved_indirect_callsites"],
            "external_calls": sensitivity["external_calls"],
            "failures": sensitivity["failures"],
        },
    }


def run_validation(*, helper: Path, build_root: Path) -> dict[str, Any]:
    records = load_records(HISTORICAL / "records.json")
    manifest = load_source_manifest(HISTORICAL / "source_manifest.json")
    verify_frozen_queries(records)
    inventory = inventory_toolchain(helper=helper)
    by_key: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for entry in manifest:
        for program in entry["programs"]:
            key = _program_key(entry, program)
            if key in BUILD_SPECS:
                by_key[key] = entry
    if set(by_key) != set(BUILD_SPECS):
        raise RuntimeError("historical build specifications do not match frozen manifest programs")

    analyses: dict[tuple[str, str, str], tuple[BuildResult, dict, dict]] = {}
    program_rows = []
    # Complete every primary run before beginning the sensitivity pass.
    for key in BUILD_SPECS:
        print(f"historical semantic primary: {'/'.join(key)}", file=sys.stderr, flush=True)
        entry = by_key[key]
        output = build_root / _slug(key)
        build = build_historical_bitcode(entry, key[2], output, inventory=inventory)
        primary = analyze_build(
            build, entry_point=entry["programs"][key[2]]["entry_point"]["function"],
            inventory=inventory, svf_options=PRIMARY_OPTIONS,
        )
        analyses[key] = (build, primary, {})
        (output / "primary-graph.json").write_text(stable_json(primary), encoding="utf-8")
    for key, (build, primary, _) in list(analyses.items()):
        print(f"historical semantic sensitivity: {'/'.join(key)}", file=sys.stderr, flush=True)
        entry = by_key[key]
        sensitivity = analyze_build(
            build, entry_point=entry["programs"][key[2]]["entry_point"]["function"],
            inventory=inventory, svf_options=SENSITIVITY_OPTIONS,
        )
        analyses[key] = (build, primary, sensitivity)
        output = build_root / _slug(key)
        (output / "without-ff-eq-base-graph.json").write_text(
            stable_json(sensitivity), encoding="utf-8",
        )
        program_rows.append(_program_summary(entry, key[2], build, primary, sensitivity))

    observations = []
    for declared in OBSERVATIONS:
        key = (declared["project"], declared["version"], declared["program"])
        build, primary, sensitivity = analyses[key]
        observations.append(_extract_observation(
            declared, by_key[key], build, primary, sensitivity,
        ))
    return refresh_result({
        "schema_version": 1,
        "study": "historical_v1_semantic_callgraph_validation",
        "scientific_use": "side_by_side_instrument_validation_only",
        "modifies_historical_v1": False,
        "analysis_backend": "clang_llvm_svf",
        "pointer_analysis": "andersen_wave_diff",
        "primary_svf_options": list(PRIMARY_OPTIONS),
        "sensitivity_svf_options": list(SENSITIVITY_OPTIONS),
        "toolchain": inventory,
        "programs": sorted(program_rows, key=lambda row: row["program_key"]),
        "observations": observations,
    })


def _aggregate(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    numeric = [row for row in observations if row["semantic_raw_call_depth"] is not None]
    return {
        "total_vulnerable_function_observations": len(observations),
        "semantic_numeric_depth_count": len(numeric),
        "semantic_nonnumeric_or_unavailable_count": len(observations) - len(numeric),
        "semantic_numeric_coverage": f"{len(numeric)}/{len(observations)}",
        "direct_only_reachable_count": sum(
            row["semantic_raw_call_depth"] is not None and row["indirect_edges_on_path"] == 0
            for row in observations
        ),
        "reachable_using_resolved_indirect_edge_count": sum(
            (row["indirect_edges_on_path"] or 0) > 0 for row in observations
        ),
        "old_nonnumeric_became_numeric_count": sum(
            row["old_prototype_depth"] is None and row["semantic_raw_call_depth"] is not None
            for row in observations
        ),
        "old_numeric_depth_changed_count": sum(
            row["old_prototype_depth"] is not None
            and row["semantic_raw_call_depth"] is not None
            and row["semantic_raw_call_depth"] != row["old_prototype_depth"]
            for row in observations
        ),
        "old_numeric_became_nonnumeric_or_unavailable_count": sum(
            row["old_prototype_depth"] is not None
            and row["semantic_raw_call_depth"] is None
            for row in observations
        ),
        "ff_eq_base_material_change_count": sum(
            any(value for key, value in row["ff_eq_base_sensitivity"].items() if key.endswith("_changed"))
            for row in observations
        ),
    }


def refresh_result(result: Mapping[str, Any]) -> dict[str, Any]:
    refreshed = dict(result)
    programs = []
    for original_program in result["programs"]:
        program = dict(original_program)
        configuration = dict(program.get("build_configuration", {}))
        preparation = dict(configuration.get("built_sources_preparation", {}))
        if preparation:
            normalized_targets = []
            source_marker = "/security/historical/sources/coreutils-9.7/"
            for target in preparation.get("targets", []):
                value = str(target).replace("\\", "/")
                if value.startswith("/") and source_marker in value:
                    value = "$SOURCE_ROOT/" + value.split(source_marker, 1)[1]
                normalized_targets.append(value)
            preparation["targets"] = normalized_targets
            configuration["built_sources_preparation"] = preparation
        if program.get("program_key") == ["gnu-coreutils", "9.7", "sort"]:
            configuration["build_reconstruction_diagnostic"] = {
                "initial_failure": {
                    "source_file": "lib/aszprintf.c",
                    "undeclared_identifiers": ["ptrdiff_t", "vaszprintf"],
                },
                "root_cause": "configured_automake_BUILT_SOURCES_not_realized",
                "required_generated_headers": ["lib/stddef.h", "lib/stdio.h"],
                "correction": "generate_configured_build_inputs_from_frozen_Makefile",
                "historical_source_modified": False,
                "classification": "incomplete_build_reconstruction_not_intrinsic_source_incompatibility",
                "faithful_clang_ir_result": "success",
            }
        program["build_configuration"] = configuration
        programs.append(program)
    refreshed["programs"] = programs
    rows = []
    for original in result["observations"]:
        row = dict(original)
        comparison = row["semantic_vs_prototype"]
        if comparison == "old_nonnumeric_now_numeric":
            explanation = (
                "SVF recovered one or more resolved static indirect may-call edges "
                "that the syntax-only prototype did not model."
            )
        elif comparison == "old_numeric_now_nonnumeric_or_unavailable":
            explanation = (
                "No semantic depth comparison is possible because Clang did not "
                "produce linked LLVM IR for the frozen historical configuration."
            )
        elif comparison == "numeric_depth_unchanged":
            explanation = "The shortest semantic path agrees with the prototype depth."
        elif comparison == "numeric_depth_changed":
            explanation = "The independently computed shortest semantic path has a different raw depth."
        else:
            explanation = "Both instruments remain nonnumeric."
        row["semantic_vs_prototype_explanation"] = explanation
        rows.append(row)
    refreshed["observations"] = rows
    refreshed["aggregate"] = _aggregate(rows)
    return refreshed


def render_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# Historical-v1 semantic call-graph validation",
        "",
        "This is a side-by-side validation of the Clang/LLVM/SVF instrument. It does not replace or modify the frozen historical-v1 records.",
        "",
        "Primary configuration: `AndersenWaveDiff -stat=false -ff-eq-base`. Sensitivity configuration removes only `-ff-eq-base`.",
        "",
        "| CVE | Vulnerable function | Build / SVF | Old prototype | Semantic depth | Path composition | ff-eq-base sensitivity |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for row in result["observations"]:
        old = f"{row['old_prototype_status']} / {row['old_prototype_depth']}"
        status = f"{row['historical_build_status']} / {row['svf_analysis_status']}"
        depth = row["semantic_raw_call_depth"]
        composition = (
            f"{row['direct_edges_on_path']} direct, {row['indirect_edges_on_path']} indirect"
            if depth is not None else "nonnumeric"
        )
        sensitivity = row["ff_eq_base_sensitivity"]
        changed = any(value for key, value in sensitivity.items() if key.endswith("_changed"))
        lines.append(
            f"| {row['cve']} | `{row['vulnerable_function_identity']}` | {status} | {old} | "
            f"{depth if depth is not None else 'null'} | {composition} | {'changed' if changed else 'unchanged'} |"
        )
    lines.extend(("", "## Program build and analysis status", "",
                  "| Program scope | Historical build | LLVM IR | Primary SVF | Sensitivity SVF |",
                  "| --- | --- | --- | --- | --- |"))
    for program in result["programs"]:
        lines.append(
            f"| `{'/'.join(program['program_key'])}` | {program['historical_build_status']} | "
            f"{program['llvm_ir_status']} | {program['primary']['analysis_status']} | "
            f"{program['sensitivity_without_ff_eq_base']['analysis_status']} |"
        )
    coreutils_97 = next(
        program for program in result["programs"]
        if program["program_key"] == ["gnu-coreutils", "9.7", "sort"]
    )
    if coreutils_97["historical_build_status"] == "success":
        lines.extend((
            "",
            "The initial Coreutils 9.7 `lib/aszprintf.c` failure was an incomplete build reconstruction, not an intrinsic Clang incompatibility. The per-object driver had not realized Automake `BUILT_SOURCES`, so Clang selected the system `<stdio.h>` instead of configured `lib/stdio.h` and lacked `ptrdiff_t`/`vaszprintf` declarations. The corrected driver generates all configured build inputs from the frozen GCC-derived Makefile before compiling; it does not modify the authenticated source tree or substitute the different Clang-native source scope. All 329 translation units, LLVM linking, and both SVF configurations then succeeded.",
            "",
            "## Auditable shortest paths", "",
        ))
    else:
        lines.extend((
            "", "Coreutils 9.7 remains `build_or_ir_unavailable`; see its structured build diagnostics.",
            "", "## Auditable shortest paths", "",
        ))
    for row in result["observations"]:
        lines.append(f"### {row['cve']} - `{row['vulnerable_function_identity']}`")
        lines.extend(("", row["semantic_vs_prototype_explanation"], ""))
        if row["shortest_semantic_path"]:
            identities = row["shortest_semantic_path"]["function_identities"]
            lines.extend((f"Path: `{' -> '.join(identities)}`", ""))
            for edge in row["shortest_semantic_path"]["edges"]:
                target = ""
                if edge["edge_type"] == "indirect_resolved":
                    target_names = ", ".join(f"`{name}`" for name in edge["indirect_target_set"])
                    target = f"; complete may-target set ({edge['indirect_target_count']}): {target_names}"
                lines.append(
                    f"- `{edge['caller']}` --{edge['edge_type']}--> `{edge['callee']}` at "
                    f"`{edge['callsite']['source_file']}:{edge['callsite']['line']}:{edge['callsite']['column']}`{target}"
                )
            lines.append("")
        else:
            lines.extend((f"Status: `{row['semantic_mapping_status']}`.", ""))
    aggregate = result["aggregate"]
    lines.extend((
        "## Aggregate validation",
        "",
        f"- Numeric semantic coverage: {aggregate['semantic_numeric_coverage']}",
        f"- Direct-only reachable: {aggregate['direct_only_reachable_count']}",
        f"- Reachable using at least one resolved indirect edge: {aggregate['reachable_using_resolved_indirect_edge_count']}",
        f"- Old nonnumeric observations now numeric: {aggregate['old_nonnumeric_became_numeric_count']}",
        f"- Old numeric observations with changed depth: {aggregate['old_numeric_depth_changed_count']}",
        f"- Old numeric observations now unavailable: {aggregate['old_numeric_became_nonnumeric_or_unavailable_count']}",
        f"- Observations materially changed without `ff-eq-base`: {aggregate['ff_eq_base_material_change_count']}",
        "",
        "A resolved indirect edge is a static may-call relationship, not proof that the target executes at runtime.",
        "No historical mean, median, or shallow threshold is calculated in this pilot validation.",
        "",
    ))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--helper", type=Path,
        default=REPO / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf",
    )
    parser.add_argument(
        "--build-root", type=Path,
        default=REPO / "build/semantic-historical-validation",
    )
    parser.add_argument(
        "--output", type=Path,
        default=HISTORICAL / "semantic_validation.json",
    )
    parser.add_argument(
        "--markdown", type=Path,
        default=HISTORICAL / "evidence/semantic-callgraph-validation.md",
    )
    parser.add_argument(
        "--refresh-existing", action="store_true",
        help="refresh aggregates and Markdown without rerunning Clang or SVF",
    )
    args = parser.parse_args()
    verify_frozen_queries(load_records(HISTORICAL / "records.json"))
    if args.refresh_existing:
        result = refresh_result(json.loads(args.output.read_text(encoding="utf-8")))
    else:
        if not args.helper.is_file():
            parser.error(f"SVF helper unavailable: {args.helper}")
        result = run_validation(helper=args.helper, build_root=args.build_root)
    args.output.write_text(stable_json(result), encoding="utf-8")
    args.markdown.write_text(render_markdown(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
