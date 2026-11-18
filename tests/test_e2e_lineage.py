"""End-to-end lineage-mode runs with scripted (deterministic) models.

1. The Aider shim on its own, in the real agent-c image (single and
   orchestrator topologies): only the editable source survives a session.
2. `python -m src lineage` through the unchanged src/harness/run_lineage_experiment.sh ->
   run_experiment.sh with Docker build/judge. This needs the linux-utilities
   benchmark images named by the effective lock (LINUX_BENCHMARK_LOCK or
   coreutils/images.lock.json) and is skipped without them.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src import REPO_ROOT
from src.config import load_config
from src.lineage import runner, shim

from test_e2e_mock import SUBMIT, have_image, say

pytestmark = pytest.mark.skipif(not have_image("agent-c:latest"), reason="agent-c image not built")


def benchmark_images_present() -> bool:
    lock = Path(os.environ.get("LINUX_BENCHMARK_LOCK", REPO_ROOT / "coreutils/images.lock.json"))
    if not lock.is_file():
        return False
    data = json.loads(lock.read_text())
    return all(have_image(data[k]) for k in ("oracle_image", "compiler_image") if k in data)


def shim_workdir(tmp_path: Path) -> Path:
    attempt = tmp_path / "lineage-001" / "000" / "temp-0p0" / "attempt-001"
    work = attempt / "workdir"
    (work / "src").mkdir(parents=True)
    (work / "tests").mkdir()
    (work / "prompt.md").write_text("Write src/hello.c: a C program that prints hello.\n")
    (work / "tests" / "spec.md").write_text("expected: hello\n")
    (attempt / "settings.yml").write_text(json.dumps([{"name": "mock/w", "extra_params": {"temperature": 0.3}}]))
    return work


def run_shim(work: Path, config: dict, monkeypatch, capsys) -> tuple[int, str]:
    cfg_path = work.parent / "shim.json"
    cfg_path.write_text(json.dumps(config))
    monkeypatch.chdir(work)
    monkeypatch.setattr("sys.argv", ["shim"])
    status = shim.main(["--agent-config", str(cfg_path), "--architect", "--model", "mock/w",
                        "--model-settings-file", str(work.parent / "settings.yml"),
                        "--message-file", "prompt.md", "--file", "src/hello.c",
                        "--read", "tests/spec.md", "--no-git"])
    return status, capsys.readouterr().out


HELLO = '#include <stdio.h>\nint main(void) { puts("hello"); return 0; }'


def shim_config(topology: str, outputs: dict) -> dict:
    c = load_config(None, None, {"agent.topology": topology, "retry.session_timeout_s": 300, "cache.enabled": False},
                    environ={"AGENT_WORKER_MODEL": "mock/w", "AGENT_ORCHESTRATOR_MODEL": "mock/o"})
    cfg = runner.shim_config(c)
    cfg["mock_outputs"] = outputs
    return cfg


def test_shim_single_keeps_only_the_source(tmp_path, monkeypatch, capsys):
    work = shim_workdir(tmp_path)
    outputs = {"worker": [
        say(f"cat > src/hello.c <<'SRC_EOF'\n{HELLO}\nSRC_EOF\necho tampered > tests/spec.md\nagent-build"),
        SUBMIT,
    ]}
    status, out = run_shim(work, shim_config("single", outputs), monkeypatch, capsys)
    assert status == 0, out
    assert (work / "src" / "hello.c").read_text().strip() == HELLO
    assert (work / "tests" / "spec.md").read_text() == "expected: hello\n"
    assert "Applied edit to src/hello.c" in out
    assert "discarded changes outside the editable source: tests/spec.md" in out
    session = work.parent / "agent" / "session-01"
    doc = json.loads((session / "session" / "session.json").read_text())
    assert doc["kind"] == "lineage" and doc["sampling"]["worker"] == {"temperature": 0.3}
    task = (session / "out" / "task.md").read_text()
    assert "Write src/hello.c" in task and "`tests/spec.md`" in task
    trajectory = (session / "out" / "trajectory-worker.json").read_text()
    assert "BUILD: OK" in trajectory


def test_shim_orchestrator_delegates(tmp_path, monkeypatch, capsys):
    work = shim_workdir(tmp_path)
    outputs = {
        "orchestrator": [say('agent-worker "write the program"'), SUBMIT],
        "worker": [say(f"cat > src/hello.c <<'SRC_EOF'\n{HELLO}\nSRC_EOF"), SUBMIT],
    }
    status, out = run_shim(work, shim_config("orchestrator", outputs), monkeypatch, capsys)
    assert status == 0, out
    assert (work / "src" / "hello.c").read_text().strip() == HELLO
    session = work.parent / "agent" / "session-01" / "out"
    labels = [json.loads(l)["label"] for l in (session / "agents.jsonl").read_text().splitlines()]
    assert labels == ["worker-1", "orchestrator"]
    assert "BUILD: OK" in (session / "trajectory-orchestrator.json").read_text()


@pytest.mark.skipif(not benchmark_images_present(), reason="linux-utilities benchmark images not present")
def test_lineage_through_run_lineage_experiment(tmp_path):
    """Two lineages in parallel through the unchanged scripts, then an offline replay."""
    wrong = '#include <stdio.h>\nint main(void) { puts("not sort"); return 0; }'

    def config(out, **extra):
        cli = {"lineage.utility": "c-sort", "lineage.output_dir": str(out), "retry.max_loops": 1,
               "retry.session_timeout_s": 600, "lineage.security.enabled": False, "cache.dir": str(tmp_path / "cache"),
               "lineage.lineages": 2, "lineage.parallel": 2}
        cli.update(extra)
        return load_config(None, None, cli, environ={"AGENT_WORKER_MODEL": "mock/w"})

    out = tmp_path / "lineage"
    outputs = {"worker": [say(f"mkdir -p src/c_sort && cat > src/c_sort/c_sort.c <<'SRC_EOF'\n{wrong}\nSRC_EOF"), SUBMIT]}
    assert runner.run_lineage(config(out), mock_outputs=outputs) in (0, 1)
    run_record = json.loads((out / "lineages.json").read_text())
    assert run_record["planned_lineage_ids"] == ["lineage-001", "lineage-002"]
    for lineage in ("lineage-001", "lineage-002"):
        record = json.loads((out / lineage / "lineage.json").read_text())
        assert record["state"] == "stopped" and record["failure_stage"] == "000"
        assert record["aider_version"].startswith("minisweagent-shim")
        assert record["model_provenance"]["pipeline"]["roles"] == {"worker": "mock/w"}
        attempt = out / lineage / "000" / "temp-0p0" / "attempt-001"
        meta = json.loads((attempt / "metadata.json").read_text())
        assert meta["stop_reason"] in ("loop_limit", "no_progress")
        # The judges really ran (1 = case failures for this wrong program), not
        # 126/127/2 from a missing judge, harness module or suite.
        assert meta["build_exit_code"] == 0
        assert meta["feature_test_exit_code"] == 1 and meta["extra_test_exit_code"] == 1, meta
        assert "1/70 pass" in (attempt / "feature-tests.log").read_text()
        assert "Held-out evaluation complete" in (attempt / "extra-tests.log").read_text()
        assert (attempt / "agent" / "session-01" / "out" / "trajectory-worker.json").is_file()
        assert (attempt / "candidate" / "c_sort.c").read_text().strip() == wrong
    assert (out / "pipeline" / "logs" / "lineage-002.log").is_file()
    assert [r["state"] for r in json.loads((out / "pipeline" / "summary.json").read_text())] == ["stopped", "stopped"]

    # Replay into a new directory with no model: same candidates, every call from the cache.
    replay = tmp_path / "replay"
    assert runner.run_lineage(config(replay, **{"cache.llm": "replay", "cache.match": "sequence"}), mock_outputs={}) in (0, 1)
    attempt = replay / "lineage-001" / "000" / "temp-0p0" / "attempt-001"
    assert (attempt / "candidate" / "c_sort.c").read_text().strip() == wrong
    assert "cache_hits=2" in (attempt / "aider.log").read_text()


def test_shim_record_then_replay_offline(tmp_path, monkeypatch, capsys):
    cache = tmp_path / "cache"
    outputs = {"worker": [say(f"cat > src/hello.c <<'SRC_EOF'\n{HELLO}\nSRC_EOF\nagent-build"), SUBMIT]}

    def config(mode, outs):
        c = load_config(None, None, {"retry.session_timeout_s": 300, "cache.dir": str(cache), "cache.llm": mode,
                                     "cache.match": "sequence", "lineage.utility": "c-sort"},
                        environ={"AGENT_WORKER_MODEL": "mock/w"})
        cfg = runner.shim_config(c)
        cfg["mock_outputs"] = outs
        return cfg

    first = shim_workdir(tmp_path / "record")
    status, out = run_shim(first, config("record", outputs), monkeypatch, capsys)
    assert status == 0 and "Applied edit" in out
    second = shim_workdir(tmp_path / "replay")  # same lineage/checkpoint/attempt names -> same scope
    status, out = run_shim(second, config("replay", {}), monkeypatch, capsys)
    assert status == 0, out
    assert "cache_hits=2" in out and "network=none" in out
    assert (second / "src" / "hello.c").read_text().strip() == HELLO


def test_shim_sigterm_still_harvests_the_source(tmp_path):
    """run_experiment.sh's `timeout` sends SIGTERM: the source written so far must survive."""
    work = shim_workdir(tmp_path)
    cfg = shim_config("single", {"worker": [say(f"cat > src/hello.c <<'SRC_EOF'\n{HELLO}\nSRC_EOF\nsleep 600"), SUBMIT]})
    cfg_path = work.parent / "shim.json"
    cfg_path.write_text(json.dumps(cfg))
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    proc = subprocess.Popen([sys.executable, "-m", "src.lineage.shim", "--agent-config", str(cfg_path),
                             "--message-file", "prompt.md", "--file", "src/hello.c"],
                            cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    written = work.parent / "agent" / "session-01" / "work" / "src" / "hello.c"
    deadline = time.time() + 120
    while not written.is_file() and time.time() < deadline:
        time.sleep(0.5)
    assert written.is_file()
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=120)
    assert proc.returncode == 128 + signal.SIGTERM, out
    assert "Applied edit to src/hello.c" in out
    assert (work / "src" / "hello.c").read_text().strip() == HELLO
