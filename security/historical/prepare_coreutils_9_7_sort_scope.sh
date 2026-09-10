#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
manifest="$script_dir/source_manifest.json"

bash "$script_dir/prepare_coreutils_9_7.sh"

identity=$(
  PYTHONPATH="$repo_root" python3 -c \
    'import sys
from pathlib import Path
from security.historical.analysis import load_source_manifest
entries = load_source_manifest(Path(sys.argv[1]))
matches = [entry for entry in entries
           if entry.get("upstream_project") == "gnu-coreutils"
           and isinstance(entry.get("programs", {}).get("sort"), dict)]
if len(matches) != 1:
    raise SystemExit("manifest must contain exactly one GNU Coreutils sort identity")
entry = matches[0]
source_tree = Path(sys.argv[1]).parent / entry["source_tree"]
print(entry["affected_version"], source_tree, sep="\t")' \
    "$manifest"
)
IFS=$'\t' read -r release_version source_tree <<< "$identity"
build_dir="$repo_root/build/coreutils-$release_version-sort-scope"

if test "$(uname -s)" = Darwin; then
  # The manifest freezes the documented GNU/Linux GCC configuration. Apple's
  # `gcc` is Clang and activates a different conditional gnulib source set, so
  # do not pretend a Darwin configuration is the provenance of that scope.
  PYTHONPATH="$repo_root" python3 "$script_dir/derive_coreutils_sort_scope.py" \
    --source-tree "$source_tree" \
    --verify-manifest "$manifest" \
    --verify-frozen-files-only \
    --summary
else
  mkdir -p "$build_dir"
  (
    cd "$build_dir"
    CC='gcc -std=gnu17' "$source_tree/configure" \
      --disable-nls --without-selinux
  )

  PYTHONPATH="$repo_root" python3 "$script_dir/derive_coreutils_sort_scope.py" \
    --source-tree "$source_tree" \
    --makefile "$build_dir/Makefile" \
    --verify-manifest "$manifest" \
    --summary
fi
