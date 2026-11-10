#!/usr/bin/env bash
set -euo pipefail

# Run on Vessel. Only the supplied candidate is mounted into the container.
if [[ $# -ne 1 ]]; then
    echo "Usage: bash $0 /absolute/path/to/final/c_cp.c" >&2
    exit 2
fi
src="$1"
[[ -f "$src" ]] || { echo "Candidate not found: $src" >&2; exit 2; }
expected=1775d84c1a5988ac837fd734e07e3b3fa5c71194d058f480ea111c0961ee9732
actual=$(shasum -a 256 "$src" | awk '{print $1}')
echo "Candidate SHA-256: $actual"
[[ "$actual" == "$expected" ]] || { echo 'Candidate checksum mismatch; stopping.' >&2; exit 2; }

docker run --rm -i \
    --platform linux/amd64 \
    --network none \
    --memory 512m \
    --cpus 1 \
    --pids-limit 64 \
    --user 65534:65534 \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --read-only \
    --tmpfs /tmp:rw,exec,size=32m,mode=1777 \
    --mount "type=bind,source=$src,target=/candidate.c,readonly" \
    --entrypoint /bin/bash \
    agentic-linux-utilities -s <<'BASH'
set -euo pipefail
export LC_ALL=C

gcc -O0 -g /candidate.c -o /tmp/candidate_cp
printf '\n=== REFERENCE VERSION ===\n'
/opt/gnu/bin/cp --version | sed -n '1p'

child=$(printf 'd%.0s' {1..80})

run_test() {
    local label="$1" binary="$2" workspace="$3" rc count
    mkdir -p "/tmp/$workspace/tree"
    cd "/tmp/$workspace"
    printf '\n=== %s ===\n' "$label"
    set +e
    timeout -k 1s 5s "$binary" -r ./tree "tree/$child" >stdout.log 2>stderr.log
    rc=$?
    set -e
    printf 'Exit code: %s\n' "$rc"
    if count=$(find tree -mindepth 1 -type d -printf '.' | wc -c); then
        printf 'Directories created: %s\n' "$count"
    else
        printf 'Directory count incomplete (find failed).\n' >&2
    fi
    printf 'First diagnostic:\n'
    head -c 500 stderr.log
    printf '\n'
}

run_test 'CANDIDATE' /tmp/candidate_cp candidate-test
run_test 'GNU ORACLE' /opt/gnu/bin/cp oracle-test
BASH
