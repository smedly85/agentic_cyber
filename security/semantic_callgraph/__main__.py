from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backend import analyze_build, build_bitcode, inventory_toolchain, stable_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Clang/LLVM/SVF semantic may-call graph")
    parser.add_argument("config", type=Path, help="JSON build configuration")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--svf-helper", type=Path)
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    inventory = inventory_toolchain(helper=args.svf_helper)
    if args.inventory_only:
        args.output.write_text(stable_json(inventory), encoding="utf-8")
        return 0
    config = json.loads(args.config.read_text(encoding="utf-8"))
    build = build_bitcode(
        config["source_root"], config["source_files"], args.build_dir,
        compile_flags=config.get("compile_flags", ()), inventory=inventory,
    )
    result = analyze_build(
        build, entry_point=config.get("entry_point", "main"),
        inventory=inventory, helper=args.svf_helper,
    )
    args.output.write_text(stable_json(result), encoding="utf-8")
    return 0 if result["analysis_status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
