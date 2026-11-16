# Legacy benchmark cleanup audit

Date: 2026-11-15. This is an inventory only. No historical file was deleted,
moved, rewritten or unsealed. Any retirement should be a separate commit after
reviewing this report and the standardized grep validation addendum.

## Classification rules

- **A — Safe to retire after verification:** no active standardized runtime
  dependency; preserve an immutable archive and update only current navigation.
- **B — Retain for reproducibility or historical evidence:** published results,
  live historical-byte checks or measurement provenance depends on the path.
- **C — Retain temporarily until standardized grep is validated:** the gate is
  now satisfied; no item remains in C, but C must be reconsidered if the final
  sealed regeneration or adapter validation is invalidated.
- **D — Uncertain:** references, imports or provenance need a separate audit.

Git history alone is necessary but not sufficient for sealed results: external
model artifacts, Docker images and exact run trees need an independently hashed
archive before a conference-facing cleanup.

## A — Safe to retire after verification

| Exact path | Current purpose | Active standardized dependency | Historical/hash/import findings | Retirement condition |
|---|---|---|---|---|
| `scripts/prepare_linux_languages.py` | One-time Rust/Python standardization generator | None; must not be rerun | Listed in old file inventories, not imported by active orchestration | Archive bytes, then remove in cleanup commit |
| `scripts/prepare_linux_names.py` | One-time selector/path naming migration | None | Historical naming reports cite it; no live importer | Archive with cross-language validation evidence |
| `scripts/wire_linux_languages.py` | One-time wiring migration | None | Historical inventory only; active wiring is already committed | Archive, then remove after a clean 15-selector audit |
| `scripts/document_cross_language.py` | Generated the old 12-configuration report/evidence | None for execution | `scripts/record_linux_delivery.py` delegates to it; old reports cite it | Retire together with that wrapper after preserving generated reports |
| `scripts/record_cross_language.py` | Old environment/report recorder | None for current validation | `scripts/record_linux_environment.py` delegates to it | Retire recorder and wrapper as one unit |
| `scripts/record_linux_delivery.py` | Compatibility wrapper for the old report generator | None | Imports `document_cross_language.py`; recorded by old hashes/status | Retire only with the delegated generator |
| `scripts/record_linux_environment.py` | Compatibility wrapper for old environment recording | None | Imports `record_cross_language.py` | Retire only with the delegated recorder |
| `tmp/` | Untracked local validation outputs from this task | None | No historical provenance; disposable after copying required evidence into this addendum | Remove only the task-created directory after review |
| `**/__pycache__/` and `**/*.pyc` when untracked/ignored | Interpreter cache | None | Not evidence unless a tracked inventory explicitly names it | Delete as cache after `git ls-files` confirms untracked |
| `build/` when untracked/ignored | Compiler/analysis cache | None | Regenerable; published journals may name commands but not require cache bytes | Delete only after confirming no sealed result symlink points into it |

The A scripts are not part of the current planner path. Their information is
preserved in immutable Git history and the existing cross-language validation
reports; the cleanup commit should replace obsolete command examples with links
to the retained reports rather than editing those reports.

## B — Retain for reproducibility or historical evidence

