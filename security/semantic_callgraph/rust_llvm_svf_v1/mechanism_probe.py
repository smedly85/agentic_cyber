"""Post-hoc mechanism probes for README findings F4 and F5 (not preregistered).

Three tiny C programs isolate SVF behaviour from rustc.  Each is compiled
with the C study's clang flags; the declaration of ``probe_alloc`` then gets
the LLVM ``allockind("alloc,uninitialized")`` / ``allocsize(0)`` attributes
that Rust's ``__rust_alloc`` carries and that no extapi.bc entry names.  Every
instrument is run on identical bitcode, and the result is whether ``entry``'s
indirect call resolves to ``target``.

    PYTHONPATH=. python3 -m security.semantic_callgraph.rust_llvm_svf_v1.mechanism_probe \
        --output build/rust-llvm-svf-v1/mechanism-probe
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from security.semantic_callgraph.backend import DEFAULT_CFLAGS
from security.semantic_callgraph.rust_llvm_svf_v1 import pipeline as P

HERE = Path(__file__).resolve().parent
PROBES = ("heap_direct", "heap_aggregate", "pair_return")
ALLOC_ATTRIBUTES = 'attributes #900 = { allockind("alloc,uninitialized") allocsize(0) "alloc-family"="probe_alloc" }'


def build(name: str, out: Path) -> tuple[Path, dict]:
    source = HERE / "fixtures/mechanism" / f"{name}.c"
    text_ir = out / f"{name}.ll"
    log: list = []
    P.run([P.CLANG, *DEFAULT_CFLAGS, "-fdebug-compilation-dir=.", f"-fdebug-prefix-map={P.ROOT}=.",
           "-emit-llvm", "-S", source, "-o", text_ir], cwd=P.ROOT, log=log, out=out, stage="clang")
    ir = text_ir.read_text()
    declaration = re.compile(r"^(declare ptr @probe_alloc\(i64 noundef\)) #\d+$", re.M)
    patched, count = declaration.subn(r"\1 #900", ir)
    if "probe_alloc" in ir and count != 1:
        raise P.PipelineError("expected exactly one probe_alloc declaration")
    if count:
        patched += "\n" + ALLOC_ATTRIBUTES + "\n"
    text_ir.write_text(patched)
    bitcode = out / f"{name}.bc"
    P.run([P.LLVM_BIN / "llvm-as", text_ir, "-o", bitcode], cwd=out, log=log, out=out, stage="llvm-as")
    P.run([P.LLVM_BIN / "opt", "-passes=verify", "-disable-output", bitcode], cwd=out, log=log, out=out, stage="verify")
    facts = {"extractvalue_instructions": len(re.findall(r"= extractvalue ", patched)),
             "allockind_declaration": bool(count), "commands": log,
             "source_sha256": P.sha256(source), "bitcode_sha256": P.sha256(bitcode)}
    return bitcode, facts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = (P.ROOT / args.output) if not args.output.is_absolute() else args.output
    out.mkdir(parents=True, exist_ok=False)
    results = {}
    for name in PROBES:
        bitcode, facts = build(name, out)
        row = {"ir": facts, "configurations": {}}
        for configuration in P.CONFIGURATIONS:
            directory = out / name / configuration
            directory.mkdir(parents=True)
            raw, _ = P.run_helper(configuration, bitcode, directory)
            entry = [f["identity"] for f in raw["functions"] if f["name"] == "entry"]
            targets = sorted(e["callee"].split("::")[-1] for e in raw["call_edges"]
                             if e["caller"] in entry and e["edge_type"] == "indirect_resolved")
            unresolved = [u for u in raw["unresolved_indirect_callsites"] if u["caller"] in entry]
            row["configurations"][configuration] = {
                "entry_indirect_targets": targets, "entry_unresolved_sites": len(unresolved),
                "resolved_to_target": targets == ["target"]}
        results[name] = row
        print(name, {c: v["entry_indirect_targets"] or f"unresolved:{v['entry_unresolved_sites']}"
                     for c, v in row["configurations"].items()}, "extractvalue:", facts["extractvalue_instructions"])
    (HERE / "mechanism_probe_results.json").write_text(json.dumps(
        {"status": "post-hoc mechanism probe; not part of the preregistered acceptance decision",
         "alloc_attributes_added": ALLOC_ATTRIBUTES, "probes": results}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
