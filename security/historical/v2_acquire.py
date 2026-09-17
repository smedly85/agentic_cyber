"""Acquire read-only evidence/releases into ignored v2 storage; no analysis."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error

from security.historical.v2_study import ROOT, IDS, read, write, validate_population

REPO = ROOT.parents[1]
CACHE = REPO / "build/historical-v2/downloads"
PRIMARY = {
    "freebsd-binary-archive-index": "https://archive.freebsd.org/old-releases/i386/4.1.1-RELEASE/bin/",
    "freebsd-binary-ftp-archive-index": "https://ftp-archive.freebsd.org/pub/FreeBSD-Archive/old-releases/i386/4.1.1-RELEASE/bin/",
    "cp-fix-release": "https://lists.gnu.org/archive/html/coreutils-announce/2001-11/msg00002.html",
    "chroot-original-disclosure": "https://www.openwall.com/lists/oss-security/2016/02/28/3",
    "freebsd-sort-directory": "https://api.github.com/repos/freebsd/freebsd-src/contents/gnu/usr.bin/sort?ref=release/4.1.1",
    "freebsd-release-tag": "https://api.github.com/repos/freebsd/freebsd-src/git/tags/dde13c27ae4a3f039700e6986e7d6856f3a78395",
    **{f"ls-fix-reply-{n}": f"https://lists.gnu.org/archive/html/bug-coreutils/2003-10/msg000{n}.html" for n in (74, 75, 76, 78)},
    "fileutils-old-index": "https://ftp.gnu.org/old-gnu/fileutils/",
    "ls-fix-thread": "https://lists.gnu.org/archive/html/bug-coreutils/2003-10/msg00070.html",
    "freebsd-release-ref": "https://api.github.com/repos/freebsd/freebsd-src/git/ref/tags/release/4.1.1",
    "freebsd-sort-makefile": "https://raw.githubusercontent.com/freebsd/freebsd-src/release/4.1.1/gnu/usr.bin/sort/Makefile",
    "freebsd-sort-source": "https://raw.githubusercontent.com/freebsd/freebsd-src/release/4.1.1/gnu/usr.bin/sort/sort.c",
    "freebsd-sort-fix": "https://www.freebsd.org/security/patches/SA-01:13/sort-4.1.1.patch",
    "distcheck-fix": "https://github.com/coreutils/coreutils/commit/ae034822c535fa5.patch",
    "pam-advisory": "https://access.redhat.com/errata/RHSA-2008:0780",
    "ls-original-disclosure": "https://www.guninski.com/binls.html",
    "fileutils-race-disclosure": "https://lists.gnu.org/archive/html/bug-fileutils/2002-03/msg00028.html",
    "date-gnulib-fix": "https://github.com/coreutils/gnulib/commit/a10acfb1d2118f9a180181d3fed5399dbbe1df3c.patch",
    "unexpand-fix": "https://github.com/coreutils/coreutils/commit/b60a159fdc5bfcf9988d3a4cb6f53abe8ad5d35d.patch",
    "uniq-fix": "https://github.com/coreutils/coreutils/commit/d64e35a8a4c0e4608321433e0d84d917e4e36371.patch",
    "split-fix": "https://github.com/coreutils/coreutils/commit/c4c5ed8f4e9cd55a12966d4f520e3a13101637d9.patch",
    "util-linux-su-fix": "https://github.com/util-linux/util-linux/commit/dffab154d29a288aa171ff50263ecc8f2e14a891.patch",
    "shadow-su-fix": "https://github.com/shadow-maint/shadow/commit/08fd4b69e84364677a10e519ccb25b71710ee686.patch",
    "freebsd-sort-advisory": "https://www.freebsd.org/security/advisories/FreeBSD-SA-01:13.sort.asc",
    "i18n-disclosure": "https://www.openwall.com/lists/oss-security/2013/01/21/14",
    "i18n-followup": "https://www.openwall.com/lists/oss-security/2013/01/22/7",
    "date-disclosure": "https://debbugs.gnu.org/cgi/bugreport.cgi?bug=16872",
    "date-fix": "https://debbugs.gnu.org/cgi/bugreport.cgi?msg=19;filename=coreutils-date-crash.patch;att=1;bug=16872",
    "rm-disclosure": "https://bugzilla.redhat.com/show_bug.cgi?id=1211300",
    "cp-disclosure": "https://bugzilla.redhat.com/show_bug.cgi?id=356471",
    "distcheck-disclosure": "https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=560898",
    "chown-disclosure": "https://lists.gnu.org/archive/html/coreutils/2017-12/msg00045.html",
    "chroot-disclosure": "https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=816320",
}
RELEASES = {
    **{f"coreutils-{ver}.tar.xz": f"https://ftp.gnu.org/gnu/coreutils/coreutils-{ver}.tar.xz"
       for ver in ("8.22", "8.25", "8.29", "9.4", "9.11")},
    "coreutils-8.4.tar.gz": "https://ftp.gnu.org/gnu/coreutils/coreutils-8.4.tar.gz",
    "coreutils-5.0.tar.gz": "https://ftp.gnu.org/gnu/coreutils/coreutils-5.0.tar.gz",
    "fileutils-4.1.tar.gz": "https://ftp.gnu.org/old-gnu/fileutils/fileutils-4.1.tar.gz",
    "util-linux-2.29.1.tar.xz": "https://www.kernel.org/pub/linux/utils/util-linux/v2.29/util-linux-2.29.1.tar.xz",
}


def fetch(item: tuple[str, str]) -> dict:
    name, url = item
    path = CACHE / name
    row = {"name": name, "url": url, "cache_path": path.relative_to(REPO).as_posix()}
    try:
        if path.exists():
            data = path.read_bytes()
            row["retrieval"] = "existing_download"
        else:
            request = urllib.request.Request(url, headers={"User-Agent": "agentic-cyber-historical-research/2"})
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read()
                row["resolved_url"] = response.url
                row["content_type"] = response.headers.get("Content-Type")
            path.write_bytes(data)
            row["retrieval"] = "https_download"
        row.update(status="downloaded", sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        row.update(status="retrieval_failed", diagnostic=str(error))
    print(name, row["status"], flush=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=["cve-records", "primary", "releases"])
    args = parser.parse_args()
    validate_population(read("v2_population.json"))
    CACHE.mkdir(parents=True, exist_ok=True)
    requests = ({c + ".json": "https://cveawg.mitre.org/api/cve/" + c for c in IDS}
                if args.group == "cve-records" else PRIMARY if args.group == "primary" else RELEASES)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(fetch, requests.items()))
    index_name = "v2_" + args.group.replace("-", "_") + "_acquisition.json"
    existing = read(index_name) if (ROOT / index_name).exists() else {}
    history = existing.get("previous_attempts", [])
    for previous in existing.get("requests", []):
        if previous not in history:
            history.append(previous)
    write(index_name, {"schema_version": 1, "purpose": "evidence/source acquisition only; no applicability or mapping inferred from download success", "requests": rows, "previous_attempts": history})


if __name__ == "__main__":
    main()
