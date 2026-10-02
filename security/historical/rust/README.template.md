# Rust/uutils historical population: pre-measurement freeze

This is a **separate** study namespace. The frozen GNU/C v2 population,
mappings, measurements and evidence are unchanged. Scope is published CVEs
assigned to Rust code owned by `uutils/coreutils`, including its shared uucore
library, through **2026-09-11**, the same publication cutoff as the C study.
No compilation, semantic call graph, BFS, depth calculation, threshold,
depth-based selection or buildability-based exclusion was performed.

## Census reconciliation

The independently reconciled population has **45 CVEs**: the 44 assignments
CVE-2026-35338 through CVE-2026-35381 and CVE-2021-29934. The expected census
therefore matches, but was not the inclusion rule. The repository advisory API
returned 65 distinct advisories, of which 44 carried CVE assignments. Its second
page repeated the first response and was deduplicated. NVD's `uutils` search
returned 45 records: the 44 audit CVEs and a later CVE, not the older od CVE.
RustSec's repository tree and uu_od advisory supply that older assignment.
RustSec's scoped tree search found no other uu_*/uucore/coreutils package advisory
directory. GitHub ecosystem advisories, the oss-security disclosure and
Canonical's announcement provide cross-checks. All included CVE records are
PUBLISHED, not rejected or withdrawn. GHSA aliases are deduplicated by CVE.

Two discovered records are explicitly outside the population:

- **CVE-2026-93658**, uutils install, published **2026-09-18**: after cutoff.
  Its repository GHSA still lacks cve_id in the cached feed; the CVE record
  establishes the alias. Advisory publication and CVE publication differ.
- **CVE-2002-0435**, GNU Fileutils: a different implementation family, not Rust.

The discovery audit retains the 21 repository advisories without a CVE field,
including the subsequently resolved install alias. They are not silently counted
as CVEs. No dependency-only CVE was encountered in the scoped searches; this is
not a claim that all transitive dependencies have no vulnerabilities. Arbitrary
crate advisories are outside this source-owned population. Discovery is a dated
snapshot: later retroactive assignments require an explicit new freeze.

## Mapping status and specimens

There are **42 verified function-level CVEs**, **2 unresolved function-level
CVEs with verified partial locations**, and **1 configuration-only CVE**.
Two function-level CVEs reside in shared runtime library code (35340 and 35354);
these are a subset, not additional population units. Configuration-only 35362
also concerns shared code, but is not a shared *runtime function* record.

43 audit CVEs use released tag **0.2.2**, exact audited commit
`3a07ffc5a9bd4c283e75afa548ba1f1957bad242`. Configuration CVE-2026-35362 uses
**0.5.0**, `64203e309810d7e01eaf9c6cc7c21df22a8a896d`: direct source review
found that the common audit revision lacks safe_traversal entirely, whereas
0.5.0 contains the vulnerable Linux-only gate and is within the affected range.
The advisory's boilerplate audit revision is therefore not used for this CVE.
CVE-2021-29934 uses **0.0.3**,
`2bb9a85ddedc7b8aa1bd866bd70e41364c8783f7`. Tag metadata, archives and individual
mapped source files are SHA-bound in `source_manifest.json`. This is HTTPS/tag
provenance, not a claim to have verified release signatures. Selection follows
released vulnerable specimens, not current main or the function after repair.
Public fixes discovered after the publication cutoff may inform retrospective
mapping; the cutoff governs CVE inclusion, not evidence-retrieval dates.

Function membership comes from advisory/fix reasoning checked against vulnerable
source. Merely being touched by a patch is insufficient. New helpers, tests,
diagnostics and propagation-only callers are excluded. Multiple independently
supported sites are retained without a shallowest-site choice. In particular,
mkdir's vulnerable `create_dir` is not renamed to the later patch's
`create_single_dir`. The mv pilot maps to `copy_dir_contents_recursive`.
Shared xattr records distinguish mv's assigned scope from cp's source-supported
expected exposure. Executable lists are not semantic reachability results.

**Human review required before measurement:**

