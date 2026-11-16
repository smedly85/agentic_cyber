#!/usr/bin/env bash
set -euo pipefail
base="${1:?usage: build.sh IMMUTABLE_LINUX_UTILITIES_IMAGE [linux/amd64]}"
target="${2:-linux/amd64}"
component='[a-z0-9]+(([._]|__|-+)[a-z0-9]+)*'
host='[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?'
registry="($host(\.$host)*|\[[a-fA-F0-9:]+\])(:[0-9]+)?"
repository="($registry/)?$component(/$component)*(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?"
[[ "$base" =~ ^sha256:[a-f0-9]{64}$ || "$base" =~ ^$repository@sha256:[a-f0-9]{64}$ ]] || {
  echo 'immutable validated base image required' >&2; exit 2;
}
case "$target" in linux/amd64) ;; *)
  echo 'only the locked linux/amd64 grep oracle is supported' >&2; exit 2;;
esac
cd "$(dirname "$0")"
docker build --pull=false --platform "$target" --build-arg BASE_IMAGE="$base" \
  --build-arg TARGETARCH="${target#linux/}" -t agentic-grep-oracle .
image_id="$(docker image inspect --platform "$target" agentic-grep-oracle --format '{{.Id}}')"
expected_binary='5f90bdcaa8d67f8cae1be43fb4ef0a1642c04a8dd0fd7870d33b9eb358b935f2'
observed_binary="$(docker run --rm --pull never --platform "$target" --network none \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  "$image_id" sha256sum /opt/gnu/bin/grep | awk '{print $1}')"
[[ "$observed_binary" == "$expected_binary" ]] || {
  echo "GNU grep binary SHA-256 mismatch: $observed_binary" >&2; exit 2;
}
printf '%s\n' "$image_id"
