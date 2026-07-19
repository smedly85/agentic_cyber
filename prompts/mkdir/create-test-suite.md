# Plan: `tests/mkdir-test-suite/` — an exhaustive, GNU-mkdir-backed test suite

## Context

The repo `agentic_cyber` studies how LLM-generated coreutils implementations evolve.
Its heavyweight evaluation asset is [`tests/sort-test-suite/`](tests/sort-test-suite/):
a standalone, binary-agnostic harness that judges *any* `sort`-like binary against
**frozen golden outputs** captured from real GNU `sort`, with tiered exhaustive
coverage (every flag alone, every flag pair, seeded higher-order combos, curated
error/quirk cases, adversarial inputs, I/O fault injection), plus ASan/UBSan and
live differential fuzzing against the oracle. 751 frozen goldens + 195 fuzz
regressions ship gzipped in `suites/`, so a candidate can be judged **without GNU
sort installed** (only fuzzing/regeneration need the oracle).

We want the same thing for **`mkdir`** — a first parallel coreutil suite establishing
the one-suite-per-util pattern. Confirmed scope: **the standalone test suite only**
(no `new_mkdir` implementation or prompts). It must be exhaustive, standalone, and
carry the same feature set.

**The one fundamental difference:** `sort`'s observable output is stdout ordering;
**`mkdir`'s observable output is filesystem *state*** — which directories now exist,
their permission bits (incl. setuid/setgid/sticky), and any symlink targets — plus
stdout (only `-v` prints), stderr, and exit code. So the golden schema and the
shared engine gain a **fixture filesystem** (pre-populated before the run) and a
**tree snapshot** (captured after), and the engine **pins the umask** (as it already
pins locale) so mode goldens are reproducible. Golden granularity (confirmed): per
entry capture `type` (dir/file/symlink) + full permission bits + symlink `target`;
**no** timestamps (nondeterministic) and **no** uid/gid (constant for the invoking
user; setgid group inheritance is already visible in the mode bits).

## Target layout

Create `tests/mkdir-test-suite/` mirroring `tests/sort-test-suite/`:

```
config.json  config.py  engine.py  runner.py  props.py  diff_fuzz.py
report_summary.py  run_all.sh  selfcheck.sh  build_asan.sh  README.md
model/{flag_model.py, constraints.py}
corpus/corpus.py
gen/{generate.py, combos.py, curated_cases.py, freeze.py}
suites/{singles,pairs,random,curated,adversarial,faults,fuzz_regressions}.json.gz + MANIFEST.json
```

## Reuse verbatim / near-verbatim (copy from sort-test-suite, minimal edits)

- **`config.py`** — copy as-is (generic dotted-key JSON loader; no sort specifics).
- **`report_summary.py`** — copy as-is (merges normal/asan/fuzz JSON reports; pass-rate
  denominator already excludes SKIP/XFAIL).
- **`build_asan.sh`** — copy as-is (compiles a single-C-file candidate with sanitizers).
- **`run_all.sh`** / **`selfcheck.sh`** — copy structure; only edit the wording, the
  "teeth" shims (see §selfcheck), and drop the sort-word references.
- **`gen/generate.py`** — copy the tier→freeze→gzip pipeline and `write_suite`
  (canonical `indent=1, sort_keys=True`, gzip `mtime=0` for byte-identical determinism).
  Edits: rename `--sort-bin`→`--mkdir-bin`, `sort_version`→`mkdir_version`, oracle
  default resolves from `paths.oracle_bin`, and `assert_discriminating` becomes the
  mkdir discrimination check (§corpus).
- **`runner.py`** — reuse the whole verdict model unchanged: severities
  `PASS/SKIP/XFAIL(0) < FAIL(1) < TIMEOUT(2) < SANITIZER(3) < CRASH(4)`,
  `case_selected()` manifest/tag filtering, `ThreadPoolExecutor`, `--json-report`,
  `_stderr_ok` (exact/base64/regex/class). **Changes:** drop `modes_for()`/stdin-mode
  expansion (mkdir has no stdin); the `golden` check now compares the **tree snapshot**
  (`res.tree` vs `case["tree"]`) *and* stdout/stderr/exit, instead of stdout ordering;
  `property:*` dispatches to the new `props.py` checks.

