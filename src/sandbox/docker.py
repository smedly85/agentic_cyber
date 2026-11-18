"""Thin, hardened `docker run` wrapper used by every container step.

Defaults follow src/harness/docker_benchmark.py::invoke: no network, all
capabilities dropped, no-new-privileges, cpu/memory/pids limits. Agent
sessions opt into network access explicitly (for the model endpoint).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from src import REPO_ROOT

# The pipeline sources (and the harness) are mounted read-only here in every container.
CONTAINER_REPO = "/agent-src"


class DockerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Mount:
    source: Path
    target: str
    read_only: bool = True

    def arg(self) -> str:
        spec = f"type=bind,source={Path(self.source).resolve()},target={self.target}"
        return spec + (",readonly" if self.read_only else "")


@dataclass
class RunResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_s: float
    timed_out: bool = False

    def to_json(self) -> dict:
        return {
            "argv": self.argv,
            "returncode": self.returncode,
            "elapsed_s": round(self.elapsed_s, 3),
            "timed_out": self.timed_out,
        }


@dataclass
class Limits:
    cpus: float = 2
    memory: str = "4g"
    pids: int = 512

    @classmethod
    def from_config(cls, docker_cfg: Mapping) -> "Limits":
        return cls(cpus=docker_cfg.get("cpus", 2), memory=docker_cfg.get("memory", "4g"), pids=docker_cfg.get("pids", 512))


@dataclass
class ContainerSpec:
    image: str
    command: Sequence[str]
    mounts: Sequence[Mount] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    workdir: str = "/work"
    network: bool | str = False  # False/"none", True/"bridge", or "host"
    limits: Limits = field(default_factory=Limits)
    tmpfs: Sequence[str] = ("/tmp:rw,exec,size=1g",)
    name: str | None = None
    user: str | None = None  # default: host uid:gid so outputs are owned by the user
    extra_args: Sequence[str] = ()


def network_mode(value: bool | str) -> str:
    if value is True:
        return "bridge"
    if value in (False, None, ""):
        return "none"
    if value not in ("none", "bridge", "host"):
        raise DockerError(f"unsupported network mode {value!r}")
    return str(value)


def build_argv(spec: ContainerSpec, include_repo: bool = True) -> list[str]:
    argv = [
        "docker", "run", "--rm", "--init",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--cpus", str(spec.limits.cpus),
        "--memory", str(spec.limits.memory),
        "--pids-limit", str(spec.limits.pids),
        "--network", network_mode(spec.network),
        "--workdir", spec.workdir,
        "--user", spec.user or f"{os.getuid()}:{os.getgid()}",
        "--env", "HOME=/tmp",
    ]
    if spec.name:
        argv += ["--name", spec.name]
    for tmp in spec.tmpfs:
        argv += ["--tmpfs", tmp]
    mounts = list(spec.mounts)
    if include_repo:
        mounts.append(Mount(REPO_ROOT, CONTAINER_REPO, read_only=True))
        argv += ["--env", f"PYTHONPATH={CONTAINER_REPO}", "--env", "PYTHONDONTWRITEBYTECODE=1"]
    for mount in mounts:
        argv += ["--mount", mount.arg()]
    argv += list(spec.extra_args)
    for key, value in sorted(spec.env.items()):
        argv += ["--env", f"{key}={value}"]
    argv.append(spec.image)
    argv += list(spec.command)
    return argv


def run(spec: ContainerSpec, timeout: float | None = None, include_repo: bool = True) -> RunResult:
    argv = build_argv(spec, include_repo=include_repo)
    start = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if spec.name:
            kill(spec.name)
        return RunResult(
            argv=redact_env(argv),
            returncode=124,
            stdout=_text(exc.stdout),
            stderr=_text(exc.stderr),
            elapsed_s=time.monotonic() - start,
            timed_out=True,
        )
    except FileNotFoundError as exc:
        raise DockerError("docker CLI not found") from exc
    return RunResult(redact_env(argv), proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start)


def kill(name: str) -> None:
    subprocess.run(["docker", "kill", name], capture_output=True)


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


SECRET_ENV_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")


def redact_env(argv: list[str]) -> list[str]:
    out = []
    for item in argv:
        key, sep, _ = item.partition("=")
        if sep and key.endswith(SECRET_ENV_SUFFIXES):
            out.append(f"{key}=<redacted>")
        else:
            out.append(item)
    return out


def image_id(tag: str) -> str | None:
    proc = subprocess.run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def require_image(tag: str) -> str:
    """Return the image id (recorded in the run manifest); fail if the image is missing."""
    actual = image_id(tag)
    if actual is None:
        target = tag.split(":")[0]
        raise DockerError(f"image {tag} not found; build it with "
                          f"docker build -f docker/Dockerfile --target {target} -t {tag} src")
    return actual
