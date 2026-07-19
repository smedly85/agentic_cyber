#!/usr/bin/env bash
# Validate the SUITE itself (not any candidate). This must pass before the
# suite is trusted to judge a candidate. Gates:
#   1. discrimination assertion (inside the generator)
#   2. regeneration determinism (generate twice -> byte-identical)
#   3. oracle self-pass    (the oracle passes 100% of its own goldens)
#   4. teeth check         (deliberately-wrong oracles must FAIL)
#   5. (cross-check of predict_error happens inside freeze during gen)
#
# The oracle binary comes from config.json's paths.oracle_bin (default
# /usr/bin/mkdir) -- nothing here is hardcoded to a specific path.
#
# Usage: ./selfcheck.sh [config.json]
set -u
cd "$(dirname "$0")"
CONFIG=${1:-config.json}
MKDIR=$(python3 config.py "$CONFIG" paths.oracle_bin --default /usr/bin/mkdir)
SUITES=(); for s in suites/*.json suites/*.json.gz; do
  [ -f "$s" ] && [[ "$(basename "$s")" != "MANIFEST.json" ]] && SUITES+=("$s")
done
fail=0

if [ ! -x "$MKDIR" ]; then
  echo "selfcheck.sh: paths.oracle_bin ('$MKDIR') is not an executable file." >&2
  echo "This suite's self-check needs a real GNU mkdir to compare against." >&2
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
# publish the freshly-generated suites
cp /tmp/exh_mkdir_g1/*.json.gz /tmp/exh_mkdir_g1/MANIFEST.json suites/ 2>/dev/null

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
