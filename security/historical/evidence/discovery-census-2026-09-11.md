# Target-utility historical vulnerability discovery census

Population cutoff: **2026-09-11**. Population reconciliation/audit date:
**2026-09-13**. This later audit considered only issues published on or before
the unchanged cutoff. Discovery and reconciliation preceded interpretation of
the historical call-depth distribution. Search terms named packages, projects,
utilities, predecessor packages, and advisory identifiers; no depth outcome,
mapping convenience criterion, or desired experiment region influenced entry
or exclusion decisions.

## Population and sources

The in-population lineage is GNU Coreutils, GNU grep, predecessor GNU
fileutils/textutils/sh-utils packages when they supplied `sort`, `mkdir`,
`grep`, or `chmod`, and downstream patches applied to those GNU sources.
Independent implementations returned by name-based searches are recorded as
excluded false positives so that they cannot silently enter the GNU/CVE
denominator.

The audit reconciled CVE/NVD records and configurations, GNU release archives,
Savannah history and GNU mailing lists, oss-security, FreeBSD advisories, Red
Hat reports, Debian source-package ledgers, SUSE/openSUSE references, Ubuntu
notices, Fedora packaging history, and predecessor-package names. Debian's
`grep` and `coreutils` ledgers supplied the package-level cross-check; GNU
Fileutils and Textutils were screened separately because they predate
Coreutils. Libraries and independent implementations are not assigned to a
target utility merely because their issue can be demonstrated through a
similarly named command or shared code.

## Frozen dispositions

| Identifier | Type | Utility | Provenance | Disposition | Reason |
| --- | --- | --- | --- | --- | --- |
| CVE-2025-5278 | CVE | sort | upstream GNU | eligible | Existing verified record. |
| CVE-2015-1345 | CVE | grep | upstream GNU | eligible | Existing verified record. |
| CVE-2005-1039 | CVE | mkdir | upstream GNU | eligible | Existing verified record. |
| CVE-2012-5667 | CVE | grep | upstream GNU | eligible | Existing verified record. |
| CVE-2015-4041 | CVE | sort | downstream patch | eligible | The Fedora 22 source state is reproducibly reconstructed from authenticated GNU source plus frozen dist-git content; the multibyte-expansion defect is mapped. The SRPM itself was not authenticated. |
| CVE-2015-4042 | CVE | sort | downstream patch | eligible | The distinct aggregate-size overflow is authenticated and mapped. |
| CVE-2013-0221 | CVE | sort | downstream patch | eligible | Follow-up verification froze Fedora 18 coreutils-8.17-7.fc18, both disclosure-supported sort locations (`keycompare_mb`, `getmonth_mb`), the complete RPM patch stack, and the linker-exact scope; see `CVE-2013-0221.md`. |
| CVE-2001-0310 | CVE | sort | unrelated implementation | excluded | The assignment, concrete NVD configurations, and FreeBSD-SA-01:13 identify FreeBSD sort. "Possibly other operating systems" does not assign it to GNU, and no primary source links GNU Textutils 2.1's separate unspecified DoS hardening to this CVE. |
| TEMP-0306076-4B7D89 | temporary | mkdir | upstream GNU | excluded | Debian says this automatically generated name is not for external reference; it is not a CVE denominator member. |
| CVE-2026-35338 | CVE | chmod | unrelated implementation | excluded | uutils Rust implementation, outside the GNU lineage. |
| CVE-2026-35339 | CVE | chmod | unrelated implementation | excluded | uutils Rust implementation, outside the GNU lineage. |
| CVE-2026-35348 | CVE | sort | unrelated implementation | excluded | uutils Rust implementation, outside the GNU lineage. |
| CVE-2026-35353 | CVE | mkdir | unrelated implementation | excluded | uutils Rust implementation, outside the GNU lineage. |

Thus the frozen ledger contains 13 discoveries: 12 CVE identifiers and one
temporary identifier. Seven entries are eligible, none is unresolved, and six
are excluded. `records.json` remains the same seven-CVE, nine-location
analysis-ready dataset; CVE-2001-0310 and every other excluded identifier are
absent.

## Package-lineage screening matrix

### Independent uutils screening

The independent Rust uutils source-package ledger contained 44 CVEs in total
at the cutoff. Exactly four named one of the four target utilities:
CVE-2026-35338 and CVE-2026-35339 (`chmod`), CVE-2026-35348 (`sort`), and
CVE-2026-35353 (`mkdir`). All four are already retained in the census and
excluded as unrelated implementations. Uutils CVEs naming non-target sibling
utilities, including `mkfifo` and `mknod`, were deliberately not added merely
because the historical GNU CVE-2005-1039 also involved those utilities. The
population unit is the target utility named by the issue, not association with
a different multi-utility CVE.

