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
entries=load_source_manifest(Path(sys.argv[1]))
matches=[item for item in entries if item.get("affected_version")=="8.17-7.fc18"
         and item.get("source_provenance")=="downstream_patch"
         and isinstance(item.get("programs",{}).get("sort"),dict)]
if len(matches)!=1: raise SystemExit("manifest must contain the Fedora 18 sort identity")
item=matches[0]; downstream=item["downstream_source"]
print(item["upstream_base_version"], item["source_revision"], item["affected_version"],
      item["downstream_revision"], downstream["source_package"],
      Path(sys.argv[1]).parent/item["source_tree"], item["source_tree_sha256"],
      downstream["packaging_repository"], downstream["spec_file"],
      downstream["spec_sha256"], downstream["security_patch_file"],
      downstream["security_patch_sha256"], downstream["security_patch_git_blob"],
      downstream["upstream_archive_sha256"], downstream["upstream_signature_sha256"], sep="\t")' \
    "$manifest"
)
IFS=$'\t' read -r base_version release_revision affected_version packaging_revision \
  source_package source_tree source_tree_sha256 packaging_repository spec_file \
  spec_sha256 security_patch_file security_patch_sha256 security_patch_git_blob \
  archive_sha256 signature_sha256 <<< "$identity"

fixed_revision=8def2175102337e5c315fa9c0dbe265a76358dda
fixed_version=8.17-8.fc18
fixed_spec_sha256=4ec56aab0d234f9145980cff42deeedcfbea09116f5c29bc8cf2200c934d6d39
fixed_patch_sha256=8e5e7759e1e175d9befa3d60916bbc5cf51fd4efb384a6929c28d739e1c85f5a
fixed_patch_blob=704941fd665209cff14143dae6b98d442a2cd9bc
fixed_tree="$sources_dir/coreutils-8.17-fedora-$fixed_version"
fixed_tree_sha256=02924049435335cd8dbb6d5210d4d3f2f81cc54706d87446ac3320fa186359af

archive="$sources_dir/coreutils-$base_version.tar.xz"
signature="$archive.sig"
upstream_git="$sources_dir/coreutils-upstream.git"
packaging_git="$sources_dir/fedora-coreutils-packaging.git"
correspondence_files=(src/sort.c src/Makefile.am lib/Makefile.am Makefile.am configure.ac)

printf 'network=required_for_savannah_tag_gnu_archive_and_fedora_packaging\n'
tag_refs=$(git ls-remote https://git.savannah.gnu.org/git/coreutils.git \
  "refs/tags/v$base_version" "refs/tags/v$base_version^{}")
tag_object=$(printf '%s\n' "$tag_refs" | awk '$2 !~ /\^\{\}$/ { print $1 }')
resolved_revision=$(printf '%s\n' "$tag_refs" | awk '$2 ~ /\^\{\}$/ { print $1 }')
if ! printf '%s\n' "$tag_object" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "v$base_version is not an annotated Savannah tag" >&2; exit 1
fi
if test "$resolved_revision" != "$release_revision"; then
  echo "Savannah tag peel mismatch: $resolved_revision" >&2; exit 1
fi

mkdir -p "$sources_dir"
test -f "$archive" || curl --fail --location --output "$archive" \
  "https://ftp.gnu.org/gnu/coreutils/coreutils-$base_version.tar.xz"
test -f "$signature" || curl --fail --location --output "$signature" \
  "https://ftp.gnu.org/gnu/coreutils/coreutils-$base_version.tar.xz.sig"
sha256() { python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }
observed_archive_sha256=$(sha256 "$archive")
observed_signature_sha256=$(sha256 "$signature")
test "$observed_archive_sha256" = "$archive_sha256" || { echo "archive checksum mismatch" >&2; exit 1; }
test "$observed_signature_sha256" = "$signature_sha256" || { echo "signature checksum mismatch" >&2; exit 1; }

signature_status=not_checked_gpgv_unavailable
if command -v gpgv >/dev/null 2>&1; then
  gnu_keyring="$sources_dir/gnu-keyring.gpg"
  test -f "$gnu_keyring" || curl --fail --location --output "$gnu_keyring" \
    https://ftp.gnu.org/gnu/gnu-keyring.gpg
  gpgv --keyring "$gnu_keyring" "$signature" "$archive"
  signature_status=verified_with_gnu_keyring
fi

test -d "$upstream_git" || git init --bare "$upstream_git"
if git --git-dir="$upstream_git" config --get remote.origin.url >/dev/null 2>&1; then
  git --git-dir="$upstream_git" remote set-url origin https://git.savannah.gnu.org/git/coreutils.git
else
  git --git-dir="$upstream_git" remote add origin https://git.savannah.gnu.org/git/coreutils.git
fi
git --git-dir="$upstream_git" fetch --force --no-tags origin \
  "refs/tags/v$base_version:refs/tags/v$base_version"
cached_revision=$(git --git-dir="$upstream_git" rev-parse --verify "refs/tags/v$base_version^{}")
test "$cached_revision" = "$release_revision" || { echo "cached tag mismatch" >&2; exit 1; }
for relative_file in "${correspondence_files[@]}"; do
  release_blob=$(tar -xOf "$archive" "coreutils-$base_version/$relative_file" | git hash-object --stdin)
  upstream_blob=$(git --git-dir="$upstream_git" rev-parse --verify "$release_revision:$relative_file")
  test "$release_blob" = "$upstream_blob" || { echo "release/Git mismatch: $relative_file" >&2; exit 1; }
