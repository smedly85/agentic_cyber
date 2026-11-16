# Final standardized grep reproducibility audit

Date: 2026-11-15. Branch: `feature/standardized-grep`. Audited extension base:
`f51b9ad0eb74a935a8993552b6f633bb7b3ef304`. This audit generated no candidate,
trace, commit, push, merge or historical-result change.

## 1. Fingerprint compatibility — WARNING

All original 12 configurations must receive new fingerprints under the expanded
working tree. `scripts/lineage_plan.py` hashes shared execution inputs, and this
extension changes exactly six of those inputs relative to the extension base:

- `scripts/linux_benchmark.py`
- `scripts/docker_benchmark.py`
- `scripts/docker_benchmark_worker.py`
- `scripts/linux_utilities_catalog.py`
- `docs/benchmarks/linux-utilities-contract.md`
- `docker/linux-utilities/run.sh`

The original 12 manifests, prompts and canonical suite trees are unchanged. It
would be possible to preserve an old fingerprint only by executing the old,
byte-identical infrastructure from its old revision (or by maintaining a
separately versioned copy of that old protocol). Excluding the changed shared
inputs, selectively special-casing the old selectors, or rewriting sealed
metadata would falsely assert compatibility and is rejected.

The prior comparison report had two independent baseline errors. The historical
table was created at commit `5ffe7420253dfc18f466a2385678f17a30fb39fc`, while
the extension began at `f51b9ad0eb74a935a8993552b6f633bb7b3ef304` after
additional main-branch changes. In addition, `record_cross_language.py` used
`max_loops=0` and `timeout_seconds=0`, while the withdrawn after-values used the
planner CLI defaults of 3 and 1800. The corrected
`grep-extension-fingerprint-impact.json` records input hashes and deliberately
leaves final fingerprints null until a commit exists and a clean Linux checkout
can run one documented invocation. Windows CRLF working bytes must not be used as
the final Linux record.

Every checked-in formal trace already records its own `repository_commit` and
`config_fingerprint` in `runs/formal/*/lineages.json`. Those pairs, their image
locks and their plans are the association for old evidence; no old trace may be
resumed using revision-2 fingerprints. The execution schema can remain protocol
version 1, but the expanded 15/60 catalog is now identified as benchmark catalog
revision 2.

## 2. GNU grep oracle portability — BLOCKER for independent Vessel use

The local Linux/AMD64 lock is internally consistent:

- repository digest: `agentic-grep-oracle@sha256:cbbad98ee0789ff00de59bf1a3a825f38a137f86ee4a67c19e3fbd1528217508`
- platform image ID: `sha256:5a1839c2ff7be3eee3a8e482ab334aa174e9f2f16b8edc8be1c85387d1cc39bc`
- GNU grep source SHA-256: `2649b27c0e90e632eadcd757be06c6e9a4f48d941de51e7c0f83ff76408a07b9`
- installed grep binary SHA-256: `5f90bdcaa8d67f8cae1be43fb4ef0a1642c04a8dd0fd7870d33b9eb358b935f2`

Docker inspection resolved the repository digest to the recorded AMD64 platform
ID. The Dockerfile verifies the upstream source checksum. The build script and
runtime verifier now independently reject a binary hash mismatch and reject
non-AMD64 use. The base Coreutils image can be rebuilt from its public pinned
Python base digest and Debian snapshot, then supplied to the grep build by
immutable image ID.

That is sufficient for a fail-closed source rebuild, but not for retrieval of the
exact locked OCI object. Both `agentic-grep-oracle` and `agentic-c-linux-v1` are
local repository names. No registry location or `docker save` archive/hash is
recorded, and a clean Vessel host cannot pull either name. A rebuild may reproduce
the binary hash without reproducing the OCI manifest digest because image build
metadata can differ.

Before independent Vessel validation, either publish both images under pullable,
immutable registry digests or distribute verified `docker save` archives. Record
archive SHA-256 and byte count, load them on Vessel, then verify the repository
digest/platform ID, architecture, source checksum and binary checksum. No archive
or registry provenance is claimed by this branch.

## 3. Grep-specific validation — PASS

- All three manifests use the same five cumulative checkpoints: none, `-H`,
  `-H -h`, `-H -h -r`, and `-H -h -r -i`, with the documented long aliases.
