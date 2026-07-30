# Utility manifests

One JSON file per experimental utility. `scripts/run_lineage_experiment.sh`
reads the manifest named by `--utility` and turns it into an ordered sequence of
`scripts/run_experiment.sh` invocations — one per checkpoint — so no utility
detail is hardcoded in the controller.

## Schema

```json
{
  "schema_version": 1,
  "utility": "<manifest name, matches the file basename>",
  "program": "<executable basename>",
  "source_path": "<working-directory-relative primary C source>",
  "executable_path": "<working-directory-relative built executable>",
  "build_command": "<shell command run from the working directory>",
  "test_dir": "<repo-relative visible test suite copied into the sandbox>",
  "judge": "<repo-relative checkpoint judge script>",
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

`scripts/run_lineage_experiment.sh --list-utilities` prints the manifests it can
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
| `chmod` | `000` → `-R` → `-c` → `-v` → `-f` |
