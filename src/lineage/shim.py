"""Aider-compatible executable that runs a pipeline mini-swe-agent session instead.

src/harness/run_experiment.sh runs its generator as

    cd <attempt>/workdir && env -i HOME=.. PATH=.. TMPDIR=.. GIT_CEILING_DIRECTORIES=.. \\
        timeout --signal=TERM --kill-after=30 SECONDS \\
        "$AIDER_BIN" --architect ... --model M --editor-model E \\
        --model-settings-file <attempt>/aider-model-settings.yml \\
        --message-file <prompt> --file <SOURCE_PATH> [--read <file>]... </dev/null

`python -m src lineage` points AIDER_BIN at a generated wrapper that runs

    python -m src.lineage.shim --agent-config <private json> <the same arguments>

so the script's whole controller (prompts, repair continuations, validation,
capture, fingerprints) is unchanged. One invocation of this shim:

1. copies the workdir into a private session directory,
2. runs `src.incontainer.agent_session run` (single / planner_worker /
   orchestrator) in a hardened language container with that copy at /work,
3. copies back ONLY the editable source (--file); every other change is
   discarded, which matches Aider's structural boundary,
4. prints a log for aider.log (including Aider's "Applied edit to <file>" line
   when the source changed) and exits 0, or 1 when the agent container
   produced no session record (an infrastructure failure).

Sampling comes from the architect entry (`name == --model`) of the
per-attempt model settings file, so the values the script fingerprints are the
values every agent role uses. Session artifacts (task, trajectories,
agents.jsonl, container log) are kept under <attempt>/agent/session-NN/.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import signal
import sys
import uuid
from pathlib import Path
from typing import Any

from src import __version__
from src.agents.minisweagent import REPLAY_MODEL, agent_network, llm_cache_mounts
from src.cache import digest
from src.config import required_roles
from src.sandbox import docker

MSWEA_VERSION = "2.4.6"
SAMPLING_KEYS = ("temperature", "top_p", "seed", "max_tokens", "num_ctx", "think")
AGENT_BUILD = """#!/bin/sh
exec python3 -m src.incontainer.lineage_build "$@"
"""
AGENT_WORKER = """#!/bin/sh
exec /opt/agent/bin/python -m src.incontainer.agent_session worker "$@"
"""
IGNORED_COPY = shutil.ignore_patterns("__pycache__")


def version_string(config: dict[str, Any] | None = None) -> str:
    topology = (config or {}).get("topology", "?")
    return f"minisweagent-shim {__version__} (mini-swe-agent {MSWEA_VERSION}, topology={topology})"


def parse_aider_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="aider-shim", add_help=False)
    parser.add_argument("--agent-config")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--editor-model")
    parser.add_argument("--model-settings-file")
    parser.add_argument("--message-file")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--read", action="append", default=[])
    args, _unknown = parser.parse_known_args(argv)  # every other Aider flag is irrelevant here
    return args


def sampling_from_settings(path: str | None, model: str | None) -> dict[str, Any]:
    """Architect extra_params from the script's settings file (JSON is valid YAML)."""
    if not path or not Path(path).is_file():
        return {}
    entries = json.loads(Path(path).read_text())
    for entry in entries:
        if entry.get("name") == model:
            params = entry.get("extra_params", {})
            return {k: params[k] for k in SAMPLING_KEYS if k in params}
    return {}


def image_for(source: str, config: dict[str, Any]) -> str:
    return config["rust_image"] if source.endswith(".rs") else config["c_image"]


def next_session_dir(attempt_dir: Path) -> Path:
    root = attempt_dir / "agent"
    root.mkdir(parents=True, exist_ok=True)
    n = 1 + sum(1 for p in root.iterdir() if p.name.startswith("session-"))
    return root / f"session-{n:02d}"


