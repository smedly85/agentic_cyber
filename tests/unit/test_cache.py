"""Unit tests for src.cache, the parallel/cache config and the parallel-lineage helpers."""

from __future__ import annotations

import pytest

from src.cache import StepCache, digest, llm_settings, tree_hash
from src.cli import build_parser, cli_overrides
from src.config import ConfigError, check_ready_for_run, load_config
from src.lineage.runner import with_lineages


def test_digest_is_order_independent_for_dicts():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    assert digest("x", 1) != digest("x", 2)


def test_tree_hash_tracks_content_and_ignores_build_dirs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.c").write_text("int a;")
    first = tree_hash(tmp_path)
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "junk").write_text("x")
    assert tree_hash(tmp_path) == first
    (tmp_path / "src" / "a.c").write_text("int b;")
    assert tree_hash(tmp_path) != first
    assert tree_hash(None) is None


def test_step_cache_put_get_memo(tmp_path):
    cache = StepCache(tmp_path)
    assert cache.get("k", "abc") is None
    (tmp_path / "emit").mkdir()
    (tmp_path / "emit" / "f").write_text("1")
    cache.put("k", "abc", {"ok": True}, {"emit": tmp_path / "emit"})
    value, entry = cache.get("k", "abc")
    assert value == {"ok": True} and (entry / "emit" / "f").read_text() == "1"
    calls = []
    compute = lambda: calls.append(1) or {"v": len(calls)}
    assert cache.memo("m", {"x": 1}, compute) == {"v": 1}
    assert cache.memo("m", {"x": 1}, compute) == {"v": 1} and len(calls) == 1  # hit returned unmodified
    assert cache.stats()["hits"] == 2


def test_step_cache_disabled(tmp_path):
    cache = StepCache(tmp_path, enabled=False)
    cache.put("k", "abc", {"ok": True})
    assert cache.get("k", "abc") is None and not (tmp_path / "steps").exists()


def test_llm_settings_scope_and_namespace():
    base = load_config(None, None, {}, environ={})
    assert llm_settings(base, ["s"])["mode"] == "record"
    other = load_config(None, None, {"cache.namespace": "repeat-2"}, environ={})
    assert llm_settings(base, ["s"])["scope"] != llm_settings(other, ["s"])["scope"]
    assert llm_settings(load_config(None, None, {"cache.llm": "off"}, environ={}), ["s"]) is None
    assert llm_settings(load_config(None, None, {"cache.enabled": False}, environ={}), ["s"]) is None


@pytest.mark.parametrize("override", [{"depth.parallel": 0}, {"lineage.parallel": "2"}, {"cache.llm": "always"}, {"cache.match": "fuzzy"}])
def test_cache_and_parallel_validation(override):
    with pytest.raises(ConfigError):
        load_config(None, None, override, environ={})


def test_replay_needs_no_model():
    cfg = load_config(None, None, {"depth.input": "x", "tests.visible_suite": "v", "tests.hidden_suite": "h", "cache.llm": "replay"}, environ={})
    assert check_ready_for_run(cfg) == []


def test_cli_cache_flags():
    args = build_parser().parse_args(["depth", "-j", "4", "--replay", "--cache-namespace", "n"])
    o = cli_overrides(args)
    assert o["depth.parallel"] == 4 and o["cache.llm"] == "replay" and o["cache.match"] == "sequence" and o["cache.namespace"] == "n"
    o = cli_overrides(build_parser().parse_args(["lineage", "--parallel", "3", "--no-cache", "--cache-match", "exact"]))
    assert o["lineage.parallel"] == 3 and o["cache.enabled"] is False and o["cache.match"] == "exact"


def test_with_lineages():
    argv = ["bash", "s.sh", "--lineages", "5", "--lineage-start", "1", "--x"]
    assert with_lineages(argv, 3, 1) == ["bash", "s.sh", "--lineages", "1", "--lineage-start", "3", "--x"]


def test_tree_hash_not_fooled_by_preserved_mtime(tmp_path):
    import os
    import shutil

    a, b, work = tmp_path / "a", tmp_path / "b", tmp_path / "work"
    for d, text in ((a, "AAAA"), (b, "BBBB")):
        d.mkdir()
        (d / "f.c").write_text(text)
        os.utime(d / "f.c", ns=(1, 1))  # identical size and mtime
    shutil.copytree(a, work)
    first = tree_hash(work)
    shutil.rmtree(work)
    shutil.copytree(b, work)  # copy2 preserves the (identical) mtime
    assert tree_hash(work) != first
