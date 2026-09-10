#!/usr/bin/env python3
"""Derive and verify Coreutils sort's conservative C source scope.

This expands an already configured Coreutils Makefile.  It does not compile or
link Coreutils.  The result is the translation-unit superset used to build the
objects in libcoreutils.a, not the subset of archive members extracted by the
static linker.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath


FROZEN_REVISION = "8e075ff8ee11692c5504d8e82a48ed47a7f07ba9"


VARIABLES = {
    "sort_sources": "$(src_sort_SOURCES)",
    "sort_ldadd": "$(src_sort_LDADD)",
    "library_sources": "$(lib_libcoreutils_a_SOURCES)",
    "library_libadd": "$(lib_libcoreutils_a_LIBADD)",
    "library_objects": (
        "$(am_lib_libcoreutils_a_OBJECTS) $(lib_libcoreutils_a_LIBADD)"
    ),
    "generated_version_sources": "$(nodist_src_libver_a_SOURCES)",
}


def expand_make_variables(makefile: Path) -> dict[str, list[str]]:
    make = shutil.which("make")
    if make is None:
        raise RuntimeError("GNU make is required to expand the configured Makefile")
    makefile = makefile.resolve()
    if not makefile.is_file():
        raise RuntimeError(f"configured Makefile does not exist: {makefile}")
    target = "print-sort-scope-metadata"
    lines = [
        f"include {makefile.name}", "", f".PHONY: {target}", f"{target}:",
    ]
    for name, expression in VARIABLES.items():
        lines.extend((
            f"\t@printf '@@{name}@@\\n'",
            f"\t@printf '%s\\n' {expression}",
        ))
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="sort-scope-", suffix=".mk",
        dir=makefile.parent, delete=False, encoding="utf-8",
    ) as helper:
        helper.write("\n".join(lines))
        helper_path = Path(helper.name)
    try:
        process = subprocess.run(
            [make, "--no-print-directory", "-s", "-f", helper_path.name, target],
            cwd=makefile.parent, check=True, text=True, capture_output=True,
        )
        expanded: dict[str, list[str]] = {name: [] for name in VARIABLES}
        current: str | None = None
        for line in process.stdout.splitlines():
            if line.startswith("@@") and line.endswith("@@"):
                current = line[2:-2]
            elif current is not None:
                expanded[current].extend(line.split())
        return expanded
    finally:
        helper_path.unlink(missing_ok=True)


def libadd_object_source(object_name: str) -> str:
    path = PurePosixPath(object_name)
    prefix = "libcoreutils_a-"
    if path.suffix != ".o" or not path.name.startswith(prefix):
        raise RuntimeError(f"cannot deterministically map LIBADD object to C source: {object_name}")
    source_name = path.name[len(prefix):-2] + ".c"
    return str(path.parent / source_name)


def derive_scope(source_tree: Path, variables: dict[str, list[str]]) -> dict[str, object]:
    source_tree = source_tree.resolve()
    direct_c = [item for item in variables["library_sources"] if item.endswith(".c")]
    generated_from_grammar = [
        str(PurePosixPath(item).with_suffix(".c"))
        for item in variables["library_sources"]
        if item.endswith((".y", ".l"))
    ]
    libadd_c = [
        libadd_object_source(item)
        for item in variables["library_libadd"]
        if item.endswith(".o")
    ]
    sort_c = [item for item in variables["sort_sources"] if item.endswith(".c")]
    analyzed = sorted(set((*sort_c, *direct_c, *generated_from_grammar, *libadd_c)))
    missing = [item for item in analyzed if not (source_tree / item).is_file()]
    if missing:
        raise RuntimeError(
            "metadata-derived C source files are missing from the release tree: "
            + ", ".join(missing)
        )
    generated_version = sorted(set(
        item for item in variables["generated_version_sources"] if item.endswith(".c")
    ))
    archive_objects = [item for item in variables["library_objects"] if item.endswith(".o")]
    if len(set((*direct_c, *generated_from_grammar, *libadd_c))) != len(set(archive_objects)):
        raise RuntimeError(
            "C source/object counts disagree; inspect Automake mappings before freezing scope"
        )
    return {
        "scope_kind": "configured_archive_source_superset",
        "sort_sources": sorted(set(sort_c)),
        "linked_archives": sorted(set(
            item for item in variables["sort_ldadd"] if item.endswith(".a")
        )),
        "libcoreutils_archive_object_count": len(set(archive_objects)),
        "direct_libcoreutils_c_sources": len(set(direct_c)),
        "generated_from_grammar": sorted(set(generated_from_grammar)),
        "conditional_libadd_c_sources": sorted(set(libadd_c)),
        "generated_version_sources_not_in_release_tree": [
            item for item in generated_version if not (source_tree / item).is_file()
        ],
        "analyzed_source_file_count": len(analyzed),
        "analyzed_source_files": analyzed,
        "linker_member_exact": False,
        "linker_member_exact_reason": (
            "the static linker extracts only referenced libcoreutils.a members; "
            "a successful compatible link or link-map analysis is required to identify them"
        ),
    }


def verify_manifest(scope: dict[str, object], manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [
        item for item in manifest
        if item.get("upstream_project") == "gnu-coreutils"
        and item.get("affected_version") == "9.7"
    ]
    if len(matches) != 1:
        raise RuntimeError("manifest must have exactly one GNU Coreutils 9.7 entry")
    frozen = matches[0].get("programs", {}).get("sort", {}).get("source_files")
    if frozen != scope["analyzed_source_files"]:
        frozen_set = set(frozen) if isinstance(frozen, list) else set()
        derived_set = set(scope["analyzed_source_files"])
        raise RuntimeError(
            "manifest sort.source_files differs from configured build metadata; "
            f"missing={sorted(derived_set - frozen_set)}, "
            f"extra={sorted(frozen_set - derived_set)}, "
            f"order_only={frozen_set == derived_set}"
        )


def verify_frozen_source_files(source_tree: Path, manifest_path: Path) -> dict[str, object]:
    """Verify a frozen Linux-derived scope on a non-Linux preparation host."""
    root = source_tree.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [
        item for item in manifest
        if item.get("upstream_project") == "gnu-coreutils"
        and item.get("affected_version") == "9.7"
        and item.get("source_revision") == FROZEN_REVISION
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "manifest must have exactly one frozen GNU Coreutils 9.7 source identity"
        )
    program = matches[0].get("programs", {}).get("sort", {})
    source_files = program.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise RuntimeError("manifest sort.source_files must be a non-empty array")
    if len(set(source_files)) != len(source_files):
        raise RuntimeError("manifest sort.source_files contains duplicates")
    for value in source_files:
        if not isinstance(value, str):
            raise RuntimeError("manifest sort.source_files entries must be strings")
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
        raise RuntimeError("frozen sort entry-point source is outside source_files")
    return {
        "scope_kind": "frozen_configured_archive_source_superset",
        "source_revision": FROZEN_REVISION,
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
    parser.add_argument("--makefile", type=Path)
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
        if arguments.makefile is not None:
            parser.error("--makefile cannot be used with --verify-frozen-files-only")
        if arguments.verify_manifest is None:
            parser.error("--verify-manifest is required with --verify-frozen-files-only")
        scope = verify_frozen_source_files(
            arguments.source_tree, arguments.verify_manifest
        )
    else:
        if arguments.makefile is None:
            parser.error("--makefile is required unless --verify-frozen-files-only is used")
        scope = derive_scope(
            arguments.source_tree, expand_make_variables(arguments.makefile)
        )
        if arguments.verify_manifest:
            verify_manifest(scope, arguments.verify_manifest)
            scope["manifest_verified"] = True
    if arguments.summary:
        scope = {
            key: value for key, value in scope.items()
            if key != "analyzed_source_files"
        }
    print(json.dumps(scope, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
