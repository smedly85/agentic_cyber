#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
sources_dir="$script_dir/sources"
manifest="$script_dir/source_manifest.json"

archive_sha256=e8bb26ad0293f9b5a1fc43fb42ba970e312c66ce92c1b0b16713d7500db251bf

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
print(entry["affected_version"], entry["source_revision"],
      source_tree, entry["source_tree_sha256"], sep="\t")' \
    "$manifest"
)
IFS=$'\t' read -r release_version release_revision source_tree source_tree_sha256 \
  <<< "$identity"
archive="$sources_dir/coreutils-$release_version.tar.xz"

resolved_revision=$(
  git ls-remote https://git.savannah.gnu.org/git/coreutils.git \
    "refs/tags/v$release_version^{}" |
    awk 'NR == 1 { print $1 }'
)
if test "$resolved_revision" != "$release_revision"; then
  echo "v$release_version resolved to '$resolved_revision', expected '$release_revision'" >&2
  exit 1
fi

mkdir -p "$sources_dir"
if ! test -f "$archive"; then
  curl --fail --location --output "$archive" \
    "https://ftp.gnu.org/gnu/coreutils/coreutils-$release_version.tar.xz"
fi
observed_archive_sha256=$(
  python3 -c \
    'import hashlib, sys
digest = hashlib.sha256()
with open(sys.argv[1], "rb") as source:
    for block in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(block)
print(digest.hexdigest())' \
    "$archive"
)
if test "$observed_archive_sha256" != "$archive_sha256"; then
  echo "archive checksum mismatch: observed $observed_archive_sha256, expected $archive_sha256" >&2
  exit 1
fi

if ! test -d "$source_tree"; then
  tar -xf "$archive" -C "$sources_dir"
fi

observed_tree_sha256=$(
  PYTHONPATH="$repo_root" python3 -c \
    'import sys; from pathlib import Path; from security.historical.analysis import source_tree_sha256; print(source_tree_sha256(Path(sys.argv[1])))' \
    "$source_tree"
)
if test "$observed_tree_sha256" != "$source_tree_sha256"; then
  echo "source-tree fingerprint mismatch: $observed_tree_sha256" >&2
  exit 1
fi

printf 'source_revision=%s\nsource_tree_sha256=%s\nsource_tree=%s\n' \
  "$release_revision" "$observed_tree_sha256" "$source_tree"
