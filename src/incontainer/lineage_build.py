"""`agent-build`: the lineage agent's local compile check.

    agent-build            # compiles the session's source file

It approximates the benchmark's official build (src/harness/docker_benchmark_worker.py)
with the agent image's toolchain:

  .c   gcc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -pedantic -O2
  .rs  rustc --edition=2021 -C opt-level=2 -D warnings
  .py  python3 -m py_compile

`lineage.check_cmd` overrides it; `{source}` and `{output}` are substituted.
Compiler versions differ from the pinned benchmark images, so the controller's
official build after the session remains the only verdict.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

SESSION_FILE = Path("/src/session/session.json")
OUTPUT = "/tmp/agent-build/program"


def default_command(source: str) -> list[str]:
    suffix = Path(source).suffix
    if suffix == ".c":
        return ["gcc", "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra", "-Werror",
                "-pedantic", "-O2", source, "-o", OUTPUT]
    if suffix == ".rs":
        return ["rustc", "--edition=2021", "-C", "opt-level=2", "-D", "warnings", source, "-o", OUTPUT]
    if suffix == ".py":
        return [sys.executable if Path(sys.executable).name.startswith("python3") else "python3", "-m", "py_compile", source]
    raise SystemExit(f"agent-build: no default compile check for {suffix or source!r}")


def command_for(session: dict) -> list[str]:
    source = session["source_path"]
    custom = session.get("check_cmd")
    if custom:
        return shlex.split(custom.format(source=shlex.quote(source), output=OUTPUT))
    return default_command(source)


def main() -> int:
    session = json.loads(SESSION_FILE.read_text())
    cwd = session.get("cwd", "/work")
    source = Path(cwd) / session["source_path"]
    if not source.is_file():
        print(f"agent-build: {session['source_path']} does not exist yet")
        return 1
    Path(OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    argv = command_for(session)
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=300)
    output = (proc.stdout + proc.stderr).strip()
    print("$ " + shlex.join(argv))
    if output:
        print(output[-6000:])
    print("BUILD: OK" if proc.returncode == 0 else f"BUILD: FAILED (exit {proc.returncode})")
    if proc.returncode == 0 and Path(OUTPUT).is_file():
        print(f"binary: {OUTPUT}")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