## Rewrite for mkdir semantics

### `engine.py` — the shared execution core (freeze + runner + fuzz all use it)
Keep the bytes-everything subprocess core, `pinned_env()`, `Result`, sanitizer scan,
signal decoding, `TemporaryDirectory` isolation, and the `_Faults` preexec/rlimit
machinery. Adapt:
- **`pinned_env`**: keep `LC_ALL/LANG/LANGUAGE=C`; drop the sort-obsolete-syntax env
  pops. `argv0` forced to `"mkdir"` so usage/`--help` wording matches oracle↔candidate.
- **Umask pinning (new):** wrap the child spawn so it runs under a fixed umask
  (default `022`, overridable per case via `case["umask"]`). Set it in `preexec_fn`
  via `os.umask(int(case.get("umask","022"), 8))` so it applies only to the child.
- **Fixture setup (replaces stdin/files materialization):** before spawning,
  materialize `case["fixture"]` — a list of `{path, type: dir|file|symlink, mode,
  target?, contents_b64?}` entries created inside the temp dir (so cases can start
  from pre-existing dirs, files-as-path-components, symlinks, restricted-perm parents).
- **Tree snapshot (new, replaces `outfiles`):** after the run, walk the temp dir and
  return `Result.tree` = sorted list of `{path, type, mode, target?}` for every entry
  (relative paths, `mode` = `st_mode & 0o7777`, symlink `target` via `os.readlink`,
  **not** following symlinks). Skip the fixture's own restricted dirs gracefully.
  This is the primary golden.
- **mkdir `_Faults`:** replace sort's stdin/stdout faults with filesystem faults:
  `readonly_parent` (parent dir chmod `0o500` → EACCES), `file_as_parent` (a path
  component is a regular file → ENOTDIR), `missing_parent` (nonexistent parent, no
  `-p` → ENOENT), `unwritable_cwd`, `rlimit_nofile` (kept from sort, for deep `-p`),
  optionally `ELOOP` (symlink cycle) and `ENAMETOOLONG` (overlong component). Keep the
  `is_root()` → `SKIP_ROOT` sentinel (chmod-based EACCES faults are no-ops as root).
  Keep a `restore` list to chmod back so `TemporaryDirectory` cleanup succeeds.
- No stdin: drop `stdin_mode`, `case_stdin_bytes`, the file/pipe/redirect delivery.

### `model/flag_model.py` — the GNU mkdir flag surface (data only)
`FLAGS` dict, much smaller than sort's:
- `-p`/`--parents` (bool), `-v`/`--verbose` (bool), `-m`/`--mode` (value),
  `-Z`/`--context` (bool/value, **tagged `selinux`** and excluded by default like
  sort's `excluded_tags`, since it's Linux-only), `--help`, `--version` (tagged `doc`).
- `-m` value pools (the exhaustiveness engine for mkdir):
  - **valid:** octal `0000,0700,0755,0644,0777,2755,1777,4755,0111,0000`; symbolic
    `u+rwx`, `a=rx`, `go-w`, `u=rwx,g=rx,o=`, `+t` (sticky), `g+s` (setgid), `a-w`,
    `o+w`, `u+s`. (symbolic modes for mkdir apply relative to `a=rwx` base — captured
    from the oracle, not hand-computed.)
  - **invalid:** `""`, `8`, `0999`, `u+z`, `,`, `+`, `08`.
- `LONG_ALIASES` (`--parents`→`-p`, `--mode`→`-m`, `--verbose`→`-v`), `to_argv`,
  `default_value`, `preferred_inputs` (which corpus fixture a flag prefers), `tags_for`,
  `all_flag_ids`.

