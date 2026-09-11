#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
sources_dir="$script_dir/sources"
manifest="$script_dir/source_manifest.json"
requested_version=2.10

# Frozen after authenticating grep-2.10.tar.xz with GNU's detached signature.
archive_sha256=6c796773f23bcd9bb751165bb9ce13a04d678e6d426ca59843e386f99dc77ab3

identity=$(
  PYTHONPATH="$repo_root" python3 -c \
    'import sys
from pathlib import Path
from security.historical.analysis import load_source_manifest
entries = load_source_manifest(Path(sys.argv[1]))
matches = [entry for entry in entries
           if entry.get("upstream_project") == "gnu-grep"
           and entry.get("affected_version") == sys.argv[2]
           and isinstance(entry.get("programs", {}).get("grep"), dict)]
if len(matches) != 1:
    raise SystemExit("manifest must contain exactly one requested GNU grep identity")
entry = matches[0]
source_tree = Path(sys.argv[1]).parent / entry["source_tree"]
print(entry["affected_version"], entry["source_revision"],
      source_tree, entry["source_tree_sha256"], sep="\t")' \
    "$manifest" "$requested_version"
)
IFS=$'\t' read -r release_version release_revision source_tree source_tree_sha256 \
  <<< "$identity"
archive="$sources_dir/grep-$release_version.tar.xz"
signature="$archive.sig"
upstream_git="$sources_dir/grep-upstream.git"
correspondence_files=(
  src/main.c
  src/dfa.c
  src/dfa.h
  src/dfasearch.c
  src/kwset.c
  src/kwset.h
  src/Makefile.am
  lib/Makefile.am
  configure.ac
)

printf 'upstream_git_network=required_for_tag_and_release_correspondence\n'
tag_refs=$(
  git ls-remote https://git.savannah.gnu.org/git/grep.git \
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
    "https://ftp.gnu.org/gnu/grep/grep-$release_version.tar.xz"
fi
if ! test -f "$signature"; then
  curl --fail --location --output "$signature" \
    "https://ftp.gnu.org/gnu/grep/grep-$release_version.tar.xz.sig"
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
    'import sys; from pathlib import Path; from security.historical.analysis import verify_source_tree_sha256; print(verify_source_tree_sha256(Path(sys.argv[1]), sys.argv[2]))' \
    "$source_tree" "$source_tree_sha256"
)
if test "$observed_tree_sha256" != "$source_tree_sha256"; then
  echo "source-tree fingerprint mismatch: $observed_tree_sha256" >&2
  exit 1
fi

if ! test -d "$upstream_git"; then
  git init --bare "$upstream_git"
fi
if git --git-dir="$upstream_git" config --get remote.origin.url >/dev/null 2>&1; then
  git --git-dir="$upstream_git" remote set-url origin \
    https://git.savannah.gnu.org/git/grep.git
else
  git --git-dir="$upstream_git" remote add origin \
    https://git.savannah.gnu.org/git/grep.git
fi
git --git-dir="$upstream_git" fetch --force --no-tags origin \
  "refs/tags/v$release_version:refs/tags/v$release_version"
cached_revision=$(git --git-dir="$upstream_git" rev-parse --verify \
  "refs/tags/v$release_version^{}")
if test "$cached_revision" != "$release_revision"; then
  echo "cached v$release_version resolved to '$cached_revision', expected '$release_revision'" >&2
  exit 1
fi
for relative_file in "${correspondence_files[@]}"; do
  release_file="$source_tree/$relative_file"
  if ! test -f "$release_file"; then
    echo "release/Git correspondence file is missing: $relative_file" >&2
    exit 1
  fi
  release_blob=$(git hash-object "$release_file")
  upstream_blob=$(git --git-dir="$upstream_git" rev-parse --verify \
    "$release_revision:$relative_file")
  if test "$release_blob" != "$upstream_blob"; then
    echo "release/Git blob mismatch for $relative_file: release $release_blob, upstream $upstream_blob" >&2
    exit 1
  fi
done

printf 'source_revision=%s\narchive_sha256=%s\nsignature_status=%s\nsource_tree_sha256=%s\nrelease_git_correspondence=%s\nrelease_git_correspondence_files=%s\nsource_tree=%s\n' \
  "$release_revision" "$observed_archive_sha256" "$signature_status" \
  "$observed_tree_sha256" verified "${correspondence_files[*]}" "$source_tree"
