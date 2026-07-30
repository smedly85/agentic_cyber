#!/usr/bin/env python3
"""Freeze the curated new_grep cases into suites/*.json.

Reads the input-only case definitions from gen/curated_cases.py, derives each
case's expected stdout, exit status and stderr class from tests/reference_generators/grep_reference.py,
and writes one suite file per checkpoint group plus suites/MANIFEST.json.

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

from reference_generators import grep_reference as reference  # noqa: E402
from gen import curated_cases  # noqa: E402

SCHEMA_VERSION = 1

GROUP_FILES = {
    "base": "base.json",
    "with_filename": "with_filename.json",
    "no_filename": "no_filename.json",
    "recursive": "recursive.json",
    "ignore_case": "ignore_case.json",
}


def encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def build_filesystem(fixture: list[dict] | None) -> dict[str, reference.Entry]:
    """Turn a case's fixture list into the model's filesystem view.

    A fixture mode with no read bits is what makes a file unreadable on the real
    filesystem, so the model must see the same thing or its goldens would claim
    a successful read where the candidate gets EACCES.
    """
    filesystem: dict[str, reference.Entry] = {}
    for entry in fixture or []:
        path = entry["path"].rstrip("/") or entry["path"]
        kind = entry["type"]
        if kind == "file":
            mode = entry.get("mode", "0644")
            filesystem[path] = reference.Entry(
                kind="file",
                contents=entry.get("contents", b""),
                readable=bool(int(mode, 8) & 0o444),
            )
        elif kind == "dir":
            mode = entry.get("mode", "0755")
            filesystem[path] = reference.Entry(
                kind="dir", readable=bool(int(mode, 8) & 0o444)
            )
        elif kind == "symlink":
            filesystem[path] = reference.Entry(kind="symlink", target=entry["target"])
        else:
            raise SystemExit(f"unknown fixture type: {kind!r}")
    return filesystem


def model_option_set(definition: dict) -> set[str] | None:
    """The option set the model should parse this case under.

    None -- the complete ladder -- for an ordinary case. A case carrying
    `absent_flags` describes a checkpoint that has not introduced those flags,
    so the model must treat them as unknown options; otherwise it would happily
    honour `-H` and freeze a success golden for a case whose whole purpose is to
    assert that `-H` is still rejected.
    """
    absent = set(definition.get("absent_flags") or [])
    if not absent:
        return None
    return set(reference.FEATURE_FLAG.values()) - absent


def freeze_case(definition: dict) -> dict:
    fixture = definition.get("fixture")
    filesystem = build_filesystem(fixture)
    stdin = definition.get("stdin")
    implemented = model_option_set(definition)

    stdout, subjects, exit_code = reference.run(
        list(definition["args"]), stdin or b"", filesystem, implemented
    )

    # A usage rejection never reaches the prefix decision, so there is nothing
    # to record for it.
    try:
        options = reference.parse_args(list(definition["args"]), implemented)
        prefixed = reference.prefix_filenames(options, filesystem)
    except reference.UsageError:
        prefixed = False

    case: dict = {
        "name": definition["name"],
        "args": list(definition["args"]),
        "flags": list(definition["flags"]),
        "tags": list(definition["tags"]),
        "exit_code": exit_code,
        "stdout_b64": encode(stdout),
        "stderr_class": "nonempty" if subjects else "empty",
        "expect_filename_prefix": prefixed,
    }

    if definition.get("absent_flags"):
        case["absent_flags"] = list(definition["absent_flags"])

    if subjects and subjects != ["usage"]:
        # Require the diagnostic to name what it is about, without pinning the
        # surrounding wording: the prompts specify which conditions are
        # diagnosed, not how the sentence reads.
        case["stderr_regex"] = re.escape(subjects[0])

    if stdin is not None:
        case["stdin_b64"] = encode(stdin)
    if "stdin_modes" in definition:
        case["stdin_modes"] = list(definition["stdin_modes"])
    if "timeout" in definition:
        case["timeout"] = definition["timeout"]
    if fixture is not None:
        case["fixture"] = [_encode_fixture(entry) for entry in fixture]
    return case


def _encode_fixture(entry: dict) -> dict:
    out = {"path": entry["path"], "type": entry["type"]}
    if entry["type"] == "file":
        out["contents_b64"] = encode(entry.get("contents", b""))
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
        "oracle": "tests/reference_generators/grep_reference.py (offline specification model, no external binary, never copied into a sandbox)",
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
