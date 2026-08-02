#!/usr/bin/env bash
# Validate the SUITE itself (not any candidate). This must pass before the
# suite is trusted to judge a candidate. Gates:
#   1. discrimination assertion (inside the generator)
#   2. regeneration determinism (generate twice -> byte-identical)
#   3. oracle self-pass    (the oracle passes 100% of its own goldens)
#   4. teeth check         (deliberately-wrong oracles must FAIL)
#   5. (cross-check of predict_error happens inside freeze during gen)
#
# The oracle binary is resolved by ../reference_generators/oracle_contract.py:
# --oracle-bin, then $MKDIR_ORACLE_BIN, then config.json's paths.oracle_bin,
# then conventional locations. Nothing here is hardcoded to one machine's
# layout -- this file used to depend on a macOS Homebrew path, which is why it
# could not run on WSL.
#
# Its version is checked BEFORE anything is regenerated, because the frozen
# goldens were produced by a specific GNU coreutils release.
#
# Usage: ./selfcheck.sh [config.json]
#        MKDIR_ORACLE_BIN=/usr/bin/mkdir ./selfcheck.sh
#        ./selfcheck.sh config.json --publish   # overwrite suites/ (see below)
set -u

# Resolve our own directory defensively. On a container whose coreutils are
# half-broken -- alpine:edge shipped a `dirname`/`id` that died with
# "Error relocating ... renameat2: symbol not found" -- the command
# substitution yields an empty string, `cd ""` fails, and with only `set -u`
# the script would carry on in whatever directory it was launched from. Every
# relative path after this point (config.json, gen/generate.py,
# ../reference_generators/) would then resolve somewhere meaningless and the
# failure would surface far away from its cause. Fail here instead.
SCRIPT_DIR=$(dirname "$0" 2>/dev/null) || SCRIPT_DIR=""
if [ -z "$SCRIPT_DIR" ] || [ ! -d "$SCRIPT_DIR" ]; then
  echo "selfcheck.sh: cannot resolve its own directory from \$0='$0'." >&2
  echo "  'dirname' returned '${SCRIPT_DIR}'. On a container with a broken" >&2
  echo "  coreutils install this is usually a relocation error; check with:" >&2
  echo "    dirname /a/b && id -u" >&2
  exit 2
fi
cd "$SCRIPT_DIR" || {
  echo "selfcheck.sh: cannot cd into '$SCRIPT_DIR'." >&2
  exit 2
}
# The directory has to actually be this suite, not merely exist.
for required in config.json gen/generate.py ../reference_generators; do
  if [ ! -e "$required" ]; then
    echo "selfcheck.sh: '$SCRIPT_DIR' is not a complete test suite:" >&2
    echo "  missing '$required' after changing directory." >&2
    exit 2
  fi