### `model/constraints.py` — mkdir combination legality + `predict_error`
mkdir's rule set is tiny (mkdir has almost no mutually-exclusive flags), so most of the
"negatives" come from **operand/mode/filesystem errors** rather than flag conflicts:
- `is_valid(flag_ids, values)` → `OK` unless: `-m` value is an invalid mode
  (`M_bad_mode`, exit 1), unknown flag (`unknown_flag`, exit 1). `-p`+`-m`, `-p`+`-v`,
  `-m`+`-v` are all **valid** (no conflict) — they route to positive goldens.
- `RULES`/`predict_error(rule_id)` → `ExpectedError(exit_code, stderr_contains)` for:
  `M_bad_mode`(1,"invalid mode"), `unknown_flag`(1,"unrecognized option"),
  `EEXIST`(1,"File exists"), `ENOENT`(1,"No such file or directory"),
  `ENOTDIR`(1,"Not a directory"), `EACCES`(1,"Permission denied"),
  `no_operand`(1,"missing operand"). Same freeze-time cross-check as sort: observed GNU
  exit must equal the predicted code or generation aborts (model-mismatch guard).
  Exact stderr is still captured from the oracle, not hardcoded here.

### `corpus/corpus.py` — path-operand + fixture fixtures, with a discrimination guarantee
mkdir "input" = target path operands + a starting filesystem, not stdin bytes.
- **CORE targets** (name → `{args, fixture}` skeleton pieces): `simple` (`newdir`),
  `multi` (`a b c` — several operands at once), `nested` (`a/b/c/d`, needs `-p`),
  `existing` (target dir already in fixture → EEXIST without `-p`, OK with `-p`),
  `partial` (`a/b` where `a` exists → needs `-p`), `trailing_slash` (`newdir/`),
  `dot_segments` (`a/./b`, `a/../b`), `abs_vs_rel`.
- **`assert_discriminating(mkdir_bin)`** (the mkdir analog of sort's mode-discrimination
  gate): run GNU mkdir under **different umasks** (`000/022/077`) and **with/without
  `-m`** on a probe target, and assert the resulting **modes differ** — proving the
  suite can tell a umask-ignoring or `-m`-ignoring mkdir from a correct one. Also assert
  `-p` vs no-`-p` differ on `nested`/`existing` (one errors, one succeeds). Abort
  generation if the corpus can't discriminate (corpus bug, not candidate bug).
- **ADVERSARIAL targets** (`build_adversarial`): very long single component
  (near `NAME_MAX`), very deep path (hundreds of components, with `-p`), names with
  spaces/newlines/tabs, unicode names, leading-`-` name (needs `--`), `.`/`..` operands,
  many operands (hundreds), a target whose parent is a symlink-to-dir (with `-p`),
  absolute path into the temp dir. (No NUL — illegal in paths.)

### `gen/combos.py` — case builders (`make_case`, singles, pairs, random)
Reuse `make_case`'s schema-v2 shape; swap `stdin_b64`/`files_b64` for **`fixture`** and
add **`umask`**. Drop stdin-mode plumbing.
- **`gen_singles`**: every flag alone across preferred targets; `-m` **sweeps its full
  valid pool** (each value × a couple targets) **and** — importantly — **crosses the
  umask sweep** (`000/022/077`) so the mode goldens exercise the umask×`-m` interaction
  that is the heart of mkdir correctness; `-m` invalid pool → negatives (`M_bad_mode`).
  Bare `mkdir DIR`, multi-operand, and `-v` (whose golden includes stdout text).
- **`gen_pairs`**: all unordered flag pairs (`-p -m`, `-p -v`, `-m -v`, plus `-p -m -v`
  as a curated triple) — small space, all positive.
