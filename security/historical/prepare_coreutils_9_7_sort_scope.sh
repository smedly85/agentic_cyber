#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
source_tree="$script_dir/sources/coreutils-9.7"
build_dir="$repo_root/build/coreutils-9.7-sort-scope"
manifest="$script_dir/source_manifest.json"

bash "$script_dir/prepare_coreutils_9_7.sh"

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
  source_tree_from_build=$(
    python3 -c \
      'import os, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' \
      "$source_tree" "$build_dir"
  )
  (
    cd "$build_dir"
    CC='gcc -std=gnu17' "$source_tree_from_build/configure" \
      --disable-nls --without-selinux
  )

  PYTHONPATH="$repo_root" python3 "$script_dir/derive_coreutils_sort_scope.py" \
    --source-tree "$source_tree" \
    --makefile "$build_dir/Makefile" \
    --verify-manifest "$manifest" \
    --summary
fi
