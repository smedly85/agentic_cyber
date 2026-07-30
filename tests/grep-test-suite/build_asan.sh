#!/usr/bin/env bash
# Build the candidate from source with AddressSanitizer + UndefinedBehavior-
# Sanitizer, so `runner.py --sanitizer` can turn memory-safety bugs (buffer
# overflow, use-after-free, OOB read, integer UB) into hard failures instead of
# silent corruption.
#
# Everything comes from config.json's "paths" section:
#   cc                  compiler to invoke                (default: clang)
#   candidate_src       single C source file to compile   (REQUIRED)
#   cc_flags            extra compiler flags (list)       (optional)
#   candidate_asan_bin  where to write the output binary  (default: ./candidate_asan)
#
# If your candidate is not a single C source file, do not use this script:
# build your own ASan/UBSan binary however your toolchain supports it and point
# paths.candidate_asan_bin at it directly.
#
# The checkpoint wrapper (judge_candidate.sh) never calls this. Checkpoint
# judgment is the deterministic golden comparison only; a sanitizer pass is an
# extra, separate evaluation.
#
# Usage: ./build_asan.sh [config.json]
set -eu
cd "$(dirname "$0")"
CONFIG=${1:-config.json}

cfg() { python3 config.py "$CONFIG" "$@"; }

SRC=$(cfg paths.candidate_src --default "")
if [ -z "$SRC" ]; then
  echo "build_asan.sh: paths.candidate_src is empty in $CONFIG -- nothing to build." >&2
  echo "(If you build your own ASan binary, set paths.candidate_asan_bin instead.)" >&2
  exit 1
fi

CC=$(cfg paths.cc --default clang)
OUT=$(cfg paths.candidate_asan_bin --default ./candidate_asan)
FLAGS=$(cfg paths.cc_flags --join " " --default "-O1 -g -Wall -Wextra")

# shellcheck disable=SC2086
"$CC" $FLAGS -fsanitize=address,undefined -fno-omit-frame-pointer \
    -o "$OUT" "$SRC"
echo "built $OUT"
