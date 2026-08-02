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

## Platform contract

> **This suite's frozen goldens require Linux *and* GNU coreutils 9.11.**
> Both halves are load-bearing; the version alone is not enough.

Two independent reasons, each measured rather than assumed.

**1. Obsolete `+POS` key syntax resolves differently by platform.** The same
9.11 binary honours `+1` as an obsolete key specification on Linux and reads it
as a filename on Darwin:

| invocation | Linux 9.11 | Darwin 9.11 |
|---|---|---|
| `sort +1`, `POSIXLY_CORRECT=1` (case `obs-pos-posixly`) | exit **0**, sorted output, empty stderr | exit **2**, empty stdout, `sort: cannot read: +1: No such file or directory` |

Confirmed by generating the corpus with the *same* coreutils 9.11 build on both
platforms: every other case in all six generated tiers is byte-identical across
the two hosts, so this is a genuine platform difference rather than a suite,
engine or locale defect. (Collation, the usual source of platform variance in
`sort`, is already neutralised — `engine.py` pins `LC_ALL`, `LANG` and
`LANGUAGE` to `C` for every judged invocation.)

**2. The corpus cannot be generated on Darwin at all.** The `fault-devfull`
case writes to `/dev/full` to provoke ENOSPC on output. `/dev/full` is a
Linux-only device node; on macOS `engine.py` fails with `PermissionError:
Operation not permitted: '/dev/full'` and generation aborts partway, so the
`faults` and `random` tiers are never written.

This is why **`sort` is gated to Linux while `mkdir` is gated to Darwin**. The
two suites are platform-specific in opposite directions, each for a recorded
reason: mkdir's is symbolic `-m` mode resolution, sort's is the two above. The
split is deliberate, not an artifact of the machines they were first built on.

| Enforced at | Behavior on a non-Linux host |
|---|---|
| `selfcheck.sh` | stops **before** regeneration and before the oracle self-pass, exit 2 |
| `runner.py` (candidate evaluation) | `check_platform` exits **3 = PLATFORM INCOMPATIBLE**, distinct from 1 (a case failed) |
| `scripts/run_lineage_experiment.sh` | records exit 3 as `platform_incompatible`, **not** `validation_failed` |
| `scripts/lineage_plan.py` | `required_platform` and `host_platform` join the configuration fingerprint |

`required_platform` is declared once, in `config.json`, and inherited
everywhere else. The offline half of the gate is shared with the mkdir suite in
`tests/reference_generators/platform_contract.py`; `runner.py`'s copy is
deliberately separate, because it ships inside the sandbox and must run from the
five files `scripts/stage_test_bundle.py` allows.

## Oracle contract

`suites/` was frozen by running a **real GNU coreutils sort**, so the oracle
is part of this benchmark's definition rather than an implementation detail:
coreutils changes diagnostic wording between releases, and goldens frozen
against one release are not what another release produces.

| | |
|---|---|
| Pinned version | **GNU coreutils 9.11** |
| Required platform | **Linux** (see the platform contract above) |
| Recorded in | `suites/MANIFEST.json` (`sort_version`), `config.json` (`oracle_version_required`, `required_platform`) |
| Override | `SORT_ORACLE_BIN` environment variable |

### Re-pin history

Re-pinned from 9.4 to 9.11 to match the mkdir suite, which was already on 9.11.
Regenerating all 751 generated cases against 9.11 on the same platform changed
**two**, both of which quote the version by construction:

| case | 9.4 | 9.11 |
|---|---|---|
| `single-version-x-none` | `sort (GNU coreutils) 9.4`, © 2023 | `sort (GNU coreutils) 9.11`, © 2026 |
| `single-help-x-none` | `--help` text, 5548 bytes | `--help` text, 9368 bytes |

The other 749 were byte-identical, so the re-pin carried **no behavioral
change**. `fuzz_regressions.json.gz` is separately maintained and was not
regenerated.

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
