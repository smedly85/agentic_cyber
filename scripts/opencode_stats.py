#!/usr/bin/env python3
"""Extract per-session statistics from a legacy OpenCode attempt.

OpenCode records every session in a SQLite database under its data directory:
token counts, cost, per-assistant-message timing, reasoning blocks and tool
calls. Historical OpenCode-era runs called this helper after each attempt. The
active Aider runner does not call it; this reader remains so unchanged legacy
artifacts can still be inspected and analyzed.

Sessions are matched by working directory. Each attempt gets a fresh workdir
and each validation loop is a new session against it, so the sessions for a
workdir, ordered by creation time, line up with loop 0..N.

Writes two files:

  opencode-stats.json  machine-readable, one record per session
  opencode-stats.txt   human-readable summary for reading later

Usage:
    opencode_stats.py --workdir DIR --output-dir DIR [--db PATH]
                      [--model M] [--temperature T] [--attempt ID]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def default_db() -> Path:
    """Mirror OpenCode's own data-directory resolution."""
    override = os.environ.get("OPENCODE_DATA")
    if override:
        return Path(override) / "opencode.db"
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "opencode" / "opencode.db"


def connect(db: Path) -> sqlite3.Connection:
    # Read-only: a sweep may run while the user has OpenCode open elsewhere,
    # and this must never be the writer that corrupts their session history.
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def load_json(raw: Any) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def empty_tokens() -> dict[str, int]:
    return {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
        "total": 0,
    }


def add_tokens(into: dict[str, int], tokens: dict) -> None:
    cache = tokens.get("cache") or {}
    into["input"] += int(tokens.get("input") or 0)
    into["output"] += int(tokens.get("output") or 0)
    into["reasoning"] += int(tokens.get("reasoning") or 0)
    into["cache_read"] += int(cache.get("read") or 0)
    into["cache_write"] += int(cache.get("write") or 0)
    into["total"] += int(tokens.get("total") or 0)


def collect_parts(connection: sqlite3.Connection, session_id: str) -> dict:
    """Tool usage and reasoning volume, from the part stream."""
    tool_calls: Counter[str] = Counter()
    tool_errors: Counter[str] = Counter()
    tool_ms: Counter[str] = Counter()
    reasoning_blocks = 0
    reasoning_chars = 0
    reasoning_ms = 0
    text_chars = 0

    rows = connection.execute(
        "select data from part where session_id = ? order by time_created",
        (session_id,),
    )
    for row in rows:
        part = load_json(row["data"])
        kind = part.get("type")
        if kind == "reasoning":
            reasoning_blocks += 1
            reasoning_chars += len(part.get("text") or "")
            span = part.get("time") or {}
            start, end = span.get("start"), span.get("end")
            if isinstance(start, int) and isinstance(end, int) and end >= start:
                reasoning_ms += end - start
        elif kind == "text":
            text_chars += len(part.get("text") or "")
        elif kind == "tool":
            name = part.get("tool") or "unknown"
            tool_calls[name] += 1
            state = part.get("state") or {}
            if state.get("status") == "error":
                tool_errors[name] += 1
            span = state.get("time") or {}
            start, end = span.get("start"), span.get("end")
            if isinstance(start, int) and isinstance(end, int) and end >= start:
                tool_ms[name] += end - start

    return {
        "reasoning_blocks": reasoning_blocks,
        "reasoning_chars": reasoning_chars,
        "reasoning_ms": reasoning_ms,
        "assistant_text_chars": text_chars,
        "tool_calls_total": sum(tool_calls.values()),
        "tool_errors_total": sum(tool_errors.values()),
        "tool_calls": dict(sorted(tool_calls.items())),
        "tool_errors": dict(sorted(tool_errors.items())),
        "tool_ms": dict(sorted(tool_ms.items())),
    }


