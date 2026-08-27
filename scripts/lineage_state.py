#!/usr/bin/env python3
"""Durable, atomically-updated state for one lineage.

Reliability is measured over every lineage the controller STARTED, so a lineage
must become countable the moment it begins rather than when it finishes. The
previous design wrote `lineage.json` once, after the walk was over: a run
interrupted by Ctrl-C, a crash, a lost SSH session or a scheduler timeout left a
lineage directory with stage results in it but no record, and the analyzer
skipped it with a warning. That silently shrinks the denominator, and it shrinks
it in exactly the biased direction -- interruptions are more likely in the long,
repair-heavy lineages.

So the record is created before checkpoint 000 runs, rewritten after every
checkpoint, and only marked `completed` once the final checkpoint has passed:

    running    the controller created this and has not finished the walk. A
               record still in this state at analysis time means the controller
               died; the analyzer reports it as controller_interrupted.
    stopped    a checkpoint failed. The lineage ended normally, unsuccessfully.
    completed  every checkpoint passed and final/ was written.

Every write goes through `write_atomic`, which writes a sibling temporary file
and `os.replace`s it into place. `os.replace` is atomic on POSIX and on Windows,
so a process killed mid-write leaves either the old record or the new one, never
a half-written file the analyzer would have to guess about.

Used from scripts/run_lineage_experiment.sh, one subprocess per transition:

    lineage_state.py --path L/lineage.json init  --lineage-id lineage-001 ...
    lineage_state.py --path L/lineage.json stage --stage-json '{...}'
    lineage_state.py --path L/lineage.json finish --success true
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

STATE_RUNNING = "running"
STATE_STOPPED = "stopped"
STATE_COMPLETED = "completed"


class StateError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"lineage_state: {message}")


def write_atomic(path: Path, payload: Any) -> None:
    """Replace `path` with `payload` as JSON, atomically.

    The temporary file is created in the destination directory so that
    `os.replace` stays within one filesystem, where it is atomic. Without that
    an interrupted controller could leave a truncated lineage.json, which is
    indistinguishable from a corrupted one and would force the analyzer to
    discard a lineage that really did start.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def read_record(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StateError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise StateError(f"{path} does not contain a JSON object")
    return data


def optional_float(value: str | None) -> float | None:
    """An unset sampling knob stays null rather than becoming 0."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise StateError(f"expected a number, got {value!r}") from None


def optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise StateError(f"expected an integer, got {value!r}") from None


def init_record(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "lineage_id": args.lineage_id,
        "utility": args.utility,
        "agent_backend": "aider",
        "aider_version": args.aider_version,
        "architect_model": args.model,
        "editor_model": args.editor_model,
        "architect_mode": True,
        "model": args.model,
        "model_provenance": (
            json.loads(args.model_provenance_json)
            if args.model_provenance_json else None
        ),
        "temperature": float(args.temperature),
        # Recorded as null when the flag was not passed: "the server default
        # applied" is a different condition from "pinned to 0", and a lineage
        # record has to be readable on its own years later.
        "top_p": optional_float(args.top_p),
        "sampling_seed": optional_int(args.sampling_seed),
        "max_tokens": optional_int(args.max_tokens),
        "editor_temperature": 0.0,
        "editor_sampling_seed": 0,
        "editor_edit_format": "editor-diff",
        "max_loops": int(args.max_loops),
        "config_fingerprint": args.fingerprint,
        "checkpoint_count": int(args.checkpoint_count),
        "checkpoint_ids": [c for c in (args.checkpoint_ids or "").split(",") if c],
        # Live from here on. The lineage is countable as started even if the
        # controller never reaches another transition.
        "state": STATE_RUNNING,
        "current_checkpoint": None,
        "checkpoints_completed": 0,
        "completed_checkpoint_ids": [],
        "end_to_end_success": False,
        "failure_stage": None,
        "failure_reason": None,
        "final_source": None,
        "stages": [],
        "started_at": args.now,
        "updated_at": args.now,
        "finished_at": None,
    }


def apply_stage(record: dict[str, Any], stage: dict[str, Any],
                now: str) -> dict[str, Any]:
    """Fold one finished checkpoint into the record.

    Re-running a checkpoint replaces its entry rather than appending a second
    one, so a resumed or --force'd lineage cannot accumulate duplicates.
    """
    stages = [s for s in record.get("stages", [])
              if s.get("checkpoint_id") != stage.get("checkpoint_id")]
    stages.append(stage)
    order = record.get("checkpoint_ids") or []

    def position(entry: dict[str, Any]) -> int:
        identifier = str(entry.get("checkpoint_id"))
        return order.index(identifier) if identifier in order else len(order)

    stages.sort(key=position)

    record["stages"] = stages
    record["current_checkpoint"] = stage.get("checkpoint_id")
    succeeded = [s for s in stages if s.get("success")]
    record["checkpoints_completed"] = len(succeeded)
    record["completed_checkpoint_ids"] = [s["checkpoint_id"] for s in succeeded]
    if not stage.get("success"):
        record["state"] = STATE_STOPPED
        record["failure_stage"] = stage.get("checkpoint_id")
        record["failure_reason"] = stage.get("failure_reason") or "unknown"
        record["finished_at"] = now
    record["updated_at"] = now
    return record


def finish_record(record: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    success = args.success == "true"
    record["end_to_end_success"] = success
    record["state"] = STATE_COMPLETED if success else STATE_STOPPED
    if success:
        record["failure_stage"] = None
        record["failure_reason"] = None
        record["final_source"] = f"final/{args.source_basename}"
    else:
        if args.failure_stage:
            record["failure_stage"] = args.failure_stage
        if args.failure_reason:
            record["failure_reason"] = args.failure_reason
        record["final_source"] = None
    record["updated_at"] = args.now
    record["finished_at"] = args.now
    return record


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--now", default="")
    sub = parser.add_subparsers(dest="action", required=True)

    start = sub.add_parser("init")
    start.add_argument("--lineage-id", required=True)
    start.add_argument("--utility", required=True)
    start.add_argument("--model", default="")
    start.add_argument("--editor-model", default="")
    start.add_argument("--aider-version", default="unknown")
    start.add_argument("--model-provenance-json", default="")
    start.add_argument("--temperature", default="0")
    start.add_argument("--top-p", default="")
    start.add_argument("--sampling-seed", default="")
    start.add_argument("--max-tokens", default="")
    start.add_argument("--max-loops", default="0")
    start.add_argument("--fingerprint", default="")
    start.add_argument("--checkpoint-count", default="0")
    start.add_argument("--checkpoint-ids", default="")

    stage = sub.add_parser("stage")
    stage.add_argument("--stage-json", required=True)

    done = sub.add_parser("finish")
    done.add_argument("--success", choices=("true", "false"), required=True)
    done.add_argument("--failure-stage", default="")
    done.add_argument("--failure-reason", default="")
    done.add_argument("--source-basename", default="")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.action == "init":
        # A re-run of an existing lineage keeps its original started_at, so the
        # record still says when the lineage first began.
        record = init_record(args)
        if args.path.is_file():
            try:
                previous = read_record(args.path)
            except StateError:
                previous = {}
            if previous.get("started_at"):
                record["started_at"] = previous["started_at"]
        write_atomic(args.path, record)
    elif args.action == "stage":
        record = read_record(args.path)
        try:
            stage = json.loads(args.stage_json)
        except json.JSONDecodeError as error:
            raise StateError(f"--stage-json is not valid JSON: {error}") from error
        write_atomic(args.path, apply_stage(record, stage, args.now))
    else:
        record = read_record(args.path)
        write_atomic(args.path, finish_record(record, args))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StateError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
