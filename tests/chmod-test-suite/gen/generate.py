#!/usr/bin/env python3
"""Freeze the curated new_chmod cases into suites/*.json.

Reads the input-only case definitions from gen/curated_cases.py, derives each
case's expected stdout, exit status, stderr class and resulting mode tree from
tests/reference_generators/chmod_reference.py, and writes one suite file per checkpoint group plus
suites/MANIFEST.json.

Regenerating is deterministic and offline: no oracle binary, no subprocess, no
filesystem beyond the output files. `gen/verify.py` checks that what is on disk
matches what this script would produce, so a stale or hand-edited suite is
detectable without trusting either file.

Usage:
  python3 gen/generate.py                 # rewrite suites/
  python3 gen/generate.py --check         # fail if suites/ is out of date
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parent.parent
SUITE_DIR = SUITE_ROOT / "suites"
sys.path.insert(0, str(SUITE_ROOT))
# The specification model lives outside this suite so it can never be
# copied into an experimental sandbox; reaching it needs tests/ on the path.
sys.path.insert(0, str(SUITE_ROOT.parent))

from engine import SYMLINK_MARKER  # noqa: E402
from reference_generators import chmod_reference as reference  # noqa: E402
from gen import curated_cases  # noqa: E402

SCHEMA_VERSION = 1

GROUP_FILES = {
    "base": "base.json",
    "recursive": "recursive.json",
    "changes": "changes.json",
    "verbose": "verbose.json",
    "silent": "silent.json",
}

# Subjects that name a class of rejection rather than a path. A diagnostic about
# a path must name that path; a usage message need not name anything, and an
# invalid MODE must carry the words the prompt requires.
SUBJECT_REGEX = {
    "usage": None,
    "invalid mode": "invalid mode",
}


def encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def build_filesystem(fixture: list[dict] | None) -> dict[str, reference.Entry]:
    """Turn a case's fixture list into the model's filesystem view, using the
    same default modes engine.materialize_fixture applies on disk."""
    filesystem: dict[str, reference.Entry] = {}
    for entry in fixture or []:
        path = reference.normalize(entry["path"])
        kind = entry["type"]
        if kind == "file":
            filesystem[path] = reference.Entry(
                kind="file", mode=int(entry.get("mode", "0644"), 8)
            )
        elif kind == "dir":
            filesystem[path] = reference.Entry(
                kind="dir", mode=int(entry.get("mode", "0755"), 8)
            )
        elif kind == "symlink":
            filesystem[path] = reference.Entry(
                kind="symlink", target=entry["target"]
            )
        else:
            raise SystemExit(f"unknown fixture type: {kind!r}")
    return filesystem


def expected_tree(fixture: list[dict] | None, modes: dict[str, int]) -> dict:
    """The mode every fixture path must carry once the run is over.

    A symlink is recorded as the marker rather than a mode: its own permission
    bits are not portably meaningful, and the contract says a link found during
    traversal is left alone entirely.
    """
    tree: dict[str, str] = {}
    for entry in fixture or []:
        path = entry["path"]
        if entry["type"] == "symlink":
            tree[path] = SYMLINK_MARKER
            continue
        tree[path] = reference.render_octal(modes[reference.normalize(path)])
    return tree


def model_option_set(definition: dict) -> set[str] | None:
    """The option set the model should parse this case under.

    None -- the complete ladder -- for an ordinary case. A case carrying
    `absent_flags` describes a checkpoint that has not introduced those flags,
    so the model must treat them as unknown options; otherwise it would happily
    honour `-v` and freeze a success golden for a case whose whole purpose is to
    assert that `-v` is still rejected.
    """
    absent = set(definition.get("absent_flags") or [])
    if not absent:
        return None
    return set(reference.FEATURE_FLAG.values()) - absent


def freeze_case(definition: dict) -> dict:
    fixture = definition.get("fixture")
    filesystem = build_filesystem(fixture)

    result = reference.run(
        list(definition["args"]), filesystem, model_option_set(definition)
    )

    case: dict = {
        "name": definition["name"],
        "args": list(definition["args"]),
        "flags": list(definition["flags"]),
        "tags": list(definition["tags"]),
        "exit_code": result.exit_code,
        "stdout_b64": encode(result.stdout),
        "stderr_class": "nonempty" if result.subjects else "empty",
        "expected_tree": expected_tree(fixture, result.modes),
    }

    if definition.get("absent_flags"):
        case["absent_flags"] = list(definition["absent_flags"])

    if result.subjects:
        subject = result.subjects[0]
        pattern = SUBJECT_REGEX.get(subject, subject)
        if pattern is not None:
            # Require the diagnostic to name what it is about, without pinning
            # the surrounding wording: the prompts specify which conditions are
            # diagnosed, not how the sentence reads.
            case["stderr_regex"] = re.escape(pattern)

    if fixture is not None:
        case["fixture"] = [_encode_fixture(entry) for entry in fixture]
    if definition.get("needs_non_root"):
        case["needs_non_root"] = True
    if "timeout" in definition:
        case["timeout"] = definition["timeout"]
    return case


def _encode_fixture(entry: dict) -> dict:
    out = {"path": entry["path"], "type": entry["type"]}
    if entry["type"] == "symlink":
        out["target"] = entry["target"]
    if "mode" in entry:
        out["mode"] = entry["mode"]
    return out


def build_suites() -> dict[str, dict]:
    suites: dict[str, dict] = {}
    seen: set[str] = set()
    for group, definitions in curated_cases.GROUPS.items():
        cases = []
        for definition in definitions:
            if definition["name"] in seen:
                raise SystemExit(f"duplicate case name: {definition['name']}")
            seen.add(definition["name"])
            cases.append(freeze_case(definition))
        suites[GROUP_FILES[group]] = {
            "schema_version": SCHEMA_VERSION,
            "group": group,
            "cases": cases,
        }
    return suites


def manifest(suites: dict[str, dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "oracle": "tests/reference_generators/chmod_reference.py (offline specification model, no external binary, never copied into a sandbox)",
        "counts": {
            data["group"]: len(data["cases"]) for data in suites.values()
        },
        "total_cases": sum(len(data["cases"]) for data in suites.values()),
    }


def render(value: dict) -> str:
    return json.dumps(value, indent=1, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit nonzero when suites/ differs from the model",
    )
    args = parser.parse_args()

    suites = build_suites()
    payloads = {name: render(data) for name, data in suites.items()}
    payloads["MANIFEST.json"] = render(manifest(suites))

    if args.check:
        stale = []
        for name, text in payloads.items():
            path = SUITE_DIR / name
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        extra = sorted(
            path.name
            for path in SUITE_DIR.glob("*.json")
            if path.name not in payloads
        )
        if stale or extra:
            for name in stale:
                print(f"stale: suites/{name}", file=sys.stderr)
            for name in extra:
                print(f"unexpected: suites/{name}", file=sys.stderr)
            return 1
        print(f"suites/ is up to date ({manifest(suites)['total_cases']} cases)")
        return 0

    SUITE_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in payloads.items():
        (SUITE_DIR / name).write_text(text, encoding="utf-8")
    print(
        f"wrote {len(payloads)} files to {SUITE_DIR} "
        f"({manifest(suites)['total_cases']} cases)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