### GNU grep

The Debian GNU `grep` source-package ledger contains exactly CVE-2012-5667 and
CVE-2015-1345. Both are already eligible and frozen. Searches of CVE/NVD, GNU
bug and release history, Red Hat, Ubuntu, and Debian records found no additional
GNU grep CVE by the cutoff. Issues in regex libraries or other grep
implementations were kept outside this lineage: for example, CVE-2018-20796 is
assigned to glibc's regex implementation even though its demonstration invokes
`grep`; `ugrep`, BSD grep, BusyBox grep, and similarly named library methods are
not GNU grep records.

| Identifier | Assigned component | Target disposition |
| --- | --- | --- |
| CVE-2012-5667 | GNU grep | eligible, frozen |
| CVE-2015-1345 | GNU grep | eligible, frozen |
| CVE-2018-20796 | glibc regex implementation, demonstrated through grep | outside GNU grep population |

### GNU Coreutils package history

The Coreutils source-package ledger was screened through the cutoff, then each
entry was classified by disclosed/CVE-assigned runtime rather than by shared
library linkage.

| Identifier | Assigned utility/component | Target disposition |
| --- | --- | --- |
| CVE-2026-56392 | `unexpand` | non-target |
| CVE-2026-56391 | `uniq` | non-target |
| CVE-2025-5278 | `sort` | eligible, frozen |
| CVE-2024-0684 | `split` | non-target |
| CVE-2017-18018 | `chown` / `chgrp` | non-target; not `chmod` |
| CVE-2017-2616 | `su` in util-linux/shadow; historical package association | non-target |
| CVE-2016-2781 | `chroot` | non-target |
| CVE-2015-4042 | downstream `sort` | eligible, frozen |
| CVE-2015-4041 | downstream `sort` | eligible, frozen |
| CVE-2015-1865 | recursive `rm -rf` using `fts.c` | non-target; shared traversal code is not reassigned to `chmod` |
| CVE-2014-9471 | `date` / `touch` | non-target |
| CVE-2013-0223 | downstream `join` | non-target |
| CVE-2013-0222 | downstream `uniq` | non-target |
| CVE-2013-0221 | downstream `sort` | eligible, frozen |
| CVE-2009-4135 | `distcheck` build machinery | non-runtime, non-target |
| CVE-2008-1946 | `su` PAM configuration | non-target |
| CVE-2007-4998 | `cp` | non-target |
| CVE-2005-1039 | `mkdir` (also `mkfifo`, `mknod`) | eligible `mkdir`, frozen |
| CVE-2003-0854 | `ls` | non-target |
| CVE-2003-0853 | `ls` | non-target |
| TEMP-0306076-4B7D89 | `mkdir`/`mkfifo`/`mknod` mode handling | target discovery hit, excluded because it is not a CVE |

This leaves the target Coreutils population at four `sort` CVEs, one `mkdir`
CVE, and no `chmod` CVE. GNU grep is handled in its separate lineage above.

### GNU Fileutils predecessor

CVE/product-name and vendor searches identified three GNU Fileutils CVEs.
CVE-2002-0435 concerns races in recursive directory deletion and cross-directory
move behavior—`rm` and `mv`, not `mkdir` or `chmod`. CVE-2003-0853 and
CVE-2003-0854 both explicitly concern `ls -w`. Structural similarity to
directory traversal is not sufficient to promote CVE-2002-0435 to another
utility.

| Identifier | Affected behavior | Target disposition |
| --- | --- | --- |
| CVE-2002-0435 | recursive deletion/move (`rm` / `mv`) | non-target |
| CVE-2003-0853 | `ls` integer overflow | non-target |
| CVE-2003-0854 | `ls` memory consumption | non-target |

### GNU sh-utils predecessor

GNU sh-utils 2.0 cannot contribute a target historical CVE by package
composition: its shipped `src/` programs contain none of `sort`, `grep`,
`mkdir`, or `chmod`. This is stronger than a negative CVE-name search—the
package did not supply any target utility to which a vulnerability could be
assigned. Its other programs therefore remain outside this population.

### GNU Textutils predecessor and CVE-2001-0310

GNU's archive identifies Textutils 2.0 (1999) and 2.1 (2002) as the final major
releases before the package was renamed/merged into Coreutils. The GNU
Textutils 2.1 announcement states that `sort` was no longer susceptible to
certain denial-of-service attacks and separately describes temporary-file
cleanup race hardening. It supplies no CVE identifier or link to FreeBSD's
predictable-name failure. This is retained as a historical security-relevant
fix, not converted into a CVE-assigned GNU vulnerability.

