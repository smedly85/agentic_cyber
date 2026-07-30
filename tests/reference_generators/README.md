# Offline reference generators

Executable specification models for the utilities whose contract comes from the
checkpoint prompts rather than from a shipping implementation, plus the
model-dependent invariant checks that audit the goldens they produce.

**Nothing in this directory is ever visible to the experimental agent.** It is
outside every `tests/<utility>-test-suite/` directory, and
`scripts/stage_test_bundle.py` builds each stage's visible bundle from an
explicit allowlist that cannot reach here.

## Why it is not in the suite

A reference implementation of the utility under test is the answer sheet. The
sort and mkdir suites freeze their goldens from a GNU oracle binary, which is
external to the repository and never copied into a sandbox. `new_grep` and
`new_chmod` are deliberately bounded utilities with no valid external oracle, so
their oracle had to be written — and an oracle written *inside* the visible
suite would have been copied into the agent's working directory alongside the
tests, handing the model a complete, correct implementation to read.

Keeping the model offline preserves the property the other two suites get for
free: the agent sees frozen expected results, never the thing that produced
them.

## Contents

| File | Role |
|---|---|
| `grep_reference.py` | Specification model for `new_grep` — the oracle for its goldens |
| `chmod_reference.py` | Specification model for `new_chmod` — the oracle for its goldens |
| `grep_invariants.py` | Model-dependent invariants asserted over each frozen grep case |
| `chmod_invariants.py` | Model-dependent invariants asserted over each frozen chmod case |

The invariant modules live here rather than in the suites' `props.py` for the
same reason: they encode what a correct implementation must produce, and several
of their checks are written in terms of the model.

## Who uses them

Only offline tooling, all of which runs from the suite directory:

```bash
tests/grep-test-suite/gen/generate.py     # freeze suites/ from the model
tests/grep-test-suite/gen/verify.py       # freshness + invariants + reachability
tests/grep-test-suite/selfcheck.sh        # both of the above, plus config immutability
```

**The runtime judge does not use them.** `judge_candidate.sh` runs `runner.py`,
which imports only `engine` and `props`; both grep and chmod freeze
golden-comparison cases exclusively, so no case dispatches to a property check
that would need the model. A stage bundle therefore contains no path by which
the oracle could be reached, and the judge works from frozen expected results
alone.

## Regenerating

```bash
cd tests/grep-test-suite && python3 gen/generate.py        # rewrite suites/
cd tests/chmod-test-suite && python3 gen/verify.py         # full offline audit
```

Editing a model changes the contract and therefore the goldens. Do that only
alongside the corresponding checkpoint prompt change, and regenerate. Because
`scripts/lineage_plan.py` fingerprints each stage's visible bundle, regenerated
goldens invalidate an in-progress lineage run's resume — which is the intended
protection, not an obstacle.
