# Review bundle: `new_mkdir` base checkpoint, gpt-oss:120b vs qwen3:235b-a22b

Start with **`findings.md`** — it has the actual analysis, the numbers that
matter, and what conclusions are and aren't supported by this data. Everything
else in here is the evidence behind it.

## Layout

```
review-bundle/
├── findings.md            <- read this first
├── results.csv             one row per (model, temperature): every metric in findings.md
├── attempt_index.json      one row per attempt: pass/fail, stop reason, repair loops
├── gpt-oss-120b/
│   └── temp-<T>/
│       ├── experiment.json     model, prompt, temperature, validation commands, repair budget
│       ├── prompt.md            exact prompt text sent to the agent
│       ├── baseline/            starting source (empty, for this checkpoint's --source-mode new)
│       ├── analysis/            analyzer output for this temperature (see below)
│       ├── analysis.log         analyzer's own stdout for this temperature
│       ├── sources/              <attempt>-<PASS|FAIL>-<file>.c  -- the graded candidate
│       ├── extra-files/          files the agent wrote but that were never built or tested
│       ├── logs/                 <attempt>-build.log, -base-tests.log, -feature-tests.log,
│       │                         -extra-tests.log, -opencode.log, -repair-prompt-N.md
│       └── stats/                <attempt>-metadata.json, -opencode-stats.json, -opencode-stats.txt
└── qwen3-235b-a22b/
    └── temp-<T>/  (same layout; only temp-0p0, temp-0p125, temp-0p25 exist -- run stopped early)
```

## What's in each folder, and why it answers "did you check the actual runs"

- **`sources/`** is the actual code produced, one file per attempt, named
  `<attempt>-PASS-<file>.c` or `<attempt>-FAIL-<file>.c` so pass/fail is visible
  from the filename without opening anything. This is the file that was
  compiled and tested — it matches `source_path` in `experiment.json`.

- **`extra-files/`** holds files the agent wrote that were **not** the graded
  source — e.g. `attempt-004-new_mmkdir.c`, an abandoned draft under a typo'd
  filename that `--build-cmd`/`--feature-test-cmd` never touched. Present in 5
  of 87 attempts. Real agent output, kept for completeness, but not part of the
  scored result.

- **`logs/`** is the actual evaluation output: `build.log` is the compiler
  invocation and any errors/warnings; `base-tests.log` and `feature-tests.log`
  are the independent test-suite runs the *controller* ran after the agent
  finished (not self-reported by the agent), broken out per repair loop with
  specific failing test-case names and the exact stdout/stderr diff — e.g.:

  ```
  ===== VALIDATION LOOP 0: CHECKPOINT TESTS =====
  FAIL  quirk-trailing-slash  [curated.json.gz]  args=['trailed/']
        exit: got 1, want 0; tree: missing paths: ['trailed']; ...
  25/28 pass
  3 PROBLEM(S)
  ```

  `opencode.log` is the full transcript of that attempt's OpenCode session(s),
  including reasoning blocks and every tool call. `repair-prompt-N.md` is the
  exact continuation prompt sent into repair loop N, built from those same
  failures.

- **`stats/`** is per-session token counts, cost, wall/model time, and tool-call
  breakdown, pulled from OpenCode's own database
  (`scripts/opencode_stats.py`) — not something the agent reports about itself.
  `metadata.json` is the controller's own record of the attempt: stop reason,
  repair-loop count, per-loop source hash, timeout enforcement.

- **`analysis/`** is `analyze_experiment.py`'s output for that temperature:
  `summary.json` (the numbers `findings.md` and `results.csv` are drawn from —
  clustering, pass@k, repair recovery, reliability), plus its clang/tree-sitter/
  GumTree architecture measurements and pairwise diffs. This is the only
  derived (i.e. computed, not raw) data in the bundle; everything else is a
  direct copy of what the run produced.

## Known gaps

- **qwen3:235b-a22b is incomplete.** Only temperatures 0, 0.125, and 0.25 ran;
  0.5, 1.0, 2.0 were never started, and 0.25 has 7 attempts instead of 10 — the
  sweep was stopped mid-run. The attempt that was in flight when it was
  stopped produced no candidate or metadata and is excluded entirely (not
  counted as a failure). Comparisons between the two models are only valid at
  the three temperatures where both have data, and even there `n <= 10` per
  point — see `findings.md` for what that does and doesn't support.

- Every experiment's `analysis/summary.json` has `family_discovery_auc_at_kmax:
  null` — the sweep didn't pass `--diversity-k-max` to the analyzer, so DF@K
  curves exist only in full-population form.

## Reproducing a result

Each `experiment.json` records the exact model, prompt path, temperature, and
validation commands used. To reproduce analysis for one temperature directly:

```bash
python3 scripts/analyze_experiment.py \
    --experiment runs/experiments/<model>/000_base_new_mkdir/temp-<T> \
    --cluster-threshold 0.30 --strategy-threshold 0.30 --clean-output
```

The full sweep commands are in `findings.md` under "Reproducing".
