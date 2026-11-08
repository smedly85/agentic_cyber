# Vessel validation after repository cleanup

The required validation checks live in `scripts/validation/`, outside the frozen
benchmark suites. `scripts/run_vessel_validation_tests.py` loads explicit suites
and rejects import failures, empty suites, skipped tests, expected failures and
ordinary failures. It does not build images, generate candidates or approve runs.

## Coverage and retired references

The checks were audited against pre-cleanup commit
`5c128adb4b44477545fa2b8bea344c51b42f9ecb`.

| Deleted module | Former live callers | Replacement coverage |
| --- | --- | --- |
| `tests/test_docker_benchmark_integration.py` | `vessel_preflight.py` validation and fresh jail; `validate_cross_language.py`; Vessel guide | `test_runtime.py`: C Linux/architecture, UID/GID, finite resource limits, privilege/network/controller-asset isolation, timeout and compiler classification, missing-Docker refusal, all C boundaries and public/held-out negative controls |
| `tests/test_cross_language_docker.py` | Same callers | `test_runtime.py`: real Rust/Python jail and binary I/O, permissions, symlinks, syntax errors, timeouts, 30 boundary checks, 60 runtime mutation controls, permissive-boundary and missing-Docker rejection |
| `tests/test_cross_language_static.py` | `vessel_preflight.py`, `validate_cross_language.py`, static validator syntax glob | `test_integrity.py`: all 45 checkpoints, 12 distinct plans, cumulative flags, cross-language prompt/scenario parity, bundle and held-out isolation, historical byte preservation and narrow EOL allowances |
| `tests/test_linux_benchmark_static.py` | `validate_linux_static.py`, static validator syntax glob | `test_integrity.py`: filtered C plans/bundles, manifest identities, boundary contracts, no native fallback, syntax, deliberate held-out leak detection and canonical command enforcement |
| `tests/test_vessel_preparation.py` | Developer regression suite; its own syntax test named deleted files | `test_workflow.py`: focused image/provenance/environment, capture, approval, freshness, failure/cleanup, Docker endpoint and all-selector evidence regressions, plus dispatch and static-wrapper checks |

The old comparison against duplicate archived regenerated oracle corpora is no
longer a live dependency: cleanup removed those copies. The replacement verifies
all 12 canonical public/held-out corpora against retained manifest hashes and
checks held-out fingerprints. Historical inventory checks remain. The existing
fresh GNU oracle validation, public/held-out calibration and mutation controls
remain mandatory; static hash checks do not replace them.

Archived reports and inventories may still mention the old filenames. Those are
historical evidence and are not rewritten. Unrelated deleted-test references in
general README examples are not formal validation dependencies.

## Unchanged acceptance gates

Formal validation still has 16 command steps: oracle validation, runtime/integrity
checks, adapter calibration, all 12 checkpoint-000 entrypoints, and containerized
static checks. Existing prerequisite toolchain, judging-input and checkpoint
checks, required report files, hashes and zero return codes remain mandatory.
Docker execution settings, Linux/AMD64 selection and finite `vessel-8g` limits are
unchanged. Fresh pre-generation verification still runs the actual C/Rust/Python
jailed controls and checks the environment again afterward.

## Revalidation after a commit

A new HEAD invalidates the previous environment binding even when image IDs are
unchanged. A changed command list also invalidates previous validation reports.
Do not edit old provenance, validation or approval JSON to make it match.

After the patch is reviewed and committed, use a clean tracked checkout on Vessel:

1. Capture a **new** lock/provenance directory with `--prepare-vessel-lock` and
   the existing authentic `--build-record`. Capture inspects/probes existing
   images; it does not rebuild them. Their recorded build revision, Dockerfile
   hashes and pinned bases must still match. A mismatch must be investigated.
2. Select that absolute lock/provenance and the `vessel-8g` profile as described in
   [the Vessel guide](linux-utilities-vessel.md). Run `--validate-vessel-built`
   into a **new external directory**. Any failure remains a failure; no approval
   is written by validation.
3. Review all fresh reports. Only an explicit `--approve-vessel-validation` with
   `--approval-scope formal-vessel-8g` may write a new approval outside the sealed
   validation directory. Then use `--verify-vessel-built` with that same scope.

The 24-hour freshness bound, exact evidence hashes, clean checkout requirement,
image identities, active adapter lock, Docker environment and emulator binding
remain enforced. A VM boot ID alone is still an observation, as before; fresh
jailed execution remains required. No existing evidence is migrated or approved.

For development checks without Docker or model execution:

```bash
python3 -B scripts/run_vessel_validation_tests.py --suite workflow --suite integrity
python3 -B -m unittest scripts.validation.test_runtime.CompilerFailureClassification
```

These development checks do not constitute formal Vessel revalidation.
