#!/usr/bin/env bash
# Build the rust_llvm_svf_v1 *sensitivity* SVF instrument in a separate tree.
#
# The canonical C instrument (build/semantic-toolchain/SVF) is only read here:
# its pinned commit is exported with `git archive`, and its Z3 package is used
# as a read-only dependency.  The helper links libSvfCore/libSvfLLVM
# dynamically, so rebuilding inside the canonical tree would silently change C
# behaviour while the helper's own SHA-256 stayed the same.  Never do that.
#
# The two patches are a sensitivity configuration, not the primary method:
#   svf-byte-offset.patch      constant i8-GEP byte offsets -> SVF fields
#                              (restored verbatim from the deleted
#                              rust_audit_v2, commit b7484fa0^)
#   svf-rust-vcall-gate.patch  do not apply the Itanium C++ vcall heuristic
#                              to Rust compile units
#
# Usage (from the repository root, Linux/WSL):
#   bash security/semantic_callgraph/rust_llvm_svf_v1/sensitivity_svf/build_sensitivity_svf.sh
#   RUST_LLVM_SVF_SENSITIVITY_ROOT=build/rust-llvm-svf-v1/svf-byte-offset-only \
#     SVF_PATCHES=svf-byte-offset.patch bash .../build_sensitivity_svf.sh
#   RUST_LLVM_SVF_SENSITIVITY_ROOT=build/rust-llvm-svf-v1/svf-vcall-gate-only \
#     SVF_PATCHES=svf-rust-vcall-gate.patch bash .../build_sensitivity_svf.sh
set -euo pipefail

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../../.." && pwd)
canonical="$repo_root/build/semantic-toolchain/SVF"
venv="$repo_root/build/semantic-toolchain/venv"
commit=67efb7745ce47b2b6853fd5696fc22c83d701e6c
here="$repo_root/security/semantic_callgraph/rust_llvm_svf_v1/sensitivity_svf"
dest="${RUST_LLVM_SVF_SENSITIVITY_ROOT:-build/rust-llvm-svf-v1/svf-sensitivity}"
case "$dest" in /*) ;; *) dest="$repo_root/$dest" ;; esac
jobs=${SVF_BUILD_JOBS:-8}

if [[ "$(git -C "$canonical" rev-parse HEAD)" != "$commit" ]]; then
  echo "canonical SVF checkout is not at $commit" >&2
  exit 1
fi
if [[ -e "$dest/SVF" ]]; then
  echo "refusing to reuse existing $dest/SVF; choose a fresh RUST_LLVM_SVF_SENSITIVITY_ROOT" >&2
  exit 1
fi

mkdir -p "$dest/SVF"
git -C "$canonical" archive "$commit" | tar -x -C "$dest/SVF"
helper_dir="$dest/SVF/svf-llvm/tools/SemanticCallGraph"
mkdir -p "$helper_dir"
# The structured helper source is byte-identical to the C instrument's helper.
cp "$repo_root/security/semantic_callgraph/native/semantic_callgraph_svf.cpp" "$helper_dir/"
cp "$repo_root/security/semantic_callgraph/native/CMakeLists.txt" "$helper_dir/"
printf '\nadd_subdirectory(SemanticCallGraph)\n' >> "$dest/SVF/svf-llvm/tools/CMakeLists.txt"
# GNU patch, not `git apply`: the export lives inside this repository's work
# tree, where `git apply` would resolve paths against the outer repository.
# SVF_PATCHES selects a subset for single-patch attribution builds
# (diagnostic configurations S-bo and S-vg); the default is both patches.
patches=${SVF_PATCHES:-"svf-byte-offset.patch svf-rust-vcall-gate.patch"}
for name in $patches; do
  patch -d "$dest/SVF" -p1 --forward --batch < "$here/$name"
done

# SVF's top-level CMakeLists links compile_commands.json into cmake's current
# directory, so configure from inside the export rather than the repo root.
cd "$dest/SVF"
PATH="$venv/bin:$PATH" LLVM_DIR=/usr/lib/llvm-21 Z3_DIR="$canonical/z3.obj" \
  cmake -D CMAKE_BUILD_TYPE:STRING=Release -DSVF_ENABLE_ASSERTIONS:BOOL=true \
    -DBUILD_SHARED_LIBS=ON -S "$dest/SVF" -B "$dest/SVF/Release-build"
PATH="$venv/bin:$PATH" LLVM_DIR=/usr/lib/llvm-21 Z3_DIR="$canonical/z3.obj" \
  cmake --build "$dest/SVF/Release-build" -j "$jobs" --target semantic-callgraph-svf

helper="$dest/SVF/Release-build/bin/semantic-callgraph-svf"
test -x "$helper"
sha256sum "$helper" "$dest/SVF/Release-build/lib/libSvfCore.so."*.* \
  "$dest/SVF/Release-build/lib/libSvfLLVM.so."*.* "$dest/SVF/Release-build/lib/extapi.bc"
printf 'patches: %s\n' "$patches"
