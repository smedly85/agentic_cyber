"""`agent-test`: splice -> signature/addition checks -> build -> suite -> summary.

Inside an agent session it is the agent's only feedback tool:

    agent-test                 # uses /src/session/session.json defaults

The controller runs the same code (without any agent) to verify a harvested
function file and to run the hidden suite:

    python3 -m src.incontainer.run_tests --project P --context C \
        [--target T --function-file F] --suite S --result R [--emit-dir D]

Exit 0 iff every stage passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from src.suite import SuiteRunner, SummaryFormatter

SESSION_FILE = Path("/src/session/session.json")
IGNORE = shutil.ignore_patterns(".git", "target", "__pycache__")


def _plugin(ref: str | None, default):
    """Instantiate an in-container plugin given as "module:Class" (no-arg constructor)."""
    if not ref:
        return default
    import importlib

    module, _, attr = ref.partition(":")
    return getattr(importlib.import_module(module), attr)()


def build_command(project: Path, ctx: dict[str, Any]) -> list[str] | str:
    if ctx.get("build_cmd"):
        return ctx["build_cmd"]
    if ctx["language"] == "c":
        if (project / "Makefile").is_file() or (project / "makefile").is_file():
            return ["make"]
        stem = Path(ctx["sources"][0]).stem if len(ctx["sources"]) == 1 else ctx.get("program_name") or project.name
        return ["clang", "-std=gnu11", "-O0", "-g", *ctx.get("flags", []), *ctx["sources"], "-o", stem]
    if (project / "Cargo.toml").is_file():
        return ["cargo", "build", "--offline", "--quiet"]
    return ["rustc", "-g", "--edition=2021", ctx["crate_root"], "-o", ctx["crate_name"]]


def run_build(project: Path, ctx: dict[str, Any], timeout: float) -> dict[str, Any]:
    cmd = build_command(project, ctx)
    env = dict(os.environ, CC=os.environ.get("CC", "clang"), CARGO_HOME=os.environ.get("CARGO_HOME", "/tmp/cargo-home"))
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=timeout, shell=isinstance(cmd, str), env=env)
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        code, out, err = 124, "", "build timed out"
    return {
        "ok": code == 0,
        "command": cmd if isinstance(cmd, str) else " ".join(cmd),
        "exit_code": code,
        "elapsed_s": round(time.monotonic() - start, 3),
        "output_tail": (out + err)[-6000:],
    }


def evaluate(
    project: Path,
    ctx: dict[str, Any],
    suite: Path,
    target: dict[str, Any] | None,
    edited: str | None,
    emit_dir: Path | None = None,
    build_timeout: float = 900,
    suite_timeout: float = 900,
    feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from src.incontainer import lang

    fmt = _plugin(ctx.get("feedback_class"), SummaryFormatter.from_config(feedback or {}))
    work = Path(tempfile.mkdtemp(prefix="agent-test-"))
    copy = work / "project"
    shutil.copytree(project, copy, ignore=IGNORE)
    result: dict[str, Any] = {"ok": False, "stage": None, "additions": {}}

    if target is not None:
        outcome = lang.splice(copy, ctx, target, edited or "")
        result["additions"] = outcome.additions
        if not outcome.ok:
            result.update(stage=outcome.stage, message=outcome.message)
            result["summary"] = f"{outcome.stage.upper()}: FAIL\n{outcome.message}"
            return result
        if emit_dir is not None:
            if emit_dir.exists():
                shutil.rmtree(emit_dir)
            shutil.copytree(copy, emit_dir, ignore=IGNORE)

    build = run_build(copy, ctx, build_timeout)
    result["build"] = build
    if not build["ok"]:
        result.update(stage="build", message="build failed")
        result["summary"] = f"BUILD: FAIL ({build['command']})\n{build['output_tail'][-3000:]}"
        return result

    tests = _plugin(ctx.get("test_runner_class"), SuiteRunner(suite_timeout)).run(suite, copy, work / "report.json")
    result["tests"] = tests
    summary = ["SIGNATURE: OK" if target is not None else "", "BUILD: OK", fmt.format(tests)]
    result["summary"] = "\n".join(s for s in summary if s)
    result.update(ok=bool(tests["ok"]), stage="done" if tests["ok"] else "tests", message="ok" if tests["ok"] else "tests failed")
    shutil.rmtree(work, ignore_errors=True)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agent-test", description="splice the function file, check, build and run the visible tests")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--function-file", type=Path)
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--emit-dir", type=Path)
    parser.add_argument("--no-splice", action="store_true", help="test the project as-is (baseline / hidden)")
    args = parser.parse_args(argv)

    session: dict[str, Any] = {}
    if SESSION_FILE.is_file():
        session = json.loads(SESSION_FILE.read_text())
    project = args.project or Path(session.get("project", "/work/project"))
    ctx = json.loads((args.context or Path(session.get("context", "/src/session/context.json"))).read_text())
    suite = args.suite or Path(session.get("suite", "/src/suite"))
    target = None
    edited = None
    if not args.no_splice:
        target = json.loads((args.target or Path(session.get("target", "/src/session/target.json"))).read_text())
        edited = (args.function_file or Path(session.get("function_file", "/src/edit/function.txt"))).read_text()
    result = evaluate(
        project, ctx, suite, target, edited, args.emit_dir,
        build_timeout=session.get("build_timeout_s", 900), suite_timeout=session.get("suite_timeout_s", 900),
        feedback=session.get("feedback"),
    )
    log_dir = Path(session["log_dir"]) if session.get("log_dir") else None
    if log_dir is not None and log_dir.is_dir():
        with (log_dir / "agent-test.jsonl").open("a") as fh:
            fh.write(json.dumps({"time": time.time(), **{k: v for k, v in result.items() if k != "summary"}, "summary": result.get("summary")}) + "\n")
    if args.result:
        args.result.write_text(json.dumps(result, indent=2))
    print(result.get("summary", ""))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
