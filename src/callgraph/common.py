"""Shared plumbing for call-graph plugins: run the in-container extractor."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.sandbox import docker
from src.project import Project


class CallGraphError(RuntimeError):
    pass


def image_for(language: str, config: Mapping[str, Any]) -> str:
    return config["docker"][f"{language}_image"]


def run_extractor(
    backend: str,
    project: Project,
    config: Mapping[str, Any],
    extra_args: Sequence[str] = (),
    keep_dir: Path | None = None,
    with_dir: bool = False,
) -> Any:
    out_dir = Path(keep_dir) if keep_dir else Path(tempfile.mkdtemp(prefix=f"agent-cg-{backend}-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    command = ["python3", "-m", "src.incontainer.callgraph", backend, "--project", "/work/project", "--out", "/out"]
    for source in project.sources:
        command += ["--source", source]
    if project.crate_name:
        command += ["--crate-name", project.crate_name]
    command += list(extra_args)
    spec = docker.ContainerSpec(
        image=image_for(project.language, config),
        command=command,
        mounts=[docker.Mount(project.root, "/work/project", True), docker.Mount(out_dir, "/out", False)],
        limits=docker.Limits.from_config(config["docker"]),
        workdir="/tmp",
    )
    result = docker.run(spec, timeout=config["callgraph"].get("options", {}).get("timeout_s", 1800))
    (out_dir / "extractor.log").write_text(result.stdout + "\n--- stderr ---\n" + result.stderr)
    graph_path = out_dir / "graph.json"
    if result.returncode != 0 or not graph_path.is_file():
        raise CallGraphError(
            f"{backend} extraction failed (exit {result.returncode}); see {out_dir/'extractor.log'}\n{result.stderr[-2000:]}"
        )
    graph = json.loads(graph_path.read_text())
    return (graph, out_dir) if with_dir else graph
