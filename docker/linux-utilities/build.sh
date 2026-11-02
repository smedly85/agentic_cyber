#!/usr/bin/env bash
set -euo pipefail
base="${1:?usage: build.sh python:3.12.8-bookworm@sha256:DIGEST [linux/arm64]}"
target="${2:-linux/arm64}"
[[ "$base" =~ ^python:3\.12\.8-bookworm@sha256:[a-f0-9]{64}$ ]] || { echo 'immutable Python base digest required' >&2; exit 2; }
case "$target" in linux/arm64|linux/amd64) ;; *) exit 2;; esac
cd "$(dirname "$0")"
docker build --platform "$target" --build-arg BASE_IMAGE="$base" \
  --build-arg TARGETARCH="${target#linux/}" -t agentic-linux-utilities .
docker image inspect agentic-linux-utilities --format '{{.Id}}'