| Exact path | Current purpose | Active standardized dependency | Historical/hash/import findings | Why retain |
|---|---|---|---|---|
| `experiments/utilities/cp.json` | Legacy Rust cp experiment | No standardized selector dependency | Live `test_historical_language_experiments_preserved` hashes it; historical runs use it | Required evidence |
| `experiments/utilities/mv.json` | Legacy Rust mv experiment | No | Live historical-byte test hashes it; legacy option order differs from standardized mv | Required evidence |
| `experiments/utilities/mkdir.json` | Legacy C mkdir experiment | No | Diversity and historical reports reference it | Preserve result interpretation |
| `experiments/utilities/sort.json` | Legacy C sort experiment | No | Diversity reports reference it | Preserve result interpretation |
| `experiments/utilities/grep.json` | Legacy C grep experiment | No; standardized grep uses new manifests | Published grep diversity measurements reference it | Preserve published evidence despite replacement |
| `experiments/utilities/chmod.json` | Legacy C chmod experiment | No standardized replacement | Published diversity/security work references it | No replacement exists |
| `experiments/utilities/python-cp.json` | Legacy Python cp experiment | No | Live historical-byte test hashes every `python-*` manifest | Required evidence |
| `experiments/utilities/python-mv.json` | Legacy Python mv experiment | No | Same | Required evidence |
| `experiments/utilities/python-mkdir.json` | Legacy Python mkdir experiment | No | Same | Required evidence |
| `experiments/utilities/python-sort.json` | Legacy Python sort experiment | No | Same; Darwin contract differs from standardized Linux sort | Required evidence |
| `prompts/cp/` | Legacy Rust cp ladder | No | Live historical-byte audit; old traces and measurements name exact paths | Required evidence |
| `prompts/mv/` | Legacy Rust mv ladder | No | Live audit and trace provenance | Required evidence |
| `prompts/mkdir/` | Legacy C mkdir ladder | No | Live historical-byte audit includes relevant suite; diversity data names prompts | Required evidence |
| `prompts/new_sort/` | Legacy C sort ladder | No | Diversity measurements name exact prompt paths | Required evidence |
| `prompts/grep/` | Legacy C grep ladder | No | Published grep trajectories and measurements name exact paths | Required evidence |
| `prompts/chmod/` | Legacy C chmod ladder | No | Published chmod trajectories and measurements name exact paths | Required evidence |
| `prompts/python-cp/` | Legacy Python cp ladder | No | Live historical-byte audit | Required evidence |
| `prompts/python-mv/` | Legacy Python mv ladder | No | Live historical-byte audit | Required evidence |
| `prompts/python-mkdir/` | Legacy Python mkdir ladder | No | Live historical-byte audit | Required evidence |
| `prompts/python-sort/` | Legacy Python sort ladder | No | Live historical-byte audit | Required evidence |
| `tests/cp-test-suite/` | Legacy Rust cp corpus/runner | No | Live byte audit and original rename comparison | Required evidence |
| `tests/mv-test-suite/` | Legacy Rust mv corpus/runner | No | Live byte audit | Required evidence |
| `tests/mkdir-test-suite/` | Legacy C mkdir corpus/runner | No | Live byte audit; standardized corpus was derived and separately frozen | Required evidence |
| `tests/sort-test-suite/` | Legacy C sort corpus/runner | No | Live byte audit and diversity evidence | Required evidence |
| `tests/grep-test-suite/` | Legacy C grep corpus/model/oracle | No runtime import from standardized grep | Published grep traces/measurements rely on its exact contract and goldens | Required historical evidence |
| `tests/chmod-test-suite/` | Legacy C chmod corpus/model/oracle | No standardized replacement | Published chmod evidence | Required historical evidence |
| `tests/python-cp-test-suite/` | Legacy Python cp corpus/runner | No | Live historical-byte audit | Required evidence |
| `tests/python-mv-test-suite/` | Legacy Python mv corpus/runner | No | Live historical-byte audit | Required evidence |
| `tests/python-mkdir-test-suite/` | Legacy Python mkdir corpus/runner | No | Live historical-byte audit and Python repair audit | Required evidence |
| `tests/python-sort-test-suite/` | Legacy Python sort corpus/runner | No | Live audit explicitly hashes its manifest | Required evidence |
| `docs/checkpoint_diversity_measurements.json` | 10.5 MB durable measurement journal | Analysis entry point | Names legacy prompts, suites, commands and candidate sources | Published measurement evidence, not cache |
| `docs/checkpoint_diversity_trajectories.json` | 2.8 MB trajectory record | Analysis entry point | Names legacy run and prompt paths | Published evidence |
| `docs/final_checkpoint_diversity_sample.json` | 2.6 MB sampled result | Analysis entry point | Names legacy candidate paths | Published evidence |
| `docs/ordered_diversity_phase27_feasibility.json` | 2.1 MB feasibility result | Analysis entry point | Derived research evidence | Retain with paper artifacts |
| `docs/ordered_diversity_threshold_pairwise.json` | 1.45 MB pairwise result | Analysis entry point | Derived research evidence | Retain with paper artifacts |
| `runs/formal/c-cp-vessel8g-5/` | Sealed standardized C cp traces | Current/published trace evidence | Source for candidates, prompts, logs, held-out reports and fingerprints | Never treat as cache |
| `runs/formal/c-mv-vessel8g-5/` | Sealed standardized C mv traces | Same | Same | Retain |
| `runs/formal/rust-cp-vessel8g-5/` | Sealed standardized Rust cp traces | Same | Same | Retain |
| `runs/formal/rust-mv-vessel8g-5/` | Sealed standardized Rust mv traces | Same | Same | Retain |
| `runs/formal/py-cp-vessel8g-5/` | Sealed standardized Python cp traces | Same | Same | Retain |
| `runs/formal/py-mv-vessel8g-5/` | Sealed standardized Python mv traces | Same | Same | Retain |
| `docs/benchmarks/cross-language-validation/` | Original hashes, fingerprints, rename and environment evidence | Live integrity tests read several files | Preserves old bytes and prior fingerprint basis | Sealed validation evidence |
| `docs/benchmarks/validation-amd64/` | Original Linux/AMD64 validation outputs | Reproduction evidence | Contains image/oracle/corpus records | Do not rewrite or deduplicate in place |

