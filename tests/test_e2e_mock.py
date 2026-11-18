"""End-to-end depth-mode runs with scripted (deterministic) models.

Exercises the real pipeline: Docker images, call-graph backends, in-container
locate/splice/signature checks, mini-swe-agent sessions, controller
verification, hidden suites and outputs. Skipped when the images are absent.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.config import load_config
from src.depth.runner import DepthRun

FIXTURES = Path(__file__).parent / "fixtures"


def have_image(tag: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0


def say(command: str) -> dict:
    return {
        "role": "assistant",
        "content": f"THOUGHT: next step.\n\n```mswea_bash_command\n{command}\n```",
        "extra": {"actions": [{"command": command}], "cost": 0.0},
    }


SUBMIT = say("echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT")


def write_and_test(path: str, text: str) -> dict:
    return say(f"cat > {path} <<'SRC_EOF'\n{text}\nSRC_EOF\nagent-test")


def make_config(tmp_path: Path, **overrides) -> dict:
    cli = {
        "depth.output_dir": str(tmp_path / "runs"),
        "depth.order": "source",
        "retry.max_loops": 1,
        "retry.session_timeout_s": 600,
        "tests.visible_suite": str(FIXTURES / "suites" / "toy-visible"),
        "tests.hidden_suite": str(FIXTURES / "suites" / "toy-hidden"),
        "cache.dir": str(tmp_path / "cache"),
    }
    cli.update(overrides)
    return load_config(None, None, cli, environ={})


SUM_ALL = """static long sum_all(int count, char **items, int *ok)
{
    long total = 0;
    int i = count;
    while (i-- > 0) {
        long value;
        if (parse_number(items[count - 1 - i], &value) != 0) {
            *ok = 0;
            return 0;
        }
        total = total + value;
    }
    *ok = 1;
    return total;
}"""

APPLY_BAD = "long apply(long (*fn)(long), long value) { return fn(value); }"
APPLY_GOOD = """long apply(long (*op)(long), long value)
{
    long (*const f)(long) = op;
    return (*f)(value);
}"""


@pytest.mark.skipif(not have_image("agent-c:latest"), reason="agent-c image not built")
def test_c_cumulative_mock(tmp_path):
    cfg = make_config(tmp_path, **{"depth.input": str(FIXTURES / "c_toy"), "depth.depth": 2})
    mock = {
        "main.c::sum_all": [{"worker": [write_and_test("/src/edit/sum_all.c", SUM_ALL), SUBMIT]}],
        "util.c::apply": [
            {"worker": [write_and_test("/src/edit/apply.c", APPLY_BAD), SUBMIT]},
            {"worker": [write_and_test("/src/edit/apply.c", APPLY_GOOD), SUBMIT]},
        ],
        "util.c::parse_number": [{"worker": [SUBMIT]}, {"worker": [SUBMIT]}],
        "util.c::square": [{"worker": [write_and_test("/src/edit/square.c", "long square(long value) { long r = value; return r * value; }"), SUBMIT]}],
        "util.c::negate": [{"worker": [write_and_test("/src/edit/negate.c", "long negate(long value) { return 0 - value; }"), SUBMIT]}],
    }
    run = DepthRun(cfg, mock_outputs=mock)
    assert run.run() == 0
    summary = json.loads((run.run_dir / "summary.json").read_text())
    by_id = {f["id"]: f for f in summary["functions"]}
    assert by_id["main.c::sum_all"]["accepted"] and by_id["main.c::sum_all"]["attempts"] == 1
    assert by_id["util.c::apply"]["accepted"] and by_id["util.c::apply"]["attempts"] == 2
    assert not by_id["util.c::parse_number"]["accepted"]
    assert by_id["util.c::parse_number"]["stop_reason"] == "no_progress"
    assert summary["accepted"] == 4 and summary["final_visible_ok"] and summary["final_hidden_ok"]

    apply_dir = run.run_dir / by_id["util.c::apply"]["dir"]
    first = json.loads((apply_dir / "attempt-0" / "verification.json").read_text())
    assert first["stage"] == "signature" and "param_names" in first["summary"]
    final_util = (run.run_dir / "final" / "util.c").read_text()
    assert "(*f)(value)" in final_util and "0 - value" in final_util
    assert "if (!is_digit_char(text[i])) return -1;" in final_util  # parse_number reverted/kept
    assert "while (i-- > 0)" in (run.run_dir / "final" / "main.c").read_text()
    for name in ("manifest.json", "callgraph.json", "selection.json", "baseline.json"):
        assert (run.run_dir / name).is_file()
    # hidden suite never mounted into agent sessions
    session = json.loads((apply_dir / "attempt-0" / "session" / "session.json").read_text())
    assert "hidden" not in json.dumps(session)


PARSE_RS = """use std::str::FromStr;

