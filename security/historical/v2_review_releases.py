"""Freeze reviewed upstream release mappings, independently of call depth."""
from security.historical.v2_review import install, evidence
from security.historical.v2_study import ROOT, read
from security.historical.semantic_validation import _sha256


CASES = [
    ("CVE-2007-4998", "fileutils-4.1", ["cp"], "src/copy.c", ["copy_internal"], ["cp-disclosure", "cp-fix-release"], "fixed no later than Fileutils 4.1.2; destination-history guard introduced 2001-09-28",
     "The GNU maintainer's vendor disclosure says GNU cp was already protected by Fileutils 4.1.2; use affected Fileutils 4.1, not a modern Coreutils release. Its copy_internal lacks destination-history checks before dispatching a later regular copy through a just-created symlink. The authenticated Coreutils 5.0 old/fileutils/ChangeLog entry dated 2001-09-28 explicitly locates the destination-history guard in copy_internal; the later fixed copy.c retains it. Newly introduced tracking helpers and the ordinary copy_reg byte-copy helper are not extra vulnerable functions."),
    ("CVE-2017-18018", "coreutils-8.29", ["chown", "chgrp"], "src/chown-core.c", ["change_file_owner"], ["chown-disclosure"], None,
     "The original disclosure traces the unintended ownership update through chownat during recursive dereferencing. The affected 8.29 release performs that path-based chownat operation in change_file_owner, shared by chown/chgrp. restricted_chown's ordinary fallback and FTS traversal are context, not additional functions inferred from generic patch proximity. Both executable-specific depths remain separate pending aggregation approval."),
    ("CVE-2016-2781", "coreutils-8.25", ["chroot"], "src/chroot.c", ["main"], ["chroot-original-disclosure", "chroot-disclosure"], None,
     "The CNA's original disclosure identifies chroot --userspec handing an unprivileged child the parent's terminal session. Release 8.25, contemporary with the February 2016 disclosure, implements credential changes and execvp in main without session/terminal isolation. This is a real runtime entry-function mapping, not a zero assigned for missingness. A later kernel TIOCSTI mitigation is not represented as a Coreutils source fix."),
    ("CVE-2002-0435", "fileutils-4.1", ["rm", "mv"], "src/remove.c", ["remove_dir"], ["fileutils-race-disclosure"], "upstream remove.c parent-directory identity fix, 2002-03-11",
     "The upstream repair verifies the parent device/inode after chdir(\"..\") in remove_dir; the disclosed affected release 4.1 has no such verification. Signature/context propagation into callers does not make them additional vulnerable functions. rm and mv share this removal implementation; keep executable-specific results distinct."),
    ("CVE-2026-56392", "coreutils-9.11", ["unexpand"], "src/unexpand.c", ["unexpand"], ["unexpand-fix"],
     "b60a159fdc5bfcf9988d3a4cb6f53abe8ad5d35d",
     "The fixing commit explicitly names unexpand's unchecked multiplication allocating pending_blank; NEWS identifies introduction in 9.11. The authenticated 9.11 source contains that exact allocation. Tests and allocation-library helpers are not additional vulnerable functions."),
    ("CVE-2026-56391", "coreutils-9.11", ["uniq"], "src/uniq.c", ["find_field"], ["uniq-fix"],
     "d64e35a8a4c0e4608321433e0d84d917e4e36371",
     "The upstream fix names find_field and changes the loop from lp to the advancing ep for both bounds check and multibyte scan. Release 9.11 immediately precedes the fix, retains both faulty lp expressions, and is within the upstream NEWS affected range beginning at 9.5."),
    ("CVE-2024-0684", "coreutils-9.4", ["split"], "src/split.c", ["line_bytes_split"], ["split-fix"],
     "c4c5ed8f4e9cd55a12966d4f520e3a13101637d9",
     "The fixing commit changes only line_bytes_split's hold-buffer shrinking and size accounting. The 9.4 release retains those exact removed statements; selecting the pre-fix release follows the affected-version evidence, not build success."),
    ("CVE-2017-2616", "util-linux-2.29.1", ["su"], "login-utils/su-common.c", ["create_watching_parent"], ["util-linux-su-fix", "shadow-su-fix"],
     "dffab154d29a288aa171ff50263ecc8f2e14a891",
     "The util-linux upstream fix clears the exited child's PID and guards signal delivery within create_watching_parent. Release 2.29.1 precedes this fix and retains the vulnerable stale-PID handling. This specimen is util-linux su, not GNU Coreutils; the independently affected shadow implementation is retained as descriptive evidence, not conflated with util-linux."),
    ("CVE-2014-9471", "coreutils-8.22", ["date", "touch"], "lib/parse-datetime.y", ["parse_datetime"], ["date-fix", "date-gnulib-fix", "date-disclosure"],
     "gnulib:a10acfb1d2118f9a180181d3fed5399dbbe1df3c;coreutils:a4faa6a0a3ae93c01d036d830ae7a21b74913baf",
     "The primary patch repairs the TZ-prefix loop in parse_datetime, not neighboring generated parser functions. Coreutils 8.22 is the final affected release documented by the upstream fix. Preserve grammar-file source identity and generated parse-datetime.c translation-unit provenance. Both date and touch consume this parser; executable-specific results must remain separate pending aggregation approval."),
    ("CVE-2015-1865", "coreutils-8.4", ["rm"], "lib/fts.c", ["opendirat"], ["rm-disclosure"], None,
     "The vendor's original report identifies coreutils 8.4 lib/fts.c opendirat: opening a raced directory without O_NOFOLLOW permits rm traversal outside its intended tree. The exact release source contains the reported openat expression. fts_build is a caller; it is not added merely because later versions pass safer flags from there."),
    ("CVE-2003-0853", "coreutils-5.0", ["ls"], "src/ls.c", ["init_column_info"], ["ls-original-disclosure", "ls-fix-reply-74"], "upstream CVS ls.c arithmetic-overflow fix, 2003-10-13",
     "The disclosed large-width overflow reaches allocation/indexing in init_column_info; release 5.0 retains int max_idx and unchecked XMALLOC multiplication there. The broad upstream arithmetic-hardening patch also changes many unrelated types/helpers; those are not automatically classified as vulnerable functions."),
    ("CVE-2003-0854", "coreutils-5.0", ["ls"], "src/ls.c", ["init_column_info"], ["ls-original-disclosure", "ls-fix-reply-75", "ls-fix-reply-76"], "upstream CVS ls.c resource-exhaustion fix, 2003-10-13",
     "The maintainer explicitly attributes quadratic width-based allocation to init_column_info and limits its allocation to the actual file count. Coreutils 5.0 contains the unbounded width-based allocation. calculate_columns is newly factored fixed code, not a vulnerable pre-fix function; patched callers are not extra observations."),
]


