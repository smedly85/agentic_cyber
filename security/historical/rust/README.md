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

| CVE | Utility / component | Vulnerable function(s) | Source file(s) | Vulnerable version/revision | Fix revision | Depth applicability | Mapping status |
|---|---|---|---|---|---|---|---|
| CVE-2002-0435 | GNU Fileutils | not applicable |  |  |  | not_applicable | excluded |
| CVE-2021-29934 | od | PartialReader<R>::read | src/uu/od/src/partialreader.rs | 0.0.3 / 2bb9a85ddedc7b8aa1bd866bd70e41364c8783f7 | 39d62c6c1f809022c903180471c10fde6ecd12d1 | applicable | verified |
| CVE-2026-35338 | chmod | Chmoder::chmod | src/uu/chmod/src/chmod.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 413055b378fa6fe2299c5e5f538c8e6e841ab810 | applicable | verified |
| CVE-2026-35339 | chmod | Chmoder::chmod | src/uu/chmod/src/chmod.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | abd581f62e97d0b147306ac40eac13af71c6fbba | applicable | verified |
| CVE-2026-35340 | uucore/perms | ChownExecutor::dive_into | src/uucore/src/lib/features/perms.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | ebc08af9c34138f474b32ea0ef34bed3b086a3ed | applicable | verified |
| CVE-2026-35341 | mkfifo | uumain | src/uu/mkfifo/src/mkfifo.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 00f77cc7081f8e6837271d21b4fe8ca6d2f047c3 | applicable | verified |
| CVE-2026-35342 | mktemp | Options::from | src/uu/mktemp/src/mktemp.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | eb25ec328b226d8fbbaa4058bf9187165bf06d51 | applicable | verified |
| CVE-2026-35343 | cut | cut_fields_newline_char_delim | src/uu/cut/src/cut.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 9bbb58b746c41802278b0cba738eebbf21517cf7 | applicable | verified |
| CVE-2026-35344 | dd | BlockWriter::truncate | src/uu/dd/src/dd.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 0f538b942a5cdaba6e0960f6952429a1baaedf93 | applicable | verified |
| CVE-2026-35345 | tail | Observer::handle_event | src/uu/tail/src/follow/watch.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 2c2f1b0c1f11f120fc8cbf8d518194f6532c0607 | applicable | verified |
| CVE-2026-35346 | comm | comm | src/uu/comm/src/comm.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | b9372e509ea9b278fe13763237067a261bb8c946 | applicable | verified |
| CVE-2026-35347 | comm | are_files_identical | src/uu/comm/src/comm.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 75f45e87e52ed95840494963ab9a28651165d56e | applicable | verified |
| CVE-2026-35348 | sort | uumain | src/uu/sort/src/sort.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 6e28633263ea84aad9ef7a30750232b73fb9133f | applicable | verified |
| CVE-2026-35349 | rm | handle_dir | src/uu/rm/src/rm.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 5e5968cdbc6618acd6c2402a8a98b503f278835e | applicable | verified |
| CVE-2026-35350 | cp | copy_attributes | src/uu/cp/src/cp.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | bd170a5d4b19ed985417d322dffb8cade2cbbad5 | applicable | verified |
| CVE-2026-35351 | mv | rename_file_fallback; copy_file_with_hardlinks_helper; copy_dir_contents_recursive | src/uu/mv/src/mv.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 874efa7cc3361cb5af2a97db869147f910bcab44 | applicable | verified |
| CVE-2026-35352 | mkfifo | uumain | src/uu/mkfifo/src/mkfifo.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | c004672c5eb2415b03f11f766583c4b967ba024f | applicable | verified |
| CVE-2026-35353 | mkdir | create_dir | src/uu/mkdir/src/mkdir.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 037b9583bc03d814e8516df54ebcda6f681fe1f8 | applicable | verified |
| CVE-2026-35354 | uucore/fsxattr | copy_xattrs; retrieve_xattrs; apply_xattrs | src/uucore/src/lib/features/fsxattr.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 6372fd3b239add19bf863f9d3f1d3c4c91276711 | applicable | verified |
| CVE-2026-35355 | install | copy_file | src/uu/install/src/install.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | b5bbabc18a1121908848d836f869a4e98eb63886 | applicable | verified |
| CVE-2026-35356 | install | standard; copy_file | src/uu/install/src/install.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 0c41299975f3c1e21cf5ca968d42cad55ceb42a1 | applicable | verified |
| CVE-2026-35357 | cp | clone; sparse_copy_without_hole; sparse_copy | src/uu/cp/src/platform/linux.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 681030bca3d5fc8fa4886b75eaefc2ca04471668 | applicable | unresolved |
| CVE-2026-35358 | cp | copy_helper | src/uu/cp/src/cp.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | e6a3bb596f149628ba973eec3d099f3bb69f2464 | applicable | verified |
| CVE-2026-35359 | cp | clone; sparse_copy_without_hole; sparse_copy; copy_stream; copy_on_write; copy_on_write; copy_on_write | src/uu/cp/src/platform/linux.rs; src/uu/cp/src/platform/macos.rs; src/uu/cp/src/platform/other_unix.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | ef5d75228262d62f3ff2ad21d35323b1f6665820 | applicable | unresolved |
| CVE-2026-35360 | touch | touch_file | src/uu/touch/src/touch.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | ca0c842e71a9f75b31c87f701952f9e174a320ce | applicable | verified |
| CVE-2026-35361 | mknod | mknod | src/uu/mknod/src/mknod.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 42b2ad83cdcf6e959ecb378c5040c60d9c64becf | applicable | verified |
| CVE-2026-35362 | uucore/safe_traversal | not applicable | src/uu/chmod/src/chmod.rs; src/uu/du/src/du.rs; src/uu/rm/src/platform/mod.rs; src/uu/rm/src/rm.rs; src/uucore/src/lib/features.rs; src/uucore/src/lib/lib.rs | 0.5.0 / 64203e309810d7e01eaf9c6cc7c21df22a8a896d | 30239e69a328e76d2377f2a0bc02fbde61c34280 | not_applicable | not_applicable |
| CVE-2026-35363 | rm | path_is_current_or_parent_directory | src/uu/rm/src/rm.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | d0e5af23217ed671eeb8db586f12d6dc6cd79b75 | applicable | verified |
| CVE-2026-35364 | mv | rename_file_fallback | src/uu/mv/src/mv.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 7183073b3259ba06241b29470a9e7accbb4096e7 | applicable | verified |
| CVE-2026-35365 | mv | copy_dir_contents_recursive | src/uu/mv/src/mv.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 9654e4abaf24449ef2279e9a16963edb5c8b8fef | applicable | verified |
| CVE-2026-35366 | printenv | uumain | src/uu/printenv/src/printenv.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 0bfbbc00c7895c0fb6ea94987b4aab99e3d7ee52 | applicable | verified |
| CVE-2026-35367 | nohup | find_stdout | src/uu/nohup/src/nohup.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | acd51ef18d90e5c26f694df721f896fa1c4a9edc | applicable | verified |
| CVE-2026-35368 | chroot | set_context | src/uu/chroot/src/chroot.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | f33bfb9321e5ebef0ef703aa6bfc8ee95bd21e1f | applicable | verified |
| CVE-2026-35369 | kill | uu_app | src/uu/kill/src/kill.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 2d3aebce6712841bc08b9b94e9078be50a25fc10 | applicable | verified |
| CVE-2026-35370 | id | uumain | src/uu/id/src/id.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | ff382f527994b8a021ec0a086dec4c5cafa34f2a | applicable | verified |
| CVE-2026-35371 | id | pretty | src/uu/id/src/id.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 18a50ff513444da99dd8e09451ebecd2ebbe5758 | applicable | verified |
| CVE-2026-35372 | ln | link_files_in_dir | src/uu/ln/src/ln.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 394c4b17f2f382b4be9f54389bcb79028de02f39 | applicable | verified |
| CVE-2026-35373 | ln | link_files_in_dir | src/uu/ln/src/ln.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 48d030dfb2ca7659ee2735f09cda706c8245a3fc | applicable | verified |
| CVE-2026-35374 | split | instantiate_current_writer; instantiate_current_writer | src/uu/split/src/platform/unix.rs; src/uu/split/src/platform/windows.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 58040feb5c66fce588a7ffac299b3a23bd55cd81 | applicable | verified |
| CVE-2026-35375 | split | FilenameIterator::next | src/uu/split/src/filenames.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | d2b9550fe821a9a10bf0cec057509211357363f1 | applicable | verified |
| CVE-2026-35376 | chcon | process_file; change_file_context | src/uu/chcon/src/chcon.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 7cfc74e47ffab452663be6842d788a5164d9688b | applicable | verified |
| CVE-2026-35377 | env | SplitIterator::split_single_quoted_backslash | src/uu/env/src/split_iterator.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 9d7a0e849109c82262ac2d65324739aac690200f | applicable | verified |
| CVE-2026-35378 | expr | Parser::parse_simple_expression | src/uu/expr/src/syntax_tree.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 76b2f7877f558f3bfa78e3d4f49f022460f509b7 | applicable | verified |
| CVE-2026-35379 | tr | Sequence::flatten | src/uu/tr/src/operation.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 358063f3367cb23a1e5db314cfdbfeb607749b3d | applicable | verified |
| CVE-2026-35380 | cut | get_delimiters | src/uu/cut/src/cut.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 593f5b191e8b9c87e4292955999c2d0b5cbcce69 | applicable | verified |
| CVE-2026-35381 | cut | cut_fields_newline_char_delim | src/uu/cut/src/cut.rs | 0.2.2 / 3a07ffc5a9bd4c283e75afa548ba1f1957bad242 | 9bbb58b746c41802278b0cba738eebbf21517cf7 | applicable | verified |
| CVE-2026-93658 | install | not applicable |  |  |  | not_applicable | excluded |
