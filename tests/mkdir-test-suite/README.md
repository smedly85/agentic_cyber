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

## 1. One-time setup

Edit **`config.json`** -- it's the only file you should need to touch:

- `paths.candidate_bin` -- path to your compiled mkdir binary. **Required.**
- `paths.oracle_bin` -- a real GNU coreutils `mkdir`. Only needed for the
  fuzz pass and for regenerating `suites/`. On Linux this is usually
  `/usr/bin/mkdir` already; on macOS the system `/bin/mkdir` is BSD, not
  GNU -- install GNU coreutils (`brew install coreutils`) and point this at
  the gnubin `mkdir` (e.g.
  `/opt/homebrew/opt/coreutils/libexec/gnubin/mkdir`).
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
