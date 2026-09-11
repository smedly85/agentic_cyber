# Historical vulnerability depth dataset

This directory keeps vulnerability discovery separate from reproducible
function mapping:

```text
discovered historical issue
    !=
verified source-mappable historical record
```

`cve_census.json` is the broader discovery ledger. It may contain eligible,
excluded, or unresolved issues and records whether an issue is upstream GNU,
a downstream patch, a predecessor-package issue, or an unrelated
implementation. Its schema is `cve_census.schema.json`.

`records.json` is analysis-ready input. It must contain only source-mappable
records tied to an immutable Git commit in `source_revision`; no `TBD` values,
guessed functions, or speculative downstream mappings belong there.
`schema.json` validates the complete array.

## Data model and methodology

CVEs are discovered without reference to call depth. The historical vulnerable
source revision and all verified vulnerable functions are frozen before a call
graph is measured. A record declares one or more locations with the canonical
field:

```json
"vulnerable_functions": ["begfield", "another_verified_location"]
```

The array is non-empty and contains unique, non-blank strings. Patched
functions are recorded separately because a hardening patch may touch a
function without establishing it as a vulnerable location.

Analysis emits two levels:

- `historical_function_mappings`: one row per vulnerable function location,
  retaining the CVE, utility, mapping state, resolved function ID,
  raw graph reachability, `call_depth_status`, raw shortest call depth and
  path, normalized depth, direct callers/callees, and any evidence-gated
  unresolved indirect-dispatch boundary.
- `historical_record_mappings`: one row per CVE, retaining every function row,
  declared/mapped/reachable counts, an explicit overall mapping status, and
  minimum/maximum reachable location depth.

The summary exposes both the vulnerable-function-location depth distribution
and the distribution of each CVE's shallowest reachable location, plus counts
for nonnumeric depth states such as `unresolved_indirect_dispatch`. No fixed
"shallow" cutoff is inferred, and call depth is descriptive rather than a
claim that shallow functions are vulnerable.

Existing HVC selection support remains available only as an explicit CLI
option. A historical CVE is covered by a selection if at least one of its
verified, mapped-and-reachable vulnerable functions is selected. The HVC
denominator counts eligible CVE records, never vulnerable-function rows, and
per-location coverage remains in the output for future stricter definitions.

Historical data never affects generation, functional validation, dynamic
security findings, repair, or promotion.

## Reproduce the Coreutils 9.7 source tree

The analyzer never downloads or changes historical sources. Preparation is a
separate step:

```bash
bash security/historical/prepare_coreutils_9_7.sh
```

The script independently verifies that annotated tag `v9.7` peels to commit
`8e075ff8ee11692c5504d8e82a48ed47a7f07ba9`, verifies GNU's published release
archive SHA-256 with Python's portable `hashlib.sha256`, extracts the archive
under the ignored
`security/historical/sources/coreutils-9.7/` directory, and checks the exact
C/H fingerprint used by `source_tree_sha256()`:

```text
e089e110944a43864e4b754ba628fc2a7fbf8e59f216a2cbd6c8183d788507e1
```

The preparation scripts read the affected version, source revision, source
tree, and tree fingerprint from `source_manifest.json`; they do not maintain a
second hard-coded historical identity.

The 9.7 `sort` program itself has one program-owned translation unit,
`src/sort.c`. The configured GNU/Linux build metadata gives:

- `src_sort_SOURCES = src/sort.c`;
- `src_sort_LDADD` includes `src/libver.a` and `lib/libcoreutils.a`;
- the configured `libcoreutils.a` has 328 C-derived archive objects: 320
  direct C sources, the distributed Bison output `lib/parse-datetime.c`, and
  seven configured gnulib replacement sources supplied through `LIBADD`.

The manifest freezes those sources as 329 exact release-tree paths (the 328
library sources plus `src/sort.c`) instead of using `lib/**/*.c`. Automake also
generates `src/version.c` for `src/libver.a`; it contains only the `Version`
data definition and no function, so it contributes no node or edge to this
function call graph and is recorded but not added to the pristine release
tree. The configured scope can be reproduced and checked without compiling:

```bash
bash security/historical/prepare_coreutils_9_7_sort_scope.sh
```

On GNU/Linux, that wrapper prepares the verified release, runs an out-of-tree
configuration with `--disable-nls --without-selinux` and
`CC='gcc -std=gnu17'`, and checks the expanded Automake variables against the
exact `source_files` array in the manifest. `derive_coreutils_sort_scope.py`
fails if a configured archive object cannot be mapped deterministically or the
frozen list differs. On macOS, it does not misrepresent Apple Clang metadata as
the frozen GNU/Linux/GCC scope; it instead checks all 329 frozen paths against
the already revision- and fingerprint-verified source tree.

