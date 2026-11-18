#!/usr/bin/env python3
"""Controller-only syntax check and interpreter-pinned Python launcher.

Never supplies candidate code, imports it, or executes it during the build.
The launcher is disposable; the original source is the lineage artifact.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import sys


def prepare(source: Path, output: Path) -> None:
    if source.resolve() == output.resolve():
        raise ValueError("launcher must not replace candidate source")
    # Never leave a stale successful build after a failed repair.
    output.unlink(missing_ok=True)
    data = source.read_bytes()
    if not data.strip():
        raise ValueError("candidate source is empty")
    compile(data, str(source), "exec")  # py_compile equivalent, without cache files
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -B "
        + shlex.quote(str(source.resolve())) + ' "$@"\n', encoding="utf-8"
    )
    output.chmod(0o755)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        prepare(args.source, args.output)
    except (OSError, SyntaxError, ValueError) as error:
        print(f"Python candidate validation failed: {error}", file=sys.stderr)
        return 1
    print(f"Python syntax valid: {args.source} ({sys.executable})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
