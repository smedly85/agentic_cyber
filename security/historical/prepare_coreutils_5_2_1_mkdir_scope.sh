#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
manifest="$script_dir/source_manifest.json"

bash "$script_dir/prepare_coreutils_5_2_1.sh"

identity=$(
  PYTHONPATH="$repo_root" python3 -c \
    'import sys
from pathlib import Path
from security.historical.analysis import load_source_manifest
entries = load_source_manifest(Path(sys.argv[1]))
matches = [entry for entry in entries
           if entry.get("upstream_project") == "gnu-coreutils"
           and isinstance(entry.get("programs", {}).get("mkdir"), dict)]
if len(matches) != 1:
    raise SystemExit("manifest must contain exactly one GNU Coreutils mkdir identity")
entry = matches[0]
source_tree = Path(sys.argv[1]).parent / entry["source_tree"]
print(entry["affected_version"], source_tree, sep="\t")' \
    "$manifest"
)
IFS=$'\t' read -r release_version source_tree <<< "$identity"
build_dir="$repo_root/build/coreutils-$release_version-mkdir-scope"

if test "$(uname -s)" = Darwin; then
  # The manifest freezes an x86-64 GNU/Linux/GCC/GNU-ld closure.  Darwin can
  # authenticate the release and its paths, but cannot reproduce that link.
  PYTHONPATH="$repo_root" python3 "$script_dir/derive_coreutils_mkdir_scope.py" \
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
    # -fcommon restores GCC's pre-10 tentative-definition behavior; gnu89 is
    # the language mode expected by this 2004 release.
    CC='gcc -std=gnu89 -fcommon' "$configure_script" --disable-nls
  )
  make -C "$build_dir/lib" -j2
  make -C "$build_dir/src" localedir.h
  if test -f "$build_dir/src/mkdir.o"; then
    touch "$build_dir/src/mkdir.o"
  fi
  make -C "$build_dir/src" mkdir LDFLAGS='-Wl,-Map=mkdir.map'

  PYTHONPATH="$repo_root" python3 "$script_dir/derive_coreutils_mkdir_scope.py" \
    --source-tree "$source_tree" \
    --src-makefile "$build_dir/src/Makefile" \
    --lib-makefile "$build_dir/lib/Makefile" \
    --link-map "$build_dir/src/mkdir.map" \
    --verify-manifest "$manifest" \
    --summary
fi
