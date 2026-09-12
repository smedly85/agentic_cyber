#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
sources_dir="$script_dir/sources"
manifest="$script_dir/source_manifest.json"

identity=$(
  PYTHONPATH="$repo_root" python3 -c \
    'import sys
from pathlib import Path
from security.historical.analysis import load_source_manifest
entries = load_source_manifest(Path(sys.argv[1]))
matches = [entry for entry in entries
           if entry.get("source_provenance") == "downstream_patch"
           and isinstance(entry.get("programs", {}).get("sort"), dict)]
if len(matches) != 1:
    raise SystemExit("manifest must contain exactly one downstream sort identity")
entry = matches[0]
downstream = entry["downstream_source"]
source_tree = Path(sys.argv[1]).parent / entry["source_tree"]
print(entry["upstream_base_version"], entry["source_revision"],
      entry["affected_version"], entry["downstream_revision"],
      downstream["source_package"],
      source_tree, entry["source_tree_sha256"],
      downstream["packaging_repository"], downstream["spec_file"],
      downstream["spec_sha256"], downstream["security_patch_file"],
      downstream["security_patch_sha256"],
      downstream["security_patch_git_blob"],
      downstream["upstream_archive_sha256"],
      downstream["upstream_signature_sha256"], sep="\t")' \
    "$manifest"
)
IFS=$'\t' read -r base_version release_revision affected_version \
  packaging_revision source_package source_tree source_tree_sha256 packaging_repository \
  spec_file spec_sha256 security_patch_file security_patch_sha256 \
  security_patch_git_blob archive_sha256 signature_sha256 <<< "$identity"

archive="$sources_dir/coreutils-$base_version.tar.xz"
signature="$archive.sig"
upstream_git="$sources_dir/coreutils-upstream.git"
packaging_git="$sources_dir/fedora-coreutils-packaging.git"
correspondence_files=(src/sort.c src/local.mk lib/local.mk Makefile.am configure.ac)

printf 'network=required_for_savannah_tag_gnu_archive_and_fedora_packaging\n'
tag_refs=$(git ls-remote https://git.savannah.gnu.org/git/coreutils.git \
  "refs/tags/v$base_version" "refs/tags/v$base_version^{}")
tag_object=$(printf '%s\n' "$tag_refs" | awk '$2 !~ /\^\{\}$/ { print $1 }')
resolved_revision=$(printf '%s\n' "$tag_refs" | awk '$2 ~ /\^\{\}$/ { print $1 }')
if ! printf '%s\n' "$tag_object" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "v$base_version is not exposed as an annotated Savannah tag" >&2
  exit 1
fi
if test "$resolved_revision" != "$release_revision"; then
  echo "v$base_version resolved to '$resolved_revision', expected '$release_revision'" >&2
  exit 1
fi

mkdir -p "$sources_dir"
if ! test -f "$archive"; then
  curl --fail --location --output "$archive" \
    "https://ftp.gnu.org/gnu/coreutils/coreutils-$base_version.tar.xz"
fi
if ! test -f "$signature"; then
  curl --fail --location --output "$signature" \
    "https://ftp.gnu.org/gnu/coreutils/coreutils-$base_version.tar.xz.sig"
fi
observed_archive_sha256=$(python3 -c \
  'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' \
  "$archive")
observed_signature_sha256=$(python3 -c \
  'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' \
  "$signature")
if test "$observed_archive_sha256" != "$archive_sha256"; then
  echo "archive checksum mismatch: $observed_archive_sha256" >&2
  exit 1
fi
if test "$observed_signature_sha256" != "$signature_sha256"; then
  echo "signature-file checksum mismatch: $observed_signature_sha256" >&2
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

if ! test -d "$upstream_git"; then
  git init --bare "$upstream_git"
fi
if git --git-dir="$upstream_git" config --get remote.origin.url >/dev/null 2>&1; then
  git --git-dir="$upstream_git" remote set-url origin \
    https://git.savannah.gnu.org/git/coreutils.git
else
  git --git-dir="$upstream_git" remote add origin \
    https://git.savannah.gnu.org/git/coreutils.git
fi
git --git-dir="$upstream_git" fetch --force --no-tags origin \
  "refs/tags/v$base_version:refs/tags/v$base_version"
cached_revision=$(git --git-dir="$upstream_git" rev-parse --verify \
  "refs/tags/v$base_version^{}")
if test "$cached_revision" != "$release_revision"; then
  echo "cached Savannah tag peel mismatch: $cached_revision" >&2
  exit 1
fi
for relative_file in "${correspondence_files[@]}"; do
  release_blob=$(tar -xOf "$archive" \
    "coreutils-$base_version/$relative_file" | git hash-object --stdin)
  upstream_blob=$(git --git-dir="$upstream_git" rev-parse --verify \
    "$release_revision:$relative_file")
  if test "$release_blob" != "$upstream_blob"; then
    echo "release/Git blob mismatch for $relative_file" >&2
    exit 1
  fi
