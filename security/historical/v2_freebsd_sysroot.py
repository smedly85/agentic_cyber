"""Acquire official FreeBSD 4.1.1 headers/link inputs without installing an OS."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import re
import tarfile
from pathlib import Path
from security.historical.v2_acquire import fetch, CACHE
from security.historical.v2_study import ROOT, write
from security.historical.semantic_validation import _run, _sha256


def main():
    repo = ROOT.parents[1]
    base = "https://archive.freebsd.org/old-releases/i386/4.1.1-RELEASE/bin/"
    listing = (CACHE / "freebsd-binary-archive-index").read_text()
    parts = sorted(set(re.findall(r'href="(bin\.[a-z]{2})"', listing)))
    if not parts or parts[0] != "bin.aa":
        raise RuntimeError("official release split-archive listing unavailable")
    sums = fetch(("freebsd-4.1.1-CHECKSUM.MD5", base + "CHECKSUM.MD5"))
    checksum_text = (repo / sums["cache_path"]).read_text()
    expected = dict(re.findall(r"MD5 \((bin\.[a-z]{2})\) = ([0-9a-f]{32})", checksum_text))
    if set(parts) != set(expected):
        raise RuntimeError("release archive parts do not match vendor checksum inventory")
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(fetch, (("freebsd-4.1.1-" + p, base + p) for p in parts)))
    output = repo / "build/historical-v2/dependencies/freebsd-4.1.1"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "bin.tgz"
    with archive.open("wb") as handle:
        for part, row in zip(parts, rows):
            if row["status"] != "downloaded":
                raise RuntimeError("incomplete official archive retrieval")
            data = (repo / row["cache_path"]).read_bytes()
            if hashlib.md5(data).hexdigest() != expected[part]:
                raise RuntimeError("vendor archive-piece checksum mismatch")
            handle.write(data)
    sysroot = output / "sysroot"
    sysroot.mkdir(exist_ok=True)
    retained, omitted_links = [], []
    # The historical release distribution concatenates directory tar streams;
    # zero end markers separate sections, not necessarily the whole payload.
    with tarfile.open(archive, ignore_zeros=True) as tar:
        for member in tar:
            normalized = member.name.removeprefix("./")
            path = Path(normalized)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError("unsafe archive member")
            normalized = path.as_posix()
            if not normalized.startswith(("usr/include/", "usr/lib/", "usr/share/mk/")):
                continue
            if member.issym() or member.islnk():
                omitted_links.append({"path": normalized, "target": member.linkname})
                continue
            if not member.isfile():
                continue
            # Extract development inputs only, never run historical binaries.
            data = tar.extractfile(member).read()
            target = sysroot / normalized
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != data:
                raise RuntimeError("existing sysroot content differs from authenticated distribution")
            if not target.exists():
                target.write_bytes(data)
            retained.append({"path": normalized, "sha256": hashlib.sha256(data).hexdigest()})
    if not retained:
        raise RuntimeError("distribution yielded no development inputs; cannot call this a sysroot")
    native_make = output / "native-bmake"
    native_make.mkdir(exist_ok=True)
    command = ["apt-get", "download", "bmake"]
    acquired = _run(command, cwd=native_make)
    package_rows = []
    if acquired.returncode == 0:
        packages = list(native_make.glob("bmake_*.deb"))
        if len(packages) != 1:
            raise RuntimeError("ambiguous native bmake package")
        unpacked = _run(["dpkg-deb", "-x", str(packages[0]), str(native_make / "root")])
        package_rows.append({"path": packages[0].relative_to(repo).as_posix(), "sha256": _sha256(packages[0]),
                             "extraction_returncode": unpacked.returncode, "diagnostic": unpacked.stderr})
    write("v2_freebsd_sysroot.json", {"schema_version": 1, "release": "FreeBSD 4.1.1-RELEASE/i386",
        "official_archive_url": base, "archive_parts": rows, "vendor_checksums": sums,
        "combined_archive_sha256": _sha256(archive), "sysroot": sysroot.relative_to(repo).as_posix(),
        "development_files": retained, "omitted_links_pending_review": omitted_links,
        "bmake_acquisition": {"command": command, "returncode": acquired.returncode,
                              "diagnostics": acquired.stdout + acquired.stderr, "packages": package_rows},
        "status": "historical_cross_build_inputs_acquired_not_yet_validated", "system_packages_installed": False})
    print("FreeBSD historical sysroot regular development files:", len(retained), "links needing review:", len(omitted_links), flush=True)


if __name__ == "__main__":
    main()
