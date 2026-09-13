#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
manifest="$script_dir/source_manifest.json"

bash "$script_dir/prepare_coreutils_8_17_fedora.sh"
identity=$(
  PYTHONPATH="$repo_root" python3 -c \
    'import sys
from pathlib import Path
from security.historical.analysis import load_source_manifest
matches=[item for item in load_source_manifest(Path(sys.argv[1]))
         if item.get("affected_version")=="8.17-7.fc18"
         and item.get("source_provenance")=="downstream_patch"]
if len(matches)!=1: raise SystemExit("manifest must contain the Fedora 18 identity")
item=matches[0]
print(item["upstream_base_version"], Path(sys.argv[1]).parent/item["source_tree"],
      item["source_tree_sha256"], sep="\t")' \
    "$manifest"
)
IFS=$'\t' read -r base_version source_tree source_tree_sha256 <<< "$identity"
build_dir="$repo_root/build/coreutils-$base_version-fedora-sort-scope-portable"

test ! -e "$source_tree/config.hin" || {
  echo "unexpected top-level config.hin in the frozen Coreutils 8.17 tree" >&2
  exit 1
}

if test "$(uname -s)" = Darwin; then
  PYTHONPATH="$repo_root" python3 "$script_dir/derive_coreutils_8_17_sort_scope.py" \
    --source-tree "$source_tree" --verify-manifest "$manifest" \
    --verify-frozen-files-only --summary
  exit 0
fi

mkdir -p "$build_dir"
if ! test -f "$build_dir/Makefile"; then
  for timestamp_input in "$source_tree/aclocal.m4" "$source_tree/configure" \
    "$source_tree/Makefile.in" "$source_tree"/*/Makefile.in \
    "$source_tree/lib/config.hin"; do
    if test -e "$timestamp_input"; then
      touch "$timestamp_input"
    fi
  done
  source_tree_from_build=$(python3 -c \
    'import os,sys; print(os.path.relpath(sys.argv[1],sys.argv[2]))' \
    "$source_tree" "$build_dir")
  (
    cd "$build_dir"
    FORCE_UNSAFE_CONFIGURE=1 "$source_tree_from_build/configure" \
      --disable-nls --without-selinux --without-gmp --enable-largefile \
      --enable-install-program=hostname,arch --with-tty-group \
      DEFAULT_POSIX2_VERSION=200112 alternative=199209
  )
fi

compat_cppflags='-D_IO_ftrylockfile=1 -D_IO_IN_BACKUP=0x100'
compat_cflags='-g -O2 -Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types -Wno-error=int-conversion'
make -C "$build_dir/lib" -j2 MAKEINFO=true CPPFLAGS="$compat_cppflags" \
  CFLAGS="$compat_cflags" all
make -C "$build_dir/src" MAKEINFO=true CPPFLAGS="$compat_cppflags" \
  CFLAGS="$compat_cflags" version.h
make -C "$build_dir/src" -j2 MAKEINFO=true CPPFLAGS="$compat_cppflags" \
  CFLAGS="$compat_cflags" sort
touch "$build_dir/src/sort.o"
make -C "$build_dir/src" MAKEINFO=true CPPFLAGS="$compat_cppflags" \
  CFLAGS="$compat_cflags" LDFLAGS='-Wl,-Map=../sort.map' sort

grep -Eq '^#define HAVE_MBRTOWC 1$' "$build_dir/lib/config.h" || {
  echo "configured build does not activate HAVE_MBRTOWC" >&2; exit 1; }
test ! -e "$source_tree/config.hin" || {
  echo "build preparation created a spurious top-level config.hin" >&2
  exit 1
}
post_build_source_tree_sha256=$(PYTHONPATH="$repo_root" python3 -c \
  'import sys; from pathlib import Path
from security.historical.analysis import verify_source_tree_sha256
print(verify_source_tree_sha256(Path(sys.argv[1]), sys.argv[2]))' \
  "$source_tree" "$source_tree_sha256")
printf 'post_build_source_tree_sha256=%s\n' "$post_build_source_tree_sha256"
PYTHONPATH="$repo_root" python3 "$script_dir/derive_coreutils_8_17_sort_scope.py" \
  --source-tree "$source_tree" --src-makefile "$build_dir/src/Makefile" \
  --lib-makefile "$build_dir/lib/Makefile" --link-map "$build_dir/sort.map" \
  --verify-manifest "$manifest" --summary
