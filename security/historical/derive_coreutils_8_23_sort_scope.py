#!/usr/bin/env python3
"""Derive Fedora Coreutils 8.23-9 sort's GNU-ld C-source closure."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath

from security.historical.analysis import load_source_manifest
from security.historical.derive_coreutils_sort_scope import (
    expand_make_variables,
    verify_frozen_source_files,
)


def object_source(value: str) -> str:
    path = PurePosixPath(value)
    if path.suffix != ".o" or path.parts[:1] != ("lib",):
        raise RuntimeError(f"cannot map archive object to C source: {value}")
    name = path.name
    prefix = "libcoreutils_a-"
    if name.startswith(prefix):
        name = name[len(prefix):]
    return str(path.parent / f"{name[:-2]}.c")


def archive_members(link_map: Path, archive: str) -> list[str]:
    pattern = re.compile(rf"^{re.escape(archive)}\(([^()]+)\)")
    members = {
        match.group(1)
        for line in link_map.read_text(encoding="utf-8", errors="replace").splitlines()
        if (match := pattern.match(line)) is not None
    }
    if not members:
        raise RuntimeError(f"GNU ld map names no extracted {archive} members")
    return sorted(members)


def derive_scope(source_tree: Path, makefile: Path, link_map: Path) -> dict[str, object]:
    variables = expand_make_variables(makefile)
    root = source_tree.resolve()
    sort_sources = sorted({
        value for value in variables["sort_sources"] if value.endswith(".c")
    })
    if sort_sources != ["src/sort.c"]:
        raise RuntimeError(f"unexpected configured sort sources: {sort_sources}")

    direct_library = {
        value for value in variables["library_sources"] if value.endswith(".c")
    }
    generated_library = {
        str(PurePosixPath(value).with_suffix(".c"))
        for value in variables["library_sources"] if value.endswith((".y", ".l"))
    }
    conditional_library = {
        object_source(value)
        for value in variables["library_libadd"] if value.endswith(".o")
    }
    archive_sources = direct_library | generated_library | conditional_library
    archive_objects = {
        value for value in variables["library_objects"] if value.endswith(".o")
    }
    if len(archive_sources) != len(archive_objects):
        raise RuntimeError(
            "libcoreutils C source/object counts disagree: "
            f"sources={len(archive_sources)}, objects={len(archive_objects)}"
        )

    members = archive_members(link_map.resolve(), "lib/libcoreutils.a")
    member_sources = {f"lib/{member[:-2]}.c" for member in members}
    unexpected = member_sources - archive_sources
    if unexpected:
        raise RuntimeError(
            f"GNU ld map contains unexpected libcoreutils members: {sorted(unexpected)}"
        )

    archive_superset = sorted({*sort_sources, *archive_sources})
    analyzed = sorted({*sort_sources, *member_sources})
    missing = [value for value in archive_superset if not (root / value).is_file()]
    if missing:
        raise RuntimeError(f"metadata-derived C files are missing: {missing}")
    return {
        "scope_kind": "linker_exact_libcoreutils_member_closure",
        "configuration": {
            "host": "x86_64-unknown-linux-gnu",
            "compiler": "gcc",
            "configure_options": [
                "--disable-nls", "--without-selinux", "--without-openssl",
                "--without-gmp", "--enable-largefile",
                "--enable-install-program=hostname,arch", "--with-tty-group",
                "DEFAULT_POSIX2_VERSION=200112", "alternative=199209",
            ],
            "multibyte_support": "HAVE_MBRTOWC=1; runtime locale must be multibyte",
            "build_only_compatibility": [
                "-D_IO_ftrylockfile=1",
                "-D_IO_IN_BACKUP=0x100",
                "-Wno-error=implicit-function-declaration",
                "-Wno-error=incompatible-pointer-types",
                "-Wno-error=int-conversion",
                "MAKEINFO=true",
            ],
        },
        "sort_sources": sort_sources,
        "linked_archives": sorted({
            value for value in variables["sort_ldadd"] if value.endswith(".a")
        }),
        "libcoreutils_archive_source_count": len(archive_sources),
        "conditional_libadd_c_sources": sorted(conditional_library),
        "linked_libcoreutils_member_count": len(member_sources),
        "linked_libcoreutils_members": members,
        "archive_source_superset_count": len(archive_superset),
        "archive_source_superset_files": archive_superset,
        "analyzed_source_file_count": len(analyzed),
        "analyzed_source_files": analyzed,
        "linker_member_exact": True,
    }


def manifest_entry(manifest_path: Path, source_tree: Path) -> dict[str, object]:
    root = source_tree.resolve()
    matches = [
        item for item in load_source_manifest(manifest_path)
        if item.get("source_provenance") == "downstream_patch"
        and isinstance(item.get("programs", {}).get("sort"), dict)
        and Path(str(item["resolved_source_tree"])).resolve() == root
    ]
    if len(matches) != 1:
        raise RuntimeError("manifest lacks the exact Fedora Coreutils 8.23-9 identity")
    return matches[0]


def verify_manifest(scope: dict[str, object], manifest_path: Path, source_tree: Path) -> None:
    entry = manifest_entry(manifest_path, source_tree)
    frozen = entry.get("programs", {}).get("sort", {}).get("source_files")
    if frozen != scope["analyzed_source_files"]:
        raise RuntimeError("frozen downstream sort scope differs from GNU ld closure")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-tree", type=Path, required=True)
    parser.add_argument("--makefile", type=Path)
    parser.add_argument("--link-map", type=Path)
    parser.add_argument("--verify-manifest", type=Path)
    parser.add_argument("--verify-frozen-files-only", action="store_true")
    parser.add_argument("--summary", action="store_true")
    arguments = parser.parse_args()
    if arguments.verify_frozen_files_only:
        if arguments.verify_manifest is None:
            parser.error("--verify-manifest is required with --verify-frozen-files-only")
        scope = verify_frozen_source_files(arguments.source_tree, arguments.verify_manifest)
        scope["scope_kind"] = "frozen_linker_exact_libcoreutils_member_closure"
    else:
        if arguments.makefile is None or arguments.link_map is None:
            parser.error("--makefile and --link-map are required")
        scope = derive_scope(arguments.source_tree, arguments.makefile, arguments.link_map)
        if arguments.verify_manifest:
            verify_manifest(scope, arguments.verify_manifest, arguments.source_tree)
            scope["manifest_verified"] = True
    if arguments.summary:
        scope = {
            key: value for key, value in scope.items()
            if key not in {
                "analyzed_source_files", "archive_source_superset_files",
                "linked_libcoreutils_members",
            }
        }
    print(json.dumps(scope, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
