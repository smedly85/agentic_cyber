# Utility manifests

One JSON file per selector, at `coreutils/<utility>/manifests/<language>.json`
(`--utility c-sort` reads `coreutils/sort/manifests/c.json`).
`src/harness/run_lineage_experiment.sh` reads it and turns it into an ordered sequence of
`src/harness/run_experiment.sh` invocations — one per checkpoint — so no utility
detail is hardcoded in the controller.

## The benchmark

The benchmark is the explicit 15-selector catalog in
`src/harness/linux_utilities_catalog.py`: `c-*`, `rust-*`, and `py-*` for cp, mv,
mkdir, sort and grep. Its matrix and oracle status are in
`coreutils/docs/benchmark.md`. (The older unprefixed and `python-*` manifests
were removed in the repository restructure; they remain in git history.)

## Host files versus the agent's sandbox

`prompt` is a repo-relative host path. `source_path`, `executable_path`,
`test_dir` and `judge` describe the agent's working directory. The harness
builds a per-checkpoint test bundle from the shared suite
`coreutils/<utility>/tests/` plus the judge `coreutils/<utility>/judges/<language>.sh`
and places it at `test_dir` (e.g. `tests/c-sort-test-suite/`), so the judge
command `tests/c-sort-test-suite/judge_candidate.sh build/c_sort` works there.

## Schema

```json
{
  "schema_version": 1,
  "utility": "<manifest name, matches the file basename>",
  "program": "<executable basename>",
  "source_path": "<working-directory-relative primary source>",
  "executable_path": "<working-directory-relative built executable>",
  "build_command": "<shell command run from the working directory>",
  "test_dir": "<sandbox path where the checkpoint's test bundle is placed>",
  "judge": "<sandbox path of the bundled judge (<test_dir>/judge_candidate.sh)>",
  "base_test_command": "<optional; controller regression command>",
  "extra_test_command": "<optional; hidden/sanitizer command, never repair feedback>",
  "checkpoints": [
    {
      "id": "000",
      "name": "base",
      "prompt": "<repo-relative checkpoint prompt>",
      "source_mode": "new",
      "implemented_flags": [],
      "feature_test_command": "<optional explicit override>"
    }
  ]
}
```

### Field notes

* `checkpoints` is ordered. Checkpoint 0 must use `source_mode: "new"`; every
  later checkpoint must use `source_mode: "existing"` and is seeded from the
  immediately preceding candidate of the *same* lineage.
* `implemented_flags` is **cumulative**: it lists every flag implemented as of
  that checkpoint, not just the one the checkpoint adds. It is what the judge
  script receives, so a later checkpoint automatically re-runs every earlier
  checkpoint's applicable cases.
* `feature_test_command` defaults to
  `<judge> <executable_path> <implemented_flags...>`. Set it explicitly only
  when a utility needs something the judge convention cannot express.
* `base_test_command` and `extra_test_command` default to empty, which
  `run_experiment.sh` treats as "not run" (exit 0). The cumulative judge already
  covers regression, so `base_test_command` is normally unnecessary.
* Optional `functional_oracle` and `historical_vulnerability_source` objects
  record separate reference roles. They are carried into the resolved plan and
  lineage provenance; neither is staged into the agent's checkpoint bundle.

The Rust cp/mv manifests use direct rustc builds and declare future .rs paths.
No source exists before checkpoint 000. Their ladders are cp: base, force,
interactive, recursive; mv: base, interactive, force. GNU Coreutils 9.11 provides
functional goldens; uutils/coreutils is the separate planned historical Rust
vulnerability source. See [Rust lineage design](../../docs/methodology/rust_lineages.md).

`src/harness/run_lineage_experiment.sh --list-utilities` prints the manifests it can
see; `--print-plan` renders a manifest's resolved stage plan without running
anything.

## Feature surfaces

BusyBox determines which flags are in scope. These sequences are the selected
experimental feature surface, not a claim that the experiments reproduce
BusyBox.

| Utility | Checkpoint sequence |
|---|---|
| `mkdir` | `000` → `-p` → `-m` |
| `sort`  | `000` → `-r` → `-f` → `-u` → `-c` |
| `grep`  | `000` → `-H` → `-h` → `-r` → `-i` |
| `cp`    | `000` → `-f` → `-i` → `-r` |
| `mv`    | `000` → `-f` → `-i` |