def collect_messages(connection: sqlite3.Connection, session_id: str) -> dict:
    """Per-assistant-message tokens and latency."""
    steps: list[dict] = []
    tokens = empty_tokens()
    cost = 0.0
    finishes: Counter[str] = Counter()
    errors: list[str] = []
    models: set[str] = set()
    user_messages = 0

    rows = connection.execute(
        "select data from message where session_id = ? order by time_created",
        (session_id,),
    )
    for row in rows:
        message = load_json(row["data"])
        if message.get("role") != "assistant":
            user_messages += message.get("role") == "user"
            continue

        step_tokens = message.get("tokens") or {}
        span = message.get("time") or {}
        created, completed = span.get("created"), span.get("completed")
        duration = None
        if isinstance(created, int) and isinstance(completed, int):
            duration = max(0, completed - created)

        model_id = message.get("modelID")
        if model_id:
            models.add(f"{message.get('providerID', '')}/{model_id}".strip("/"))

        finish = message.get("finish") or "unknown"
        finishes[finish] += 1
        if message.get("error"):
            errors.append(json.dumps(message["error"])[:500])

        cache = step_tokens.get("cache") or {}
        steps.append(
            {
                "index": len(steps),
                "model": model_id,
                "provider": message.get("providerID"),
                "finish": finish,
                "duration_ms": duration,
                "cost": message.get("cost") or 0,
                "tokens": {
                    "input": step_tokens.get("input") or 0,
                    "output": step_tokens.get("output") or 0,
                    "reasoning": step_tokens.get("reasoning") or 0,
                    "cache_read": cache.get("read") or 0,
                    "cache_write": cache.get("write") or 0,
                    "total": step_tokens.get("total") or 0,
                },
            }
        )
        add_tokens(tokens, step_tokens)
        cost += float(message.get("cost") or 0)

    durations = [s["duration_ms"] for s in steps if s["duration_ms"] is not None]
    return {
        "assistant_steps": len(steps),
        "user_messages": user_messages,
        "models": sorted(models),
        "finish_reasons": dict(sorted(finishes.items())),
        "errors": errors,
        "tokens_summed_over_steps": tokens,
        "cost_summed_over_steps": round(cost, 6),
        "step_duration_ms_total": sum(durations),
        "step_duration_ms_max": max(durations) if durations else 0,
        "steps": steps,
    }


def collect_sessions(
    connection: sqlite3.Connection, workdir: Path, since_ms: int | None
) -> list[dict]:
    # Sessions are keyed by working directory, and the runner reuses that path
    # when an attempt is re-run with --force or restarted after an interruption.
    # The floor keeps an abandoned run's sessions out of this attempt's numbers.
    rows = connection.execute(
        "select * from session where directory = ? and time_created >= ?"
        " order by time_created",
        (str(workdir), since_ms if since_ms is not None else 0),
    ).fetchall()

    sessions = []
    for loop, row in enumerate(rows):
        record = dict(row)
        session_id = record["id"]
        created = record.get("time_created")
        updated = record.get("time_updated")
        wall_ms = None
        if isinstance(created, int) and isinstance(updated, int):
            wall_ms = max(0, updated - created)

        entry = {
            # Sessions are created one per validation loop, in order, so the
            # position in this list is the loop number the runner used.
            "loop": loop,
            "session_id": session_id,
            "slug": record.get("slug"),
            "title": record.get("title"),
            "opencode_version": record.get("version"),
            "directory": record.get("directory"),
            "time_created_ms": created,
            "time_updated_ms": updated,
            "wall_ms": wall_ms,
            # Session-level rollup maintained by OpenCode itself. Kept
            # alongside the per-step sum because a session that errors mid
            # stream can leave the two disagreeing, and that gap is a signal.
            "session_totals": {
                "cost": record.get("cost"),
                "tokens": {
                    "input": record.get("tokens_input"),
                    "output": record.get("tokens_output"),
                    "reasoning": record.get("tokens_reasoning"),
                    "cache_read": record.get("tokens_cache_read"),
                    "cache_write": record.get("tokens_cache_write"),
                },
            },
            "file_summary": {
                "files": record.get("summary_files"),
                "additions": record.get("summary_additions"),
                "deletions": record.get("summary_deletions"),
            },
        }
        entry.update(collect_messages(connection, session_id))
        entry.update(collect_parts(connection, session_id))
        sessions.append(entry)
    return sessions


