"""Explicit local installation of official Rust components; no system changes."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import urllib.request

from semantic_gate import ROOT, verify_frozen

VERSION = "1.93.0"
TARGET = "x86_64-unknown-linux-gnu"


def main():
    verify_frozen()  # Before downloads, mkdir, extraction or execution.
    base = ROOT / "build/historical-rust/semantic"
    downloads = base / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    prefix = base / "toolchain"
    records = []
    for component in ("rustc", "rust-std", "cargo"):
        name = f"{component}-{VERSION}-{TARGET}"
        url = f"https://static.rust-lang.org/dist/{name}.tar.xz"
        checksum_path = downloads / (name + ".tar.xz.sha256")
        if not checksum_path.exists():
            checksum_path.write_bytes(urllib.request.urlopen(url + ".sha256", timeout=120).read())
        checksum = checksum_path.read_text().split()[0]
        archive_path = downloads / (name + ".tar.xz")
        if not archive_path.exists():
            print("Downloading", url, flush=True)
            with urllib.request.urlopen(url, timeout=120) as response, archive_path.open("wb") as out:
                while block := response.read(1024 * 1024):
                    out.write(block)
        if hashlib.sha256(archive_path.read_bytes()).hexdigest() != checksum:
            raise ValueError("Official archive checksum mismatch: " + name)
        extracted = downloads / name
        marker = downloads / (name + ".installed")
        if not marker.exists():
            with tarfile.open(archive_path) as archive:
                archive.extractall(downloads, filter="data")
            # The upstream installer splits absolute arguments containing spaces.
            subprocess.run(["bash", "./install.sh", "--prefix=../../toolchain",
                            "--disable-ldconfig"], cwd=extracted, check=True)
            marker.write_text(checksum + "\n")
        records.append({"component": component, "url": url, "sha256": checksum,
                        "checksum_url": url + ".sha256"})
    (base / "toolchain_acquisition.json").write_text(json.dumps(records, indent=2) + "\n")
    subprocess.run([str(prefix / "bin/rustc"), "-vV"], check=True)
    subprocess.run([str(prefix / "bin/cargo"), "--version"], check=True)


if __name__ == "__main__":
    main()
