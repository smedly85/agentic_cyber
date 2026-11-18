"""Depth mode: baseline gate -> call graph -> selection -> per-function loop.

Parallelism (`depth.parallel = P`):
  independent  every function runs against the original program; up to P at once.
  cumulative   functions are processed in waves of P. Every function in a wave
               is diversified against the same snapshot of the evolving program.
               Accepted candidates are then merged in selection order: the first
               one directly (exactly as a serial run would), each later one by
               re-locating the function in the merged program and re-verifying
               the candidate there (splice, signature/additions, build, visible
               suite). A candidate that does not merge cleanly gets one fresh
               diversification against the merged program ("rebase").
  With P = 1 both modes are exactly the serial algorithm.

Caching (`[cache]`, src/cache.py): call graphs, locate results and every
evaluation (baseline, verification, hidden suite, final checks) are cached by
content; agent sessions record/replay model responses.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping

from src import REPO_ROOT, __version__, registry
from src.cache import code_hash, digest, llm_settings, step_cache, tree_hash
from src.config import redacted
from src.model import CallGraph, CGFunction, StopReason
from src.project import Project, copy_tree, discover, make_working_copy
from src.sandbox import docker, steps


_print_lock = threading.Lock()


def log(message: str) -> None:
    with _print_lock:
        print(f"[pipeline {dt.datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False, default=str) + "\n")


def infer_language(input_path: Path) -> str:
    if input_path.is_file():
        return {".c": "c", ".rs": "rust"}.get(input_path.suffix, "")
    if (input_path / "Cargo.toml").is_file() or list(input_path.rglob("*.rs")):
        return "rust"
    if list(input_path.rglob("*.c")):
        return "c"
    return ""


def git_commit() -> str | None:
    proc = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    return (proc.stdout.strip() + ("+dirty" if dirty else "")) if proc.returncode == 0 else None


def build_context(project: Project, config: Mapping[str, Any]) -> dict[str, Any]:
    plugins = config.get("plugins", {})
    return {
        "language": project.language,
        "sources": list(project.sources),
        "crate_root": project.sources[0] if project.language == "rust" else None,
        "crate_name": project.crate_name,
        "program_name": project.root.name,
        "flags": list(config["build"].get("flags", [])),
        "build_cmd": config["build"].get("cmd"),
        "allow": dict(config["edit"]),
        "lang_module": plugins.get("language"),
        "test_runner_class": plugins.get("test_runner"),
        "feedback_class": plugins.get("feedback"),
    }


def _normalized_code(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _session_summary(agents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "api_calls": sum(a.get("api_calls", 0) for a in agents),
        "tokens": sum(a.get("tokens", 0) for a in agents),
        "cost": sum(a.get("cost", 0.0) for a in agents),
        "exit_statuses": [a.get("exit_status") for a in agents],
        "cache_hits": sum(a.get("cache_hits", 0) for a in agents),
    }


class DepthRun:
    def __init__(self, config: dict[str, Any], mock_outputs: Mapping[str, Any] | None = None):
        self.config = config
        self.mock_outputs = mock_outputs  # tests only: {function_key: [ {role: [outputs]} per loop ]}
        self.cache = step_cache(config)

    # ------------------------------------------------------------------ setup
    def prepare(self) -> None:
        cfg = self.config
        dcfg = cfg["depth"]
        if not dcfg["input"]:
            raise SystemExit("pipeline: depth.input is not set")
        self.input = Path(dcfg["input"]).expanduser()
        if not self.input.is_absolute():
            self.input = (Path.cwd() / self.input).resolve()
        if not self.input.exists():
            raise SystemExit(f"pipeline: input not found: {self.input}")
        language = dcfg["language"] or infer_language(self.input)
        if language not in ("c", "rust"):
            raise SystemExit("pipeline: cannot infer language; set depth.language")
        dcfg["language"] = language
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_root = Path(dcfg["output_dir"])
        if not out_root.is_absolute():
            out_root = REPO_ROOT / out_root
        self.run_dir = out_root / f"{stamp}-{self.input.stem}"
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.original = make_working_copy(self.input, self.run_dir / "original")
        self.project = discover(self.original, language)
        self.context = build_context(self.project, cfg)
        self.image = cfg["docker"][f"{language}_image"]
        self.image_id = docker.require_image(self.image)
        self.visible = self._suite_path("visible_suite")
        self.hidden = self._suite_path("hidden_suite")
        self.original_hash = tree_hash(self.original)
        write_json(
            self.run_dir / "manifest.json",
            {
                "tool_version": __version__,
                "mode": "depth",
                "started_at": dt.datetime.now().isoformat(timespec="seconds"),
                "git_commit": git_commit(),
                "input": str(self.input),
                "language": language,
                "project_kind": self.project.kind,
                "sources": list(self.project.sources),
                "image": {"tag": self.image, "id": self.image_id},
                "config": redacted(cfg),
                "argv": sys.argv,
                "input_hash": self.original_hash,
                "code_hash": code_hash(),
            },
        )
        log(f"run directory: {self.run_dir}")

    def _suite_path(self, key: str) -> Path | None:
        value = self.config["tests"][key]
        if not value:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if not (path / "run").is_file():
            raise SystemExit(f"pipeline: tests.{key} has no executable `run`: {path}")
        return path

    # ------------------------------------------------------------------ cached steps
    def evaluate(self, project: Path, suite: Path | None, target: Mapping[str, Any] | None = None,
                 text: str | None = None, emit_dir: Path | None = None) -> dict[str, Any]:
        """steps.evaluate, cached by the content of everything it depends on."""
        cfg = self.config
        parts = {
            "image": self.image_id,
            "project": tree_hash(project),
            "suite": tree_hash(suite),
            "context": self.context,
            "target": target,
            "text": text,
            "feedback": cfg["tests"].get("feedback", {}),
            "emit": emit_dir is not None,
            "limits": [cfg["docker"][k] for k in ("cpus", "memory", "pids")],
        }
        key = digest("evaluate", parts, code_hash())
        hit = self.cache.get("evaluate", key)
        if hit is not None:
            value, entry = hit
            if emit_dir is not None and (entry / "emit").is_dir():
                emit_dir.mkdir(parents=True, exist_ok=True)
                copy_tree(entry / "emit", emit_dir / "project")
            value["cache"] = "hit"
            return value
        value = steps.evaluate(self.image, project, self.context, suite, cfg, target, text, emit_dir=emit_dir)
        if value.get("stage") != "infrastructure":
            emitted = emit_dir / "project" if emit_dir is not None else None
            self.cache.put("evaluate", key, value, {"emit": emitted} if emitted is not None and emitted.is_dir() else None)
        return value

    def locate(self, base: Path, key: str) -> dict[str, Any]:
        parts = {"image": self.image_id, "project": tree_hash(base), "context": self.context, "key": key}
        return self.cache.memo("locate", parts, lambda: steps.locate(self.image, base, self.context, key, self.config))

    # ------------------------------------------------------------------ stages
    def baseline(self) -> None:
        log("baseline: visible and hidden suites on the original program")
        with ThreadPoolExecutor(2) as pool:
            futures = {label: pool.submit(self.evaluate, self.original, suite)
                       for label, suite in (("visible", self.visible), ("hidden", self.hidden))}
            results = {label: f.result() for label, f in futures.items()}
        write_json(self.run_dir / "baseline.json", results)
        for label, res in results.items():
            if not res.get("ok"):
                raise SystemExit(f"pipeline: baseline {label} suite failed on the original program; aborting\n{res.get('summary', '')}")

    def callgraph(self):
        lang = self.project.language
        ref = self.config["callgraph"][f"{lang}_backend"]
        keep = self.run_dir / "callgraph"
        parts = {
            "backend": ref,
            "options": self.config["callgraph"].get("options", {}),
            "image": self.image_id,
            "project": self.original_hash,
            "kind": self.project.kind,
            "sources": list(self.project.sources),
            "crate": self.project.crate_name,
        }
        key = digest("callgraph", parts, code_hash())
        hit = self.cache.get("callgraph", key)
        if hit is not None:
            value, entry = hit
            log(f"call graph: {ref} (cached)")
            if (entry / "raw").is_dir():
                copy_tree(entry / "raw", keep)
            graph = CallGraph.from_json(value)
        else:
            backend = registry.resolve("callgraph", ref)()
            log(f"call graph: {ref}")
            graph = backend.build(self.project, self.config, keep_dir=keep)
            self.cache.put("callgraph", key, graph.to_json(), {"raw": keep} if keep.is_dir() else None)
        write_json(self.run_dir / "callgraph.json", graph.to_json())
        return graph

    def select(self, graph) -> list[CGFunction]:
        selector = registry.resolve("selector", self.config["depth"].get("selector", "depth"))()
        chosen = selector.select(graph, self.config)
        write_json(self.run_dir / "selection.json", [f.to_json() for f in chosen])
        return chosen

    # ------------------------------------------------------------------ per function
    def key_for(self, fn: CGFunction) -> str:
        if self.project.language == "rust":
            return fn.attributes["key"]
        return fn.id

    def diversify(self, fn: CGFunction, index: int, total: int, base: Path, tag: str = "") -> dict[str, Any]:
        cfg = self.config
        fdir = self.run_dir / "functions" / f"{index:03d}-{re.sub(r'[^A-Za-z0-9_.]+', '_', fn.id)[:80]}{'-' + tag if tag else ''}"
        fdir.mkdir(parents=True)
        record: dict[str, Any] = {"function": fn.to_json(), "attempts": [], "accepted": False}
        started = time.monotonic()
        log(f"[{index}/{total}] {fn.id} (depth {fn.depth}){' ' + tag if tag else ''}")
        try:
            target = self.locate(base, self.key_for(fn))
        except steps.StepError as exc:
            record.update(stop_reason="locate_failed", error=str(exc))
            write_json(fdir / "record.json", record)
            log(f"    skipped: cannot locate ({exc})")
            return record
        write_json(fdir / "target.json", target)
        (fdir / "original.txt").write_text(target["original_text"])
        generator = registry.resolve("generator", cfg["agent"]["generator"])(cfg)
        start_text = target["original_text"]
        repair = None
        stop = StopReason.LOOP_LIMIT
        prompt_vars = {
            "language": self.project.language,
            "language_name": "C" if self.project.language == "c" else "Rust",
            "target_name": target["name"],
            "target_file": target["file"],
            "target_line": target["line"],
            "target_depth": fn.depth if fn.depth is not None else "unreachable",
            "parent_kind": target.get("parent_kind", "module"),
            **cfg["edit"],
        }
        mock = (self.mock_outputs or {}).get(self.key_for(fn))
        for loop in range(cfg["retry"]["max_loops"] + 1):
            adir = fdir / f"attempt-{loop}"
            request = {
                "image": self.image,
                "project": base,
                "suite": self.visible,
                "context": self.context,
                "target": target,
                "start_text": start_text,
                "prompt_vars": prompt_vars,
                "repair": repair,
                "session_dir": adir,
                "mock_outputs": mock[loop] if mock and loop < len(mock) else ({} if mock is not None else None),
                "llm_cache": llm_settings(cfg, ["depth", self.original_hash, self.key_for(fn), loop, cfg["agent"]["topology"], tag]),
                "cache_dir": self.cache.root,
            }
            log(f"    [{index}] attempt {loop}: agent session ({cfg['agent']['topology']})")
            session = generator.run_session(request)
            final = session["final_text"]
            (adir / "candidate.txt").write_text(final)
            attempt: dict[str, Any] = {"loop": loop, "session": _session_summary(session["agents"]), "timed_out": session["timed_out"]}
            if session.get("infrastructure_error"):
                attempt.update(verdict="infrastructure_failure", detail=session.get("stderr_tail"))
                record["attempts"].append(attempt)
                stop = StopReason.INFRASTRUCTURE_FAILURE
                break
            if loop > 0 and final == start_text:
                attempt.update(verdict="no_progress")
                record["attempts"].append(attempt)
                stop = StopReason.NO_PROGRESS
                break
            if _normalized_code(final) == _normalized_code(target["original_text"]):
                verification = {"ok": False, "stage": "unchanged", "summary": "UNCHANGED: the function is identical to the original; it must be re-implemented differently."}
            else:
                verification = self.evaluate(base, self.visible, target, final, emit_dir=adir / "spliced")
            write_json(adir / "verification.json", verification)
            attempt.update(verdict="pass" if verification.get("ok") else "fail", stage=verification.get("stage"), summary=verification.get("summary"), additions=verification.get("additions"))
            record["attempts"].append(attempt)
            if verification.get("ok"):
                stop = StopReason.SUCCESS
                spliced = adir / "spliced" / "project"
                hidden = self.evaluate(spliced, self.hidden)
                write_json(adir / "hidden.json", hidden)
                record.update(
                    accepted=True,
                    accepted_loop=loop,
                    target=target,
                    candidate_file=str((adir / "candidate.txt").relative_to(self.run_dir)),
                    spliced_project=str(spliced.relative_to(self.run_dir)),
                    hidden={"ok": hidden.get("ok"), "passed": hidden.get("tests", {}).get("passed"), "failed": hidden.get("tests", {}).get("failed")},
                    additions=verification.get("additions"),
                )
                log(f"    [{index}] accepted (hidden suite: {'pass' if hidden.get('ok') else 'FAIL'})")
                break
            log(f"    [{index}] rejected at {verification.get('stage')}")
            if session["timed_out"] and loop == cfg["retry"]["max_loops"]:
                stop = StopReason.TIMEOUT
            repair = {
                "loop": loop + 1,
                "max_loops": cfg["retry"]["max_loops"],
                "failure_summary": (verification.get("summary") or "")[-6000:],
                "original_text": target["original_text"],
            }
            start_text = final if final.strip() else target["original_text"]
        record["stop_reason"] = stop.value
        record["elapsed_s"] = round(time.monotonic() - started, 3)
        record["totals"] = {
            "api_calls": sum(a["session"]["api_calls"] for a in record["attempts"] if "session" in a),
            "tokens": sum(a["session"]["tokens"] for a in record["attempts"] if "session" in a),
            "llm_cache_hits": sum(a["session"].get("cache_hits", 0) for a in record["attempts"] if "session" in a),
        }
        if not record["accepted"]:
            log(f"    [{index}] not diversified ({stop.value}); original kept")
        write_json(fdir / "record.json", record)
        record["dir"] = str(fdir.relative_to(self.run_dir))
        return record

    # ------------------------------------------------------------------ merging (cumulative)
    def merge(self, record: dict[str, Any], work: Path, index: int) -> bool:
        """Re-verify an accepted candidate (made against an older snapshot) in `work`."""
        fdir = self.run_dir / record["dir"]
        mdir = fdir / "merge"
        text = (self.run_dir / record["candidate_file"]).read_text()
        try:
            target = self.locate(work, record["target"]["key"])
        except steps.StepError as exc:
            record["merge"] = {"ok": False, "stage": "locate", "summary": str(exc)}
            return False
        verification = self.evaluate(work, self.visible, target, text, emit_dir=mdir)
        write_json(mdir / "verification.json", verification)
        if not verification.get("ok"):
            record["merge"] = {"ok": False, "stage": verification.get("stage"), "summary": verification.get("summary")}
            log(f"    [{index}] merge into the current program failed at {verification.get('stage')}")
            return False
        hidden = self.evaluate(mdir / "project", self.hidden)
        write_json(mdir / "hidden.json", hidden)
        record["merge"] = {"ok": True}
        record["spliced_project"] = str((mdir / "project").relative_to(self.run_dir))
        record["hidden"] = {"ok": hidden.get("ok"), "passed": hidden.get("tests", {}).get("passed"), "failed": hidden.get("tests", {}).get("failed")}
        write_json(fdir / "record.json", record)
        return True

    # ------------------------------------------------------------------ main
    def run(self, dry_run: bool = False) -> int:
        self.prepare()
        if not dry_run:
            self.baseline()
        graph = self.callgraph()
        selection = self.select(graph)
        print_selection(graph, selection)
        if dry_run:
            log("dry run: stopping after selection")
            return 0
        accumulation = self.config["depth"]["accumulation"]
        parallel = max(1, int(self.config["depth"].get("parallel", 1)))
        total = len(selection)
        indexed = list(enumerate(selection, 1))
        records: dict[int, dict[str, Any]] = {}
        started = time.monotonic()

        with ThreadPoolExecutor(parallel) as pool:
            if accumulation == "independent":
                futures = {i: pool.submit(self.diversify, fn, i, total, self.original) for i, fn in indexed}
                for i, future in futures.items():
                    record = future.result()
                    if record["accepted"]:
                        copy_tree(self.run_dir / record["spliced_project"], self.run_dir / "variants" / Path(record["dir"]).name)
                    records[i] = record
                work = None
            else:
                work = copy_tree(self.original, self.run_dir / "work")
                for w in range(0, total, parallel):
                    wave = indexed[w:w + parallel]
                    if parallel > 1:
                        log(f"wave {w // parallel + 1}: functions {', '.join(str(i) for i, _ in wave)} against the current program")
                    futures = {i: pool.submit(self.diversify, fn, i, total, work) for i, fn in wave}
                    results = {i: f.result() for i, f in futures.items()}  # `work` is unchanged until the wave is done
                    merged_any = False
                    for i, fn in wave:
                        record = results[i]
                        if record["accepted"]:
                            if not merged_any or self.merge(record, work, i):
                                copy_tree(self.run_dir / record["spliced_project"], work)
                                merged_any = True
                            else:
                                failed = record
                                record = self.diversify(fn, i, total, work, tag="rebase")
                                record["rebased_from"] = {"dir": failed["dir"], "merge": failed.get("merge")}
                                if record["accepted"]:
                                    copy_tree(self.run_dir / record["spliced_project"], work)
                        records[i] = record

        ordered = [records[i] for i in sorted(records)]
        if work is not None:
            copy_tree(work, self.run_dir / "final")
            with ThreadPoolExecutor(2) as pool:
                fv = pool.submit(self.evaluate, work, self.visible)
                fh = pool.submit(self.evaluate, work, self.hidden)
                final_visible, final_hidden = fv.result(), fh.result()
        else:
            final_hidden = final_visible = None
        summary = {
            "selected": total,
            "accepted": sum(r["accepted"] for r in ordered),
            "accumulation": accumulation,
            "parallel": parallel,
            "elapsed_s": round(time.monotonic() - started, 3),
            "final_program": "final" if work is not None else None,
            "final_visible_ok": final_visible.get("ok") if final_visible else None,
            "final_hidden_ok": final_hidden.get("ok") if final_hidden else None,
            "cache": {"steps": self.cache.stats(), "llm_hits": sum(r.get("totals", {}).get("llm_cache_hits", 0) for r in ordered)},
            "functions": [
                {
                    "id": r["function"]["id"],
                    "depth": r["function"]["depth"],
                    "accepted": r["accepted"],
                    "stop_reason": r.get("stop_reason"),
                    "attempts": len(r["attempts"]),
                    "hidden_ok": (r.get("hidden") or {}).get("ok"),
                    "merge": r.get("merge"),
                    "rebased": "rebased_from" in r,
                    "dir": r.get("dir"),
                }
                for r in ordered
            ],
            "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
        write_json(self.run_dir / "summary.json", summary)
        log(f"done: {summary['accepted']}/{summary['selected']} functions diversified -> {self.run_dir}")
        log(f"cache: steps {summary['cache']['steps']}, llm hits {summary['cache']['llm_hits']}")
        return 0


def print_selection(graph, selection: list[CGFunction]) -> None:
    chosen = {f.id for f in selection}
    print(f"\nCall graph ({graph.backend}), entry {graph.entry}:")
    print(f"  {'selected':<9}{'depth':>6}  function")
    for fn in sorted(graph.functions, key=lambda f: (f.depth is None, f.depth or 0, f.id)):
        mark = "  *" if fn.id in chosen else ""
        depth = "-" if fn.depth is None else str(fn.depth)
        print(f"  {mark:<9}{depth:>6}  {fn.id}{'  (entry)' if fn.is_entry else ''}")
    print(f"\n{len(selection)} function(s) selected, in processing order:")
    for i, fn in enumerate(selection, 1):
        print(f"  {i}. {fn.id} (depth {fn.depth})")
    print()


def run_depth(config: dict[str, Any], dry_run: bool = False) -> int:
    try:
        return DepthRun(config).run(dry_run=dry_run)
    except docker.DockerError as exc:
        print(f"pipeline: {exc}", file=sys.stderr)
        return 2