fn digits_ok(d: &str) -> bool {
    !d.is_empty() && d.chars().all(is_digit_char)
}

fn parse_number(text: &str) -> Option<i64> {
    let negative = text.starts_with('-');
    let digits = if negative { &text[1..] } else { text };
    if !digits_ok(digits) {
        return None;
    }
    let magnitude = i64::from_str(digits).ok()?;
    Some(if negative { -magnitude } else { magnitude })
}"""

ADD_RS = """fn add(&mut self, value: i64) {
        self.total = self.total.wrapping_add(0) + value;
    }"""


@pytest.mark.skipif(not have_image("agent-rust:latest"), reason="agent-rust image not built")
def test_rust_planner_worker_independent_mock(tmp_path):
    cfg = make_config(
        tmp_path,
        **{
            "depth.input": str(FIXTURES / "rust_toy"),
            "depth.depth": 2,
            "depth.rule": "eq",
            "callgraph.rust_backend": "mir",
            "agent.topology": "planner_worker",
            "depth.accumulation": "independent",
            "retry.max_loops": 0,
        },
    )
    plan = say("printf 'Use starts_with and from_str.\\n' > /src/session/plan.md && echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat /src/session/plan.md")
    mock = {
        "::parse_number": [{"planner": [plan], "worker": [write_and_test("/src/edit/parse_number.rs", PARSE_RS), SUBMIT]}],
        "::{impl#2}::add": [{"planner": [plan], "worker": [write_and_test("/src/edit/Accumulator_add.rs", ADD_RS), SUBMIT]}],
    }
    run = DepthRun(cfg, mock_outputs=mock)
    # restrict to two functions to keep the test fast
    original_select = run.select
    run.select = lambda graph: [f for f in original_select(graph) if f.attributes["key"] in mock]
    assert run.run() == 0
    summary = json.loads((run.run_dir / "summary.json").read_text())
    assert summary["accepted"] == 2, summary
    variants = sorted((run.run_dir / "variants").iterdir())
    assert len(variants) == 2
    parse_dir = run.run_dir / [f for f in summary["functions"] if f["id"].endswith("parse_number")][0]["dir"]
    verification = json.loads((parse_dir / "attempt-0" / "verification.json").read_text())
    assert verification["additions"]["helpers"] == ["digits_ok"]
    assert verification["additions"]["includes"] == ["use std::str::FromStr;"]
    assert (parse_dir / "attempt-0" / "out" / "plan.md").read_text().startswith("Use starts_with")


@pytest.mark.skipif(not have_image("agent-c:latest"), reason="agent-c image not built")
def test_c_orchestrator_mock(tmp_path):
    cfg = make_config(tmp_path, **{"depth.input": str(FIXTURES / "c_toy"), "agent.topology": "orchestrator", "retry.max_loops": 0})
    mock = {
        "util.c::negate": [
            {
                "orchestrator": [say('agent-worker "Use subtraction from zero."'), say("agent-test"), SUBMIT],
                "worker": [write_and_test("/src/edit/negate.c", "long negate(long value) { return 0 - value; }"), SUBMIT],
            }
        ]
    }
    run = DepthRun(cfg, mock_outputs=mock)
    original_select = run.select
    run.select = lambda graph: [f for f in original_select(graph) if f.id in mock]
    assert run.run() == 0
    summary = json.loads((run.run_dir / "summary.json").read_text())
    assert summary["accepted"] == 1
    fdir = run.run_dir / summary["functions"][0]["dir"]
    agents = [json.loads(l) for l in (fdir / "attempt-0" / "out" / "agents.jsonl").read_text().splitlines()]
    assert [a["label"] for a in agents] == ["worker-1", "orchestrator"]


def c_toy_mock() -> dict:
    return {
        "main.c::sum_all": [{"worker": [write_and_test("/src/edit/sum_all.c", SUM_ALL), SUBMIT]}],
        "util.c::apply": [
            {"worker": [write_and_test("/src/edit/apply.c", APPLY_BAD), SUBMIT]},
            {"worker": [write_and_test("/src/edit/apply.c", APPLY_GOOD), SUBMIT]},
        ],
        "util.c::parse_number": [{"worker": [SUBMIT]}, {"worker": [SUBMIT]}],
        "util.c::square": [{"worker": [write_and_test("/src/edit/square.c", "long square(long value) { long r = value; return r * value; }"), SUBMIT]}],
        "util.c::negate": [{"worker": [write_and_test("/src/edit/negate.c", "long negate(long value) { return 0 - value; }"), SUBMIT]}],
    }


def assert_c_toy_result(run: DepthRun) -> dict:
    summary = json.loads((run.run_dir / "summary.json").read_text())
    by_id = {f["id"]: f for f in summary["functions"]}
    assert summary["accepted"] == 4 and summary["final_visible_ok"] and summary["final_hidden_ok"], summary
    assert by_id["util.c::parse_number"]["stop_reason"] == "no_progress"
    final_util = (run.run_dir / "final" / "util.c").read_text()
    assert "(*f)(value)" in final_util and "0 - value" in final_util and "long r = value" in final_util
    assert "while (i-- > 0)" in (run.run_dir / "final" / "main.c").read_text()
    return summary


@pytest.mark.skipif(not have_image("agent-c:latest"), reason="agent-c image not built")
def test_c_cumulative_parallel_wave_then_replay(tmp_path):
    """All five functions in one wave; later candidates merge into the evolving program.
    Then the same run is replayed from the LLM cache with no model at all."""
    cfg = make_config(tmp_path, **{"depth.input": str(FIXTURES / "c_toy"), "depth.depth": 2, "depth.parallel": 5})
    run = DepthRun(cfg, mock_outputs=c_toy_mock())
    assert run.run() == 0
    summary = assert_c_toy_result(run)
    assert summary["parallel"] == 5
    merged = [f for f in summary["functions"] if f["merge"]]
    assert merged and all(f["merge"]["ok"] for f in merged) and not any(f["rebased"] for f in summary["functions"])

    # Replay: every model call must come from the cache (the scripted models are empty).
    replay_cfg = make_config(tmp_path, **{"depth.input": str(FIXTURES / "c_toy"), "depth.depth": 2,
                                          "cache.llm": "replay", "cache.match": "sequence"})
    replay = DepthRun(replay_cfg, mock_outputs={k: [] for k in c_toy_mock()})
    assert replay.run() == 0
    replayed = assert_c_toy_result(replay)
    assert replayed["cache"]["llm_hits"] >= 9
    assert replayed["cache"]["steps"]["hits"] > 0  # baseline, call graph, verifications


@pytest.mark.skipif(not have_image("agent-c:latest"), reason="agent-c image not built")
def test_replay_miss_is_reported_not_called(tmp_path):
    cfg = make_config(tmp_path, **{"depth.input": str(FIXTURES / "c_toy"), "retry.max_loops": 0,
                                   "cache.llm": "replay", "cache.match": "exact"})
    run = DepthRun(cfg, mock_outputs={"util.c::negate": []})
    original_select = run.select
    run.select = lambda graph: [f for f in original_select(graph) if f.id == "util.c::negate"]
    assert run.run() == 0
    summary = json.loads((run.run_dir / "summary.json").read_text())
    assert summary["accepted"] == 0
    fdir = run.run_dir / summary["functions"][0]["dir"]
    agents = [json.loads(l) for l in (fdir / "attempt-0" / "out" / "agents.jsonl").read_text().splitlines()]
    assert "CacheMiss" in json.dumps(agents)
