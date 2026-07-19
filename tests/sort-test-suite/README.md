# sort-test-suite

An exhaustive, GNU-sort-backed test suite for any `sort`-like binary: every
flag alone, every valid flag pairing, curated/random higher-order combos,
I/O fault injection, adversarial inputs, ASan/UBSan, and live differential
fuzzing against real GNU `sort`. 751 frozen golden cases + 195 previously
fuzz-discovered regressions ship in `suites/`, so you can judge a candidate
without even needing GNU `sort` installed (only fuzzing/regeneration need it).

## 1. One-time setup

Edit **`config.json`** — it's the only file you should need to touch:

- `paths.candidate_bin` — path to your compiled sort binary. **Required.**
- `paths.oracle_bin` — a real GNU `sort` (default `/usr/bin/sort`). Only
  needed for the fuzz pass and for regenerating `suites/`.
- `paths.candidate_asan_bin` / `candidate_src` / `cc` / `cc_flags` —
  optional, for the ASan/UBSan pass. Either point `candidate_asan_bin` at a
  binary you already built yourself with sanitizers (any language), or,
  if your sort is a single C file, fill in `candidate_src` and let
  `build_asan.sh` compile it for you. Leave both unset to skip that pass.
- `implemented` — which flags your binary currently supports (e.g. `"-n"`,
  `"-k"`, `"--sort"`). A case only runs if every flag it needs is listed
  here; everything else is skipped, not failed. Start small and add to
  this list as you implement more — coverage grows automatically.

## 2. Run it

```sh
./run_all.sh                  # uses ./config.json, 60s of fuzzing
./run_all.sh config.json 120  # explicit config + fuzz duration
```

This runs three passes (normal / ASan / differential fuzz vs the oracle),
prints an `OVERALL SUMMARY` with pass/fail counts and percentages, and
saves everything to `run_logs/<timestamp>/` (full log + per-pass JSON) for
your own reporting.

## 3. (Optional) validate the suite itself

```sh
./selfcheck.sh   # regeneration is deterministic, GNU sort self-passes,
                 # and a deliberately-wrong sort is correctly failed
```

Requires `paths.oracle_bin` to be a working GNU `sort`.

## Extending the suite

`suites/*.json.gz` are frozen, self-contained goldens (gzipped; run
scripts read them transparently). To add tiers, tweak the corpus, or
refreeze against a different GNU sort version, run:

```sh
python3 gen/generate.py            # regenerates suites/ using config.json's oracle_bin
```

`diff_fuzz.py` auto-records every new distinct bug it finds into
`suites/fuzz_regressions.json.gz` as a permanent regression test.
