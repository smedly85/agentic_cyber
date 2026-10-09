"""Entry-policy diagnostic (not a preregistered criterion).

For each binary controlled program, ask the SVF graph whether the user's
source-level ``fn main`` is reachable from the compiled ``std::rt::lang_start``
wrapper, and record why not.  The rustc-generated C-ABI ``main`` symbol has no
DISubprogram, so the helper exports no node for it; ``lang_start<()>`` is the
nearest exported executable-entry wrapper.

    PYTHONPATH=. python3 -m security.semantic_callgraph.rust_llvm_svf_v1.entry_probe \
        --validation build/rust-llvm-svf-v1/validation
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from security.semantic_callgraph.rust_llvm_svf_v1 import pipeline as P

HERE = Path(__file__).resolve().parent


def probe(raw_path: Path, application_file: str) -> dict:
    raw = json.loads(raw_path.read_text())
    rows = raw["functions"]
    wrappers = [r["identity"] for r in rows if r.get("source_file", "").endswith("library/std/src/rt.rs")
                and P.strip_generics(r.get("name", "")) == "lang_start"]
    user_main = [r["identity"] for r in rows if r.get("source_file") == application_file and r.get("name") == "main"]
    exported_c_main = [r for r in rows if r.get("llvm_symbol") == "main"]
    result = {"lang_start_nodes": wrappers, "user_main_nodes": user_main,
              "c_abi_main_exported": bool(exported_c_main)}
    if len(wrappers) == 1 and len(user_main) == 1:
        graph = P.finalize(raw, wrappers[0], {"diagnostic": "entry_probe"})
        nodes = {r["identity"]: r for r in graph["functions"]}
        reached = {i for i, r in nodes.items() if r["reachable_from_entry"]}
        result.update({
            "user_main_reachable_from_lang_start": nodes[user_main[0]]["reachable_from_entry"],
            "reachable_from_lang_start": len(reached),
            "boundaries_on_the_way": {
                "external_calls": sorted({x["callee_name"] for x in graph["external_calls"] if x["caller"] in reached}),
                "unresolved_indirect_callsites": sorted({x["caller"] for x in graph["unresolved_indirect_callsites"]
                                                         if x["caller"] in reached}),
            },
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--configuration", default="P")
    args = parser.parse_args()
    base = (P.ROOT / args.validation) if not args.validation.is_absolute() else args.validation
    out = {}
    for raw in sorted((base / "run-1/expanded").glob(f"*/analysis/{args.configuration}/raw.json")):
        out[raw.parts[-4]] = probe(raw, "tests/fixtures/rust_semantic/expanded.rs")
    (HERE / "entry_probe_results.json").write_text(json.dumps(
        {"configuration": args.configuration, "source": str(base.relative_to(P.ROOT).as_posix()), "programs": out},
        indent=1, sort_keys=True) + "\n", encoding="utf-8")
    reachable = [v.get("user_main_reachable_from_lang_start") for v in out.values()]
    print(f"user main reachable from lang_start in {sum(bool(x) for x in reachable)}/{len(reachable)} expanded programs")


if __name__ == "__main__":
    main()
