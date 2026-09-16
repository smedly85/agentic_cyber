# Historical-v1 semantic call-graph validation

This is a side-by-side validation of the Clang/LLVM/SVF instrument. It does not replace or modify the frozen historical-v1 records.

Primary configuration: `AndersenWaveDiff -stat=false -ff-eq-base`. Sensitivity configuration removes only `-ff-eq-base`.

| CVE | Vulnerable function | Build / SVF | Old prototype | Semantic depth | Path composition | ff-eq-base sensitivity |
| --- | --- | --- | --- | ---: | --- | --- |
| CVE-2005-1039 | `src/mkdir.c::main` | success / success | resolved_static_path / 0 | 0 | 0 direct, 0 indirect | unchanged |
| CVE-2005-1039 | `lib/makepath.c::make_path` | success / success | resolved_static_path / 1 | 1 | 1 direct, 0 indirect | unchanged |
| CVE-2025-5278 | `src/sort.c::begfield` | success / success | resolved_static_path / 3 | 3 | 3 direct, 0 indirect | unchanged |
| CVE-2015-1345 | `src/kwset.c::bmexec_trans` | success / success | unresolved_indirect_dispatch / None | 4 | 3 direct, 1 indirect | unchanged |
| CVE-2012-5667 | `src/dfasearch.c::EGexecute` | success / success | unresolved_indirect_dispatch / None | 4 | 3 direct, 1 indirect | unchanged |
| CVE-2015-4041 | `src/sort.c::keycompare_mb` | success / success | unresolved_indirect_dispatch / None | 3 | 2 direct, 1 indirect | unchanged |
| CVE-2015-4042 | `src/sort.c::keycompare_mb` | success / success | unresolved_indirect_dispatch / None | 3 | 2 direct, 1 indirect | unchanged |
| CVE-2013-0221 | `src/sort.c::keycompare_mb` | success / success | unresolved_indirect_dispatch / None | 3 | 2 direct, 1 indirect | unchanged |
| CVE-2013-0221 | `src/sort.c::getmonth_mb` | success / success | no_resolved_static_path / None | 4 | 2 direct, 2 indirect | unchanged |

## Program build and analysis status

| Program scope | Historical build | LLVM IR | Primary SVF | Sensitivity SVF |
| --- | --- | --- | --- | --- |
| `gnu-coreutils/5.2.1/mkdir` | success | success | success | success |
| `gnu-coreutils/8.17-7.fc18/sort` | success | success | success | success |
| `gnu-coreutils/8.23-9.fc22/sort` | success | success | success | success |
| `gnu-coreutils/9.7/sort` | success | success | success | success |
| `gnu-grep/2.10/grep` | success | success | success | success |
| `gnu-grep/2.21/grep` | success | success | success | success |

The initial Coreutils 9.7 `lib/aszprintf.c` failure was an incomplete build reconstruction, not an intrinsic Clang incompatibility. The per-object driver had not realized Automake `BUILT_SOURCES`, so Clang selected the system `<stdio.h>` instead of configured `lib/stdio.h` and lacked `ptrdiff_t`/`vaszprintf` declarations. The corrected driver generates all configured build inputs from the frozen GCC-derived Makefile before compiling; it does not modify the authenticated source tree or substitute the different Clang-native source scope. All 329 translation units, LLVM linking, and both SVF configurations then succeeded.

## Auditable shortest paths

### CVE-2005-1039 - `src/mkdir.c::main`

The shortest semantic path agrees with the prototype depth.

Path: `src/mkdir.c::main`


### CVE-2005-1039 - `lib/makepath.c::make_path`

The shortest semantic path agrees with the prototype depth.

Path: `src/mkdir.c::main -> lib/makepath.c::make_path`

- `src/mkdir.c::main` --direct--> `lib/makepath.c::make_path` at `src/mkdir.c:154:11`

### CVE-2025-5278 - `src/sort.c::begfield`

The shortest semantic path agrees with the prototype depth.

