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
  reachability, raw shortest call depth and path, normalized depth, and
  direct callers/callees.
- `historical_record_mappings`: one row per CVE, retaining every function row,
  declared/mapped/reachable counts, an explicit overall mapping status, and
  minimum/maximum reachable location depth.

The summary exposes both the vulnerable-function-location depth distribution
and the distribution of each CVE's shallowest reachable location. No fixed
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

The call-graph output includes `shortest_call_path` for every reachable
function. Ambiguous direct-call targets are retained as unresolved calls with
`reason = "ambiguous_target"`; extra translation units therefore cannot change
resolution silently.

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
unreachable functions remain distinct fail-closed states.

The preserved comparison infrastructure is opt-in and is not part of the
current call-depth smoke test. A later study can add `--coverage-study` plus
`--k`, `--percent`, and `--random-seeds` after the historical census and frozen
mappings are complete.