done
CONFIG=${1:-config.json}
PUBLISH=0
for arg in "$@"; do [ "$arg" = "--publish" ] && PUBLISH=1; done
ORACLE_TOOL=../reference_generators/oracle_contract.py
MKDIR=$(python3 "$ORACLE_TOOL" resolve --suite mkdir --config "$CONFIG"                                --suite-root .)
SUITES=(); for s in suites/*.json suites/*.json.gz; do
  [ -f "$s" ] && [[ "$(basename "$s")" != "MANIFEST.json" ]] && SUITES+=("$s")
done
fail=0

# Permission-sensitive gate. Several fault cases assert that an operation is
# REFUSED -- an unwritable output directory, an unreadable input. root ignores
# those permission bits, so as root the oracle "succeeds" where the frozen
# golden says it must fail. Running anyway produces two wrong conclusions at
# once: a fabricated oracle defect, and a regenerated faults tier whose exit
# codes silently encode root's privileges. Refuse instead.
if [ "$(id -u)" = 0 ]; then
  cat >&2 <<'ROOTMSG'
selfcheck.sh: refusing to run as root.

  This suite contains permission-sensitive fault cases (unwritable output
  directory, unreadable input). root bypasses the permission bits those cases
  exist to exercise, so running as root reports the ORACLE as broken and, if
  regeneration were published, would freeze root-only exit codes into the
  benchmark.

  Re-run as an unprivileged user, for example:

    docker run --rm --user "$(id -u):$(id -g)"  -v "$PWD":/w -w /w IMAGE  bash tests/mkdir-test-suite/selfcheck.sh

  or inside the container:
    setpriv --reuid=1000 --regid=1000 --clear-groups  bash tests/mkdir-test-suite/selfcheck.sh
ROOTMSG
  exit 2
fi

# Platform gate, before regeneration and before the oracle self-pass. This
# suite's frozen goldens are Darwin-specific; the reason is recorded in
# config.json's _platform_contract, which the shared checker prints.
#
# Regenerating on the wrong host would redefine the benchmark; running the
# oracle self-pass there would report the ORACLE as broken for a difference that
# is the host's, not the binary's. Stop before either.
#
# Shared with the sort suite: selfcheck.sh is offline and never bundled, so the
# mechanism lives in one place. runner.py's equivalent cannot be shared -- it
# ships inside the sandbox and must run from the bundle's five-file allowlist.
if ! python3 ../reference_generators/platform_contract.py check \
        --config "$CONFIG" --suite mkdir; then
  exit 2
fi

echo "== gate 0: oracle identity and version =="
if ! python3 "$ORACLE_TOOL" verify --suite mkdir --config "$CONFIG"                             --suite-root . --oracle-bin "$MKDIR"; then
  echo "selfcheck.sh: refusing to regenerate against an unverified oracle." >&2
  exit 2
fi

echo "== gate 1+2: regenerate + determinism =="
rm -rf /tmp/exh_mkdir_g1 /tmp/exh_mkdir_g2
python3 gen/generate.py --out /tmp/exh_mkdir_g1 --mkdir-bin "$MKDIR" >/dev/null || { echo "GEN1 FAILED"; exit 1; }
python3 gen/generate.py --out /tmp/exh_mkdir_g2 --mkdir-bin "$MKDIR" >/dev/null || { echo "GEN2 FAILED"; exit 1; }
if diff -rq /tmp/exh_mkdir_g1 /tmp/exh_mkdir_g2 >/dev/null; then
  echo "  determinism: OK (byte-identical)"
else
  echo "  determinism: FAIL"; diff -rq /tmp/exh_mkdir_g1 /tmp/exh_mkdir_g2; fail=1
fi
# Publishing is opt-in; see the sort suite's selfcheck.sh for the reasoning.
# suites/ is the frozen benchmark, and overwriting it as a side effect of a
# self-check lets one machine silently redefine what candidates are scored
# against.
if [ "$PUBLISH" = 1 ]; then
  echo "  publishing regenerated suites into suites/ (--publish)"
  cp /tmp/exh_mkdir_g1/*.json.gz /tmp/exh_mkdir_g1/MANIFEST.json suites/ 2>/dev/null
else
  # Compares decompressed CASES over the tiers config.json declares as
  # generated, and audits the inventory. A gzip byte-diff could neither
  # say what changed nor distinguish a separately-maintained file from a
  # missing one.
  if python3 ../reference_generators/suite_diff.py  --fresh /tmp/exh_mkdir_g1 --committed suites --config "$CONFIG"; then
    :
  else
    echo "  (re-run with --publish only if changing the benchmark is intended)"
    fail=1
  fi
fi

echo "== gate 3: oracle self-pass (the oracle must be 100%) =="
if python3 runner.py "${SUITES[@]}" --all-flags -- "$MKDIR" >/tmp/exh_mkdir_oracle.log 2>&1; then
  tail -1 /tmp/exh_mkdir_oracle.log
else
  echo "  ORACLE SELF-PASS FAILED:"; tail -20 /tmp/exh_mkdir_oracle.log; fail=1
fi

echo "== gate 4: teeth check (wrong oracles must FAIL) =="
# 4a. busybox mkdir differs from GNU mkdir on several semantics (e.g. -p's
# "mode applies to the final dir only" rule) -> must be caught. Skipped
# entirely if busybox isn't installed -- optional sanity check.
if command -v busybox >/dev/null; then
  if python3 runner.py "${SUITES[@]}" --all-flags -- "$(command -v busybox)" mkdir \
       >/tmp/exh_mkdir_bb.log 2>&1; then
    echo "  TEETH FAIL: busybox mkdir passed the suite (suite too weak)"; fail=1
  else
    echo "  busybox mkdir correctly FAILS ($(grep -c FAIL /tmp/exh_mkdir_bb.log) failing lines)"
  fi
fi
# 4b. a shim that always forces -p (silently swallows EEXIST/ENOENT that
# should be reported) -> must be caught by the curated error catalog and
# adversarial "must fail without -p" cases.
cat >/tmp/exh_mkdir_shim_alwaysp <<SH
#!/usr/bin/env bash
exec "$MKDIR" -p "\$@"
SH
chmod +x /tmp/exh_mkdir_shim_alwaysp
if python3 runner.py suites/curated.json* --all-flags -- /tmp/exh_mkdir_shim_alwaysp \
     >/tmp/exh_mkdir_shim.log 2>&1; then
  echo "  TEETH FAIL: always-p shim passed (suite too weak)"; fail=1
else
  echo "  always-p shim correctly FAILS"
fi
# 4c. a shim that ignores -m (mode always default) -> must be caught by the
# -m singles sweep and the -m/umask discrimination it exercises.
cat >/tmp/exh_mkdir_shim_nom <<SH
#!/usr/bin/env bash
args=(); skip=0
for a in "\$@"; do
  if [ "\$skip" = 1 ]; then skip=0; continue; fi
  case "\$a" in
    -m) skip=1; continue ;;
    -m*) continue ;;
  esac
  args+=("\$a")
done
exec "$MKDIR" "\${args[@]}"
SH
chmod +x /tmp/exh_mkdir_shim_nom
if python3 runner.py suites/singles.json* --all-flags -- /tmp/exh_mkdir_shim_nom \
     >/tmp/exh_mkdir_shim_nom.log 2>&1; then
  echo "  TEETH FAIL: -m-ignoring shim passed (suite too weak)"; fail=1
else
  echo "  -m-ignoring shim correctly FAILS"
fi

echo
if [ "$fail" = 0 ]; then echo "SELFCHECK: ALL GATES PASSED"; else echo "SELFCHECK: FAILURES"; fi
exit $fail
