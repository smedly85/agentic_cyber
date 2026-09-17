"""Faithful FreeBSD Make cross-build probe using the official 4.1.1 sysroot."""
import json
import os
from pathlib import Path
import shlex
import shutil
import tempfile
from security.historical.v2_study import ROOT, read, write
from security.historical.v2_acquire import fetch
from security.historical import semantic_validation as v
from security.historical.analysis import verify_source_tree_sha256
from security.historical.v2_build import checked


def main():
    metadata = read("v2_freebsd_sysroot.json")
    sysroot = v.REPO / metadata["sysroot"]
    links = []
    for item in metadata["omitted_links_pending_review"]:
        # These are actual relative symlinks in the distribution. Unneeded
        # hard-linked lex archives are not guessed from their path strings.
        if not (item["path"].startswith("usr/include/") or item["path"] == "usr/lib/libc.so"):
            continue
        link = sysroot / item["path"]
        target = (link.parent / item["target"]).resolve()
        if not target.is_relative_to(sysroot.resolve()) or not target.is_file():
            raise RuntimeError("historical header/library symlink target unavailable or outside sysroot")
        if not link.is_symlink():
            if link.exists():
                raise RuntimeError("refusing to replace an existing sysroot file")
            link.symlink_to(item["target"])
        if link.resolve() != target:
            raise RuntimeError("sysroot symlink target mismatch")
        links.append(item)
    mapping = next(m for m in read("v2_vulnerable_function_mappings.json")["members"] if m["cve_id"] == "CVE-2001-0310")
    original = ROOT / mapping["source_tree"]
    verify_source_tree_sha256(original, mapping["source_tree_sha256"])
    # BSD Make embeds .CURDIR in unquoted historical recipes. Use a temporary
    # byte-identical source mirror with a space-free path, not edited sources.
    stage = Path(tempfile.mkdtemp(prefix="agentic-v2-freebsd-"))
    source = stage / "source"
    shutil.copytree(original, source)
    (stage / "sysroot").symlink_to(sysroot, target_is_directory=True)
    out = stage / "objects"
    out.mkdir()
    audit = v.REPO / "build/historical-v2/freebsd-4.1.1-sort"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "staging.json").write_text(json.dumps({"stage": str(stage), "source": str(source), "objects": str(out)}))
    parent = fetch(("freebsd-4.1.1-gnu-usr-bin-Makefile.inc", "https://raw.githubusercontent.com/freebsd/freebsd-src/" + mapping["affected_revision"] + "/gnu/usr.bin/Makefile.inc"))
    if parent["status"] == "downloaded":
        (source / "gnu/usr.bin/Makefile.inc").write_bytes((v.REPO / parent["cache_path"]).read_bytes())
    elif "404" not in parent.get("diagnostic", ""):
        raise RuntimeError("parent Makefile presence not established")
    verify_source_tree_sha256(source, mapping["source_tree_sha256"])
    toolroot = sysroot.parent / "native-bmake/root"
    bmake = toolroot / "usr/bin/bmake"
    if not bmake.is_file():
        raise RuntimeError("isolated native BSD make unavailable")
    attributes = ["-D__dead2=__attribute__((__noreturn__))",
                  "-D__pure2=__attribute__((__const__))",
                  "-D__unused=__attribute__((__unused__))"]
    linker = v.REPO / read("v2_lld_dependency.json")["linker"]
    (stage / "linker").mkdir()
    (stage / "linker/ld.lld").symlink_to(linker)
    compiler = f"clang-21 -std=gnu89 -fcommon --target=i386-unknown-freebsd4.1 --sysroot={stage / 'sysroot'} -B{stage / 'sysroot/usr/lib'} -fuse-ld={stage / 'linker/ld.lld'} " + shlex.join(attributes)
    command = [str(bmake), "-m", str(stage / "sysroot/usr/share/mk"), "-C", str(source / "gnu/usr.bin/sort"),
               "MACHINE=i386", "MACHINE_ARCH=i386", "OBJFORMAT=elf", "NOMAN=yes", "CC=" + compiler,
               "LDFLAGS=-nodefaultlibs -Wl,--dynamic-linker=/usr/libexec/ld-elf.so.1 -Wl,-Map=sort-v2.map -Wl,-t", "LDADD=-lgcc -lc -lgcc"]
    env = dict(os.environ, MAKEOBJDIR=str(out))
    def invoke(extra):
        import subprocess
        return subprocess.run(command + extra, env=env, text=True, capture_output=True)
    variables = {}
    for name in (".CURDIR", ".OBJDIR", "PROG", "SRCS", "OBJS", "LDADD", "DPADD", "CFLAGS", "LDFLAGS", "CC"):
        response = invoke(["-V", "${" + name + "}"])
        (audit / ("make-var-" + name.strip(".") + ".log")).write_text(response.stdout + response.stderr)
        if response.returncode:
            write("v2_freebsd_cross_build.json", {"schema_version": 1, "status": "bsd_make_configuration_failed_pending_review",
                "source_revision": mapping["affected_revision"], "parent_makefile_evidence": parent,
                "diagnostic": response.stdout + response.stderr, "restored_distribution_symlinks": links})
            return
        variables[name] = response.stdout.strip()
    if Path(variables[".OBJDIR"]) != out:
        raise RuntimeError("BSD Make object directory escaped isolated staging")
    result = invoke(["sort"])
    (audit / "native-cross-link.log").write_text(result.stdout + result.stderr)
    verify_source_tree_sha256(original, mapping["source_tree_sha256"])
    verify_source_tree_sha256(source, mapping["source_tree_sha256"])
    normalize = lambda s: s.replace(str(stage), "$STAGING").replace(str(v.REPO), "$REPO")
    row = {"schema_version": 1, "status": "native_cross_link_succeeded_scope_review_pending" if not result.returncode else "historical_cross_build_failed_pending_review",
           "returncode": result.returncode, "source_tree": mapping["source_tree"], "source_tree_sha256": mapping["source_tree_sha256"],
           "source_revision": mapping["affected_revision"], "parent_makefile_evidence": parent,
           "configured_make_variables": {k: normalize(val) for k, val in variables.items()},
           "command": [normalize(c) for c in command + ["sort"]], "environment": {"MAKEOBJDIR": "$STAGING/objects"},
           "restored_distribution_symlinks": links, "target_triple": "i386-unknown-freebsd4.1",
           "source_integrity_verified": True, "compiler_diagnostics": normalize(result.stderr),
           "link_build_output": normalize(result.stdout), "historical_binaries_executed": False,
           "sysroot_reference": "security/historical/v2_freebsd_sysroot.json"}
    row["compiler_header_compatibility"] = {
        "flags": attributes,
        "header": "usr/include/sys/cdefs.h",
        "header_sha256": v._sha256(sysroot / "usr/include/sys/cdefs.h"),
        "rationale": "Historical sys/cdefs.h only defines these macros for GCC major <=2. Clang advertises GCC compatibility 4.2. These flags reproduce the exact GCC >=2.7 attribute expansions, without changing compiler identity, ABI, source or headers."}
    runtime_evidence = []
    for path in ("contrib/gcc/config/freebsd.h", "contrib/gcc/config/i386/freebsd.h", "contrib/gcc/gcc.c"):
        item = fetch(("freebsd-4.1.1-" + path.replace("/", "-"), "https://raw.githubusercontent.com/freebsd/freebsd-src/" + mapping["affected_revision"] + "/" + path))
        if item["status"] != "downloaded":
            raise RuntimeError("historical compiler runtime link specification unavailable")
        runtime_evidence.append(item)
    row["compiler_runtime_linkage"] = {
        "rationale": "Pinned GCC gcc.c link_command_spec expands %G %L %G; LIBGCC_SPEC is -lgcc and FreeBSD LIB_SPEC for this nonprofiled, nonpthread executable is -lc. Replace modern Clang implicit -lgcc_s with that historical -lgcc -lc -lgcc sequence using -nodefaultlibs and LDADD. Startup objects remain driver-selected release sysroot inputs.",
        "evidence": runtime_evidence}
    previous_path = ROOT / "v2_freebsd_cross_build.json"
    if previous_path.exists():
        previous = json.loads(previous_path.read_text())
        row["previous_attempts"] = previous.get("previous_attempts", []) + [{k: value for k, value in previous.items() if k != "previous_attempts"}]
    write("v2_freebsd_cross_build.json", row)
    print("FreeBSD original BSD Make cross-build:", row["status"], flush=True)


if __name__ == "__main__":
    main()
