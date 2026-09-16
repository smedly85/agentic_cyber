#!/usr/bin/env bash
# Build the pinned LLVM-21-compatible SVF and structured helper below build/.
# This script does not install or upgrade system packages.
set -euo pipefail

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tool_root="$repo_root/build/semantic-toolchain"
venv="$tool_root/venv"
svf="$tool_root/SVF"
svf_commit=67efb7745ce47b2b6853fd5696fc22c83d701e6c
llvm_dir=/usr/lib/llvm-21
build_jobs=${CMAKE_BUILD_PARALLEL_LEVEL:-${SVF_BUILD_JOBS:-4}}

python3 -m venv "$venv"
"$venv/bin/pip" install --disable-pip-version-check cmake==3.31.6 ninja==1.11.1.3
if [[ ! -d "$svf/.git" ]]; then
  git clone https://github.com/SVF-tools/SVF.git "$svf"
fi
git -C "$svf" fetch --depth 1 origin "$svf_commit"
git -C "$svf" checkout --detach "$svf_commit"

helper_dir="$svf/svf-llvm/tools/SemanticCallGraph"
mkdir -p "$helper_dir"
if [[ ! -f "$helper_dir/semantic_callgraph_svf.cpp" ]] ||
   ! cmp -s "$repo_root/security/semantic_callgraph/native/semantic_callgraph_svf.cpp" "$helper_dir/semantic_callgraph_svf.cpp"; then
  cp "$repo_root/security/semantic_callgraph/native/semantic_callgraph_svf.cpp" "$helper_dir/"
fi
if [[ ! -f "$helper_dir/CMakeLists.txt" ]] ||
   ! cmp -s "$repo_root/security/semantic_callgraph/native/CMakeLists.txt" "$helper_dir/CMakeLists.txt"; then
  cp "$repo_root/security/semantic_callgraph/native/CMakeLists.txt" "$helper_dir/"
fi
if ! grep -Fxq 'add_subdirectory(SemanticCallGraph)' "$svf/svf-llvm/tools/CMakeLists.txt"; then
  printf '\nadd_subdirectory(SemanticCallGraph)\n' >> "$svf/svf-llvm/tools/CMakeLists.txt"
fi

if [[ -f "$svf/Release-build/CMakeCache.txt" ]]; then
  # Upstream build.sh removes Release-build before configuring. Preserve a
  # successful local build and reconfigure injected-helper changes in place.
  PATH="$venv/bin:$PATH" LLVM_DIR="$llvm_dir" \
    cmake -S "$svf" -B "$svf/Release-build"
  PATH="$venv/bin:$PATH" LLVM_DIR="$llvm_dir" \
    cmake --build "$svf/Release-build" --parallel "$build_jobs"
else
  (
    cd "$svf"
    PATH="$venv/bin:$PATH" LLVM_DIR="$llvm_dir" SVF_BUILD_JOBS="$build_jobs" source ./build.sh
  )
fi

helper=$(find "$svf" -type f -name semantic-callgraph-svf -perm -u+x | head -n 1)
if [[ -z "$helper" ]]; then
  echo "semantic-callgraph-svf was not produced" >&2
  exit 1
fi
printf '%s\n' "$helper"
