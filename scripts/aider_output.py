#!/usr/bin/env python3
"""Classify concrete Aider editor-output protocol failures.

This intentionally does not infer a malformed response from an unchanged
candidate or failed validation. Those remain candidate outcomes. It recognizes
only structurally invalid editor-diff markers or explicit Aider diagnostics
that name a malformed edit-format response.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


EDITOR_EDIT_FORMATS = ("whole", "editor-diff")
SEARCH = "<<<<<<< SEARCH"
DIVIDER = "======="
REPLACE = ">>>>>>> REPLACE"

EXPLICIT_INVALID_EDIT_PATTERNS = (
    re.compile(r"\bInvalidEditBlock\b", re.IGNORECASE),
    re.compile(
        r"\b(?:invalid|malformed)\s+"
        r"(?:edit(?:[- ]format|\s+block)?|whole[- ]file)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bdid not conform\b[^\n]*\bedit format\b", re.IGNORECASE),
    re.compile(
        r"\bexpected\b[^\n]*(?:<<<<<<<\s*SEARCH|>>>>>>>\s*REPLACE|SEARCH/REPLACE)",
        re.IGNORECASE,
    ),
)


def malformed_editor_diff(text: str) -> bool:
    """True only when concrete SEARCH/REPLACE markers violate the protocol."""
    marker_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() in {SEARCH, DIVIDER, REPLACE}
    ]
    # A bare seven-equals separator is common in ordinary logs. It is only edit
    # protocol evidence when accompanied by a SEARCH or REPLACE marker.
    if SEARCH not in marker_lines and REPLACE not in marker_lines:
        return False
    state = "outside"
    saw_marker = False
    for line in marker_lines:
        saw_marker = True
        if state == "outside" and line == SEARCH:
            state = "search"
        elif state == "search" and line == DIVIDER:
            state = "replacement"
        elif state == "replacement" and line == REPLACE:
            state = "outside"
        else:
            return True
    return saw_marker and state != "outside"


def has_invalid_editor_output(text: str, editor_edit_format: str) -> bool:
    if any(pattern.search(text) for pattern in EXPLICIT_INVALID_EDIT_PATTERNS):
        return True
    return editor_edit_format == "editor-diff" and malformed_editor_diff(text)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument(
        "--editor-edit-format", choices=EDITOR_EDIT_FORMATS, required=True
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    text = args.log.read_text(encoding="utf-8", errors="replace")
    return 0 if has_invalid_editor_output(text, args.editor_edit_format) else 1


if __name__ == "__main__":
    raise SystemExit(main())
