#!/usr/bin/env python3
"""Compare a freshly regenerated suite tree against the committed one.

**Offline only. Never copied into an agent-visible bundle.**

Why not `diff -rq`
------------------
The self-check used to byte-compare `.json.gz` files. That answers the wrong
question twice over:

* a byte difference does not say *what* changed. When a root-privileged
  container regenerated `faults.json.gz`, `diff -rq` reported only "files
  differ" -- it could not say that `fault-o-unwritable` had flipped from
  `exit 2` to `exit 0` because root ignores the permission bit. Reading that as
  "the benchmark drifted" would have been exactly backwards.
* it compares files the generator never claims to produce. `fuzz_regressions`
  is appended by `diff_fuzz.py` as the live fuzzer finds new distinct bugs; it
  accretes and is not reproducible by regeneration, so its absence from a fresh
  tree is correct, not a defect.

So this compares **decompressed cases, by name**, over exactly the tiers the
suite declares as generated, and separately reports the inventory: which
committed files are generated, which are declared separately maintained, and
which are unaccounted for. An unaccounted file is an error -- that is what stops
"just exclude it until the check passes".

The generated/separately-maintained split is read from the suite's own
`config.json` (`generated_suites`, `separately_maintained_suites`), so the
repository defines it, not this tool.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

MANIFEST = "MANIFEST.json"

# Fields whose difference is a real change in what a candidate must produce.
# Everything else in a case is descriptive.
SEMANTIC_HINT = (
    "exit_code", "stdout_b64", "stdout", "stderr", "stderr_b64",
    "stderr_class", "stderr_regex", "expected_tree", "output_file",
    "flags", "args", "check", "absent_flags",
)


class SuiteDiffError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"suite_diff: {message}")


def load_cases(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(header, cases) from a .json or .json.gz suite file."""
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SuiteDiffError(f"cannot read {path}: {error}") from error
    if isinstance(payload, dict) and "cases" in payload:
        header = {k: v for k, v in payload.items() if k != "cases"}
        return header, list(payload["cases"])
    return {}, list(payload)


def case_key(case: dict[str, Any], index: int) -> str:
    return str(case.get("name") or f"<unnamed #{index}>")


# Tree-shaped fields whose symlink entries carry host-OS permission bits.
TREE_FIELDS = ("tree", "expected_tree", "fixture")


def canonicalize(case: dict[str, Any]) -> dict[str, Any]:
    """Apply the canonical symlink policy before comparing two frozen cases.

    A symlink's `mode` is host-OS metadata -- 0777 on Linux, 0755 on macOS --
    and mkdir never sets it, so a corpus frozen on one OS would otherwise never
    reproduce on the other. Path, type and target are preserved, so a wrong
    target or a symlink where a directory belongs still differs. Directory and
    file modes are left alone: those are core mkdir behavior.

    Kept identical in intent to `engine.canonical_tree_entry`, which applies the
    same rule when a candidate is judged.
    """
    canonical = dict(case)
    for field in TREE_FIELDS:
        entries = canonical.get(field)
        if not isinstance(entries, list):
            continue
        canonical[field] = [
            {k: v for k, v in entry.items() if k != "mode"}
            if isinstance(entry, dict) and entry.get("type") == "symlink"
            else entry
            for entry in entries
        ]
    return canonical


def compare_cases(fresh: list[dict[str, Any]],
                  committed: list[dict[str, Any]]) -> list[str]:
    """Semantic differences between two case lists, keyed by case name."""
    left = {case_key(c, i): canonicalize(c) for i, c in enumerate(fresh)}
    right = {case_key(c, i): canonicalize(c) for i, c in enumerate(committed)}
    problems: list[str] = []

    for name in sorted(set(right) - set(left)):
        problems.append(f"only in committed: {name}")
    for name in sorted(set(left) - set(right)):
        problems.append(f"only in fresh: {name}")

    for name in sorted(set(left) & set(right)):
        a, b = left[name], right[name]
        for field in sorted(set(a) | set(b)):
            if a.get(field) != b.get(field):
                marker = "*" if field in SEMANTIC_HINT else " "
                problems.append(
                    f"{marker} {name}.{field}: fresh={_short(a.get(field))} "
                    f"committed={_short(b.get(field))}"
                )
    return problems


