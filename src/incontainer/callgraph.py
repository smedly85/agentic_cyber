"""In-container call-graph extraction. Runs inside agent-c / agent-rust.

    python3 -m src.incontainer.callgraph svf   --project P --out O [--source a.c ...] [--flag -I...]
    python3 -m src.incontainer.callgraph mir   --project P --out O [--source src/main.rs]
    python3 -m src.incontainer.callgraph rupta --project P --out O [--source src/main.rs]

Writes <O>/graph.json (the backend's finalized semantic graph) and
<O>/status.json. Only the repository's existing analyzers are used.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def write(out: Path, name: str, data) -> None:
    (out / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def run_svf(args) -> dict:
    from src.analyzers.svf_backend import analyze_build, build_bitcode, inventory_toolchain

    helper = os.environ.get("AGENT_SVF_HELPER")
    inventory = inventory_toolchain(helper=helper)
    with tempfile.TemporaryDirectory() as tmp:
        # SVF writes <extapi>.pre.bc next to extapi.bc; use a private copy so
        # the image stays read-only and concurrent runs never collide.
        options = ["-stat=false", "-ff-eq-base"]
        extapi = next(Path("/opt/SVF").glob("Release-build/lib/extapi.bc"), None)
        if extapi is not None:
            local = Path(tmp) / "extapi.bc"
            shutil.copyfile(extapi, local)
            options.append(f"-extapi={local}")
        build = build_bitcode(args.project, args.source, Path(tmp) / "bc", compile_flags=args.flag, inventory=inventory)
        graph = analyze_build(build, entry_point="main", helper=helper, svf_options=tuple(options))
    return graph


def _rust_sources(args) -> tuple[Path, str]:
    project = Path(args.project)
    if args.source:
        main = project / args.source[0]
    elif (project / "src" / "main.rs").is_file():
        main = project / "src" / "main.rs"
    else:
        raise SystemExit("cannot find src/main.rs; pass --source")
    crate = args.crate_name or (project.name.replace("-", "_") if project.is_dir() else main.stem)
    return main, crate


def run_mir(args) -> dict:
    from src.analyzers.mir_graph import build

    main, crate = _rust_sources(args)
    version = os.environ.get("AGENT_RUST_VERSION", "1.93.0")
    sysroot = subprocess.run(["rustc", f"+{version}", "--print", "sysroot"], capture_output=True, text=True, check=True).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        raw_path = Path(tmp) / "raw.json"
        env = dict(os.environ, MIR_PROBE_OUTPUT=str(raw_path), MIR_PROBE_TRANSITIVE="1", RUSTC_BOOTSTRAP="1")
        argv = [
            "mir-probe", str(main), "--sysroot", sysroot, "--edition=2021",
            "--target=x86_64-unknown-linux-gnu", "-C", "opt-level=0", "-C", "panic=unwind",
            "-C", "codegen-units=1", "-Z", "mir-opt-level=0", "-Z", "inline-mir=no",
            "-Z", "always-encode-mir", f"--crate-name={crate}", "--crate-type=bin",
            "--emit=metadata", "--out-dir", tmp,
        ]
        proc = subprocess.run(argv, capture_output=True, text=True, env=env)
        if proc.returncode != 0 or not raw_path.is_file():
            raise SystemExit(f"mir-probe failed ({proc.returncode}):\n{proc.stderr[-4000:]}")
        raw = json.loads(raw_path.read_text())
    entry = _mir_entry(raw, crate)
    graph = build(raw, entry)
    graph["raw_instances"] = raw["instances"]
    return graph


def _mir_entry(raw: dict, crate: str) -> str:
    want = {f"{crate}::main", "main"}
    hits = [r["instance_identity"] for r in raw["instances"] if r.get("def_path") in want or str(r.get("def_path", "")).endswith("::main") and r.get("defining_crate") == crate]
    if len(hits) != 1:
        raise SystemExit(f"cannot identify unique main among MIR instances: {hits}")
    return hits[0]


def run_rupta(args) -> dict:
    from src.analyzers.rupta_adapter import finalize, parse

    main, crate = _rust_sources(args)
    toolchain = os.environ.get("AGENT_RUPTA_TOOLCHAIN", "nightly-2024-02-03")
    mode = args.pta_type
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        sysroot = subprocess.run(["rustc", f"+{toolchain}", "--print", "sysroot"], capture_output=True, text=True, check=True).stdout.strip()
        env = dict(os.environ, LD_LIBRARY_PATH=f"{sysroot}/lib", RUSTUP_TOOLCHAIN=toolchain)
        argv = [
            "pta", str(main), "--pta-type", mode, "--entry-func", "main",
            "--dump-call-graph", str(out / "graph.dot"), "--dump-dyn-calls", str(out / "dynamic.txt"),
            "--dump-mir", str(out / "mir.txt"), "--",
            f"--crate-name={crate}", "--crate-type=bin", "--edition=2021", "--sysroot", sysroot,
        ]
        if mode == "cs":
            argv[4:4] = ["--context-depth", "1"]
        proc = subprocess.run(argv, capture_output=True, text=True, env=env)
        if proc.returncode != 0 or not (out / "graph.dot").is_file():
            raise SystemExit(f"pta failed ({proc.returncode}):\n{proc.stderr[-4000:]}")
        raw = parse(out, mode)
        entry = _rupta_entry(raw)
        graph = finalize(raw, entry)
    return graph


def _rupta_entry(raw: dict) -> str:
    names = [f["identity"] for f in raw["functions"]]
    hits = [n for n in names if n == "main" or n.endswith("::main")]
    if len(hits) != 1:
        raise SystemExit(f"cannot identify unique main among RUPTA functions: {hits}")
    return hits[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=("svf", "mir", "rupta"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--flag", action="append", default=[])
    parser.add_argument("--crate-name")
    parser.add_argument("--pta-type", default="ander", choices=("ander", "cs"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        graph = {"svf": run_svf, "mir": run_mir, "rupta": run_rupta}[args.backend](args)
    except SystemExit as exc:
        write(args.out, "status.json", {"ok": False, "error": str(exc)})
        print(exc, file=sys.stderr)
        return 1
    if args.backend in ("mir", "rupta"):
        # Source-level inventory so the host can map graph nodes to functions.
        from src.incontainer import rs_lang

        main_rs, crate = _rust_sources(args)
        root = str(main_rs.relative_to(Path(args.project)))
        write(args.out, "items.json", rs_lang.list_functions(Path(args.project), root, crate))
    write(args.out, "graph.json", graph)
    status = graph.get("analysis_status", "success")
    ok = status in ("success", "partial_export")
    write(args.out, "status.json", {"ok": ok, "analysis_status": status, "failures": graph.get("failures", [])})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
