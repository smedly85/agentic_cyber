#!/usr/bin/env python3
"""Derive and verify GNU grep 2.10's GNU/Linux executable C-source scope."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from security.historical.analysis import load_source_manifest
from security.historical.derive_grep_scope import expand_make_variables, object_source


SRC_VARIABLES = {
    "grep_sources": "$(grep_SOURCES)",
    "grep_ldadd": "$(grep_LDADD)",
    "libgrep_sources": "$(libgrep_a_SOURCES)",
    "libgrep_objects": "$(libgrep_a_OBJECTS)",
    "pcre_library": "$(LIB_PCRE)",
}
LIB_VARIABLES = {
    "library_sources": "$(libgreputils_a_SOURCES)",
    "library_libadd": "$(libgreputils_a_LIBADD)",
    "library_objects": "$(libgreputils_a_OBJECTS) $(libgreputils_a_LIBADD)",
}


def prefixed_c_sources(prefix: str, values: list[str]) -> list[str]:
    return [
        str(PurePosixPath(prefix) / PurePosixPath(value))
        for value in values if value.endswith(".c")
    ]


def archive_members(link_map: Path, archive: str) -> list[str]:
    link_map = link_map.resolve()
    if not link_map.is_file():
        raise RuntimeError(f"GNU ld link map does not exist: {link_map}")
    pattern = re.compile(rf"^{re.escape(archive)}\(([^()]+)\)")
    members = {
        match.group(1)
        for line in link_map.read_text(encoding="utf-8", errors="replace").splitlines()
        if (match := pattern.match(line)) is not None
    }
    if not members:
        raise RuntimeError(f"GNU ld link map names no extracted {archive} members")
    return sorted(members)


def derive_scope(
    source_tree: Path,
    src_variables: dict[str, list[str]],
    lib_variables: dict[str, list[str]],
    link_map: Path,
) -> dict[str, object]:
    root = source_tree.resolve()
    grep_sources = prefixed_c_sources("src", src_variables["grep_sources"])
    libgrep_sources = prefixed_c_sources("src", src_variables["libgrep_sources"])
    if grep_sources != ["src/grep.c"]:
        raise RuntimeError(f"unexpected configured grep sources: {grep_sources}")
    if len(libgrep_sources) != len(set(src_variables["libgrep_objects"])):
        raise RuntimeError("libgrep C source/object counts disagree")

    direct_library_c = prefixed_c_sources("lib", lib_variables["library_sources"])
    libadd_c = [
        object_source("lib", value)
        for value in lib_variables["library_libadd"]
        if value.endswith((".o", ".obj"))
    ]
    archive_objects = {
        value for value in lib_variables["library_objects"]
        if value.endswith((".o", ".obj"))
    }
    library_sources = set((*direct_library_c, *libadd_c))
    if len(library_sources) != len(archive_objects):
        raise RuntimeError("libgreputils C source/object counts disagree")

    linked_archives = sorted(set(
        value for value in src_variables["grep_ldadd"] if value.endswith(".a")
    ))
    if linked_archives != ["../lib/libgreputils.a", "libgrep.a"]:
        raise RuntimeError(f"unexpected configured grep archives: {linked_archives}")

    libgrep_member_objects = archive_members(link_map, "libgrep.a")
    libgrep_member_sources = sorted({
        object_source("src", value) for value in libgrep_member_objects
    })
    greputils_member_objects = archive_members(link_map, "../lib/libgreputils.a")
    greputils_member_sources = sorted({
        object_source("lib", value) for value in greputils_member_objects
    })
    if set(libgrep_member_sources) - set(libgrep_sources):
        raise RuntimeError("link map contains an unexpected libgrep member")
    if set(greputils_member_sources) - library_sources:
        raise RuntimeError("link map contains an unexpected libgreputils member")

    archive_superset = sorted(set((
        *grep_sources, *libgrep_sources, *direct_library_c, *libadd_c,
    )))
    analyzed = sorted(set((
        *grep_sources, *libgrep_member_sources, *greputils_member_sources,
    )))
    missing = [value for value in archive_superset if not (root / value).is_file()]
    if missing:
        raise RuntimeError(
            "metadata-derived C files are missing from the release: "
            + ", ".join(missing)
        )

    return {
        "scope_kind": "linker_exact_two_archive_member_closure",
        "configuration": {
            "host": "x86_64-unknown-linux-gnu",
            "compiler": "gcc -std=gnu17",
            "configure_options": ["--disable-nls"],
            "nls_enabled": False,
            "pcre_library": src_variables["pcre_library"],
        },
        "grep_sources": grep_sources,
        "linked_archives": linked_archives,
        "libgrep_archive_source_count": len(libgrep_sources),
        "libgrep_archive_sources": sorted(libgrep_sources),
        "linked_libgrep_member_count": len(libgrep_member_sources),
        "linked_libgrep_members": libgrep_member_objects,
        "libgreputils_archive_source_count": len(library_sources),
        "conditional_libadd_c_sources": sorted(set(libadd_c)),
        "linked_libgreputils_member_count": len(greputils_member_sources),
        "linked_libgreputils_members": greputils_member_objects,
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
        if item.get("upstream_project") == "gnu-grep"
        and item.get("affected_version") == "2.10"
        and isinstance(item.get("programs", {}).get("grep"), dict)
        and Path(str(item["resolved_source_tree"])).resolve() == root
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "manifest must have exactly one GNU grep 2.10 identity for the source tree"
        )
    return matches[0]


def verify_manifest(
    scope: dict[str, object], manifest_path: Path, source_tree: Path,
) -> None:
    entry = manifest_entry(manifest_path, source_tree)
    frozen = entry.get("programs", {}).get("grep", {}).get("source_files")
    if frozen != scope["analyzed_source_files"]:
        frozen_set = set(frozen) if isinstance(frozen, list) else set()
        derived_set = set(scope["analyzed_source_files"])
        raise RuntimeError(
            "manifest grep 2.10 source_files differs from the GNU ld closure; "
            f"missing={sorted(derived_set - frozen_set)}, "
            f"extra={sorted(frozen_set - derived_set)}, "
            f"order_only={frozen_set == derived_set}"
        )


def verify_frozen_source_files(
    source_tree: Path, manifest_path: Path,
) -> dict[str, object]:
    root = source_tree.resolve()
    entry = manifest_entry(manifest_path, root)
    program = entry.get("programs", {}).get("grep", {})
    source_files = program.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise RuntimeError("manifest grep 2.10 source_files must be a non-empty array")
    if len(set(source_files)) != len(source_files):
        raise RuntimeError("manifest grep 2.10 source_files contains duplicates")
    for value in source_files:
        if not isinstance(value, str):
            raise RuntimeError("manifest grep 2.10 source_files entries must be strings")
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
        raise RuntimeError("frozen grep 2.10 entry-point source is outside source_files")
    return {
        "scope_kind": "frozen_linker_exact_two_archive_member_closure",
        "source_revision": entry["source_revision"],
        "analyzed_source_file_count": len(source_files),
        "manifest_verified": True,
        "build_metadata_reverified": False,
        "build_metadata_reverified_reason": (
            "the frozen scope came from a GNU/Linux/GCC/GNU-ld build; this host "
            "only verified exact paths against the authenticated source tree"
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
                arguments.src_makefile, SRC_VARIABLES, "print-grep210-src-metadata",
            ),
            expand_make_variables(
                arguments.lib_makefile, LIB_VARIABLES, "print-grep210-lib-metadata",
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
                "libgrep_archive_sources", "linked_libgrep_members",
                "linked_libgreputils_members",
            }
        }
    print(json.dumps(scope, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
