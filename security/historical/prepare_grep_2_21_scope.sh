#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
manifest="$script_dir/source_manifest.json"

bash "$script_dir/prepare_grep_2_21.sh"

identity=$(
  PYTHONPATH="$repo_root" python3 -c \
    'import sys
from pathlib import Path
from security.historical.analysis import load_source_manifest
entries = load_source_manifest(Path(sys.argv[1]))
matches = [entry for entry in entries
           if entry.get("upstream_project") == "gnu-grep"
           and isinstance(entry.get("programs", {}).get("grep"), dict)]
if len(matches) != 1:
    raise SystemExit("manifest must contain exactly one GNU grep identity")
entry = matches[0]
source_tree = Path(sys.argv[1]).parent / entry["source_tree"]
print(entry["affected_version"], source_tree, sep="\t")' \
    "$manifest"
)
IFS=$'\t' read -r release_version source_tree <<< "$identity"
build_dir="$repo_root/build/grep-$release_version-scope"

if test "$(uname -s)" = Darwin; then
  # The manifest freezes a GNU/Linux/GCC/GNU-ld link closure.  A Darwin
  # configuration cannot re-establish that closure, so verify only the exact
  # frozen paths against the already authenticated release tree.
  PYTHONPATH="$repo_root" python3 "$script_dir/derive_grep_scope.py" \
    --source-tree "$source_tree" \
    --verify-manifest "$manifest" \
    --verify-frozen-files-only \
    --summary
else
  mkdir -p "$build_dir"
  configure_script=$(
    python3 -c \
      'import os, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' \
      "$source_tree/configure" "$build_dir"
  )
  (
    cd "$build_dir"
    # grep 2.21's configure rejects absolute srcdir values containing spaces.
    CC='gcc -std=gnu17' "$configure_script" --disable-nls
  )
  make -C "$build_dir" -j2
  touch "$build_dir/src/grep.o"
  make -C "$build_dir/src" grep LDFLAGS='-Wl,-Map=grep.map'

  PYTHONPATH="$repo_root" python3 "$script_dir/derive_grep_scope.py" \
    --source-tree "$source_tree" \
    --src-makefile "$build_dir/src/Makefile" \
    --lib-makefile "$build_dir/lib/Makefile" \
    --link-map "$build_dir/src/grep.map" \
    --verify-manifest "$manifest" \
    --summary
fi
