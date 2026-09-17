"""Acquire an isolated LLVM 21 linker; do not install system packages."""
from security.historical import semantic_validation as v
from security.historical.v2_study import write


def main():
    directory = v.REPO / "build/historical-v2/dependencies/lld"
    directory.mkdir(parents=True, exist_ok=True)
    command = ["apt-get", "download", "lld-21=1:21.1.8-6ubuntu1"]
    result = v._run(command, cwd=directory)
    if result.returncode:
        raise RuntimeError(result.stderr)
    archives = list(directory.glob("lld-21_*.deb"))
    if len(archives) != 1:
        raise RuntimeError("ambiguous isolated lld archive")
    archive = archives[0]
    extracted = v._run(["dpkg-deb", "-x", str(archive), str(directory / "root")])
    if extracted.returncode:
        raise RuntimeError(extracted.stderr)
    linker = directory / "root/usr/lib/llvm-21/bin/ld.lld"
    version = v._run([str(linker), "--version"])
    if version.returncode:
        raise RuntimeError(version.stderr)
    write("v2_lld_dependency.json", {"schema_version": 1, "command": command,
          "archive": archive.relative_to(v.REPO).as_posix(), "sha256": v._sha256(archive),
          "linker": linker.relative_to(v.REPO).as_posix(), "version": version.stdout.strip(),
          "system_install": False})
    print(version.stdout.strip())


if __name__ == "__main__":
    main()