def changed_files(before: Path, after: Path) -> list[str]:
    changed = []
    for path in sorted(after.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(after)
        old = before / rel
        if not old.is_file() or not filecmp.cmp(old, path, shallow=False):
            changed.append(rel.as_posix())
    for path in sorted(before.rglob("*")):
        if path.is_file() and not (after / path.relative_to(before)).exists():
            changed.append(path.relative_to(before).as_posix() + " (deleted)")
    return changed


def session_scope(config: dict[str, Any], workdir: Path, session_name: str) -> dict[str, Any] | None:
    """LLM cache settings for this session; the scope does not depend on the output dir.

    workdir = <lineage root>/lineage-NNN/<checkpoint>/temp-<T>/attempt-NNN/workdir
    """
    llm = config.get("llm_cache")
    if not llm:
        return None
    attempt = workdir.parent
    parts = ["lineage", config.get("utility"), attempt.parent.parent.parent.name, attempt.parent.parent.name,
             attempt.parent.name, attempt.name, session_name, config["topology"]]
    return {"mode": llm["mode"], "match": llm["match"], "scope": digest("llm-scope", llm["namespace"], parts)}


def agent_wall_time(session_timeout_s: float) -> int:
    timeout = float(session_timeout_s)
    return int(max(timeout * 0.5, timeout - 120))


def build_session(config: dict[str, Any], args: argparse.Namespace, workdir: Path, message: str) -> dict[str, Any]:
    source = args.file[0]
    topology = config["topology"]
    roles = required_roles(topology)
    sampling = sampling_from_settings(args.model_settings_file, args.model)
    session: dict[str, Any] = {
        "kind": "lineage",
        "cwd": "/work",
        "topology": topology,
        "model_class": config.get("model_class", "litellm"),
        "models": {r: {"model": config["models"][r]["model"] or REPLAY_MODEL, "api_base": config["models"][r].get("api_base")} for r in roles},
        "sampling": {r: dict(sampling) for r in roles},
        "step_limit": config.get("step_limit", 0),
        # End the agent before run_experiment.sh's `timeout` fires, so the
        # session finishes cleanly and its work is harvested normally.
        "wall_time_s": agent_wall_time(config["session_timeout_s"]),
        "command_timeout_s": int(config.get("command_timeout_s", 900)),
        "token_budget": config.get("token_budget", {"enabled": False, "limit": 0}),
        "source_path": source,
        "check_command": "agent-build",
        "check_cmd": config.get("check_cmd"),
        "log_dir": "/src/out",
        "prompt_vars": {
            "message": message.strip(),
            "source_path": source,
            "source_exists": (workdir / source).is_file(),
            "read_files": list(args.read),
            "check_command": "agent-build",
            "time_limit_minutes": max(1, agent_wall_time(config["session_timeout_s"]) // 60),
        },
    }
    if config.get("mock_outputs") is not None:
        session["model_class"] = "mock"
        session["mock_outputs"] = config["mock_outputs"]
    return session


def run(config: dict[str, Any], args: argparse.Namespace) -> int:
    if len(args.file) != 1:
        print(f"shim: expected exactly one --file, got {args.file}", file=sys.stderr)
        return 2
    workdir = Path.cwd()
    source = args.file[0]
    message_path = Path(args.message_file)
    message = (message_path if message_path.is_absolute() else workdir / message_path).read_text()

    sdir = next_session_dir(workdir.parent)
    session_dir, out, work = sdir / "session", sdir / "out", sdir / "work"
    (session_dir / "bin").mkdir(parents=True)
    out.mkdir()
    shutil.copytree(workdir, work, symlinks=True, ignore=IGNORED_COPY)
    snapshot = sdir / ".before"
    shutil.copytree(workdir, snapshot, symlinks=True, ignore=IGNORED_COPY)

    session = build_session(config, args, workdir, message)
    session["llm_cache"] = session_scope(config, workdir, sdir.name)
    replay = (session["llm_cache"] or {}).get("mode") == "replay"
    (session_dir / "session.json").write_text(json.dumps(session, indent=2))
    for name, body in (("agent-build", AGENT_BUILD), ("agent-worker", AGENT_WORKER)):
        (session_dir / "bin" / name).write_text(body)
        (session_dir / "bin" / name).chmod(0o755)

    roles = required_roles(config["topology"])
    mock = config.get("mock_outputs") is not None
    network, rewrites = agent_network(config.get("agent_network", "auto"), [config["models"][r].get("api_base") for r in roles])
    for role in roles:
        base = session["models"][role]["api_base"]
        session["models"][role]["api_base"] = rewrites.get(base, base)
    (session_dir / "session.json").write_text(json.dumps(session, indent=2))
    env = {f"AGENT_{r.upper()}_API_KEY": config["models"][r]["api_key"] for r in roles if config["models"][r].get("api_key")}
    env.update({
        "PATH": "/src/session/bin:/opt/agent/bin:/opt/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "CARGO_HOME": "/tmp/cargo-home",
        "MSWEA_CONFIGURED": "true",
        "MSWEA_SILENT_STARTUP": "1",
        "MSWEA_COST_TRACKING": "ignore_errors",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    })
    name = f"agent-lineage-{uuid.uuid4().hex[:12]}"
    spec = docker.ContainerSpec(
        image=image_for(source, config),
        command=["/opt/agent/bin/python", "-m", "src.incontainer.agent_session", "run"],
        mounts=[
            docker.Mount(work, "/work", False),
            docker.Mount(session_dir, "/src/session", False),
            docker.Mount(out, "/src/out", False),
            *llm_cache_mounts(session["llm_cache"], config.get("cache_dir")),
        ],
        env=env,
        workdir="/work",
        network="none" if mock or replay else network,
        limits=docker.Limits.from_config(config.get("limits", {})),
        name=name,
        extra_args=["--add-host", "host.docker.internal:host-gateway"] if rewrites else [],
    )

    terminated: list[int] = []

    def on_term(signum, _frame):  # `timeout` in run_experiment.sh signals this process only
        # Stop the container; docker.run then returns and the source written so
        # far is still copied back (Aider likewise leaves partial edits in place).
        terminated.append(signum)
        docker.kill(name)

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    print(f"The pipeline mini-swe-agent session {sdir.name}: topology={config['topology']} image={spec.image} network={spec.network}")
    print(f"models: " + ", ".join(f"{r}={session['models'][r]['model']}" for r in roles))
    print(f"sampling: {json.dumps(session['sampling'].get('worker', {}), sort_keys=True)}")
    result = docker.run(spec, timeout=float(config["session_timeout_s"]) + 300)
    (out / "container.log").write_text(result.stdout + "\n--- stderr ---\n" + result.stderr)
    (sdir / "container.json").write_text(json.dumps(result.to_json(), indent=2))

    agents = []
    if (out / "agents.jsonl").is_file():
        agents = [json.loads(line) for line in (out / "agents.jsonl").read_text().splitlines() if line.strip()]
    for record in agents:
        print(f"agent {record['label']}: exit_status={record['exit_status']} api_calls={record['api_calls']} "
              f"tokens={record['tokens']} elapsed_s={record['elapsed_s']} cache_hits={record.get('cache_hits', 0)}")

    edited = work / source
    target = workdir / source
    discarded = [p for p in changed_files(snapshot, work) if p != source]
    if discarded:
        print("discarded changes outside the editable source: " + ", ".join(discarded[:20]))
    if edited.is_file() and not (target.is_file() and filecmp.cmp(edited, target, shallow=False)):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(edited, target)
        print(f"Applied edit to {source}")
    elif not edited.is_file():
        print(f"the agent left no {source}")
    else:
        print(f"{source} unchanged")
    shutil.rmtree(snapshot, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    print(f"session artifacts: {sdir}")

    if terminated:
        print(f"shim: terminated by signal {terminated[0]}; partial source harvested", file=sys.stderr)
        return 128 + terminated[0]
    if result.timed_out:
        print("shim: agent container exceeded the session timeout", file=sys.stderr)
        return 124
    if not agents:
        print("shim: the agent container produced no session record (infrastructure failure)", file=sys.stderr)
        print(result.stderr[-3000:], file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_aider_args(list(sys.argv[1:] if argv is None else argv))
    config = json.loads(Path(args.agent_config).read_text()) if args.agent_config else None
    if args.version:
        print(version_string(config))
        return 0
    if config is None:
        print("shim: --agent-config is required", file=sys.stderr)
        return 2
    return run(config, args)


if __name__ == "__main__":
    sys.exit(main())
