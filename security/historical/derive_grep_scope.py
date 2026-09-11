#!/usr/bin/env python3
"""Derive and verify GNU grep's conservative C source scope.

This expands already configured src/Makefile and lib/Makefile files.  It does
not compile or link grep.  The result is the grep-owned translation units plus
the translation-unit superset used to build libgreputils.a, not the subset of
archive members extracted by the static linker.
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
    "grep_sources": "$(grep_SOURCES)",
    "grep_ldadd": "$(grep_LDADD)",
    "pcre_library": "$(LIB_PCRE)",
}
LIB_VARIABLES = {
    "library_sources": "$(libgreputils_a_SOURCES)",
    "library_nodist_sources": "$(nodist_libgreputils_a_SOURCES)",
    "library_libadd": "$(libgreputils_a_LIBADD)",
    "library_objects": (
        "$(libgreputils_a_OBJECTS) $(libgreputils_a_LIBADD)"
    ),
    "colorize_source": "$(COLORIZE_SOURCE)",
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
        mode="w", prefix="grep-scope-", suffix=".mk",
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


def prefixed_c_sources(prefix: str, values: list[str]) -> list[str]:
    return [
        str(PurePosixPath(prefix) / PurePosixPath(value))
        for value in values if value.endswith(".c")
    ]


def object_source(prefix: str, object_name: str) -> str:
    path = PurePosixPath(object_name)
    if path.suffix not in {".o", ".obj"}:
        raise RuntimeError(
            f"cannot deterministically map archive object to C source: {object_name}"
        )
    return str(PurePosixPath(prefix) / path.with_suffix(".c"))


def link_map_members(link_map: Path) -> list[str]:
    link_map = link_map.resolve()
    if not link_map.is_file():
        raise RuntimeError(f"GNU ld link map does not exist: {link_map}")
    pattern = re.compile(r"^\.\./lib/libgreputils\.a\(([^()]+)\)")
    members = {
        match.group(1)
        for line in link_map.read_text(encoding="utf-8", errors="replace").splitlines()
        if (match := pattern.match(line)) is not None
    }
    if not members:
        raise RuntimeError("GNU ld link map names no extracted libgreputils.a members")
    return sorted(members)


def derive_scope(
    source_tree: Path,
    src_variables: dict[str, list[str]],
    lib_variables: dict[str, list[str]],
    link_map: Path | None = None,
) -> dict[str, object]:
    source_tree = source_tree.resolve()
    grep_c = prefixed_c_sources("src", src_variables["grep_sources"])
    direct_library_c = prefixed_c_sources("lib", lib_variables["library_sources"])
    libadd_c = [
        object_source("lib", value)
        for value in lib_variables["library_libadd"]
        if value.endswith((".o", ".obj"))
    ]

    nodist_c = [
        value for value in lib_variables["library_nodist_sources"]
        if value.endswith(".c")
    ]
    if nodist_c != ["colorize.c"]:
        raise RuntimeError(
            "unexpected non-distributed libgreputils sources: " + ", ".join(nodist_c)
        )
    colorize = lib_variables["colorize_source"]
    if len(colorize) != 1 or colorize[0] not in {
        "colorize-posix.c", "colorize-w32.c",
    }:
        raise RuntimeError("configured COLORIZE_SOURCE is missing or unexpected")
    configured_nodist_replacements = [f"lib/{colorize[0]}"]

    archive_superset = sorted(set((
        *grep_c, *direct_library_c, *libadd_c, *configured_nodist_replacements,
    )))
    missing = [item for item in archive_superset if not (source_tree / item).is_file()]
    if missing:
        raise RuntimeError(
            "metadata-derived C source files are missing from the release tree: "
            + ", ".join(missing)
        )

    archive_objects = [
        item for item in lib_variables["library_objects"]
        if item.endswith((".o", ".obj"))
    ]
    archive_sources = set((*direct_library_c, *libadd_c, *configured_nodist_replacements))
    if len(archive_sources) != len(set(archive_objects)):
        raise RuntimeError(
            "libgreputils C source/object counts disagree; inspect Automake mappings "
            "before freezing scope"
        )
    linked_archives = sorted(set(
        item for item in src_variables["grep_ldadd"] if item.endswith(".a")
    ))
    if linked_archives != ["../lib/libgreputils.a"]:
        raise RuntimeError(f"unexpected configured grep archive dependencies: {linked_archives}")

    member_objects: list[str] = []
    member_sources: list[str] = []
    if link_map is not None:
        member_objects = link_map_members(link_map)
        member_sources = sorted(set(
            configured_nodist_replacements[0]
            if value == "colorize.o" else object_source("lib", value)
            for value in member_objects
        ))
        unexpected = sorted(set(member_sources) - set(archive_superset))
        if unexpected:
            raise RuntimeError(
                "link map contains archive members outside the configured source superset: "
                + ", ".join(unexpected)
            )
        analyzed = sorted(set((*grep_c, *member_sources)))
        scope_kind = "linker_exact_archive_member_closure"
    else:
        analyzed = archive_superset
        scope_kind = "configured_archive_source_superset"

    return {
        "scope_kind": scope_kind,
        "configuration": {
            "host": "x86_64-unknown-linux-gnu",
            "compiler": "gcc -std=gnu17",
            "configure_options": ["--disable-nls"],
            "nls_enabled": False,
            "pcre_library": src_variables["pcre_library"],
            "configured_colorize_source": configured_nodist_replacements[0],
        },
        "grep_sources": sorted(set(grep_c)),
        "linked_archives": linked_archives,
        "libgreputils_archive_object_count": len(set(archive_objects)),
        "direct_libgreputils_c_sources": len(set(direct_library_c)),
        "conditional_libadd_c_sources": sorted(set(libadd_c)),
        "generated_wrapper_sources_not_in_release_tree": ["lib/colorize.c"],
        "archive_source_superset_count": len(archive_superset),
        "archive_source_superset_files": archive_superset,
        "linked_libgreputils_member_count": len(member_sources) if link_map else None,
        "linked_libgreputils_members": member_objects,
        "analyzed_source_file_count": len(analyzed),
        "analyzed_source_files": analyzed,
        "linker_member_exact": link_map is not None,
        "linker_member_exact_reason": None if link_map else (
            "the static linker extracts only referenced libgreputils.a members; "
            "pass a GNU ld link map to identify them"
        ),
    }


def manifest_grep_entry(manifest_path: Path, source_tree: Path) -> dict[str, object]:
    manifest = load_source_manifest(manifest_path)
    root = source_tree.resolve()
    matches = [
        item for item in manifest
        if item.get("upstream_project") == "gnu-grep"
        and isinstance(item.get("programs", {}).get("grep"), dict)
        and Path(str(item["resolved_source_tree"])).resolve() == root
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "manifest must have exactly one GNU grep identity for the source tree"
        )
    return matches[0]


def verify_manifest(
    scope: dict[str, object], manifest_path: Path, source_tree: Path,
) -> None:
    entry = manifest_grep_entry(manifest_path, source_tree)
    frozen = entry.get("programs", {}).get("grep", {}).get("source_files")
    if frozen != scope["analyzed_source_files"]:
        frozen_set = set(frozen) if isinstance(frozen, list) else set()
        derived_set = set(scope["analyzed_source_files"])
        raise RuntimeError(
            "manifest grep.source_files differs from configured build metadata; "
            f"missing={sorted(derived_set - frozen_set)}, "
            f"extra={sorted(frozen_set - derived_set)}, "
            f"order_only={frozen_set == derived_set}"
        )


def verify_frozen_source_files(
    source_tree: Path, manifest_path: Path,
) -> dict[str, object]:
    """Verify a frozen Linux-derived scope on a non-Linux preparation host."""
    root = source_tree.resolve()
    entry = manifest_grep_entry(manifest_path, root)
    program = entry.get("programs", {}).get("grep", {})
    source_files = program.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise RuntimeError("manifest grep.source_files must be a non-empty array")
    if len(set(source_files)) != len(source_files):
        raise RuntimeError("manifest grep.source_files contains duplicates")
    for value in source_files:
        if not isinstance(value, str):
            raise RuntimeError("manifest grep.source_files entries must be strings")
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
        raise RuntimeError("frozen grep entry-point source is outside source_files")
    return {
        "scope_kind": "frozen_configured_archive_source_superset",
        "source_revision": entry["source_revision"],
        "analyzed_source_file_count": len(source_files),
        "manifest_verified": True,
        "build_metadata_reverified": False,
        "build_metadata_reverified_reason": (
            "the frozen scope was derived from a GNU/Linux GCC configuration; "
            "this host only verified its exact paths against the authenticated source tree"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-tree", type=Path, required=True)
    parser.add_argument("--src-makefile", type=Path)
    parser.add_argument("--lib-makefile", type=Path)
    parser.add_argument(
        "--link-map", type=Path,
        help="GNU ld map from the configured grep link; freezes exact archive members",
    )
    parser.add_argument("--verify-manifest", type=Path)
    parser.add_argument(
        "--verify-frozen-files-only", action="store_true",
        help="verify frozen manifest paths without regenerating platform-specific metadata",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="omit the full analyzed_source_files array from printed JSON",
    )
    arguments = parser.parse_args()
    if arguments.verify_frozen_files_only:
        if arguments.src_makefile is not None or arguments.lib_makefile is not None:
            parser.error("Makefiles cannot be used with --verify-frozen-files-only")
        if arguments.verify_manifest is None:
            parser.error("--verify-manifest is required with --verify-frozen-files-only")
        scope = verify_frozen_source_files(arguments.source_tree, arguments.verify_manifest)
    else:
        if arguments.src_makefile is None or arguments.lib_makefile is None:
            parser.error(
                "--src-makefile and --lib-makefile are required unless "
                "--verify-frozen-files-only is used"
            )
        scope = derive_scope(
            arguments.source_tree,
            expand_make_variables(
                arguments.src_makefile, SRC_VARIABLES, "print-grep-scope-metadata",
            ),
            expand_make_variables(
                arguments.lib_makefile, LIB_VARIABLES,
                "print-libgreputils-scope-metadata",
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
                "linked_libgreputils_members",
            }
        }
    print(json.dumps(scope, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
