#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
source_tree="$script_dir/sources/coreutils-9.7"
build_dir="$repo_root/build/coreutils-9.7-sort-scope"
manifest="$script_dir/source_manifest.json"

"$script_dir/prepare_coreutils_9_7.sh"

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