done

test -d "$packaging_git" || git init --bare "$packaging_git"
if git --git-dir="$packaging_git" config --get remote.origin.url >/dev/null 2>&1; then
  git --git-dir="$packaging_git" remote set-url origin "$packaging_repository"
else
  git --git-dir="$packaging_git" remote add origin "$packaging_repository"
fi
git --git-dir="$packaging_git" fetch --force --no-tags origin refs/heads/f18:refs/remotes/origin/f18
for revision in "$packaging_revision" "$fixed_revision"; do
  git --git-dir="$packaging_git" cat-file -e "$revision^{commit}"
  git --git-dir="$packaging_git" merge-base --is-ancestor "$revision" refs/remotes/origin/f18 || {
    echo "packaging revision is outside Fedora f18 history: $revision" >&2; exit 1; }
done
test "$(git --git-dir="$packaging_git" rev-parse "$fixed_revision^")" = "$packaging_revision" || {
  echo "fixed Fedora revision is not the immediate child of the vulnerable revision" >&2; exit 1; }
test "$(git --git-dir="$packaging_git" rev-parse "$packaging_revision:$security_patch_file")" = "$security_patch_git_blob" || {
  echo "vulnerable patch blob mismatch" >&2; exit 1; }
test "$(git --git-dir="$packaging_git" rev-parse "$fixed_revision:$security_patch_file")" = "$fixed_patch_blob" || {
  echo "fixed patch blob mismatch" >&2; exit 1; }

temp_dir=$(mktemp -d "$sources_dir/.coreutils-fedora-8.17.XXXXXX")
trap 'rm -rf "$temp_dir"' EXIT HUP INT TERM
expected_sequence="$script_dir/coreutils_8_17_fedora_patch_sequence.tsv"

reconstruct() {
  revision=$1; output_tree=$2; expected_spec=$3; expected_patch=$4
  package_checkout="$temp_dir/package-$revision"
  mkdir -p "$package_checkout"
  git --git-dir="$packaging_git" archive "$revision" | tar -xf - -C "$package_checkout"
  observed_spec=$(sha256 "$package_checkout/$spec_file")
  observed_patch=$(sha256 "$package_checkout/$security_patch_file")
  test "$observed_spec" = "$expected_spec" || {
    echo "spec checksum mismatch at $revision: observed $observed_spec, expected $expected_spec" >&2; exit 1; }
  test "$observed_patch" = "$expected_patch" || {
    echo "patch checksum mismatch at $revision: observed $observed_patch, expected $expected_patch" >&2; exit 1; }
  sequence="$temp_dir/sequence-$revision"
  PYTHONPATH="$repo_root" python3 -c \
    'import sys
from pathlib import Path
from security.historical.downstream import rpm_patch_sequence
for item in rpm_patch_sequence(Path(sys.argv[1]).read_text()):
 print(f"{item.number}\t{item.strip_level}\t{item.path}")' \
    "$package_checkout/$spec_file" > "$sequence"
  cmp "$expected_sequence" "$sequence" || { echo "historical RPM patch sequence mismatch" >&2; exit 1; }
  if ! test -d "$output_tree"; then
    tar -xf "$archive" -C "$temp_dir"
    working_tree="$temp_dir/coreutils-$base_version"
    while IFS=$'\t' read -r number strip_level patch_file; do
      test -f "$package_checkout/$patch_file" || { echo "missing Patch$number: $patch_file" >&2; exit 1; }
      patch --directory "$working_tree" --batch --forward "-p$strip_level" < "$package_checkout/$patch_file"
    done < "$sequence"
    mv "$working_tree" "$output_tree"
  fi
}

reconstruct "$packaging_revision" "$source_tree" "$spec_sha256" "$security_patch_sha256"
reconstruct "$fixed_revision" "$fixed_tree" "$fixed_spec_sha256" "$fixed_patch_sha256"
observed_tree_sha256=$(PYTHONPATH="$repo_root" python3 -c \
  'import sys; from pathlib import Path; from security.historical.analysis import verify_source_tree_sha256; print(verify_source_tree_sha256(Path(sys.argv[1]),sys.argv[2]))' \
  "$source_tree" "$source_tree_sha256")
observed_fixed_tree_sha256=$(PYTHONPATH="$repo_root" python3 -c \
  'import sys; from pathlib import Path; from security.historical.analysis import verify_source_tree_sha256; print(verify_source_tree_sha256(Path(sys.argv[1]),sys.argv[2]))' \
  "$fixed_tree" "$fixed_tree_sha256")

printf 'source_revision=%s\ndownstream_revision=%s\nfixed_downstream_revision=%s\nsource_package_identity=%s\nfixed_source_package_identity=coreutils-%s.src.rpm\narchive_sha256=%s\nsignature_status=%s\nrelease_git_correspondence=verified\nrelease_git_correspondence_files=%s\npatch_sequence_status=verified_23_unconditional_p1_patches\nsecurity_patch_sha256=%s\nfixed_security_patch_sha256=%s\nsource_tree_sha256=%s\nfixed_source_tree_sha256=%s\nsource_tree=%s\nfixed_source_tree=%s\n' \
  "$release_revision" "$packaging_revision" "$fixed_revision" "$source_package" "$fixed_version" \
  "$observed_archive_sha256" "$signature_status" "${correspondence_files[*]}" \
  "$security_patch_sha256" "$fixed_patch_sha256" "$observed_tree_sha256" \
  "$observed_fixed_tree_sha256" "$source_tree" "$fixed_tree"