- **`gen_random`**: seeded k-order combos over `{-p,-m,-v}` × target set × umask set,
  rejection-sampled, deterministic for a fixed seed (like sort's `gen_random`).

### `gen/curated_cases.py` — hardcoded quirks/errors/faults (where the "hardcoding" lives)
- **`build`** (curated quirks + error table, exact frozen stderr):
  - `err-eexist` (`mkdir existing` → EEXIST, exit 1), `err-eexist-ok-p`
    (`mkdir -p existing` → success, exit 0 — the key `-p` idempotency quirk),
    `err-enoent` (`mkdir a/b` with `a` missing → ENOENT), `err-notdir`
    (`mkdir afile/b` where `afile` is a file → ENOTDIR), `err-bad-mode`
    (`mkdir -m u+z d`), `err-no-operand` (`mkdir` alone → missing operand),
    `err-unknown` (`mkdir --nope`), `err-dashdir` (`mkdir -- -weird`).
  - **Semantic quirks pinned as golden tree+mode:** `quirk-p-mode-last-only`
    (`mkdir -p -m 700 a/b/c` — GNU applies `-m` **only to the final** dir; intermediates
    get `0777 & ~umask` — the tree snapshot proves it), `quirk-umask-default`
    (mode = `0777 & ~umask` with no `-m`), `quirk-m-ignores-umask` (`-m 777` yields 0777
    regardless of umask), `quirk-verbose-output` (`-v` stdout text is golden),
    `quirk-setgid-inherit` (fixture parent has setgid bit → child dir inherits it),
    `quirk-trailing-slash`, `quirk-multi-partial-fail` (`mkdir existing newdir` — one
    operand fails, the other still created; exit 1 but `newdir` present in tree).
- **`build_adversarial`**: cross the adversarial targets (§corpus) with a handful of
  flag sets (bare, `-p`, `-p -v`, `-m 700 -p`).
- **`build_faults`**: the filesystem fault cases — `fault-readonly-parent` (EACCES),
  `fault-file-as-parent` (ENOTDIR), `fault-missing-parent` (ENOENT, no `-p`),
  `fault-unwritable-cwd`, `fault-fdlimit-deep-p` (rlimit_nofile + deep `-p`), optional
  `fault-eloop`/`fault-nametoolong`. `check: none` (untrusted output), expected exit
  encoded, `faults` field drives the engine; `SKIP_ROOT` when run as root.

### `gen/freeze.py` — the oracle freezer
Same shape as sort's: run **GNU mkdir** via `engine.execute`, fill golden fields —
but the golden now includes **`tree`** (the post-run snapshot from `Result.tree`) in
addition to `exit_code`, `stdout_b64` (for `-v`), `stderr_b64`/`stderr_class`. Keep the
negative-case cross-check against `constraints.predict_error(rule_id)`. `check: golden`
freezes the tree; `property:*`/`none` omit it.

### `props.py` — mkdir property checks (lighter than sort's)
mkdir is deterministic given umask, so most cases are `golden`. Keep `props.py` for a
few invariants that shouldn't be byte-pinned across implementations:
- `check_idempotent_p`: running `mkdir -p X` when `X` already exists must exit 0 and
  leave `X` a directory (mode unchanged).
- `check_created`: for cases where the exact intermediate mode is platform-sensitive,
  assert only that each requested path exists and is a directory.
- `check_partial`: for multi-operand partial-failure, assert the good operands exist
  and the bad one's error is reported (exit 1).

### `diff_fuzz.py` — differential fuzzer vs GNU mkdir
Same architecture as sort's: seeded, time-boxed, candidate-vs-oracle. Each round:
`sample_combo()` draws a valid flag combo (weighted to `implemented` flags), generates
a random target path + starting fixture + umask, runs both binaries via
`engine.execute`, and `mismatch()` reports candidate crash/timeout/sanitizer (always a
finding) or **tree / exit-code / stderr-class divergence**. `mutate()` perturbs the
path (add/drop components, inject `..`, change case, add trailing slash, swap
existing↔missing parent). On a finding, `minimize()` by shrinking the path/fixture,
`explain()` with a tree diff, and `append_regression()` freezes a schema-v2 repro into
`suites/fuzz_regressions.json.gz` with cross-run dedup by `(args, reason-class)`.

## Config, README, self-validation

- **`config.json`**: `paths.candidate_bin` (required), `paths.oracle_bin` = **GNU
  coreutils mkdir** (default `/usr/bin/mkdir`; **note in comments**: on macOS the system
  `/bin/mkdir` is BSD — point this at Homebrew `gmkdir` / `$(brew --prefix)/opt/coreutils/libexec/gnubin/mkdir`),
  `candidate_asan_bin`/`candidate_src`/`cc`/`cc_flags` (optional ASan),
  `implemented` (flags the candidate supports — start small, grows coverage),
  `excluded_tags` (`selinux, doc`), `umask_sweep` (`["000","022","077"]`),
  `fuzz` (`seed`, `time_budget_s`).
- **`README.md`**: adapt sort's — "exhaustive, GNU-mkdir-backed suite for any
  `mkdir`-like binary: every flag alone (with a umask sweep), every flag pairing,
  random combos, curated EEXIST/ENOENT/ENOTDIR/mode-error cases, `-p`/`-m`/setgid
  semantic quirks, adversarial paths, filesystem fault injection, ASan/UBSan, and live
  differential fuzzing." Same three-step usage (`config.json` → `./run_all.sh` →
  optional `./selfcheck.sh`).
