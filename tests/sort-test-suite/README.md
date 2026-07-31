# sort-test-suite

An exhaustive, GNU-sort-backed test suite for any `sort`-like binary: every
flag alone, every valid flag pairing, curated/random higher-order combos,
I/O fault injection, adversarial inputs, ASan/UBSan, and live differential
fuzzing against real GNU `sort`. `suites/` ships **751 reproducibly generated
golden cases** — the six tiers `gen/generate.py` produces, whose per-tier counts
are recorded in `suites/MANIFEST.json` — alongside
`suites/fuzz_regressions.json.gz`, a **separately maintained, accreting
regression corpus** that `diff_fuzz.py` appends to whenever the live
differential fuzzer finds a new distinct bug. Its size grows over time and is
deliberately not quoted here; read it from the file or `MANIFEST.json`, which
covers the generated tiers only. Judging a candidate needs neither the fuzzer
nor GNU `sort` (only fuzzing/regeneration do).

## Checkpoint interface (bounded new_sort experiment)

```bash
tests/sort-test-suite/judge_candidate.sh build/new_sort              # 000
tests/sort-test-suite/judge_candidate.sh build/new_sort -r           # 001
tests/sort-test-suite/judge_candidate.sh build/new_sort -r -f        # 002
tests/sort-test-suite/judge_candidate.sh build/new_sort -r -f -u     # 003
tests/sort-test-suite/judge_candidate.sh build/new_sort -r -f -u -c  # 004
```

The flag list is **cumulative**, so a later checkpoint automatically re-runs
every earlier checkpoint's applicable cases as regression coverage.

This ladder is documented here rather than inside `judge_candidate.sh` because
that script is copied into the agent-visible stage bundle, and naming a later
checkpoint's flags there would disclose work the agent has not yet been asked
for. `README.md` is never copied into a bundle. The suite as a whole still
knows about GNU sort's full flag surface — that generic infrastructure is
unrelated to the bounded checkpoint sequence above, and
`scripts/stage_test_bundle.py` keeps it out of every sandbox.

## Oracle contract

`suites/` was frozen by running a **real GNU coreutils sort**, so the oracle
is part of this benchmark's definition rather than an implementation detail:
coreutils changes diagnostic wording between releases, and goldens frozen
against one release are not what another release produces.

| | |
|---|---|
| Pinned version | **GNU coreutils 9.4** |
| Recorded in | `suites/MANIFEST.json` (`sort_version`), `config.json` (`oracle_version_required`) |
| Override | `SORT_ORACLE_BIN` environment variable |

Selection order, implemented by `tests/reference_generators/oracle_contract.py`:

1. an explicit `--sort-bin` / `--oracle-bin` argument
2. `$SORT_ORACLE_BIN`
3. `paths.oracle_bin` in `config.json`
4. conventional locations (`/usr/bin/sort`, Homebrew gnubin, …)

Prefer the environment variable — it needs no edit to a tracked file, so a
Linux, WSL and macOS checkout can each point at their own coreutils:

```bash
SORT_ORACLE_BIN=/usr/bin/sort ./selfcheck.sh
```

`selfcheck.sh` verifies **before regenerating anything** that the binary exists,
is GNU coreutils, and matches the pin. A mismatch fails immediately and names
both versions, instead of surfacing later as a confusing model mismatch about
one error message.

`suites/` is only overwritten when you pass `--publish`. Without it the
self-check regenerates into a temporary directory and *compares*, which proves
the committed goldens are reproducible without letting one machine silently
redefine the benchmark. Re-pinning is a deliberate act: update
`oracle_version_required`, re-freeze with `--publish`, and say so in the commit.

Judging a candidate needs **no oracle at all** — it runs entirely from the
frozen goldens. The oracle path never reaches an agent-visible stage bundle.

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
