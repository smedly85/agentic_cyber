#!/usr/bin/env python3
"""Derive Fedora Coreutils 8.17-7 sort's GNU-ld C-source closure."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from security.historical.analysis import load_source_manifest
from security.historical.derive_coreutils_sort_scope import verify_frozen_source_files


def expand(makefile: Path, expressions: dict[str, str]) -> dict[str, list[str]]:
    make = shutil.which("make")
    if make is None:
        raise RuntimeError("GNU make is required")
    makefile = makefile.resolve()
    target = "print-sort-scope-metadata"
    lines = [f"include {makefile.name}", "", f".PHONY: {target}", f"{target}:"]
    for name, expression in expressions.items():
        lines += [f"\t@printf '@@{name}@@\\n'", f"\t@printf '%s\\n' {expression}"]
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="sort-scope-", suffix=".mk", dir=makefile.parent,
        delete=False, encoding="utf-8",
    ) as helper:
        helper.write("\n".join(lines))
        helper_path = Path(helper.name)
    try:
        process = subprocess.run(
            [make, "--no-print-directory", "-s", "-f", helper_path.name, target],
            cwd=makefile.parent, check=True, text=True, capture_output=True,
        )
    finally:
        helper_path.unlink(missing_ok=True)
    result = {name: [] for name in expressions}
    current = None
    for line in process.stdout.splitlines():
        if line.startswith("@@") and line.endswith("@@"):
            current = line[2:-2]
        elif current is not None:
            result[current].extend(line.split())
    return result


def archive_members(link_map: Path) -> list[str]:
    pattern = re.compile(r"^\.\./lib/libcoreutils\.a\(([^()]+)\)")
    members = {
        match.group(1)
        for line in link_map.read_text(encoding="utf-8", errors="replace").splitlines()
        if (match := pattern.match(line)) is not None
    }
    if not members:
        raise RuntimeError("GNU ld map names no extracted libcoreutils.a members")
    return sorted(members)


def object_source(value: str) -> str:
    name = Path(value).name
    prefix = "libcoreutils_a-"
    if not name.endswith(".o"):
        raise RuntimeError(f"cannot map archive object to C source: {value}")
    if name.startswith(prefix):
        name = name[len(prefix):]
    return f"lib/{name[:-2]}.c"


def derive_scope(
    source_tree: Path, src_makefile: Path, lib_makefile: Path, link_map: Path,
) -> dict[str, object]:
    src = expand(src_makefile, {
        "sort_sources": "$(sort_SOURCES)",
        "sort_ldadd": "$(sort_LDADD)",
    })
    lib = expand(lib_makefile, {
        "library_sources": "$(libcoreutils_a_SOURCES)",
        "library_libadd": "$(libcoreutils_a_LIBADD)",
        "library_objects": "$(am_libcoreutils_a_OBJECTS) $(libcoreutils_a_LIBADD)",
    })
    sort_sources = sorted(f"src/{item}" for item in src["sort_sources"] if item.endswith(".c"))
    if sort_sources != ["src/sort.c"]:
        raise RuntimeError(f"unexpected configured sort sources: {sort_sources}")
    direct = {f"lib/{item}" for item in lib["library_sources"] if item.endswith(".c")}
    grammar = {
        f"lib/{Path(item).with_suffix('.c').as_posix()}"
        for item in lib["library_sources"] if item.endswith((".y", ".l"))
    }
    conditional = {
        object_source(item) for item in lib["library_libadd"] if item.endswith(".o")
    }
    archive_sources = direct | grammar | conditional
    archive_objects = {item for item in lib["library_objects"] if item.endswith(".o")}
    if len(archive_sources) != len(archive_objects):
        raise RuntimeError(
            "libcoreutils C source/object counts disagree: "
            f"sources={len(archive_sources)}, objects={len(archive_objects)}"
        )
    members = archive_members(link_map.resolve())
    member_sources = {object_source(member) for member in members}
    unexpected = member_sources - archive_sources
    if unexpected:
        raise RuntimeError(f"unexpected linked members: {sorted(unexpected)}")
    archive_superset = sorted({*sort_sources, *archive_sources})
    analyzed = sorted({*sort_sources, *member_sources})
    missing = [item for item in archive_superset if not (source_tree / item).is_file()]
    if missing:
        raise RuntimeError(f"metadata-derived C files are missing: {missing}")
    return {
        "scope_kind": "linker_exact_libcoreutils_member_closure",
        "configuration": {
            "host": "x86_64-unknown-linux-gnu",
            "compiler": "gcc",
            "configure_options": [
                "--disable-nls", "--without-selinux", "--without-gmp",
                "--enable-largefile", "--enable-install-program=hostname,arch",
                "--with-tty-group", "DEFAULT_POSIX2_VERSION=200112",
                "alternative=199209",
            ],
            "multibyte_support": "HAVE_MBRTOWC=1; runtime locale must be multibyte",
            "build_only_compatibility": [
                "-D_IO_ftrylockfile=1", "-D_IO_IN_BACKUP=0x100",
                "-Wno-error=implicit-function-declaration",
                "-Wno-error=incompatible-pointer-types",
                "-Wno-error=int-conversion", "MAKEINFO=true",
            ],
        },
        "sort_sources": sort_sources,
        "linked_archives": sorted(item for item in src["sort_ldadd"] if item.endswith(".a")),
        "libcoreutils_archive_source_count": len(archive_sources),
        "conditional_libadd_c_sources": sorted(conditional),
        "linked_libcoreutils_member_count": len(member_sources),
        "linked_libcoreutils_members": members,
        "archive_source_superset_count": len(archive_superset),
        "archive_source_superset_files": archive_superset,
        "analyzed_source_file_count": len(analyzed),
        "analyzed_source_files": analyzed,
        "linker_member_exact": True,
    }


def manifest_entry(manifest_path: Path, source_tree: Path) -> dict[str, object]:
    matches = [
        item for item in load_source_manifest(manifest_path)
        if item.get("affected_version") == "8.17-7.fc18"
        and item.get("source_provenance") == "downstream_patch"
        and Path(str(item["resolved_source_tree"])).resolve() == source_tree.resolve()
    ]
    if len(matches) != 1:
        raise RuntimeError("manifest lacks the exact Fedora Coreutils 8.17-7 identity")
    return matches[0]


def verify_manifest(scope: dict[str, object], manifest_path: Path, source_tree: Path) -> None:
    frozen = manifest_entry(manifest_path, source_tree)["programs"]["sort"]["source_files"]
    if frozen != scope["analyzed_source_files"]:
        raise RuntimeError("frozen Fedora 18 sort scope differs from GNU ld closure")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-tree", type=Path, required=True)
    parser.add_argument("--src-makefile", type=Path)
    parser.add_argument("--lib-makefile", type=Path)
    parser.add_argument("--link-map", type=Path)
    parser.add_argument("--verify-manifest", type=Path)
    parser.add_argument("--verify-frozen-files-only", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.verify_frozen_files_only:
        if args.verify_manifest is None:
            parser.error("--verify-manifest is required with --verify-frozen-files-only")
        scope = verify_frozen_source_files(args.source_tree, args.verify_manifest)
        scope["scope_kind"] = "frozen_linker_exact_libcoreutils_member_closure"
    else:
        if args.src_makefile is None or args.lib_makefile is None or args.link_map is None:
            parser.error("--src-makefile, --lib-makefile, and --link-map are required")
        scope = derive_scope(args.source_tree, args.src_makefile, args.lib_makefile, args.link_map)
        if args.verify_manifest:
            verify_manifest(scope, args.verify_manifest, args.source_tree)
            scope["manifest_verified"] = True
    if args.summary:
        scope = {key: value for key, value in scope.items() if key not in {
            "analyzed_source_files", "archive_source_superset_files",
            "linked_libcoreutils_members",
        }}
    print(json.dumps(scope, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