The six checked-in `runs/formal/*-vessel8g-5/` trees total approximately
477,526,860 bytes. Their nested `.aider/caches/`, repeated test bundles and logs
look mechanically redundant, but measurements and provenance can refer to exact
paths or hashes. They remain B until a content-addressed archive proves that a
thinned representation reproduces every published input and derived result.

## C — Retain temporarily until standardized grep is validated

No path remains in C. The standardized grep corpus, all three Docker adapters,
boundary gates, mutations and deterministic sealed oracle regeneration passed.
If those results are invalidated, move `experiments/utilities/grep.json`,
`prompts/grep/`, `tests/grep-test-suite/`, and
`tests/reference_generators/grep_invariants.py` back to C pending investigation;
do not delete them.

## D — Additional dependency or provenance investigation

| Exact path | Current purpose | Dependency finding | Investigation needed |
|---|---|---|---|
| `tests/reference_generators/grep_invariants.py` | Offline invariant checks for the legacy grep model | Standardized grep does not import it; legacy verification does | Decide whether it belongs inside the legacy archive or remains shared documentation |
| `tests/reference_generators/oracle_contract.py` | Cross-legacy oracle identity helpers | Refers to grep, mkdir and sort legacy suites | Split by archived suite before removal |
| `tests/reference_generators/README.md` | Legacy generator entry point | Documents direct legacy regeneration commands | Replace with archive navigation only after preserving the old workflow |
| `tests/reference_generators/chmod_invariants.py` | Legacy chmod invariants | Chmod has no standardized replacement | Retain unless chmod is archived wholesale |
| `runs/formal/*` paths named by diversity JSON but absent from this working tree, including `grep-qwen38-t1-seed42-low-ctx64k-max64k-n10/`, `mkdir-qwen38-t1-seed42-low-ctx64k-max64k-n10/`, `sort-qwen38-t1-seed42-low-ctx64k-max64k-final-n10/`, and `chmod-qwen38-t1-seed42-low-ctx64k-max64k-n10/` | Referenced legacy trace sources | Current reports contain exact paths, but the directories are not present here | Locate the external reproducibility archive and verify hashes before conference claims or cleanup |
| Repeated oracle copies under `docs/benchmarks/validation-amd64/oracle-006/`, `docs/benchmarks/validation-amd64/oracle-007/`, `docs/benchmarks/cross-language-validation/final-oracle/`, and `docs/benchmarks/cross-language-validation/rename-oracle/` | Prior validation snapshots | Some duplicate compressed corpora exceed 5 MB each | Confirm which snapshots are sealed inputs versus replaceable copies; never deduplicate before hash mapping |

## Archive and deletion strategy

Before any cleanup commit:

1. Create an annotated, preferably signed tag such as
   `conference-legacy-benchmarks-v1` at the exact pre-cleanup commit.
2. Produce a `git bundle` containing all refs required by that tag and a
   content-addressed archive of every checked-in `runs/formal/` tree plus any
   currently external legacy run tree. Record SHA-256, byte count and retrieval
   location in a small tracked index.
3. Archive the Coreutils and grep OCI images with `docker save`; record archive
   hashes separately from repository/image digests.
4. Re-run the historical hash audit and the 15-selector validation against the
   tagged tree. Verify that every diversity/security report resolves all source
   paths or its archive mapping.
5. First retire only A scripts and disposable caches. Next remove legacy
   manifests/prompts/suites as one dependency-closed unit only if their B/D
   classification has been resolved by the archive. Update active navigation and
   manifest discovery, but do not edit sealed reports to hide missing paths.
6. Keep formal traces and published measurement journals last. Prefer moving
   them to an immutable reproducibility release rather than deleting them.

Recommended commit order: archive index/tag documentation; one-time script
retirement; legacy manifest/prompt/suite retirement; optional large-artifact
externalization with verified path map. Each phase should be independently
reviewable and revertible. Do not combine cleanup with grep infrastructure or
with a formal experiment run.