- **`selfcheck.sh`**: keep the four gates — (1+2) regenerate twice, require
  byte-identical `.json.gz` (determinism); (3) **oracle self-pass** — GNU mkdir passes
  100% of its own goldens with `--all-flags`; (4) **teeth** — deliberately-wrong mkdir
  shims MUST FAIL: e.g. a shim that (a) always adds `-p` (so it never reports EEXIST),
  (b) ignores `-m`/umask (always 0777), or (c) applies `-m` to *all* `-p` levels. Proves
  the suite discriminates. Plus the corpus `assert_discriminating` gate inside generation.

## Verification (end-to-end)

1. **Generate** (needs a GNU mkdir oracle): from `tests/mkdir-test-suite/`,
   `python3 gen/generate.py` → writes all `suites/*.json.gz` + `MANIFEST.json`.
   Confirm the discrimination assertion passes and per-tier counts print.
2. **Determinism**: `python3 gen/generate.py --out /tmp/mk1 --no-gzip` twice, `diff -r`
   the outputs — must be byte-identical.
3. **Oracle self-pass**: point `config.json` `candidate_bin` at the same GNU mkdir and
   run `python3 runner.py suites/*.json.gz --config config.json --all-flags -- <gnu-mkdir>`
   → expect 100% PASS (no FAIL/CRASH).
4. **Teeth**: run the runner against each wrong-mkdir shim → each must produce FAILs.
5. **Full pipeline**: `./run_all.sh` → three passes + `OVERALL SUMMARY`; `./selfcheck.sh`
   → all gates green.
6. **Fuzz smoke**: `python3 diff_fuzz.py --candidate <gnu-mkdir> --oracle <gnu-mkdir>`
   for a few seconds → zero distinct issues when candidate==oracle (sanity).
7. Decompress a couple of `suites/*.json.gz` and eyeball a `quirk-p-mode-last-only` and
   a `fault-*` case to confirm the `fixture`/`umask`/`tree` schema is well-formed.

## Notes / decisions

- **Standalone**: pure Python 3 stdlib + shell, no third-party deps; frozen goldens ship
  in `suites/`, so judging a candidate needs no GNU mkdir (only fuzz/regen do).
- **Oracle = GNU mkdir** (coreutils), matching the repo's GNU-coreutils theme; BSD mkdir
  differs on `-m`-under-`-p` and verbose wording, so the oracle must be GNU.
- **Root**: filesystem-permission faults are skipped (`SKIP_ROOT`) when running as root,
  exactly as sort skips its unreadable-file fault.
