# mkdir-test-suite

An exhaustive, GNU-mkdir-backed test suite for any `mkdir`-like binary:
every flag alone (crossed with a umask sweep), every valid flag pairing,
curated/random higher-order combos, curated EEXIST/ENOENT/ENOTDIR/mode-error
cases, `-p`/`-m` semantic quirks, filesystem fault injection, adversarial
paths, ASan/UBSan, and live differential fuzzing against real GNU `mkdir`.
Frozen golden cases ship in `suites/`, so you can judge a candidate without
even needing GNU `mkdir` installed (only fuzzing/regeneration need it).

Unlike a `sort`-style suite, mkdir's observable output is mostly
**filesystem state** -- which directories now exist and their permission
bits (including setuid/setgid/sticky) and any symlink targets -- not
stdout. Every case therefore golden-checks a `tree` snapshot (every path
under a fresh, per-case temp dir, after the run) in addition to exit code,
stderr, and stdout (for `-v`). The umask is pinned per case (default
`0022`), exactly as locale/env are pinned, so mode goldens are reproducible.

## Checkpoint interface (bounded new_mkdir experiment)

```bash
tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir        # 000
tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir -p     # 001
tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir -p -m  # 002
```

The flag list is **cumulative**, so a later checkpoint automatically re-runs
every earlier checkpoint's applicable cases as regression coverage.

This ladder is documented here rather than inside `judge_candidate.sh` because
that script is copied into the agent-visible stage bundle, and naming a later
checkpoint's flags there would disclose work the agent has not yet been asked
for. `README.md` is never copied into a bundle.

## Platform contract

> **This suite's frozen goldens require Darwin (macOS) *and* GNU coreutils 9.11.**
> Both halves are load-bearing; the version alone is not enough.

GNU coreutils 9.11 resolves a symbolic `-m` argument that does not itself set
the rwx bits from a **0777 departure on Darwin** and a **0755 departure on
Linux**. The same binary version therefore produces different directory modes on
the two platforms. Measured in both environments, with the umask verified in the
process that execs mkdir:

| invocation | Darwin 9.11 | Linux 9.11 |
|---|---|---|
| `mkdir` (no `-m`), umask 0000/0022/0077 | 0777 / 0755 / 0700 | 0777 / 0755 / 0700 |
| `mkdir -m +t`, any umask | **01777** | **01755** |
| `mkdir -m a+t`, any umask | 01777 | 01755 |
| `mkdir -m a=rwx,+t`, any umask | 01777 | 01777 |
| `mkdir -m 1777`, any umask | 01777 | 01777 |

The umask reaches mkdir correctly on both platforms — the bare-`mkdir` row
varies exactly as it should, and the declared per-case umask was confirmed at
the exec'ing process. This is a genuine platform difference, not a suite,
engine, runner or umask-propagation defect. On Darwin the committed corpus
reproduces exactly and every self-check gate passes.

| Enforced at | Behavior on a non-Darwin host |
|---|---|
| `selfcheck.sh` | stops **before** regeneration and before the oracle self-pass, exit 2 |
| `runner.py` (candidate evaluation) | `check_platform` exits **3 = PLATFORM INCOMPATIBLE**, distinct from 1 (a case failed) |
| `scripts/run_lineage_experiment.sh` | records exit 3 as `platform_incompatible`, **not** `validation_failed` |
| `scripts/lineage_plan.py` | `required_platform` and `host_platform` join the configuration fingerprint |

`required_platform` is declared once, in `config.json`, and inherited
everywhere else. It is carried into the agent-visible stage bundle so the judge
can refuse correctly inside a sandbox; that value is an operating-system name —
part of the generic execution environment — and discloses nothing about flags,
features or checkpoints.

**No frozen case was changed.** The goldens are correct for the platform they
were produced on; the contract records which platform that is.

## Canonical symlink policy

A symlink's permission bits are **host-OS metadata, not mkdir behavior**. Linux
`lstat` reports `0777` for every symlink; macOS reports `0755`; there is no
portable way to `chmod` a symlink and mkdir never tries. The committed corpus
was frozen through a Homebrew GNU mkdir on macOS, so it records `0755`, and a
Linux regeneration records `0777` for identical, correct behavior.

The canonical policy, applied identically everywhere a tree is compared:

> For an entry of type `symlink`, compare **path, type and target**, and ignore
> **`mode`**. For every other type, compare the mode unchanged.

| Where | Implementation |
|---|---|
| candidate evaluation | `runner.py` `_tree_diff` → `engine.canonical_tree` |
| oracle self-pass | same path (gate 3 runs the oracle through `runner.py`) |
| fresh-vs-committed comparison | `../reference_generators/suite_diff.py` `canonicalize` |
| fresh generation | `engine.snapshot_tree` still records the mode; nothing is discarded, it is ignored at comparison |

This deliberately does **not** touch directory or regular-file modes. Those are
core mkdir behavior — umask interaction, `-m`, setuid/setgid/sticky — and remain
fully checked; a directory that comes out `01755` where `01777` was frozen still
fails, as it must.

