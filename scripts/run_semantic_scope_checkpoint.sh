#!/usr/bin/env bash
# Reproduce the Coreutils 9.7 link-closure sensitivity experiment, not v2.
set -euo pipefail
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
run_root=$(mktemp -d /tmp/agentic-scope-checkpoint.XXXXXX)
case "$run_root" in
  /tmp/agentic-scope-checkpoint.*) ;;
  *) echo "unexpected temporary path: $run_root" >&2; exit 1 ;;
esac
cleanup() { rm -rf -- "$run_root"; }
trap cleanup EXIT
ln -s "$repo_root" "$run_root/repo"
cd "$run_root/repo"
export PYTHONPATH=.
python3 -c 'from pathlib import Path; from security.historical.analysis import load_source_manifest, verify_source_tree_sha256; e=next(e for e in load_source_manifest(Path("security/historical/source_manifest.json")) if e["affected_version"] == "9.7"); verify_source_tree_sha256(Path(e["resolved_source_tree"]), e["source_tree_sha256"])'
mkdir -p build/coreutils-9.7-sort-scope build/semantic-scope-checkpoint
(
  cd build/coreutils-9.7-sort-scope
  CC='gcc -std=gnu17' "$run_root/repo/security/historical/sources/coreutils-9.7/configure" --disable-nls --without-selinux
) > build/semantic-scope-checkpoint/configure.log 2>&1
python3 -c 'from pathlib import Path; from security.historical.semantic_validation import _prepare_configured_built_sources; _prepare_configured_built_sources(source_root=Path("security/historical/sources/coreutils-9.7").resolve(), build_root=Path("build/coreutils-9.7-sort-scope").resolve(), output_root=Path("build/semantic-scope-checkpoint").resolve())'
# Retain configured LDFLAGS and program AM_LDFLAGS (--as-needed).
configured_ldflags=$(python3 -c 'from pathlib import Path; from security.historical.semantic_validation import _configured_make_variable; print(" ".join(_configured_make_variable(Path("build/coreutils-9.7-sort-scope").resolve(), "LDFLAGS")))')
{
  make -C build/coreutils-9.7-sort-scope -j2 V=1 src/sort \
    "LDFLAGS=$configured_ldflags -Wl,-Map=sort-linker-exact.map"
  # Only after all real objects exist: force map-producing relink when an
  # executable from a previous build was already up to date.
  make -C build/coreutils-9.7-sort-scope -W src/sort.o V=1 src/sort \
    "LDFLAGS=$configured_ldflags -Wl,-Map=sort-linker-exact.map"
} > build/semantic-scope-checkpoint/native-link.log 2>&1
python3 -m security.historical.scope_checkpoint \
  --output-dir build/semantic-scope-checkpoint "$@"