def _short(value: Any, limit: int = 70) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def suite_files(directory: Path) -> dict[str, Path]:
    """Suite files by stem, e.g. {'faults': .../faults.json.gz}."""
    found: dict[str, Path] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name == MANIFEST:
            continue
        if path.name.endswith(".json"):
            found[path.name[: -len(".json")]] = path
        elif path.name.endswith(".json.gz"):
            found[path.name[: -len(".json.gz")]] = path
    return found


def compare(fresh_dir: Path, committed_dir: Path, generated: list[str],
            separate: list[str]) -> dict[str, Any]:
    fresh = suite_files(fresh_dir)
    committed = suite_files(committed_dir)
    separate_stems = {
        name[: -len(".json.gz")] if name.endswith(".json.gz")
        else name[: -len(".json")] if name.endswith(".json") else name
        for name in separate
    }

    report: dict[str, Any] = {
        "generated_tiers": list(generated),
        "separately_maintained": sorted(separate_stems),
        "differences": {},
        "inventory_problems": [],
        "reproducible": True,
    }

    for tier in generated:
        if tier not in committed:
            report["inventory_problems"].append(
                f"declared generated tier {tier!r} is missing from the "
                f"committed suites"
            )
            continue
        if tier not in fresh:
            report["inventory_problems"].append(
                f"declared generated tier {tier!r} was not produced by "
                f"regeneration"
            )
            continue
        _, fresh_cases = load_cases(fresh[tier])
        _, committed_cases = load_cases(committed[tier])
        problems = compare_cases(fresh_cases, committed_cases)
        if problems:
            report["differences"][tier] = problems

    # Anything committed that is neither generated nor declared separate is
    # unaccounted for. Refusing here is the point: it prevents quietly widening
    # an exclusion list until the check goes green.
    unaccounted = sorted(set(committed) - set(generated) - separate_stems)
    for name in unaccounted:
        report["inventory_problems"].append(
            f"committed suite {name!r} is neither a declared generated tier "
            f"nor declared separately maintained (config.json: "
            f"generated_suites / separately_maintained_suites)"
        )

    # A separately-maintained file appearing in a fresh tree would mean the
    # generator has started producing it, which changes its provenance.
    for name in sorted(separate_stems & set(fresh)):
        report["inventory_problems"].append(
            f"{name!r} is declared separately maintained but regeneration "
            f"produced it; its provenance has changed"
        )

    report["reproducible"] = not (report["differences"]
                                  or report["inventory_problems"])
    return report


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    if report["separately_maintained"]:
        lines.append(
            "  separately maintained (not regenerated, verified by the oracle "
            "self-pass and teeth gates): "
            + ", ".join(report["separately_maintained"])
        )
    for problem in report["inventory_problems"]:
        lines.append(f"  INVENTORY: {problem}")
    for tier, problems in sorted(report["differences"].items()):
        lines.append(f"  {tier}: {len(problems)} semantic difference(s)")
        for problem in problems[:12]:
            lines.append(f"      {problem}")
        if len(problems) > 12:
            lines.append(f"      ... and {len(problems) - 12} more")
    if report["reproducible"]:
        lines.append("  committed generated tiers reproduce exactly: OK")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fresh", required=True, type=Path)
    parser.add_argument("--committed", required=True, type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SuiteDiffError(f"cannot read {args.config}: {error}") from error

    generated = config.get("generated_suites")
    if not isinstance(generated, list) or not generated:
        raise SuiteDiffError(
            f"{args.config} does not declare 'generated_suites'; the "
            "reproducible artifact set must be defined by the repository"
        )
    separate = config.get("separately_maintained_suites") or []

    report = compare(args.fresh, args.committed, generated, separate)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(report))
    return 0 if report["reproducible"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SuiteDiffError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
