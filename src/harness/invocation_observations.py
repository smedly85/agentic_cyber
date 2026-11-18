"""Public-only score observations; missing or incomparable evidence is unknown."""
from __future__ import annotations

import json
from pathlib import Path

from repair_prompt import current_loop_section, SUITE_TOTALS


def score(report: Path, log: Path) -> dict | None:
    try:
        counts = json.loads(report.read_text(encoding="utf-8"))["counts"]
        if not isinstance(counts, dict) or not counts or not all(
            type(v) is int and v >= 0 for v in counts.values()
        ):
            raise ValueError("invalid counts")
        total = sum(v for k, v in counts.items() if k not in {"SKIP", "XFAIL"})
        return {"passed": counts.get("PASS", 0), "total": total}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        totals = SUITE_TOTALS.findall(current_loop_section(log.read_text(encoding="utf-8")))
    except OSError:
        return None
    if totals:
        passed, total = map(int, totals[-1])
        return {"passed": passed, "total": total}
    return None


def public_scores(attempt_dir: str, loop: int) -> dict:
    root = Path(attempt_dir)
    return {
        "base": score(root / f"public-validation-{loop}-base.json", root / "base-tests.log"),
        "checkpoint": score(root / f"public-validation-{loop}.json", root / "feature-tests.log"),
    }


def compare_scores(previous: dict | None, current: dict) -> str | None:
    if previous is None:
        return None
    changes = []
    for stage in ("base", "checkpoint"):
        before, after = previous.get(stage), current.get(stage)
        if before is None and after is None:
            continue
        if before is None or after is None or before["total"] != after["total"]:
            return None
        changes.append(after["passed"] - before["passed"])
    if not changes:
        return None
    # Mixed stage movement cannot be summarized as one improvement/regression.
    if min(changes) < 0 < max(changes):
        return None
    return "improved" if max(changes) > 0 else "regressed" if min(changes) < 0 else "unchanged"