Path: `src/sort.c::main -> src/sort.c::check -> src/sort.c::fillbuf -> src/sort.c::begfield`

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:4872:13`
- `src/sort.c::check` --direct--> `src/sort.c::fillbuf` at `src/sort.c:2976:10`
- `src/sort.c::fillbuf` --direct--> `src/sort.c::begfield` at `src/sort.c:1837:36`

### CVE-2015-1345 - `src/kwset.c::bmexec_trans`

SVF recovered one or more resolved static indirect may-call edges that the syntax-only prototype did not model.

Path: `src/grep.c::main -> src/dfasearch.c::EGexecute -> src/kwset.c::kwsexec -> src/kwset.c::bmexec -> src/kwset.c::bmexec_trans`

- `src/grep.c::main` --indirect_resolved--> `src/dfasearch.c::EGexecute` at `src/grep.c:2531:24`; complete may-target set (3): `src/dfasearch.c::EGexecute`, `src/kwsearch.c::Fexecute`, `src/pcresearch.c::Pexecute`
- `src/dfasearch.c::EGexecute` --direct--> `src/kwset.c::kwsexec` at `src/dfasearch.c:241:31`
- `src/kwset.c::kwsexec` --direct--> `src/kwset.c::bmexec` at `src/kwset.c:848:20`
- `src/kwset.c::bmexec` --direct--> `src/kwset.c::bmexec_trans` at `src/kwset.c:677:13`

### CVE-2012-5667 - `src/dfasearch.c::EGexecute`

SVF recovered one or more resolved static indirect may-call edges that the syntax-only prototype did not model.

Path: `src/main.c::main -> src/main.c::grepfile -> src/main.c::grep -> src/main.c::prpending -> src/dfasearch.c::EGexecute`

- `src/main.c::main` --direct--> `src/main.c::grepfile` at `src/main.c:2206:21`
- `src/main.c::grepfile` --direct--> `src/main.c::grep` at `src/main.c:1287:11`
- `src/main.c::grep` --direct--> `src/main.c::prpending` at `src/main.c:1143:13`
- `src/main.c::prpending` --indirect_resolved--> `src/dfasearch.c::EGexecute` at `src/main.c:889:16`; complete may-target set (3): `src/dfasearch.c::EGexecute`, `src/kwsearch.c::Fexecute`, `src/pcresearch.c::Pexecute`

### CVE-2015-4041 - `src/sort.c::keycompare_mb`

SVF recovered one or more resolved static indirect may-call edges that the syntax-only prototype did not model.

Path: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb`

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5402:13`
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3449:33`
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3355:14`; complete may-target set (2): `src/sort.c::keycompare_mb`, `src/sort.c::keycompare_uni`

### CVE-2015-4042 - `src/sort.c::keycompare_mb`

SVF recovered one or more resolved static indirect may-call edges that the syntax-only prototype did not model.

Path: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb`

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5402:13`
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3449:33`
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3355:14`; complete may-target set (2): `src/sort.c::keycompare_mb`, `src/sort.c::keycompare_uni`

### CVE-2013-0221 - `src/sort.c::keycompare_mb`

SVF recovered one or more resolved static indirect may-call edges that the syntax-only prototype did not model.

Path: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb`

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5274:13`
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3369:33`
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3275:14`; complete may-target set (2): `src/sort.c::keycompare_mb`, `src/sort.c::keycompare_uni`

### CVE-2013-0221 - `src/sort.c::getmonth_mb`

SVF recovered one or more resolved static indirect may-call edges that the syntax-only prototype did not model.

Path: `src/sort.c::main -> src/sort.c::check -> src/sort.c::compare -> src/sort.c::keycompare_mb -> src/sort.c::getmonth_mb`

- `src/sort.c::main` --direct--> `src/sort.c::check` at `src/sort.c:5274:13`
- `src/sort.c::check` --direct--> `src/sort.c::compare` at `src/sort.c:3369:33`
- `src/sort.c::compare` --indirect_resolved--> `src/sort.c::keycompare_mb` at `src/sort.c:3275:14`; complete may-target set (2): `src/sort.c::keycompare_mb`, `src/sort.c::keycompare_uni`
- `src/sort.c::keycompare_mb` --indirect_resolved--> `src/sort.c::getmonth_mb` at `src/sort.c:3134:16`; complete may-target set (2): `src/sort.c::getmonth_mb`, `src/sort.c::getmonth_uni`

## Aggregate validation

- Numeric semantic coverage: 9/9
- Direct-only reachable: 3
- Reachable using at least one resolved indirect edge: 6
- Old nonnumeric observations now numeric: 6
- Old numeric observations with changed depth: 0
- Old numeric observations now unavailable: 0
- Observations materially changed without `ff-eq-base`: 0

A resolved indirect edge is a static may-call relationship, not proof that the target executes at runtime.
No historical mean, median, or shallow threshold is calculated in this pilot validation.
