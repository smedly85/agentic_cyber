#!/usr/bin/env python3
"""Build the self-contained Aider model settings used by formal runs.

The file emitted here is JSON, which is also valid YAML. Keeping construction
in one small module lets the single-stage runner and lineage fingerprint use
the exact same representation without requiring PyYAML in the controller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


EDITOR_TEMPERATURE = 0.0
EDITOR_SEED = 0
EDITOR_EDIT_FORMAT = "editor-diff"
EDITOR_EDIT_FORMATS = ("whole", "editor-diff")
ARCHITECT_THINK_VALUES = ("low", "medium", "high")


def optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def build_model_settings(
    architect_model: str,
    editor_model: str,
    temperature: Any,
    *,
    top_p: Any = None,
    sampling_seed: Any = None,
    max_tokens: Any = None,
    num_ctx: Any = None,
    architect_think: Any = None,
    editor_edit_format: str = EDITOR_EDIT_FORMAT,
) -> list[dict[str, Any]]:
    """Return the role-specific settings passed to Aider/LiteLLM.

    Experimental sampling belongs only to the architect. The editor is pinned
    to temperature zero and a fixed seed so it does not add an uncontrolled
    second sampling condition.
    """
    if not architect_model:
        raise ValueError("architect model must not be empty")
    if not editor_model:
        raise ValueError("editor model must not be empty")
    if architect_model == editor_model:
        raise ValueError(
            "architect and editor models must differ so role-specific sampling "
            "settings cannot collide"
        )
    if editor_edit_format not in EDITOR_EDIT_FORMATS:
        raise ValueError(
            "editor edit format must be one of " + ", ".join(EDITOR_EDIT_FORMATS)
        )

    architect_params: dict[str, int | float | str] = {
        "temperature": float(temperature),
    }
    if architect_think not in (None, ""):
        if architect_think not in ARCHITECT_THINK_VALUES:
            raise ValueError(
                "architect think must be one of "
                + ", ".join(ARCHITECT_THINK_VALUES)
            )
        # LiteLLM preserves the native string-valued `think` parameter and its
        # Ollama adapter promotes it to the top-level request. Do not substitute
        # reasoning_effort: for this model that collapses low/medium/high to the
        # same boolean `think=true` condition.
        architect_params["think"] = architect_think
    parsed_top_p = optional_float(top_p)
    parsed_seed = optional_int(sampling_seed)
    parsed_max_tokens = optional_int(max_tokens)
    parsed_num_ctx = optional_int(num_ctx)
    if parsed_num_ctx is not None and parsed_num_ctx < 1:
        raise ValueError("num ctx must be a positive integer")
    if parsed_top_p is not None:
        architect_params["top_p"] = parsed_top_p
    if parsed_seed is not None:
        architect_params["seed"] = parsed_seed
    if parsed_max_tokens is not None:
        architect_params["max_tokens"] = parsed_max_tokens
    if parsed_num_ctx is not None:
        architect_params["num_ctx"] = parsed_num_ctx

    editor_params: dict[str, int | float] = {
        "temperature": EDITOR_TEMPERATURE,
        "seed": EDITOR_SEED,
    }
    if parsed_num_ctx is not None:
        # Pin both roles. Otherwise Aider may dynamically resize the editor's
        # Ollama request even though the architect is explicitly controlled.
        editor_params["num_ctx"] = parsed_num_ctx

    return [
        {
            "name": architect_model,
            "use_repo_map": False,
            "extra_params": architect_params,
        },
        {
            "name": editor_model,
            "use_repo_map": False,
            "editor_edit_format": editor_edit_format,
            "extra_params": editor_params,
        },
    ]


def canonical_bytes(settings: list[dict[str, Any]]) -> bytes:
    return (
        json.dumps(settings, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def settings_sha256(settings: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_bytes(settings)).hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architect-model", required=True)
    parser.add_argument("--editor-model", required=True)
    parser.add_argument("--temperature", required=True)
    parser.add_argument("--top-p", default="")
    parser.add_argument("--sampling-seed", default="")
    parser.add_argument("--max-tokens", default="")
    parser.add_argument("--num-ctx", default="")
    parser.add_argument("--architect-think", default="")
    parser.add_argument("--editor-edit-format", default=EDITOR_EDIT_FORMAT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--emit", choices=("settings", "sha256"), default="settings")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = build_model_settings(
            args.architect_model,
            args.editor_model,
            args.temperature,
            top_p=args.top_p,
            sampling_seed=args.sampling_seed,
            max_tokens=args.max_tokens,
            num_ctx=args.num_ctx,
            architect_think=args.architect_think,
            editor_edit_format=args.editor_edit_format,
        )
    except (TypeError, ValueError) as error:
        raise SystemExit(f"aider_settings: {error}") from error

    content = json.dumps(settings, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    if args.emit == "settings":
        print(content, end="")
    else:
        print(settings_sha256(settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
