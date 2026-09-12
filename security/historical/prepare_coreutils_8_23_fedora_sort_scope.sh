#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
manifest="$script_dir/source_manifest.json"

bash "$script_dir/prepare_coreutils_8_23_fedora.sh"

identity=$(
  PYTHONPATH="$repo_root" python3 -c \
    'import sys
from pathlib import Path
from security.historical.analysis import load_source_manifest
entries=load_source_manifest(Path(sys.argv[1]))
matches=[entry for entry in entries
         if entry.get("source_provenance") == "downstream_patch"
         and isinstance(entry.get("programs", {}).get("sort"), dict)]
if len(matches) != 1:
    raise SystemExit("manifest must contain exactly one downstream sort identity")
entry=matches[0]
print(entry["upstream_base_version"], entry["affected_version"],
      Path(sys.argv[1]).parent / entry["source_tree"], sep="\t")' \
    "$manifest"
)
IFS=$'\t' read -r base_version affected_version source_tree <<< "$identity"
build_dir="$repo_root/build/coreutils-$base_version-fedora-sort-scope-portable"

if test "$(uname -s)" = Darwin; then
  PYTHONPATH="$repo_root" python3 \
    "$script_dir/derive_coreutils_8_23_sort_scope.py" \
    --source-tree "$source_tree" --verify-manifest "$manifest" \
    --verify-frozen-files-only --summary
  exit 0
fi

mkdir -p "$build_dir"
if ! test -f "$build_dir/Makefile"; then
  # Match Fedora's generated-file timestamp stabilization.  This changes no
  # analyzed file content and prevents unavailable historical Autotools
  # versions from being invoked merely because a patch updated an m4 input.
  touch "$source_tree/aclocal.m4" "$source_tree/configure" \
    "$source_tree/config.hin" "$source_tree/Makefile.in" \
    "$source_tree"/*/Makefile.in "$source_tree/lib/config.hin"
  # This Automake vintage rejects an absolute srcdir containing spaces.  A
  # relative path from the build directory is stable and still names the same
  # authenticated tree (important for Vessel workspaces mounted below paths
  # such as "UofA School").
  source_tree_from_build=$(python3 -c \
    'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' \
    "$source_tree" "$build_dir")
  (
    cd "$build_dir"
    FORCE_UNSAFE_CONFIGURE=1 "$source_tree_from_build/configure" \
      --disable-nls --without-selinux --without-openssl --without-gmp \
      --enable-largefile --enable-install-program=hostname,arch \
      --with-tty-group DEFAULT_POSIX2_VERSION=200112 alternative=199209
  )
  touch "$build_dir/config.status" "$build_dir/Makefile"
fi

compat_cppflags='-D_IO_ftrylockfile=1 -D_IO_IN_BACKUP=0x100'
compat_cflags='-g -O2 -Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types -Wno-error=int-conversion'
if ! test -f "$build_dir/lib/configmake.h" || ! test -f "$build_dir/src/version.h"; then
  make -C "$build_dir" MAKEINFO=true CPPFLAGS="$compat_cppflags" \
    CFLAGS="$compat_cflags" lib/configmake.h src/version.h
fi
make -C "$build_dir" -j2 MAKEINFO=true CPPFLAGS="$compat_cppflags" \
  CFLAGS="$compat_cflags" src/sort
touch "$build_dir/src/sort.o"
make -C "$build_dir" MAKEINFO=true CPPFLAGS="$compat_cppflags" \
  CFLAGS="$compat_cflags" LDFLAGS='-Wl,-Map=sort.map' src/sort

PYTHONPATH="$repo_root" python3 \
  "$script_dir/derive_coreutils_8_23_sort_scope.py" \
  --source-tree "$source_tree" --makefile "$build_dir/Makefile" \
  --link-map "$build_dir/sort.map" --verify-manifest "$manifest" --summary
