# sort-test-suite

An exhaustive, GNU-sort-backed test suite for any `sort`-like binary: every
flag alone, every valid flag pairing, every 3- and 4-flag combination of the
bounded ladder, curated/random higher-order combos,
I/O fault injection, adversarial inputs, ASan/UBSan, and live differential
fuzzing against real GNU `sort`. The seven reproducibly generated tiers and
their counts are recorded in `suites/MANIFEST.json`. The Darwin generator
produces **755 cases**; an infrastructure-only checkout prepared for the
Vessel re-freeze may still contain the old 756-case Linux corpus until the
explicit Vessel-side publish step below. The generated tiers sit alongside
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

> **The formal sort contract requires Darwin/macOS *and* GNU coreutils 9.11.**
> Both halves are load-bearing; the version alone is not enough.

The target formal corpus describes the actual Vessel execution environment. It is not
platform-neutral, and a Linux run must be rejected as an infrastructure
incompatibility rather than scored as a candidate failure.

**1. Obsolete `+POS` key syntax resolves differently by platform.** The same
9.11 binary honours `+1` as an obsolete key specification on Linux and reads it
as a filename on Darwin:

| invocation | Linux 9.11 | Darwin 9.11 |
|---|---|---|
| `sort +1`, `POSIXLY_CORRECT=1` (case `obs-pos-posixly`) | exit **0**, sorted output, empty stderr | exit **2**, empty stdout, `sort: cannot read: +1: No such file or directory` |

The Darwin golden must record the Darwin result directly; the candidate evaluator
does not emulate Linux. Collation is controlled separately: `engine.py` pins
`LC_ALL`, `LANG` and `LANGUAGE` to `C` for every judged invocation.

**`fault-devfull` is deliberately excluded by Darwin generation.** That case writes to
Linux's `/dev/full` device to provoke ENOSPC. macOS has no such device, so
`gen/curated_cases.py` omits the case when building the Darwin corpus. The
omission and its reason are recorded in `suites/MANIFEST.json`. Because the
case is not in the frozen corpus, the candidate runner neither expects nor
executes it, and it contributes no skip or failure.

| Enforced at | Behavior on a non-Darwin host |
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
| Required platform | **Darwin/macOS** (see the platform contract above) |
| Recorded in | `suites/MANIFEST.json` (`sort_version`), `config.json` (`oracle_version_required`, `required_platform`) |
| Override | `SORT_ORACLE_BIN` environment variable |

### Re-pin history

The former Linux corpus was re-pinned from 9.4 to 9.11 to match the mkdir
suite, which was already on 9.11. Regenerating all 756 generated cases against
9.11 on Linux changed
**two**, both of which quote the version by construction:

| case | 9.4 | 9.11 |
|---|---|---|
| `single-version-x-none` | `sort (GNU coreutils) 9.4`, © 2023 | `sort (GNU coreutils) 9.11`, © 2026 |
| `single-help-x-none` | `--help` text, 5548 bytes | `--help` text, 9368 bytes |

The Darwin re-freeze changes `obs-pos-posixly` from exit 0 with sorted
stdout to exit 2 with empty stdout and the Darwin GNU 9.11 missing-file
diagnostic. It also omitted `fault-devfull` for the platform reason above,
reducing the generated corpus from 756 to 755 cases. The old Linux corpus is
retained only until the Vessel publish step and is not the formal sort corpus.
`fuzz_regressions.json.gz` is separately maintained and is not regenerated.

Selection order, implemented by `tests/reference_generators/oracle_contract.py`:

1. an explicit `--sort-bin` / `--oracle-bin` argument
2. `$SORT_ORACLE_BIN`
3. `paths.oracle_bin` in `config.json`
4. conventional GNU locations (Homebrew gnubin/`gsort` first, then system paths)

Prefer the environment variable — it needs no edit to a tracked file. On
macOS, `/usr/bin/sort` is BSD sort and the verifier will refuse it; point to
the Homebrew/coreutils 9.11 binary explicitly:

```bash
SORT_ORACLE_BIN=/opt/homebrew/bin/gsort ./selfcheck.sh
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

### Vessel re-freeze and publish

Do not publish the Darwin goldens from a Windows or Linux development host.
On Vessel, first identify and verify the pinned oracle, then run the complete
selfcheck without publication:

```bash
cd tests/sort-test-suite
export SORT_ORACLE_BIN=/Users/sonjabrown/opt/coreutils-9.11/bin/sort
printf 'oracle path: %s\n' "$SORT_ORACLE_BIN"
"$SORT_ORACLE_BIN" --version
./selfcheck.sh config.json
```

During the one-time Linux-to-Darwin transition, that comparison is expected to
exit nonzero because the committed corpus is still the old Linux freeze. It
must report only the measured Darwin change to `obs-pos-posixly`, omission of
`fault-devfull`, and the corresponding manifest/count changes; the temporary
Darwin corpus must still pass the oracle and teeth gates.

After reviewing that dry-run comparison, publish with a separate explicit
command. `--publish` copies nothing until both deterministic regenerations,
the 100% oracle self-pass, and the wrong-oracle teeth checks have succeeded:

```bash
./selfcheck.sh config.json --publish
./selfcheck.sh config.json
SORT_ORACLE_BIN="$SORT_ORACLE_BIN" python3 gen/heldout.py --check
```

The second, non-publishing selfcheck is the final comparison against the newly
committed Darwin corpus. From the repository root, then run `make test`,
`git diff --check`, and verify `git status --short runs` is empty before
committing the generated suite files. Finally, exercise the lineage preflight
without starting a formal lineage by adding `--dry-run` to the normal Vessel
command:

```bash
cd ../..
bash scripts/run_lineage_experiment.sh --utility sort \
  ...normal arguments... --dry-run