- 35351: verified mapping is restricted to the three paths explicitly named in
  issue 9714. Additional ownership-restoration sites changed by PR 11706 are
  remediation-completeness changes, not additional vulnerable functions.
- 35357: three Linux creation sites establish private-read exposure; stream
  write-permission and standard-library fallback hardening do not alone prove
  additional locations of this CVE. Mapping remains explicitly unresolved.
- 35359: seven branch-qualified data-copy locations are confirmed. The previous
  non-Unix other.rs record is withdrawn; explicit stream sites in other_unix.rs
  and macos.rs are included separately. Probe-only opens are not mapped merely
  for opening the source. Opaque native/delegated cases still prevent a complete
  platform-wide mapping; the status remains unresolved.
- 35361: mapping to mknod is verified by the direct cleanup correction. Atomic
  SELinux labeling remains solely a remediation-history nuance, not a mapping
  uncertainty.
- 35354: file xattr and directory xattr repairs occur separately. The recorded
  final corrective PR must not be confused with the advisory's first fixed release.
- 35370: structured advisory fixed-version data supersedes stale narrative;
  an unmerged proposal is not a fixing commit.
- 35381: the CNA's later PR is a regression/whitespace follow-up. The earlier
  substantive runtime fix is recorded, preserving both CVE IDs.

`mapping_frozen_before_semantic_measurement: true` freezes this reviewed snapshot
**including its unresolved statuses**. It does not turn partial mappings into
complete ones. No depth result fields or placeholder results exist. Measurement
must wait for review of this complete table and explicit resolution/disposition
of the remaining mapping uncertainties in a versioned amendment.

## Artifacts and offline verification

- `population.json` and schema: all discovered CVEs, inclusion decisions,
  publication dates, aliases, version assertions and discovery reconciliation.
- `vulnerable_function_mappings.json` and schema: source-qualified functions,
  exact vulnerable/fix revisions, reasons, confidence and uncertainty.
- `source_manifest.json`: specimens, source hashes and cached evidence URLs,
  byte hashes and actual UTC retrieval dates. No machine-specific oracle path.
- `evidence/<CVE>.md`: one dossier for each included or explicitly excluded CVE.
- `mapping_table.tsv`: the same eight-column table below.
- `freeze_manifest.json`: deterministic canonical-JSON fingerprints of the
  three main artifacts, plus hashes of rendered dossiers/table/documentation.
- `protected_c_artifacts.json`: content locks on pre-existing historical files
  and methodology; text CRLF/LF is normalized solely for cross-platform hashing.
- `review.py`: explicit curated mapping decisions; `freeze.py`: deterministic
  offline renderer. Lexical source-name existence checks are not a Rust parser.

Run offline from repository root:

```sh
python3 security/historical/rust/validate.py
python3 -m unittest discover -s tests -p 'test_rust_historical.py' -v
```

No test needs a network connection, historical source checkout, Rust compiler,
oracle, call graph backend or ignored cache. To verify regeneration, the recorded
research cache is additionally required:

```sh
python3 security/historical/rust/freeze.py --check
```

`research.py URL ...` is explicit one-time public-evidence acquisition into ignored
`build/historical-rust/cache`, with checksum-verified reuse. It never extracts
archive paths, executes historical source or stages source into experiment-agent
sandboxes. `freeze.py --write` is an explicit research maintenance operation,
not ordinary validation. Cached API responses are mutable upstream, so exact
regeneration requires the SHA-matching responses, not blindly re-downloading
current responses. New responses require review and a new fingerprint.

GNU Coreutils remains the independent functional oracle for generated Rust
experiments. **uutils is the historical Rust vulnerability source**. These roles
are separate; this namespace adds no candidate code or functional goldens.
The C parser/LLVM/SVF pipeline is not claimed to support Rust. A future Rust
semantic backend must separately define entry points, application functions,
shared-code executable associations and runtime/library filtering. None is
implemented here.

## Complete mapping table

Repeated function names in platform files are separate source-qualified
identities. The two excluded discoveries remain visible for auditability.
Unresolved rows show only established locations, not a claim of exhaustiveness.

<!-- MAPPING_TABLE -->