The scope is intentionally configuration-specific, not platform-independent.
For example, the inspected Clang 21 configuration activates `lib/float.c`
where the frozen GCC configuration does not. Running the verifier with a
different configuration fails instead of silently changing the graph; a study
using another target/toolchain must freeze and report that scope separately.

This is an archive-source superset, not a claim that all 328 members are
extracted into the executable. Static archive member extraction depends on the
symbols required at the successful final link. Obtaining the linker-exact
member set therefore requires a compatible historical build and link map. In
the current environment, GCC 15 and Clang 21 fail while compiling bundled
Coreutils 9.7/gnulib code (before the link), including incompatibilities around
`mbszero`, `wint_t`, and `c32tolower`; no linker-member set is fabricated.

The former 532-file scope contained 203 release-tree C files that are not even
inputs to this configured `libcoreutils.a` (38.2% of that scope; 532 is 61.7%
larger than 329). It also created resolved edges to unselected replacement
implementations such as bundled `fread`, `fprintf`, and `open`. For that reason,
the build-metadata-derived archive-source scope is the preferred conservative
source-level approximation.

The entry point is source-qualified as `src/sort.c::main`. The whole-tree C/H
fingerprint is independent of program filtering.

## Reproduce GNU grep 2.21 and its program scope

The second frozen identity is GNU grep 2.21. GNU's annotated Savannah tag
`v2.21` peels to:

```text
d930f765041bb2ad936056ddfdad60042d44bd9d
```

GNU's signed 2.21 release announcement identifies the official archive and
detached signature. The archive was verified with that signature and GNU's
official keyring (key `7FD9FCCB000BEEEE`), then frozen with the portable
SHA-256 used by the preparation script:

```text
archive SHA-256:          5244a11c00dee8e7e5e714b9aaa053ac6cbfa27e104abee20d3c778e4bb0e5de
whole-tree C/H SHA-256:   7118428355f3b5283654ea7c9c99e0b740a5aa7cd265114798204a6f488a7788
```

Prepare and authenticate the released source tree with:

```bash
bash security/historical/prepare_grep_2_21.sh
```

The script reads the affected version, source revision, source-tree location,
and tree fingerprint from `source_manifest.json`; the revision is not copied
into preparation or derivation code. It verifies the peeled Savannah tag,
uses Python `hashlib.sha256` for the archive, verifies the detached signature
against the GNU keyring when `gpgv` is available, extracts under the ignored
`security/historical/sources/grep-2.21/`, and fails closed on every required
identity or fingerprint mismatch.

The released `src/Makefile.am` declares seven `grep_SOURCES` translation
units, including `src/grep.c` (which contains `main`) and `src/kwset.c` (which
contains `bmexec_trans`). The configured link also uses
`lib/libgreputils.a`. For the frozen x86-64 GNU/Linux configuration,
`CC='gcc -std=gnu17'`, `--disable-nls`, and no usable PCRE development
library, that archive has 67 C-derived objects. The generated
`lib/colorize.c` wrapper selects the distributed `lib/colorize-posix.c`.

Unlike the Coreutils build, this historical grep build succeeds with the
current GCC toolchain. A GNU ld link map proves that 36 `libgreputils.a`
members are extracted. The formal manifest scope is therefore the
linker-exact 43-file closure: those 36 distributed library sources plus the
seven grep-owned translation units. The configured archive-source superset
has 74 files and is retained only for sensitivity analysis. Rebuild the
program, reproduce the link map, and verify the exact manifest list with:

```bash
bash security/historical/prepare_grep_2_21_scope.sh
```

On macOS the wrapper does not claim to reproduce a GNU/Linux/GNU-ld closure;
it verifies the 43 frozen paths against the authenticated tree instead.

The GNU bug report and upstream commit establish `src/kwset.c::bmexec_trans`
before depth is measured. The fix says `memchr_kwset` could leave `tp` beyond
`ep`, after which `bm_delta2_search` could read beyond the main input buffer;
it changes only `bmexec_trans` in the vulnerable source file and adds
`tests/kwset-abuse`. Savannah ancestry confirms that the fix commit
`83a95bd8c8561875b948cadd417c653dbe7ef2e2` is after `v2.21` and before
`v2.22`. NVD records versions 2.19 through 2.21 and CWE-119.

