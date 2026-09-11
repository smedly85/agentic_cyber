#!/usr/bin/env python3
"""Derive and verify Coreutils 5.2.1 mkdir's GNU/Linux C source scope.

The formal scope is the mkdir-owned translation unit plus the libfetish.a
members named by a successful configured GNU ld link map.  The configured
archive-source superset is retained in the report as derivation evidence, but
is not used as the formal analysis scope when a link map is supplied.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from security.historical.analysis import load_source_manifest


SRC_VARIABLES = {
    "mkdir_sources": "$(mkdir_SOURCES)",
    "mkdir_ldadd": "$(mkdir_LDADD)",
}
LIB_VARIABLES = {
    "library_sources": "$(libfetish_a_SOURCES)",
    "library_libadd": "$(libfetish_a_LIBADD)",
    "library_objects": "$(libfetish_a_OBJECTS) $(libfetish_a_LIBADD)",
}


def expand_make_variables(
    makefile: Path, variables: dict[str, str], target: str,
) -> dict[str, list[str]]:
    make = shutil.which("make")
    if make is None:
        raise RuntimeError("GNU make is required to expand configured Makefiles")
    makefile = makefile.resolve()
    if not makefile.is_file():
        raise RuntimeError(f"configured Makefile does not exist: {makefile}")
    lines = [f"include {makefile.name}", "", f".PHONY: {target}", f"{target}:"]
    for name, expression in variables.items():
        lines.extend((
            f"\t@printf '@@{name}@@\\n'",
            f"\t@printf '%s\\n' {expression}",
        ))
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="mkdir-scope-", suffix=".mk",
        dir=makefile.parent, delete=False, encoding="utf-8",
    ) as helper:
        helper.write("\n".join(lines))
        helper_path = Path(helper.name)
    try:
        process = subprocess.run(
            [make, "--no-print-directory", "-s", "-f", helper_path.name, target],
            cwd=makefile.parent, check=True, text=True, capture_output=True,
        )
        expanded: dict[str, list[str]] = {name: [] for name in variables}
        current: str | None = None
        for line in process.stdout.splitlines():
            if line.startswith("@@") and line.endswith("@@"):
                current = line[2:-2]
            elif current is not None:
                expanded[current].extend(line.split())
        return expanded
    finally:
        helper_path.unlink(missing_ok=True)


def object_source(object_name: str) -> str:
    path = PurePosixPath(object_name)
    if path.suffix not in {".o", ".obj"}:
        raise RuntimeError(
            f"cannot deterministically map archive object to C source: {object_name}"
        )
    return str(PurePosixPath("lib") / path.with_suffix(".c"))


def link_map_members(link_map: Path) -> list[str]:
    link_map = link_map.resolve()
    if not link_map.is_file():
        raise RuntimeError(f"GNU ld link map does not exist: {link_map}")
    pattern = re.compile(r"^\.\./lib/libfetish\.a\(([^()]+)\)")
    members = {
        match.group(1)
        for line in link_map.read_text(encoding="utf-8", errors="replace").splitlines()
        if (match := pattern.match(line)) is not None
    }
    if not members:
        raise RuntimeError("GNU ld link map names no extracted libfetish.a members")
    return sorted(members)


def derive_scope(
    source_tree: Path,
    src_variables: dict[str, list[str]],
    lib_variables: dict[str, list[str]],
    link_map: Path,
) -> dict[str, object]:
    source_tree = source_tree.resolve()
    mkdir_sources = [
        str(PurePosixPath("src") / value)
        for value in src_variables["mkdir_sources"] if value.endswith(".c")
    ]
    if mkdir_sources != ["src/mkdir.c"]:
        raise RuntimeError(f"unexpected configured mkdir sources: {mkdir_sources}")

    direct_library_c = [
        str(PurePosixPath("lib") / value)
        for value in lib_variables["library_sources"] if value.endswith(".c")
    ]
    generated_from_grammar = [
        str(PurePosixPath("lib") / PurePosixPath(value).with_suffix(".c"))
        for value in lib_variables["library_sources"]
        if value.endswith((".y", ".l"))
    ]
    libadd_c = [
        object_source(value)
        for value in lib_variables["library_libadd"]
        if value.endswith((".o", ".obj"))
    ]
    archive_superset = sorted(set((
        *direct_library_c, *generated_from_grammar, *libadd_c,
    )))
    missing = [item for item in archive_superset if not (source_tree / item).is_file()]
    if missing:
        raise RuntimeError(
            "metadata-derived C source files are missing from the release tree: "
            + ", ".join(missing)
        )

    linked_archives = sorted(set(
        item for item in src_variables["mkdir_ldadd"] if item.endswith(".a")
    ))
    if linked_archives != ["../lib/libfetish.a"]:
        raise RuntimeError(f"unexpected configured mkdir archive dependencies: {linked_archives}")

    archive_objects = {
        value for value in lib_variables["library_objects"]
        if value.endswith((".o", ".obj"))
    }
    archive_sources = set((*direct_library_c, *generated_from_grammar, *libadd_c))
    if len(archive_sources) != len(archive_objects):
        raise RuntimeError(
            "libfetish C source/object counts disagree; inspect Automake mappings "
            "before freezing scope"
        )

    member_objects = link_map_members(link_map)
    member_sources = sorted({object_source(value) for value in member_objects})
    unexpected = sorted(set(member_sources) - set(archive_superset))
    if unexpected:
        raise RuntimeError(
            "link map contains archive members outside the configured source superset: "
            + ", ".join(unexpected)
        )
    analyzed = sorted(set((*mkdir_sources, *member_sources)))
    return {
        "scope_kind": "linker_exact_archive_member_closure",
        "configuration": {
            "host": "x86_64-unknown-linux-gnu",
            "compiler": "gcc -std=gnu89 -fcommon",
            "configure_options": ["--disable-nls"],
            "nls_enabled": False,
        },
        "mkdir_sources": mkdir_sources,
        "linked_archives": linked_archives,
        "libfetish_archive_object_count": len(archive_objects),
        "archive_source_superset_count": len(archive_superset),
        "archive_source_superset_files": archive_superset,
        "linked_libfetish_member_count": len(member_sources),
        "linked_libfetish_members": member_objects,
        "analyzed_source_file_count": len(analyzed),
        "analyzed_source_files": analyzed,
        "linker_member_exact": True,
    }


def manifest_mkdir_entry(manifest_path: Path, source_tree: Path) -> dict[str, object]:
    manifest = load_source_manifest(manifest_path)
    root = source_tree.resolve()
    matches = [
        item for item in manifest
        if item.get("upstream_project") == "gnu-coreutils"
        and isinstance(item.get("programs", {}).get("mkdir"), dict)
        and Path(str(item["resolved_source_tree"])).resolve() == root
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "manifest must have exactly one GNU Coreutils mkdir identity for the source tree"
        )
    return matches[0]


def verify_manifest(
    scope: dict[str, object], manifest_path: Path, source_tree: Path,
) -> None:
    entry = manifest_mkdir_entry(manifest_path, source_tree)
    frozen = entry.get("programs", {}).get("mkdir", {}).get("source_files")
    if frozen != scope["analyzed_source_files"]:
        frozen_set = set(frozen) if isinstance(frozen, list) else set()
        derived_set = set(scope["analyzed_source_files"])
        raise RuntimeError(
            "manifest mkdir.source_files differs from the GNU ld closure; "
            f"missing={sorted(derived_set - frozen_set)}, "
            f"extra={sorted(frozen_set - derived_set)}, "
            f"order_only={frozen_set == derived_set}"
        )


def verify_frozen_source_files(
    source_tree: Path, manifest_path: Path,
) -> dict[str, object]:
    """Verify the frozen Linux link closure on a non-Linux host."""
    root = source_tree.resolve()
    entry = manifest_mkdir_entry(manifest_path, root)
    program = entry.get("programs", {}).get("mkdir", {})
    source_files = program.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise RuntimeError("manifest mkdir.source_files must be a non-empty array")
    if len(set(source_files)) != len(source_files):
        raise RuntimeError("manifest mkdir.source_files contains duplicates")
    for value in source_files:
        if not isinstance(value, str):
            raise RuntimeError("manifest mkdir.source_files entries must be strings")
        relative = PurePosixPath(value)
        if (
            not value or "\\" in value or relative.is_absolute()
            or PureWindowsPath(value).drive or ".." in relative.parts
            or relative.suffix != ".c"
        ):
            raise RuntimeError(f"unsafe or non-C frozen source path: {value}")
        candidate = root.joinpath(*relative.parts).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise RuntimeError(f"frozen source path escapes source tree: {value}") from error
        if not candidate.is_file():
            raise RuntimeError(f"frozen source file is missing: {value}")
    entry_file = program.get("entry_point", {}).get("source_file")
    if entry_file not in source_files:
        raise RuntimeError("frozen mkdir entry-point source is outside source_files")
    return {
        "scope_kind": "frozen_linker_exact_archive_member_closure",
        "source_revision": entry["source_revision"],
        "analyzed_source_file_count": len(source_files),
        "manifest_verified": True,
        "build_metadata_reverified": False,
        "build_metadata_reverified_reason": (
            "the frozen scope came from a GNU/Linux/GCC/GNU-ld build; this host "
            "only verified its exact paths against the authenticated source tree"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-tree", type=Path, required=True)
    parser.add_argument("--src-makefile", type=Path)
    parser.add_argument("--lib-makefile", type=Path)
    parser.add_argument("--link-map", type=Path)
    parser.add_argument("--verify-manifest", type=Path)
    parser.add_argument("--verify-frozen-files-only", action="store_true")
    parser.add_argument("--summary", action="store_true")
    arguments = parser.parse_args()
    if arguments.verify_frozen_files_only:
        if any((arguments.src_makefile, arguments.lib_makefile, arguments.link_map)):
            parser.error("build inputs cannot be used with --verify-frozen-files-only")
        if arguments.verify_manifest is None:
            parser.error("--verify-manifest is required with --verify-frozen-files-only")
        scope = verify_frozen_source_files(arguments.source_tree, arguments.verify_manifest)
    else:
        if any(value is None for value in (
            arguments.src_makefile, arguments.lib_makefile, arguments.link_map,
        )):
            parser.error("--src-makefile, --lib-makefile, and --link-map are required")
        scope = derive_scope(
            arguments.source_tree,
            expand_make_variables(
                arguments.src_makefile, SRC_VARIABLES, "print-mkdir-scope-metadata",
            ),
            expand_make_variables(
                arguments.lib_makefile, LIB_VARIABLES, "print-libfetish-scope-metadata",
            ),
            arguments.link_map,
        )
        if arguments.verify_manifest:
            verify_manifest(scope, arguments.verify_manifest, arguments.source_tree)
            scope["manifest_verified"] = True
    if arguments.summary:
        scope = {
            key: value for key, value in scope.items()
            if key not in {
                "analyzed_source_files", "archive_source_superset_files",
                "linked_libfetish_members",
            }
        }
    print(json.dumps(scope, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