```

On Vessel this must not print `platform_incompatible`.

Ordinary candidate judging needs **no oracle at all** — it runs entirely from
the frozen goldens. GNU sort 9.11 is required only for regeneration,
selfcheck, and live differential fuzzing. The oracle path never reaches an
agent-visible stage bundle.

## 1. One-time setup

Edit **`config.json`** — it's the only file you should need to touch:

- `paths.candidate_bin` — path to your compiled sort binary. **Required.**
- `paths.oracle_bin` — an optional real GNU coreutils 9.11 `sort`. Prefer
  `SORT_ORACLE_BIN` on macOS; an empty value searches Homebrew locations. Only
  needed for differential fuzzing, regeneration, and selfcheck.
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

Requires Darwin and a working GNU coreutils 9.11 `sort`; BSD `/usr/bin/sort`
is rejected before regeneration.

## Combinatorial coverage of the bounded ladder

`new_sort`'s checkpoint ladder implements four flags — `-r`, `-f`, `-u`, `-c` —
so the space a candidate is actually judged on is the 16-subset power set of
those four. `gen_singles` and `gen_pairs` reach the empty, 1- and 2-flag
subsets: 11 of 16. The four triples and the full quad had **no case at all**,
which meant the two checkpoints that implement three and four flags were judged
only on combinations of at most two of them.

The `kwise` tier closes that. `gen/combos.py:gen_kwise` enumerates every
k-subset of the ladder for k ≥ 3 — 5 cases — built exactly the way `gen_pairs`
builds its own: each flag contributes its default value, the set is routed to
positive or negative by `model/constraints.py:is_valid`, and the result is
frozen through the same oracle pipeline, with the same freeze-time model/oracle
disagreement check, as every other tier.

| subset size | subsets | covered by |
|---|---|---|
| 0, 1, 2 | 11 | `singles`, `pairs`, and the curated/adversarial tiers |
| 3 | 4 | `kwise` |
| 4 | 1 | `kwise` |

They need no runner support: the cumulative flag filter in
`judge_candidate.sh` already withholds a case until every flag it uses is
implemented. One case, `kwise-r-f-u-discrim`, becomes reachable at checkpoint
**003** (which implements exactly `-r -f -u`); the other four use `-c` and so
are reachable only at **004**.

It is a separate tier rather than an extension of `pairs` so that adding it
leaves every pre-existing suite file byte-identical — the goldens it
supplements were never wrong, they were missing.

## Extending the suite

`suites/*.json.gz` are frozen, self-contained goldens (gzipped; run
scripts read them transparently). To add tiers, tweak the corpus, or
refreeze against a different GNU sort version, run:

```sh
python3 gen/generate.py            # regenerates suites/ using config.json's oracle_bin
```

`diff_fuzz.py` auto-records every new distinct bug it finds into
`suites/fuzz_regressions.json.gz` as a permanent regression test.

## Held-out corpus

`heldout/heldout_cases.json.gz` holds **24 cases** that no agent ever sees. They are
scored once, after the repair loop has finished, by `scripts/heldout_judge.py`
via this utility's `extra_test_command`; the result lands in the attempt
metadata and is never rendered back into a prompt.

Each held-out case is a *dual* of a visible one — the same checkpoint, the same
cumulative flag list, the same structural shape, different concrete values.

Two things are specific to this suite. First, **scope**: the visible corpus
covers far more of GNU sort than the `new_sort` ladder asks for, so duals are
drawn only from visible cases whose flags fall inside `-r -f -u -c`. A dual
using `-k` would test something no checkpoint introduces, and its failure would
report a scope mismatch as a generalisation failure. Second, **how values
change**: a lexical substitution table cannot reach a corpus that is largely
generated, so inputs are transformed by a byte map that rotates within character
class and fixes everything else. Upper and lower rotate by the same amount, so
case-variant lines stay case-variants (which is what `-f` probes); the map is a
function, so duplicates stay duplicates (which is what `-u` probes); and tabs,
NULs, blank lines and every byte ≥ 0x80 are fixed points, so field structure,
line lengths and deliberately invalid UTF-8 survive. Check-mode cases whose twin
asserts that already-sorted input is *accepted* are re-ordered by the oracle
afterwards, since rotation is not order-preserving and the dual would otherwise
have quietly become a case about rejection. The generator refuses to write a
dual that came out byte-identical to its twin.

Provenance is identical to the visible corpus: `gen/heldout.py` calls
`gen/freeze.py:freeze_case` against the same pinned oracle, under the same
version and platform contract (see *Oracle contract* above). Both generation and
the freshness check need that oracle — every expectation here comes from
executing sort, so there is no offline model to check against.

```bash
SORT_ORACLE_BIN=~/opt/cu-9.11/bin/sort python3 gen/heldout.py
SORT_ORACLE_BIN=~/opt/cu-9.11/bin/sort python3 gen/heldout.py --check
python3 ../../scripts/check_heldout_isolation.py --utility sort
```

Neither the cases nor their counts per checkpoint are documented here. What the
isolation check enforces is stronger than documentation discipline: it builds
every checkpoint's bundle payload and searches the bytes, so the guarantee rests
on what `stage_test_bundle.py` actually copies rather than on what this file
says.
