"""Controller-side container steps (no agent, no network)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from src.sandbox import docker


class StepError(RuntimeError):
    pass


def _spec(image: str, command: list[str], mounts: list[docker.Mount], config: Mapping[str, Any]) -> docker.ContainerSpec:
    return docker.ContainerSpec(
        image=image,
        command=command,
        mounts=mounts,
        limits=docker.Limits.from_config(config["docker"]),
        workdir="/tmp",
        env={"CARGO_HOME": "/tmp/cargo-home"},
    )


def list_functions(image: str, project: Path, context: Mapping[str, Any], config: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _lang("list", image, project, context, config, None)


def locate(image: str, project: Path, context: Mapping[str, Any], key: str, config: Mapping[str, Any]) -> dict[str, Any]:
    return _lang("locate", image, project, context, config, key)


def _lang(command: str, image: str, project: Path, context: Mapping[str, Any], config: Mapping[str, Any], key: str | None):
    with tempfile.TemporaryDirectory(prefix="agent-lang-") as tmp:
        io = Path(tmp)
        (io / "context.json").write_text(json.dumps(context))
        argv = ["python3", "-m", "src.incontainer.lang", command, "--project", "/work/project", "--context", "/src/io/context.json", "--out", "/src/io/out.json"]
        if key is not None:
            argv += ["--key", key]
        result = docker.run(
            _spec(image, argv, [docker.Mount(project, "/work/project", True), docker.Mount(io, "/src/io", False)], config),
            timeout=1800,
        )
        out = io / "out.json"
        data = json.loads(out.read_text()) if out.is_file() else {"error": result.stderr[-3000:] or f"exit {result.returncode}"}
        if result.returncode != 0 or (isinstance(data, dict) and "error" in data):
            raise StepError(data.get("error") if isinstance(data, dict) else result.stderr[-3000:])
        return data


def evaluate(
    image: str,
    project: Path,
    context: Mapping[str, Any],
    suite: Path,
    config: Mapping[str, Any],
    target: Mapping[str, Any] | None = None,
    function_text: str | None = None,
    emit_dir: Path | None = None,
) -> dict[str, Any]:
    """Run run_tests as the controller: splice (optional) -> checks -> build -> suite."""
    with tempfile.TemporaryDirectory(prefix="agent-eval-") as tmp:
        io = Path(tmp)
        (io / "context.json").write_text(json.dumps(context))
        session = {"feedback": config["tests"].get("feedback", {})}
        argv = [
            "python3", "-m", "src.incontainer.run_tests", "--project", "/work/project",
            "--context", "/src/io/context.json", "--suite", "/src/suite", "--result", "/src/io/result.json",
        ]
        if target is None:
            argv.append("--no-splice")
        else:
            (io / "target.json").write_text(json.dumps(target))
            (io / "function.txt").write_text(function_text or "")
            argv += ["--target", "/src/io/target.json", "--function-file", "/src/io/function.txt"]
        mounts = [
            docker.Mount(project, "/work/project", True),
            docker.Mount(suite, "/src/suite", True),
            docker.Mount(io, "/src/io", False),
        ]
        if emit_dir is not None:
            emit_dir.mkdir(parents=True, exist_ok=True)
            mounts.append(docker.Mount(emit_dir, "/src/emit", False))
            argv += ["--emit-dir", "/src/emit/project"]
        (io / "session.json").write_text(json.dumps(session))
        result = docker.run(_spec(image, argv, mounts, config), timeout=3600)
        path = io / "result.json"
        if not path.is_file():
            return {"ok": False, "stage": "infrastructure", "summary": f"agent-test produced no result (exit {result.returncode})\n{result.stderr[-3000:]}"}
        data = json.loads(path.read_text())
        data["container"] = result.to_json()
        return data
