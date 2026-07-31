#!/usr/bin/env bash
# Validate the SUITE itself (not any candidate). This must pass before the
# suite is trusted to judge a candidate. Five gates:
#   1. discrimination assertion (inside the generator)
#   2. regeneration determinism (generate twice -> byte-identical)
#   3. oracle self-pass    (the oracle passes 100% of its own goldens)
#   4. teeth check         (deliberately-wrong oracles must FAIL the suite)
#   5. (cross-check of predict_error happens inside freeze during gen)
#
# The oracle binary is resolved by ../reference_generators/oracle_contract.py:
# --oracle-bin, then $SORT_ORACLE_BIN, then config.json's paths.oracle_bin, then
# conventional locations. Nothing here is hardcoded to one machine's layout.
#
# Its version is checked BEFORE anything is regenerated. The frozen goldens were
# produced by a specific GNU coreutils release, and diagnostic wording changes
# between releases, so a different oracle would rewrite the benchmark rather
# than reproduce it -- which used to surface as a cryptic MODEL MISMATCH deep
# inside freeze, after the run had already started.
#
# Usage: ./selfcheck.sh [config.json]
#        SORT_ORACLE_BIN=/usr/bin/sort ./selfcheck.sh
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
SORT=$(python3 "$ORACLE_TOOL" resolve --suite sort --config "$CONFIG" \
                              --suite-root .)
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

    docker run --rm --user "$(id -u):$(id -g)"  -v "$PWD":/w -w /w IMAGE  bash tests/sort-test-suite/selfcheck.sh

  or inside the container:
    setpriv --reuid=1000 --regid=1000 --clear-groups  bash tests/sort-test-suite/selfcheck.sh
ROOTMSG
  exit 2
fi

echo "== gate 0: oracle identity and version =="
if ! python3 "$ORACLE_TOOL" verify --suite sort --config "$CONFIG" \
                            --suite-root . --oracle-bin "$SORT"; then
  echo "selfcheck.sh: refusing to regenerate against an unverified oracle." >&2
  exit 2
fi

echo "== gate 1+2: regenerate + determinism =="
rm -rf /tmp/exh_g1 /tmp/exh_g2
python3 gen/generate.py --out /tmp/exh_g1 --sort-bin "$SORT" >/dev/null || { echo "GEN1 FAILED"; exit 1; }
python3 gen/generate.py --out /tmp/exh_g2 --sort-bin "$SORT" >/dev/null || { echo "GEN2 FAILED"; exit 1; }
if diff -rq /tmp/exh_g1 /tmp/exh_g2 >/dev/null; then
  echo "  determinism: OK (byte-identical)"
else
  echo "  determinism: FAIL"; diff -rq /tmp/exh_g1 /tmp/exh_g2; fail=1
fi
# Publishing is opt-in. suites/ is the frozen benchmark: overwriting it as a
# side effect of a self-check means a run on a different machine can silently
# redefine what every candidate is scored against. Without --publish the
# regenerated corpus is only compared with the committed one, which is the
# stronger check anyway -- it proves the committed goldens are reproducible.
if [ "$PUBLISH" = 1 ]; then
  echo "  publishing regenerated suites into suites/ (--publish)"
  cp /tmp/exh_g1/*.json.gz /tmp/exh_g1/MANIFEST.json suites/ 2>/dev/null
else
  # Compares decompressed CASES over the tiers config.json declares as
  # generated, and audits the inventory. A gzip byte-diff could neither
  # say what changed nor distinguish a separately-maintained file from a
  # missing one.
  if python3 ../reference_generators/suite_diff.py  --fresh /tmp/exh_g1 --committed suites --config "$CONFIG"; then
    :
  else
    echo "  (re-run with --publish only if changing the benchmark is intended)"
    fail=1
  fi
fi

echo "== gate 3: oracle self-pass (the oracle must be 100%) =="
if python3 runner.py "${SUITES[@]}" --all-flags -- "$SORT" >/tmp/exh_oracle.log 2>&1; then
  tail -1 /tmp/exh_oracle.log
else
  echo "  ORACLE SELF-PASS FAILED:"; tail -20 /tmp/exh_oracle.log; fail=1
fi

echo "== gate 4: teeth check (wrong oracles must FAIL) =="
# 4a. busybox sort differs from GNU sort on many options -> must be caught
# (skipped entirely if busybox isn't installed -- optional sanity check)
if command -v busybox >/dev/null; then
  if python3 runner.py "${SUITES[@]}" --all-flags -- "$(command -v busybox)" sort \
       >/tmp/exh_bb.log 2>&1; then
    echo "  TEETH FAIL: busybox sort passed the suite (suite too weak)"; fail=1
  else
    echo "  busybox sort correctly FAILS ($(grep -c FAIL /tmp/exh_bb.log) failing lines)"
  fi
fi
# 4b. a shim that always reverses output -> must be caught
cat >/tmp/exh_shim_rev <<SH
#!/usr/bin/env bash
exec "$SORT" -r "\$@"
SH
chmod +x /tmp/exh_shim_rev
if python3 runner.py suites/singles.json* --all-flags -- /tmp/exh_shim_rev \
     >/tmp/exh_shim.log 2>&1; then
  echo "  TEETH FAIL: reverse shim passed (suite too weak)"; fail=1
else
  echo "  reverse shim correctly FAILS"
fi

echo
if [ "$fail" = 0 ]; then echo "SELFCHECK: ALL GATES PASSED"; else echo "SELFCHECK: FAILURES"; fi
exit $fail