CVE-2001-0310 says FreeBSD 4.1.1 and earlier, "and possibly other operating
systems," used predictable temporary names and aborted on collisions. Its
references are FreeBSD/vendor material; NVD's concrete configurations are
FreeBSD 3.5.1 and 4.1.1. FreeBSD-SA-01:13 describes the FreeBSD base-system
instance and FreeBSD correction dates. The nonspecific possibility language is
not primary evidence that GNU Textutils releases were affected, and no primary
record located in this reconciliation ties GNU's unspecified 2.1 hardening to
CVE-2001-0310. The CVE is therefore a verified discovery hit with
`unrelated_implementation` provenance and an excluded disposition.

### `chmod` zero-result audit

No eligible historical GNU or GNU-downstream `chmod` CVE was identified.
CVE-2017-18018 explicitly assigns its race to `chown-core.c` in `chown` and
`chgrp`, not `chmod`. Red Hat bug 1211300 describes CVE-2015-1865 as recursive
`rm -rf`; the presence of vulnerable traversal code in Coreutils `fts.c` does
not assign that runtime behavior to every linked utility. Independent Rust
uutils `chmod` hits remain excluded in the ledger.

The audit also located GNU bug #18280, titled "chmod: race condition," and the
GNU Coreutils manual's warning that combining recursive operation with
dereferencing can let an attacker replace a traversed entry with a symlink to
an arbitrary target. These show that the search did find historical GNU
`chmod` security material. Bug #18280 is not a CVE-assigned target
vulnerability under the frozen population rule, and the manual item is a
documented hazard and usage warning whose mitigation is to avoid the risky
combination or use the documented no-dereference traversal behavior, not
evidence of a missing CVE. Neither therefore enters `cve_census.json` or
`records.json`. Under the population unit of disclosed/CVE-assigned vulnerable
utility behavior, the zero is an audited result rather than an unsearched
category: eligible historical GNU/downstream `chmod` CVEs remain zero.

## Population freeze and descriptive depth result

The historical CVE population was established from utility-level,
package-level, predecessor-package, and documented downstream security records
without consulting call-depth outcomes. Candidate exclusions and non-CVE
security issues were retained in the discovery audit where necessary. The
population was reconciled against the identified authoritative sources for
issues published by the 2026-09-11 cutoff before interpreting the call-depth
distribution. It is systematically audited and complete under this stated
population definition and cutoff; this is not a claim to mathematical
exhaustiveness over every vulnerability that may ever have existed.

The checked formal summary contains nine verified vulnerable-function
locations: three numeric (33.3%) and six mapped but nonnumeric (66.7%). Numeric
raw depths are 0, 1, and 3. At CVE level, two of seven CVEs have a numeric
resolved location (28.6%), while five of seven have no numeric resolved static
path (71.4%); numeric shallowest-CVE depths are 0 and 3. Percentages were
calculated from the emitted `historical_summary` counts, not entered as analyzer
constants.

All numerically resolved historical locations occur at raw depths 0, 1, or 3,
but the majority of verified historical locations are nonnumeric under the
conservative static call-graph model, primarily because relevant paths cross
unresolved indirect dispatch. The resolved observations are therefore
consistent with vulnerabilities occurring in shallow reachable regions but are
insufficient to establish the overall historical depth distribution. No
post-hoc `depth <= 3` threshold is defined; SHALLOW remains ascending-depth
prioritization.

Key package-ledger references:

* https://security-tracker.debian.org/tracker/source-package/coreutils
* https://security-tracker.debian.org/tracker/source-package/grep
* https://security-tracker.debian.org/tracker/source-package/rust-coreutils
* https://savannah.gnu.org/bugs/?18280
* https://www.gnu.org/software/coreutils/manual/html_node/chmod-invocation.html
* https://ftp.gnu.org/old-gnu/sh-utils/sh-utils-2.0.tar.gz
* https://security-tracker.debian.org/tracker/TEMP-0306076-4B7D89
* https://nvd.nist.gov/vuln/detail/CVE-2001-0310
* https://www.freebsd.org/security/advisories/FreeBSD-SA-01:13.sort.asc
* https://lists.gnu.org/archive/html/bug-textutils/2002-08/msg00009.html
* https://ftp.gnu.org/old-gnu/textutils/
* https://nvd.nist.gov/vuln/detail/CVE-2002-0435
* https://bugzilla.redhat.com/show_bug.cgi?id=1211300
* https://nvd.nist.gov/vuln/detail/CVE-2013-0221
* https://ubuntu.com/security/CVE-2015-4041
* https://ubuntu.com/security/CVE-2015-4042
* https://www.suse.com/support/update/announcement/2015/suse-su-20151637-1.html