def main():
    sources = read("v2_candidate_sources.json")["sources"]
    decisions = []
    for cve, release, programs, file, functions, refs, fix, reason in CASES:
        candidate = next(s for s in sources if s["source_tree"] == "sources/v2/" + release)
        path = ROOT / candidate["source_tree"] / file
        text = path.read_text()
        if not all(f + " (" in text or f + "(" in text for f in functions):
            raise RuntimeError("reviewed vulnerable function absent from selected source")
        decisions.append({"cve_id": cve, "completed": True, "mapping_status": "verified",
            "depth_applicability": "applicable", "mapping_confidence": "verified_primary_patch_and_release_source",
            "mapping_frozen_before_new_measurement": True, "freeze_stage": "before_specimen_semantic_measurement",
            "project": "util-linux" if release.startswith("util-linux") else "GNU Fileutils" if release.startswith("fileutils") else "GNU Coreutils",
            "affected_version": release, "affected_revision": "official release archive SHA256:" + candidate["archive"]["sha256"],
            "fix_revision": fix, "source_tree": candidate["source_tree"], "source_tree_sha256": candidate["source_tree_sha256"],
            "release_archive": candidate["archive"], "programs": programs, "entry_point": "main",
            "functions": [{"source_file": file, "function": f, "source_identity": file + "::" + f, "source_sha256": _sha256(path)} for f in functions],
            "vulnerability_evidence": [evidence(r) for r in refs], "mapping_reason": reason,
            "specimen_selection_reason": reason})
        if cve == "CVE-2007-4998":
            changelog = ROOT / "sources/v2/coreutils-5.0/old/fileutils/ChangeLog"
            decisions[-1]["vulnerability_evidence"].append({
                "source_artifact": "sources/v2/coreutils-5.0/old/fileutils/ChangeLog",
                "sha256": _sha256(changelog), "entry_date": "2001-09-28",
                "archive_reference": "v2_candidate_sources.json#coreutils-5.0",
                "interpretation": "Primary upstream change history identifies copy_internal as the point of destination-history rejection; no depth was consulted."})
    prior = {m["cve_id"]: m for m in read("v2_vulnerable_function_mappings.json")["members"]}
    for decision in decisions:
        old = prior[decision["cve_id"]]
        if old.get("premeasurement_metadata_amendment"):
            decision["premeasurement_metadata_amendment"] = old["premeasurement_metadata_amendment"]
        elif old.get("completed") and old.get("project") != decision["project"]:
            decision["premeasurement_metadata_amendment"] = {
                "supersedes_mapping_fingerprint": old["mapping_fingerprint"],
                "previous_project": old["project"],
                "reason": "Correct generic release-import label to GNU Fileutils; source revision, vulnerable function, and evidence unchanged; no measurement has run."}
    install(decisions)
    print(f"Frozen {len(decisions)} release-based vulnerable-function mappings before their semantic measurements.")


if __name__ == "__main__":
    main()