The policy is a comparator rule, not a schema change: **no frozen file was
modified**, and the corpus keeps its recorded `0755` values.

## Oracle contract

`suites/` was frozen by running a **real GNU coreutils mkdir**, so the oracle
is part of this benchmark's definition rather than an implementation detail:
coreutils changes diagnostic wording between releases, and goldens frozen
against one release are not what another release produces.

| | |
|---|---|
| Pinned version | **GNU coreutils 9.11** |
| Recorded in | `suites/MANIFEST.json` (`mkdir_version`), `config.json` (`oracle_version_required`) |
| Override | `MKDIR_ORACLE_BIN` environment variable |

Selection order, implemented by `tests/reference_generators/oracle_contract.py`:

1. an explicit `--mkdir-bin` / `--oracle-bin` argument
2. `$MKDIR_ORACLE_BIN`
3. `paths.oracle_bin` in `config.json`
4. conventional locations (`/usr/bin/mkdir`, Homebrew gnubin, …)

Prefer the environment variable — it needs no edit to a tracked file, so a
Linux, WSL and macOS checkout can each point at their own coreutils:

```bash
MKDIR_ORACLE_BIN=/usr/bin/mkdir ./selfcheck.sh
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

Edit **`config.json`** -- it's the only file you should need to touch:

- `paths.candidate_bin` -- path to your compiled mkdir binary. **Required.**
- `paths.oracle_bin` -- a real GNU coreutils `mkdir`. Only needed for the
  fuzz pass and for regenerating `suites/`. Leave it empty and set
  `MKDIR_ORACLE_BIN` instead; see [Oracle contract](#oracle-contract) for the
  full resolution order and the pinned version. On Linux/WSL `/usr/bin/mkdir`
  is already GNU; on macOS the system `/bin/mkdir` is BSD, so install GNU
  coreutils (`brew install coreutils`) and point at its gnubin `mkdir`.
- `paths.candidate_asan_bin` / `candidate_src` / `cc` / `cc_flags` --
  optional, for the ASan/UBSan pass. Either point `candidate_asan_bin` at a
  binary you already built yourself with sanitizers (any language), or, if
  your mkdir is a single C file, fill in `candidate_src` and let
  `build_asan.sh` compile it for you. Leave both unset to skip that pass.
- `implemented` -- which flags your binary currently supports (e.g. `"-p"`,
  `"-v"`, `"-m"`). A case only runs if every flag it needs is listed here;
  everything else is skipped, not failed. Start small and add to this list
  as you implement more -- coverage grows automatically.

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
./selfcheck.sh   # regeneration is deterministic, GNU mkdir self-passes,
                 # and deliberately-wrong mkdir shims are correctly failed
```

Requires `paths.oracle_bin` to be a working GNU `mkdir`.

## What's exhaustive here

mkdir's flag surface is tiny compared to `sort`'s (`-p`, `-v`, `-m`, plus
the Linux-only `-Z`/`--context`), so exhaustiveness comes from crossing
that small surface against:

- **`-m`'s full mode-value pool x a umask sweep** (`0000`/`0022`/`0077`) --
  the interaction between the requested mode and the umask *is* mkdir
  correctness, and both octal (`0755`, `4755`, `1777`, ...) and symbolic
  (`u+rwx`, `a=rx`, `+t`, `g+s`, ...) syntaxes are covered, plus a curated
  invalid-mode catalog (empty, bad digits, unrecognized symbolic chars).
- **path/fixture targets**: bare creation, multi-operand, deeply-nested
  paths requiring `-p`, targets that already exist (EEXIST vs. `-p`
  idempotency), partially-present parents, trailing slashes, dot segments,
  absolute paths, symlinked parents.
- **curated semantic quirks**, pinned as golden trees: `-p -m` applies the
  requested mode *only* to the final directory (intermediates get the
  umask default); `-p` on an already-existing target never chmods it, even
  under `-m`; `-v` output text; special permission bits (setuid/sticky) set
  directly via `-m`; multi-operand partial failure (one bad operand doesn't
  block the good ones).
- **adversarial paths**: very long/deep names, spaces/tabs/newlines/
  unicode in names, leading-dash names (needs `--`), `.`/`..` operands,
  hundreds of operands, symlinked parents.
- **filesystem fault injection**: read-only parent directories (EACCES,
  with and without `-p`), an unwritable cwd, and fd exhaustion under a deep
  `-p`.

## Extending the suite

`suites/*.json.gz` are frozen, self-contained goldens (gzipped; run
scripts read them transparently). To add tiers, tweak the corpus, or
refreeze against a different GNU mkdir version, run:

```sh
python3 gen/generate.py            # regenerates suites/ using config.json's oracle_bin
```

`diff_fuzz.py` auto-records every new distinct bug it finds into
`suites/fuzz_regressions.json.gz` as a permanent regression test. It
mutates path structure and starting fixtures (not stdin bytes, since mkdir
has none) and always runs inside a per-case sandboxed temp dir -- any
mutation that would resolve outside that sandbox (e.g. an unbalanced `..`)
is rejected before either binary is invoked, so fuzzing never touches the
real filesystem.
