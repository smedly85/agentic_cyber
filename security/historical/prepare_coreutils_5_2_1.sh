#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
sources_dir="$script_dir/sources"
manifest="$script_dir/source_manifest.json"

# Frozen after verifying the official GNU archive with its detached signature.
archive_sha256=4eb124e9979a3ab1aaac2fbc7c3c55666b6530d2e3157dc0618782908cb2af1e
# Published in GNU's signed Coreutils 5.2.1 release announcement.
published_archive_sha1=1028755ae0fa9be840576e4837004cf5a9981c45

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
print(entry["affected_version"], entry["source_revision"],
      source_tree, entry["source_tree_sha256"], sep="\t")' \
    "$manifest"
)
IFS=$'\t' read -r release_version release_revision source_tree source_tree_sha256 \
  <<< "$identity"
archive="$sources_dir/coreutils-$release_version.tar.bz2"
signature="$archive.sig"

tag_refs=$(
  git ls-remote https://git.savannah.gnu.org/git/coreutils.git \
    "refs/tags/v$release_version" "refs/tags/v$release_version^{}"
)
tag_object=$(printf '%s\n' "$tag_refs" | awk '$2 !~ /\^\{\}$/ { print $1 }')
resolved_revision=$(printf '%s\n' "$tag_refs" | awk '$2 ~ /\^\{\}$/ { print $1 }')
if ! printf '%s\n' "$tag_object" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "v$release_version is not exposed as an annotated upstream tag" >&2
  exit 1
fi
if test "$resolved_revision" != "$release_revision"; then
  echo "v$release_version resolved to '$resolved_revision', expected '$release_revision'" >&2
  exit 1
fi

mkdir -p "$sources_dir"
if ! test -f "$archive"; then
  curl --fail --location --output "$archive" \
    "https://ftp.gnu.org/gnu/coreutils/coreutils-$release_version.tar.bz2"
fi
if ! test -f "$signature"; then
  curl --fail --location --output "$signature" \
    "https://ftp.gnu.org/gnu/coreutils/coreutils-$release_version.tar.bz2.sig"
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
observed_archive_sha1=$(
  python3 -c \
    'import hashlib, sys
digest = hashlib.sha1()
with open(sys.argv[1], "rb") as source:
    for block in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(block)
print(digest.hexdigest())' \
    "$archive"
)
if test "$observed_archive_sha1" != "$published_archive_sha1"; then
  echo "published archive SHA-1 mismatch: observed $observed_archive_sha1, expected $published_archive_sha1" >&2
  exit 1
fi

signature_status=not_checked_gpgv_unavailable
if command -v gpgv >/dev/null 2>&1; then
  gnu_keyring="$sources_dir/gnu-keyring.gpg"
  if ! test -f "$gnu_keyring"; then
    curl --fail --location --output "$gnu_keyring" \
      https://ftp.gnu.org/gnu/gnu-keyring.gpg
  fi
  gpgv --keyring "$gnu_keyring" "$signature" "$archive"
  signature_status=verified_with_gnu_keyring
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

printf 'source_revision=%s\narchive_sha256=%s\narchive_sha1=%s\nsignature_status=%s\nsource_tree_sha256=%s\nsource_tree=%s\n' \
  "$release_revision" "$observed_archive_sha256" "$observed_archive_sha1" "$signature_status" \
  "$observed_tree_sha256" "$source_tree"