done

if ! test -d "$packaging_git"; then
  git init --bare "$packaging_git"
fi
if git --git-dir="$packaging_git" config --get remote.origin.url >/dev/null 2>&1; then
  git --git-dir="$packaging_git" remote set-url origin "$packaging_repository"
else
  git --git-dir="$packaging_git" remote add origin "$packaging_repository"
fi
git --git-dir="$packaging_git" fetch --force --no-tags origin \
  refs/heads/f22:refs/remotes/origin/f22
git --git-dir="$packaging_git" cat-file -e "$packaging_revision^{commit}"
if ! git --git-dir="$packaging_git" merge-base --is-ancestor \
  "$packaging_revision" refs/remotes/origin/f22; then
  echo "frozen packaging revision is not in Fedora's f22 history" >&2
  exit 1
fi
observed_patch_blob=$(git --git-dir="$packaging_git" rev-parse --verify \
  "$packaging_revision:$security_patch_file")
if test "$observed_patch_blob" != "$security_patch_git_blob"; then
  echo "security patch Git blob mismatch: $observed_patch_blob" >&2
  exit 1
fi

temp_dir=$(mktemp -d "$sources_dir/.coreutils-fedora.XXXXXX")
trap 'rm -rf "$temp_dir"' EXIT HUP INT TERM
package_checkout="$temp_dir/package"
mkdir -p "$package_checkout"
git --git-dir="$packaging_git" archive "$packaging_revision" |
  tar -xf - -C "$package_checkout"
PYTHONPATH="$repo_root" python3 -c \
  'import json,sys
from pathlib import Path
from security.historical.downstream import verify_packaging_components
metadata={"spec_file":sys.argv[2],"spec_sha256":sys.argv[3],
          "security_patch_file":sys.argv[4],"security_patch_sha256":sys.argv[5]}
verify_packaging_components(Path(sys.argv[1]), metadata)' \
  "$package_checkout" "$spec_file" "$spec_sha256" \
  "$security_patch_file" "$security_patch_sha256"

patch_sequence=$(PYTHONPATH="$repo_root" python3 -c \
  'import sys
from pathlib import Path
from security.historical.downstream import rpm_patch_sequence
for application in rpm_patch_sequence(Path(sys.argv[1]).read_text()):
    print(f"{application.strip_level}\t{application.path}")' \
  "$package_checkout/$spec_file")
if ! printf '%s\n' "$patch_sequence" | cut -f2 | grep -Fxq "$security_patch_file"; then
  echo "verified packaging spec does not apply $security_patch_file" >&2
  exit 1
fi

if ! test -d "$source_tree"; then
  tar -xf "$archive" -C "$temp_dir"
  working_tree="$temp_dir/coreutils-$base_version"
  while IFS=$'\t' read -r strip_level patch_file; do
    case "$patch_file" in
      ''|/*|*'..'*|*'\\'*) echo "unsafe RPM patch path: $patch_file" >&2; exit 1 ;;
    esac
    case "$strip_level" in
      ''|*[!0-9]*) echo "unsafe RPM patch strip level: $strip_level" >&2; exit 1 ;;
    esac
    if ! test -f "$package_checkout/$patch_file"; then
      echo "RPM patch component is missing: $patch_file" >&2
      exit 1
    fi
    patch --directory "$working_tree" --batch --forward "-p$strip_level" \
      < "$package_checkout/$patch_file"
  done <<< "$patch_sequence"
  mv "$working_tree" "$source_tree"
fi

observed_tree_sha256=$(PYTHONPATH="$repo_root" python3 -c \
  'import sys; from pathlib import Path; from security.historical.analysis import verify_source_tree_sha256; print(verify_source_tree_sha256(Path(sys.argv[1]), sys.argv[2]))' \
  "$source_tree" "$source_tree_sha256")

printf 'source_revision=%s\ndownstream_revision=%s\nsource_package_identity=%s\nsrpm_authentication_status=%s\nsource_state_status=%s\narchive_sha256=%s\nsignature_status=%s\nrelease_git_correspondence=%s\nrelease_git_correspondence_files=%s\nsecurity_patch_sha256=%s\nsource_tree_sha256=%s\nsource_tree=%s\n' \
  "$release_revision" "$packaging_revision" "$source_package" \
  not_downloaded_or_authenticated \
  reconstructed_from_verified_gnu_source_and_frozen_fedora_dist_git \
  "$observed_archive_sha256" "$signature_status" verified \
  "${correspondence_files[*]}" "$security_patch_sha256" \
  "$observed_tree_sha256" "$source_tree"