The frozen 43-file analysis uses Tree-sitter, resolves the entry point as
`src/grep.c::main`, and yields 371 functions, 119 reachable functions, maximum
reachable depth 10, and three unresolved ambiguous direct calls.
`bmexec_trans` resolves uniquely in `src/kwset.c`; its direct caller is
`bmexec`, and its direct callees are `bm_delta2_search` and `memchr_kwset`.
It is mapped, but without a resolved static path from `src/grep.c::main` under
the conservative call-graph model. Its `mapping_status` is
`mapped_without_resolved_static_path`, and its `call_depth_status` is
`unresolved_indirect_dispatch`; raw depth, shortest resolved path, and
normalized depth remain null. This does not assert that the function is dead
code. The frozen manifest predeclares the source-supported boundary where
`grepbuf` calls through `execute` and `Fexecute` is a possible target. The
analyzer verifies the resolved prefix `main -> grep_command_line_arg ->
grepdesc -> grep -> grepbuf`, the unresolved `execute` call, and the resolved
suffix `Fexecute -> kwsexec -> bmexec -> bmexec_trans`, but does not promote
that declaration into a synthetic call-graph edge or numeric depth. The
upstream patch supplies the observed runtime stack
`main -> grep_command_line_arg -> grepdesc -> grep -> grepbuf -> Fexecute ->
kwsexec -> bmexec -> bmexec_trans`, but the conservative graph does not turn
that dynamic evidence into a guessed direct edge.

The scope-sensitivity check keeps that result stable:

| Scope | C files | Functions | Reachable | Max depth | Ambiguous calls | `bmexec_trans` |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Minimal known-path units (`grep.c`, `kwsearch.c`, `kwset.c`) | 3 | 74 | 44 | 7 | 0 | unique; unresolved indirect dispatch |
| Frozen linker-exact scope | 43 | 371 | 119 | 10 | 3 | unique; unresolved indirect dispatch |
| Configured archive-source superset | 74 | 479 | 120 | 10 | 6 | unique; unresolved indirect dispatch |
| Whole-release C diagnostic | 295 | 1025 | 230 | 11 | 32 | unique; unresolved indirect dispatch |

All four scopes retain the same null shortest depth/path and the same direct
caller/callees for `bmexec_trans`; the same declared indirect-dispatch boundary
explains the missing numeric depth in each scope. The larger scopes add
resolved edges from
the known-path translation units (45 for the formal scope, 46 for the archive
superset, and 60 for the whole release), but the broad scopes also introduce
more duplicate definition names and ambiguous calls. The formal result
remains the predeclared linker-exact scope, independent of those outcomes.

The call-graph output includes `shortest_call_path` for every reachable
function. Ambiguous direct-call targets are retained as unresolved calls with
`reason = "ambiguous_target"`; extra translation units therefore cannot change
resolution silently.

## Reproduce Coreutils 5.2.1 mkdir and its program scope

The third frozen identity is the released GNU Coreutils 5.2.1 source. The
annotated Savannah tag `v5.2.1` peels to:

```text
808f8a1f569303c3f6838f2c8706442939d92593
```

The official `coreutils-5.2.1.tar.bz2` detached signature verifies with GNU's
official keyring and signing key `FDD2DEACD333CBA1` (Jim Meyering). GNU's
signed release announcement publishes SHA-1
`1028755ae0fa9be840576e4837004cf5a9981c45` (and MD5
`172ee3c315af93d3385ddfbeb843c53f`) for that archive; both match. No
contemporaneous GNU-published SHA-256 was located, so the repository also
freezes a portable SHA-256 of the signature-authenticated archive:

```text
archive SHA-256:          4eb124e9979a3ab1aaac2fbc7c3c55666b6530d2e3157dc0618782908cb2af1e
whole-tree C/H SHA-256:   7c7ad7a1955ca0ef4a1f899bcd1974a2ab17fee7c6a1a7a239ec08b0aff8ecf5
```

Prepare, authenticate, build, reproduce the GNU ld link map, and verify the
frozen source scope with the single Vessel command:

```bash
bash security/historical/prepare_coreutils_5_2_1_mkdir_scope.sh
```

`prepare_coreutils_5_2_1.sh` reads the version, peeled revision, tree path, and
tree fingerprint from the manifest; only the independently calculated archive
SHA-256 and published archive SHA-1 are stored in the script. It requires the
annotated upstream tag and
matching peel, downloads the official archive and signature when absent, uses
portable Python `hashlib`, verifies the signature whenever `gpgv` is available,
and fails closed on every required checksum, identity, or fingerprint mismatch.

The 5.2.1 source fixes the entry point at `src/mkdir.c::main`. The configured
`src/Makefile` declares `mkdir_SOURCES = mkdir.c` and links
`../lib/libfetish.a` twice around the optional internationalization library.
For the frozen x86-64 GNU/Linux configuration, `--disable-nls` with
`CC='gcc -std=gnu89 -fcommon'`, `libfetish.a` has 93 C-derived members. The
compatibility flags restore the language and tentative-definition behavior
expected by this 2004 source; the historical target builds successfully with
current GCC. A GNU ld map proves that only 13 archive members are extracted.
The formal exact 14-file scope is those members plus `src/mkdir.c`, not the
94-file configured archive-source superset. On macOS, the wrapper authenticates
the same source and verifies all frozen paths, but does not claim to reproduce
the GNU/Linux/GNU-ld member closure.