def aggregate(sessions: list[dict]) -> dict:
    tokens = empty_tokens()
    totals = {
        "sessions": len(sessions),
        "assistant_steps": 0,
        "tool_calls": 0,
        "tool_errors": 0,
        "reasoning_blocks": 0,
        "reasoning_chars": 0,
        "cost": 0.0,
        "wall_ms": 0,
    }
    tool_calls: Counter[str] = Counter()
    for session in sessions:
        step_tokens = session["tokens_summed_over_steps"]
        for key in tokens:
            tokens[key] += step_tokens.get(key, 0)
        totals["assistant_steps"] += session["assistant_steps"]
        totals["tool_calls"] += session["tool_calls_total"]
        totals["tool_errors"] += session["tool_errors_total"]
        totals["reasoning_blocks"] += session["reasoning_blocks"]
        totals["reasoning_chars"] += session["reasoning_chars"]
        totals["cost"] += session["cost_summed_over_steps"]
        totals["wall_ms"] += session["wall_ms"] or 0
        tool_calls.update(session["tool_calls"])
    totals["cost"] = round(totals["cost"], 6)
    totals["tokens"] = tokens
    totals["tool_calls_by_name"] = dict(sorted(tool_calls.items()))
    return totals


def humanize_ms(value: int | None) -> str:
    if not value:
        return "0s"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m{seconds:04.1f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h{int(minutes):02d}m{seconds:04.1f}s"


def render_text(report: dict) -> str:
    lines: list[str] = []
    context = report["context"]
    lines.append("OpenCode session statistics")
    lines.append("=" * 60)
    for key in ("attempt", "model", "temperature", "workdir"):
        if context.get(key) is not None:
            lines.append(f"{key + ':':<14}{context[key]}")
    lines.append("")

    totals = report["totals"]
    tokens = totals["tokens"]
    lines.append("TOTALS")
    lines.append("-" * 60)
    lines.append(f"{'sessions:':<24}{totals['sessions']}")
    lines.append(f"{'assistant steps:':<24}{totals['assistant_steps']}")
    lines.append(f"{'wall time:':<24}{humanize_ms(totals['wall_ms'])}")
    lines.append(f"{'input tokens:':<24}{tokens['input']:,}")
    lines.append(f"{'output tokens:':<24}{tokens['output']:,}")
    lines.append(f"{'reasoning tokens:':<24}{tokens['reasoning']:,}")
    lines.append(f"{'cache read/write:':<24}{tokens['cache_read']:,} / {tokens['cache_write']:,}")
    lines.append(f"{'total tokens:':<24}{tokens['total']:,}")
    lines.append(f"{'cost:':<24}{totals['cost']}")
    lines.append(f"{'tool calls:':<24}{totals['tool_calls']} ({totals['tool_errors']} errors)")
    lines.append(f"{'reasoning blocks:':<24}{totals['reasoning_blocks']}")
    if totals["tool_calls_by_name"]:
        breakdown = ", ".join(
            f"{name}={count}" for name, count in totals["tool_calls_by_name"].items()
        )
        lines.append(f"{'tools used:':<24}{breakdown}")
    lines.append("")

    for session in report["sessions"]:
        kind = "initial" if session["loop"] == 0 else f"repair {session['loop']}"
        lines.append(f"LOOP {session['loop']} ({kind})  session {session['session_id']}")
        lines.append("-" * 60)
        tokens = session["tokens_summed_over_steps"]
        lines.append(f"{'slug:':<24}{session.get('slug')}")
        lines.append(f"{'models:':<24}{', '.join(session['models']) or 'n/a'}")
        lines.append(f"{'wall time:':<24}{humanize_ms(session['wall_ms'])}")
        lines.append(
            f"{'model time:':<24}{humanize_ms(session['step_duration_ms_total'])}"
            f" (slowest step {humanize_ms(session['step_duration_ms_max'])})"
        )
        lines.append(f"{'assistant steps:':<24}{session['assistant_steps']}")
        lines.append(
            f"{'tokens in/out:':<24}{tokens['input']:,} / {tokens['output']:,}"
            f"  (reasoning {tokens['reasoning']:,}, total {tokens['total']:,})"
        )
        lines.append(f"{'cost:':<24}{session['cost_summed_over_steps']}")
        lines.append(
            f"{'tool calls:':<24}{session['tool_calls_total']}"
            f" ({session['tool_errors_total']} errors)"
        )
        if session["tool_calls"]:
            breakdown = ", ".join(
                f"{name}={count}" for name, count in session["tool_calls"].items()
            )
            lines.append(f"{'  by tool:':<24}{breakdown}")
        if session["tool_errors"]:
            breakdown = ", ".join(
                f"{name}={count}" for name, count in session["tool_errors"].items()
            )
            lines.append(f"{'  errors by tool:':<24}{breakdown}")
        lines.append(
            f"{'reasoning:':<24}{session['reasoning_blocks']} blocks,"
            f" {session['reasoning_chars']:,} chars,"
            f" {humanize_ms(session['reasoning_ms'])}"
        )
        finishes = ", ".join(
            f"{name}={count}" for name, count in session["finish_reasons"].items()
        )
        lines.append(f"{'finish reasons:':<24}{finishes or 'n/a'}")
        summary = session["file_summary"]
        lines.append(
            f"{'files touched:':<24}{summary['files']}"
            f" (+{summary['additions']} -{summary['deletions']})"
        )
        if session["errors"]:
            lines.append(f"{'errors:':<24}{len(session['errors'])}")
            for error in session["errors"]:
                lines.append(f"    {error}")

        lines.append("")
        lines.append(
            f"  {'step':>4}  {'dur':>9}  {'in':>9}  {'out':>7}"
            f"  {'reason':>9}  finish"
        )
        for step in session["steps"]:
            step_tokens = step["tokens"]
            lines.append(
                f"  {step['index']:>4}  {humanize_ms(step['duration_ms']):>9}"
                f"  {step_tokens['input']:>9,}  {step_tokens['output']:>7,}"
                f"  {step_tokens['reasoning']:>9,}  {step['finish']}"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", default=None)
    parser.add_argument("--attempt", default=None)
    parser.add_argument(
        "--since-ms",
        type=int,
        default=None,
        help="ignore sessions created before this epoch-milliseconds value",
    )
    args = parser.parse_args(argv)

    db = args.db or default_db()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "context": {
            "attempt": args.attempt,
            "model": args.model,
            "temperature": args.temperature,
            # Resolved because OpenCode stores the resolved path, and a
            # relative or symlinked workdir would otherwise match nothing.
            "workdir": str(args.workdir.resolve()),
            "database": str(db),
            "since_ms": args.since_ms,
        },
        "sessions": [],
        "totals": aggregate([]),
    }

    if not db.exists():
        report["context"]["error"] = f"OpenCode database not found: {db}"
    else:
        try:
            connection = connect(db)
        except sqlite3.Error as exc:
            report["context"]["error"] = f"could not open database: {exc}"
        else:
            with connection:
                report["sessions"] = collect_sessions(
                    connection, args.workdir.resolve(), args.since_ms
                )
            report["totals"] = aggregate(report["sessions"])

    (args.output_dir / "opencode-stats.json").write_text(
        json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    (args.output_dir / "opencode-stats.txt").write_text(
        render_text(report), encoding="utf-8"
    )

    if report["context"].get("error"):
        print(f"opencode_stats: {report['context']['error']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