- `tests/c-grep-test-suite` is the sole expectation owner. Rust and Python are
  thin descriptors. Staged public bundles admit only runner/controller files and
  checkpoint-selected public cases; candidate request serialization removes
  expectations and private metadata.
- The dedicated isolation check searched 167 held-out values across all five
  checkpoint bundles and found none reachable by a sandbox.
- The adapter invokes only `/opt/gnu/bin/grep` with `-a -F` under `LC_ALL=C`,
  adding `-i` only when implemented. The bounded grammar, ordinary-filename `-`,
  deterministic byte-sorted traversal and recursive symlink skipping are
  specification-derived exceptions. The contract now agrees with prompts and
  the frozen `r-skips-symlinks-during-traversal` case.
- The final pinned-oracle rerun passed public/held-out populations at every
  checkpoint: 63/9, 68/15, 77/19, 90/25 and 113/37 executed PASS counts, with
  expected later-feature SKIPs. All ten public/held-out mutations were detected.
- Candidate execution remains Docker-only with no network, a read-only root,
  dropped capabilities, no-new-privileges, finite limits, a chroot and dropped
  UID/GID. No host grep or native candidate fallback exists.
- The final Linux integrity/workflow run passed 50/50 tests; shell syntax passed.
  The original standardized manifests/prompts/suites, sealed cross-language and
  AMD64 reports, and every `runs/formal` tree have no diff relative to the
  extension base.

## 4. Conference reproducibility and cleanup — WARNING

The current entry points now distinguish the standardized 15-selector catalog
from unprefixed and `python-*` historical manifests. The active matrix is
`linux-utilities.md`; grep-specific evidence is in the validation addendum; the
cleanup inventory is explicitly non-destructive.

The genuinely retireable set is limited to the one-time preparation/reporting
scripts in cleanup category A, and even those should be removed only after an
immutable pre-cleanup tag/archive and a clean dependency audit. The two
compatibility wrappers directly execute `document_cross_language.py` and
`record_cross_language.py`, so each wrapper must retire with its target. Legacy
manifests, prompts, suites, formal traces, validation snapshots and measurement
journals remain category B because live byte audits or published provenance refer
to them. Repeated oracle snapshots remain D until their hashes are mapped.

External provenance is incomplete: diversity records name legacy grep, mkdir,
sort and chmod run trees that are absent from this checkout, and no verified
archive index or retrieval location was found. Those reports remain evidence but
cannot yet support a complete independent conference reproduction. Locate and
hash the external trees before deleting, moving or claiming archival completeness.

## Corrective changes made by this audit

1. Corrected the fingerprint impact record; removed incomparable provisional
   after-values and documented the six extension-modified shared inputs.
2. Added runtime and build-time grep binary checksum enforcement, explicit
   AMD64-only enforcement, and local-only distribution metadata to the grep lock.
3. Corrected the recursive-symlink contract to match prompts, corpus and adapter.
4. Labeled the 15/60 catalog revision 2 while retaining execution protocol 1.
5. Added current-versus-legacy navigation to the root and manifest READMEs.

## Required follow-up, ranked

1. **Critical before Vessel validation:** publish immutable registry references
   for both images or create and hash verified image archives; update a new lock
   and verify the clean-host load/pull.
2. **High before any formal trace:** after commit, compute all 15 final
   fingerprints from a clean Linux checkout using one recorded planner parameter
   set and retain the resulting report as catalog revision 2 evidence.
3. **High before legacy cleanup or complete conference claims:** publish an
   archive index mapping every missing legacy run path to a content hash and
   retrieval location; create a signed/annotated pre-cleanup tag and Git bundle.
4. **Medium:** rerun Vessel preflight and the full 15-selector validation against
   the independently loaded/pulled oracle. Do not launch formal traces as part of
   that validation.

## Recommendation

The source branch is ready for review and commit, and may be pushed as an
unmerged feature branch. It is not yet ready to claim independent Vessel oracle
reproduction or to launch formal grep traces. Do not merge into the
conference-facing branch until the critical image-distribution step is complete;
capture clean-Linux fingerprints before Vessel approval. No historical cleanup
should be combined with that commit.