The function mapping was established before graph construction. For ordinary
`mkdir -m`, `src/mkdir.c::main` calls `make_dir` and then pathname-based
`chmod` on the newly created directory. For `mkdir -p -m`, the release calls
the historically correct `lib/makepath.c::make_path` name; when the requested
mode has special bits, that helper independently creates the final directory
and then applies pathname-based `chmod`. Both are therefore vulnerable
locations. `make_dir` merely creates the object and reports whether it was new,
so it is a caller-side helper and is not promoted. The later refactored
`make_dir_parents` is patch provenance, not a name projected backward into the
5.2.1 mapping.

Upstream commit `52893ffd2a3ff896e0b51f3f35bca191b71a47d4` first hardens
`main` through descriptor-based `chmod_safer`. Commits `a60cc14` and `76b12f0`
then replace the old helper and route mkdir through the redesigned
`make_dir_parents`/`dirchownmod` path. The official 5.97 source still has the
old pathname changes; the `v6.0` source contains the redesign and an
open/`fchmod`-capable `dirchownmod` implementation identical in the relevant
respect to `v6.1`. A later GNU response refers to then-current test version
6.1, but does not make it the first fixed release. Accordingly, 6.0 is the
earliest verified upstream fixed release; Debian's 6.10-1 package version is
not treated as an upstream release identifier. NVD provides only the general
`NVD-CWE-Other` classification, so no more specific CWE is invented.

As a release-to-repository correspondence check, `src/mkdir.c`,
`lib/makepath.c`, `src/Makefile.am`, `lib/Makefile.am`, and `configure` from the
signed archive all have the exact Git blob IDs found at the peeled `v5.2.1`
commit.

The frozen analysis uses Tree-sitter and resolves `src/mkdir.c::main`. Across
14 C files it finds 52 functions, 26 reachable functions, maximum reachable
depth 7, and zero unresolved ambiguous calls. Both locations map uniquely:

| Vulnerable location | Mapping | Raw depth | Shortest static path | Normalized depth |
| --- | --- | ---: | --- | ---: |
| `src/mkdir.c::main` | mapped and reachable | 0 | `main` | 0.0 |
| `lib/makepath.c::make_path` | mapped and reachable | 1 | `main -> make_path` | 1/7 (0.142857) |

The limited scope-sensitivity check keeps those depths and paths stable in the
minimal two known-path units and the formal 14-file link closure. The broader
scopes demonstrate why they are diagnostics only:

| Scope | C files | Functions | Reachable | Max depth | Ambiguous calls | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Minimal known-path units (`mkdir.c`, `makepath.c`) | 2 | 4 | 4 | 1 | 0 | both unique; depths 0 and 1 |
| Frozen linker-exact scope | 14 | 52 | 26 | 7 | 0 | both unique; depths 0 and 1 |
| Configured archive-source superset | 94 | 278 | 31 | 7 | 2 | `main` ambiguous; `make_path` remains depth 1 |
| Whole-release C diagnostic | 257 | 1354 | 39 | 7 | 27 | `main` ambiguous; `make_path` remains depth 1 |

The archive superset includes conditional/test code with another parsed
`main`; the whole release adds every other program entry point and unrelated
callers such as install. Those units create ambiguous or additional edges but
do not justify changing the predeclared formal scope or mapping. The raw
`make_path` depth and structural path do not change; its entry label becomes
source-qualified (`src/mkdir.c::main`) once duplicate `main` definitions are
present. Per-scope normalization is 1.0 in the minimal graph and 1/7 in the
formal graph because each normalization uses that graph's maximum reachable
depth; only the formal 1/7 value is reported as the historical result.

## Run depth characterization

After preparation:

```bash
python3 security/historical/run_historical_analysis.py \
  --source-manifest security/historical/source_manifest.json \
  --records security/historical/records.json \
  --output build/historical-analysis.json
```

Missing or mismatched source versions, fingerprint mismatches, invalid or empty
scopes, unresolved entry points/functions, ambiguous names, and mapped but
functions without a resolved static path remain distinct fail-closed states.

The preserved comparison infrastructure is opt-in and is not part of the
current call-depth smoke test. A later study can add `--coverage-study` plus
`--k`, `--percent`, and `--random-seeds` after the historical census and frozen
mappings are complete.
