#!/usr/bin/env python3
"""Filter-then-measure-diversity pipeline for N-version candidate sources.

Automates the workflow that has so far been run by hand for each new batch
of generated variants:

  1. Find candidate source files under a directory (e.g. one per
     ``rep-N``/``temp-*`` run).
  2. Hash-dedupe them (flag byte-identical files rather than silently
     double-counting them as independent samples).
  3. Build each with the project's compiler flags and judge it against the
     test suite (``tests/mkdir-test-suite/judge_candidate.sh`` by default).
  4. Run ``measure_diversity.py`` on the subset that passes.
  5. Cross-check the attack-surface level against Flawfinder (Wheeler) - an
     independently developed, widely cited C/C++ security scanner - so the
     "which unsafe constructs does each variant use" claim doesn't rest on
     one hand-rolled tree-sitter counter alone.
  6. Cross-check the lexical/token level against JPlag - a purpose-built,
     independently developed plagiarism detector for "N solutions to the
     same assignment," which is structurally identical to "N LLM samples
     of the same spec." Requires a JVM and tools/jplag.jar (see
     scripts/fetch_jplag.sh); skipped with a warning if either is missing.
  7. Render a single Markdown report: filtering table, all five pairwise
     similarity matrices, per-variant attack-surface vectors, near-clone
     pairs, clustering, cross-level correlation, and both cross-checks.

See docs/diversity_methodology.md for what each similarity level means and
its limits; this script only orchestrates and formats, it adds no new
*primary* metrics (Flawfinder and JPlag are existing, independent tools
wired in for validation, not hand-rolled reimplementations).

Usage:
    python3 scripts/diversity_pipeline.py runs/same-temp-n/temp-0p2 \\
        --out-dir runs/diversity/same-temp-n-temp-0p2
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from measure_diversity import derive_label  # noqa: E402

DEFAULT_JUDGE = REPO_ROOT / "tests" / "mkdir-test-suite" / "judge_candidate.sh"
DEFAULT_VENV_PYTHON = REPO_ROOT / "ac_venv" / "bin" / "python"
DEFAULT_JPLAG_JAR = REPO_ROOT / "tools" / "jplag.jar"
JAVA_CANDIDATES = [
    "/opt/homebrew/opt/openjdk@25/bin/java",
    "/opt/homebrew/opt/openjdk@21/bin/java",
    "/opt/homebrew/opt/openjdk/bin/java",
    "/usr/local/opt/openjdk/bin/java",
]

FINAL_PASS_LINE = re.compile(r"^(\d+)/(\d+) pass$")
FAILURE_LINE = re.compile(
    r"^(FAIL|TIMEOUT|SANITIZER|CRASH)\s+(\S+)\s+\[(\S+)\]\s+args=(.*)$"
)


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def find_and_dedupe(root: Path, pattern: str) -> tuple[list[Path], dict[str, list[Path]]]:
    candidates = sorted(root.glob(pattern))
    if not candidates:
        raise SystemExit(f"No files matched {pattern!r} under {root}")

    by_hash: dict[str, list[Path]] = {}
    for p in candidates:
        by_hash.setdefault(sha1(p), []).append(p)

    unique_paths = [group[0] for group in by_hash.values()]
    unique_paths.sort()
    duplicate_groups = {h: g for h, g in by_hash.items() if len(g) > 1}
    return unique_paths, duplicate_groups


def build_and_judge(
    src: Path, judge: Path, binary_name: str, cc: str
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        binary = Path(tmp) / binary_name
        compile_cmd = shlex.split(cc) + ["-o", str(binary), str(src)]
        compiled = subprocess.run(compile_cmd, capture_output=True, text=True)
        if compiled.returncode != 0:
            return {
                "path": src,
                "build_ok": False,
                "build_stderr": compiled.stderr.strip(),
                "passed": False,
                "failures": [],
                "pass_line": None,
            }

        judged = subprocess.run(
            ["bash", str(judge), str(binary)], capture_output=True, text=True
        )
        failures = []
        pass_line = None
        for line in judged.stdout.splitlines():
            m = FAILURE_LINE.match(line)
            if m:
                verdict, name, suite, args = m.groups()
                failures.append(
                    {"verdict": verdict, "name": name, "suite": suite, "args": args}
                )
            m2 = FINAL_PASS_LINE.match(line)
            if m2:
                pass_line = line
        return {
            "path": src,
            "build_ok": True,
            "build_stderr": "",
            "passed": judged.returncode == 0,
            "failures": failures,
            "pass_line": pass_line,
        }


def run_measure_diversity(
    passing_paths: list[Path],
    out_dir: Path,
    python_bin: Path,
    cluster_threshold: float,
    neural: bool,
) -> None:
    cmd = [str(python_bin), str(REPO_ROOT / "scripts" / "measure_diversity.py")]
    cmd += [str(p) for p in passing_paths]
    cmd += ["--out-dir", str(out_dir), "--cluster-threshold", str(cluster_threshold)]
    if neural:
        cmd.append("--neural")
    print(f"$ {' '.join(shlex.quote(c) for c in cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(f"measure_diversity.py failed (exit {result.returncode})")


def read_matrix_csv(path: Path) -> tuple[list[str], list[list[float]]]:
    with path.open() as fh:
        rows = list(csv.reader(fh))
    labels = rows[0][1:]
    matrix = [[float(v) for v in row[1:]] for row in rows[1:]]
    return labels, matrix


def matrix_to_markdown(labels: list[str], matrix: list[list[float]]) -> str:
    header = "|  | " + " | ".join(labels) + " |"
    sep = "|---|" + "---|" * len(labels)
    lines = [header, sep]
    for label, row in zip(labels, matrix):
        cells = " | ".join(f"{v:.3f}" for v in row)
        lines.append(f"| **{label}** | {cells} |")
    return "\n".join(lines)


def near_clone_pairs(
    labels: list[str], matrix: list[list[float]], threshold: float
) -> list[tuple[str, str, float]]:
    pairs = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            if matrix[i][j] >= threshold:
                pairs.append((labels[i], labels[j], matrix[i][j]))
    return sorted(pairs, key=lambda t: -t[2])


def most_diverse_pair(labels: list[str], matrix: list[list[float]]) -> tuple[str, str, float]:
    best = None
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            if best is None or matrix[i][j] < best[2]:
                best = (labels[i], labels[j], matrix[i][j])
    return best


# ---------------------------------------------------------------------------
# Flawfinder cross-check
#
# Flawfinder (D.A. Wheeler, https://dwheeler.com/flawfinder/) is an
# independently developed, widely cited C/C++ security scanner. It's wired
# in here as a *validation* pass for the attack-surface level: our own
# attack_surface_vector() in measure_diversity.py hand-counts risky calls
# via a tree-sitter walk, so an independent tool agreeing (or disagreeing)
# with which variants look riskier is worth more than the same claim
# resting on one bespoke counter.
# ---------------------------------------------------------------------------


def find_flawfinder(python_bin: Path) -> str:
    candidate = python_bin.with_name("flawfinder")
    if candidate.exists():
        return str(candidate)
    found = shutil.which("flawfinder")
    if found:
        return found
    raise SystemExit(
        "flawfinder not found next to the interpreter or on PATH.\n"
        "Install it with: ac_venv/bin/pip install -r scripts/diversity-requirements.txt"
    )


def run_flawfinder(path: Path, flawfinder_bin: str) -> list[dict[str, str]]:
    result = subprocess.run(
        [flawfinder_bin, "--csv", "--dataonly", str(path)],
        capture_output=True,
        text=True,
    )
    return list(csv.DictReader(io.StringIO(result.stdout)))


def flawfinder_name_vector(hits: list[dict[str, str]]) -> dict[str, int]:
    """Vector keyed by the flagged function name (e.g. "strcpy", "strcat"),
    not Flawfinder's Category field - Category is almost always just
    "buffer" for this kind of code, which collapses every hit into one
    dimension and makes the similarity vector nearly useless. Name gives
    the same granularity our own attack_surface_vector's call buckets do.
    """
    counts: dict[str, int] = {}
    for hit in hits:
        name = hit.get("Name") or "?"
        counts[name] = counts.get(name, 0) + 1
    return counts


def flawfinder_hit_summary(hits: list[dict[str, str]]) -> dict[str, Any]:
    levels = [int(h["Level"]) for h in hits if h.get("Level", "").isdigit()]
    cwes = sorted({h["CWEs"] for h in hits if h.get("CWEs")})
    return {
        "hit_count": len(hits),
        "total_risk": sum(levels),
        "max_level": max(levels) if levels else 0,
        "cwes": cwes,
    }


def _cosine_dict(a: dict[str, int], b: dict[str, int]) -> float:
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    norm_a = sum(v * v for v in a.values()) ** 0.5
    norm_b = sum(v * v for v in b.values()) ** 0.5
    if norm_a == 0.0 and norm_b == 0.0:
        return 1.0
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _jaccard_dict(a: dict[str, int], b: dict[str, int]) -> float:
    pa = {k for k, v in a.items() if v > 0}
    pb = {k for k, v in b.items() if v > 0}
    if not pa and not pb:
        return 1.0
    return len(pa & pb) / len(pa | pb)


def flawfinder_similarity(a: dict[str, int], b: dict[str, int]) -> float:
    # Mirrors measure_diversity.attack_surface_similarity's cosine+Jaccard
    # blend, so the two matrices are directly comparable.
    return (_cosine_dict(a, b) + _jaccard_dict(a, b)) / 2.0


def spearman_corr(a: list[float], b: list[float]) -> float | None:
    """Pure-Python Spearman rank correlation (no scipy dependency here -
    this script otherwise only needs the stdlib, and shells out to the venv
    python for anything that needs numpy/scipy/tree-sitter)."""
    n = len(a)
    if n < 2:
        return None

    def rank(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        ranks = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    ra, rb = rank(a), rank(b)
    mean_ra, mean_rb = sum(ra) / n, sum(rb) / n
    cov = sum((x - mean_ra) * (y - mean_rb) for x, y in zip(ra, rb))
    var_a = sum((x - mean_ra) ** 2 for x in ra)
    var_b = sum((y - mean_rb) ** 2 for y in rb)
    if var_a == 0 or var_b == 0:
        return None
    return cov / (var_a * var_b) ** 0.5


def compute_flawfinder_crosscheck(
    passing_paths: list[Path],
    labels_by_path: dict[Path, str],
    flawfinder_bin: str,
    out_dir: Path,
) -> dict[str, Any]:
    labels = [labels_by_path[p] for p in passing_paths]
    hits_by_label = {}
    for p in passing_paths:
        label = labels_by_path[p]
        hits_by_label[label] = run_flawfinder(p, flawfinder_bin)

    vectors = {l: flawfinder_name_vector(h) for l, h in hits_by_label.items()}
    summaries = {l: flawfinder_hit_summary(h) for l, h in hits_by_label.items()}

    matrix = [
        [flawfinder_similarity(vectors[a], vectors[b]) for b in labels]
        for a in labels
    ]

    with (out_dir / "flawfinder.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([""] + labels)
        for label, row in zip(labels, matrix):
            writer.writerow([label] + [f"{v:.6f}" for v in row])

    return {"labels": labels, "matrix": matrix, "summaries": summaries}


# ---------------------------------------------------------------------------
# JPlag cross-check
#
# JPlag (https://github.com/jplag/JPlag) is an independently developed
# plagiarism detector, purpose-built for exactly this scenario structurally
# - many independent solutions to one assignment/spec. It's wired in as a
# cross-check for the lexical/token level: does a tool nobody on this
# project wrote agree with our own Levenshtein/winnowing numbers about
# which variant pairs are more or less alike?
#
# Notes from getting this working:
#   - JPlag needs the "c" language module, not "cpp" - "cpp" adds
#     C++-only reserved words (e.g. "final") that break parsing of valid C
#     identifiers, silently dropping that submission from the comparison.
#   - The default min-token-match is tuned for much larger student
#     submissions; on ~50-90 line files it produces compressed, low-signal
#     similarity scores, so a lower --jplag-min-tokens is used here.
#   - "-M RUN" is required, otherwise JPlag starts an interactive report
#     viewer server and blocks waiting for a keypress.
# ---------------------------------------------------------------------------


def find_java() -> str | None:
    found = shutil.which("java")
    if found:
        try:
            subprocess.run([found, "-version"], capture_output=True, check=True)
            return found
        except (subprocess.CalledProcessError, OSError):
            pass  # macOS ships a stub /usr/bin/java that errors without a JRE
    for candidate in JAVA_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def run_jplag(
    passing_paths: list[Path],
    labels_by_path: dict[Path, str],
    out_dir: Path,
    java_bin: str,
    jplag_jar: Path,
    min_tokens: int,
) -> dict[str, Any] | None:
    submissions_dir = out_dir / "jplag_submissions"
    if submissions_dir.exists():
        shutil.rmtree(submissions_dir)
    submissions_dir.mkdir(parents=True)
    for p in passing_paths:
        label = labels_by_path[p]
        (submissions_dir / f"{label}.c").write_bytes(p.read_bytes())

    result_stem = out_dir / "jplag_result"
    cmd = [
        java_bin, "-jar", str(jplag_jar),
        "-l", "c",
        "-t", str(min_tokens),
        "-M", "RUN",
        "--csv-export",
        "--overwrite",
        "-r", str(result_stem),
        str(submissions_dir),
    ]
    print(f"$ {' '.join(shlex.quote(c) for c in cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    csv_path = result_stem / "results.csv"
    if not csv_path.exists():
        print(f"warning: JPlag did not produce {csv_path}; skipping cross-check.")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        return None

    labels = [labels_by_path[p] for p in passing_paths]
    sim: dict[tuple[str, str], float] = {}
    with csv_path.open() as fh:
        for row in csv.DictReader(fh):
            a = row["submissionName1"].removesuffix(".c")
            b = row["submissionName2"].removesuffix(".c")
            sim[(a, b)] = float(row["averageSimilarity"])
            sim[(b, a)] = float(row["averageSimilarity"])

    matrix = [
        [1.0 if a == b else sim.get((a, b), 0.0) for b in labels]
        for a in labels
    ]
    with (out_dir / "jplag.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([""] + labels)
        for label, row in zip(labels, matrix):
            writer.writerow([label] + [f"{v:.6f}" for v in row])

    return {"labels": labels, "matrix": matrix}


def _agreement_note(corr: float | None) -> str:
    if corr is None:
        return "Not enough variants to compute a correlation."
    if corr >= 0.6:
        return (
            "Strong agreement - the two independent tools rank variant "
            "pairs' similarity consistently, which is evidence this level "
            "is measuring something real rather than an artifact of our "
            "own implementation choices."
        )
    if corr >= 0.3:
        return (
            "Moderate agreement - the tools broadly agree but diverge on "
            "some pairs, worth inspecting before leaning on either one alone."
        )
    return (
        "Weak/no agreement - the two tools are picking up different "
        "signals; worth investigating which pairs drive the disagreement "
        "before citing either as ground truth."
    )


def render_report(
    root: Path,
    pattern: str,
    judge: Path,
    duplicate_groups: dict[str, list[Path]],
    filter_results: list[dict[str, Any]],
    labels_by_path: dict[Path, str],
    out_dir: Path,
    near_clone_threshold: float,
    flawfinder_crosscheck: dict[str, Any] | None,
    jplag_crosscheck: dict[str, Any] | None,
) -> str:
    lines: list[str] = []
    lines.append(f"# Diversity report — `{root}`")
    lines.append("")
    lines.append(
        f"Generated by `scripts/diversity_pipeline.py` against pattern "
        f"`{pattern}`, judged with `{judge.relative_to(REPO_ROOT)}`."
    )
    lines.append("")
    lines.append("## How to read this")
    lines.append("")
    lines.append(
        "All similarity scores are 0-1 (1 = identical). Five independent "
        "levels, each answering a different question - see "
        "`docs/diversity_methodology.md` for the full citation list and "
        "the \"interpretation contract\" (what each level can and can't "
        "tell you):"
    )
    lines.append("")
    lines.append(
        "- **Lexical (Levenshtein, comment-stripped)** - raw character-level "
        "text similarity. Sensitive to renaming and length; a manipulation "
        "check (\"are these really different files\"), not a strategy check."
    )
    lines.append(
        "- **Lexical (Type-2 token winnowing)** - same idea, but identifiers/"
        "literals are normalized to placeholders first, so renaming a "
        "variable doesn't move this number. Lower than raw Levenshtein "
        "means the diversity is real, not just cosmetic renaming."
    )
    lines.append(
        "- **AST tree edit distance (APTED)** - structural similarity of the "
        "parsed syntax tree (control-flow shape), robust to both renaming "
        "and formatting. Noisy on small files - read as a distribution."
    )
    lines.append(
        "- **API/call-set (Jaccard)** - do the two variants call the same "
        "libc functions? The most interpretable \"same algorithm or not\" "
        "signal."
    )
    lines.append(
        "- **Attack surface** - cosine+Jaccard over a vector of "
        "security-relevant construct counts (unsafe calls, bounded-risky "
        "calls, heap calls, fixed stack buffers, indexing ops). The level "
        "that speaks to exploit non-transferability: if two variants' "
        "vulnerable constructs are disjoint, an exploit against one has no "
        "structural analogue in the other."
    )
    lines.append(
        "- **Flawfinder cross-check** (below) - an independent, "
        "off-the-shelf security scanner run over the same files, to check "
        "whether the attack-surface claim above holds up against a tool "
        "we didn't write ourselves."
    )
    lines.append(
        "- **JPlag cross-check** (below) - an independent, off-the-shelf "
        "plagiarism/similarity detector, to check whether the lexical/"
        "token claims above hold up against a tool we didn't write "
        "ourselves."
    )
    lines.append("")

    if duplicate_groups:
        lines.append("## Duplicate files excluded")
        lines.append("")
        lines.append(
            "The following files are byte-identical (same SHA-1) and were "
            "collapsed to a single sample before filtering, so they don't "
            "inflate the apparent sample count:"
        )
        lines.append("")
        for h, group in duplicate_groups.items():
            rels = ", ".join(f"`{p.relative_to(REPO_ROOT)}`" for p in group)
            lines.append(f"- `{h[:10]}…`: {rels}")
        lines.append("")

    lines.append("## Step 1 — Test-harness filtering")
    lines.append("")
    n_pass = sum(1 for r in filter_results if r["passed"])
    lines.append(f"{n_pass}/{len(filter_results)} candidates pass all test cases.")
    lines.append("")
    lines.append("| Label | Path | Result | Detail |")
    lines.append("|---|---|---|---|")
    for r in filter_results:
        label = labels_by_path[r["path"]]
        rel = r["path"].relative_to(REPO_ROOT)
        if not r["build_ok"]:
            lines.append(f"| {label} | `{rel}` | ❌ build failed | {r['build_stderr'][:120]} |")
            continue
        if r["passed"]:
            lines.append(f"| {label} | `{rel}` | ✅ pass | {r['pass_line']} |")
        else:
            fail_summary = "; ".join(
                f"{f['verdict']} {f['name']}" for f in r["failures"]
            )
            lines.append(
                f"| {label} | `{rel}` | ❌ fail | {r['pass_line']}: {fail_summary} |"
            )
    lines.append("")

    if n_pass < 2:
        lines.append(
            "Fewer than 2 candidates pass — nothing to compare for diversity."
        )
        return "\n".join(lines)

    summary_path = out_dir / "summary.json"
    summary = json.loads(summary_path.read_text())

    lines.append("## Step 2 — Diversity across the passing candidates")
    lines.append("")
    lines.append("### Level similarity summary")
    lines.append("")
    lines.append("| Level | mean | min | max | stdev |")
    lines.append("|---|---|---|---|---|")
    for key, level in summary["levels"].items():
        s = level["similarity_summary"]
        lines.append(
            f"| {level['name']} | {s['mean']:.3f} | {s['min']:.3f} | "
            f"{s['max']:.3f} | {s['stdev']:.3f} |"
        )
    lines.append("")

    lines.append("### Per-variant profile")
    lines.append("")
    lines.append(
        "| Label | NLOC | cyclomatic | unsafe | bounded | heap | fixed-buf | "
        "indexing | call set |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for label, pv in summary["per_variant"].items():
        av = pv["attack_surface_vector"]
        lizard = pv["lizard"] or {}
        calls = ", ".join(pv["call_set"])
        lines.append(
            f"| {label} | {lizard.get('total_nloc', '?'):.0f} | "
            f"{lizard.get('total_cyclomatic_complexity', '?'):.0f} | "
            f"{av['unsafe_calls']} | {av['bounded_risky_calls']} | "
            f"{av['heap_calls']} | {av['fixed_stack_buffers']} | "
            f"{av['indexing_ops']} | {calls} |"
        )
    lines.append("")

    lines.append("### Pairwise similarity matrices")
    lines.append("")
    for key in summary["levels"]:
        csv_path = out_dir / f"{key}.csv"
        labels, matrix = read_matrix_csv(csv_path)
        lines.append(f"**{summary['levels'][key]['name']}**")
        lines.append("")
        lines.append(matrix_to_markdown(labels, matrix))
        lines.append("")

    labels, as_matrix = read_matrix_csv(out_dir / "attack_surface.csv")
    lines.append("### Attack-surface near-clone pairs (similarity ≥ %.2f)" % near_clone_threshold)
    lines.append("")
    pairs = near_clone_pairs(labels, as_matrix, near_clone_threshold)
    if pairs:
        lines.append("| Variant A | Variant B | Similarity |")
        lines.append("|---|---|---|")
        for a, b, sim in pairs:
            lines.append(f"| {a} | {b} | {sim:.3f} |")
    else:
        lines.append(f"None above {near_clone_threshold:.2f}.")
    lines.append("")

    a, b, sim = most_diverse_pair(labels, as_matrix)
    lines.append(
        f"Most diverse pair by attack surface: **{a}** vs **{b}** ({sim:.3f})."
    )
    lines.append("")

    lines.append("### Clustering (attack-surface level, distance threshold "
                  f"{summary['clustering']['attack_surface']['distance_threshold']})")
    lines.append("")
    clustering = summary["clustering"]["attack_surface"]
    sil = clustering["silhouette"]
    sil_str = f"{sil:.3f}" if sil is not None else "n/a"
    lines.append(f"n_clusters={clustering['n_clusters']}, silhouette={sil_str}")
    lines.append("")
    groups: dict[int, list[str]] = {}
    for label, cid in clustering["assignment"].items():
        groups.setdefault(cid, []).append(label)
    for cid, members in sorted(groups.items()):
        lines.append(f"- cluster {cid}: {', '.join(members)}")
    lines.append("")

    if "matrix" in summary.get("cross_level_correlation", {}):
        cc = summary["cross_level_correlation"]
        lines.append("### Cross-level correlation (Spearman)")
        lines.append("")
        lines.append(matrix_to_markdown(cc["levels"], cc["matrix"]))
        lines.append("")

    if flawfinder_crosscheck is not None:
        ff = flawfinder_crosscheck
        lines.append("## Step 3 — Independent cross-check: Flawfinder")
        lines.append("")
        lines.append(
            "[Flawfinder](https://dwheeler.com/flawfinder/) is an "
            "independently developed C/C++ security scanner, run here to "
            "check whether the attack-surface level above (our own "
            "tree-sitter-based counter) agrees with a tool we didn't write."
        )
        lines.append("")
        lines.append("| Label | hits | total risk | max level | CWEs |")
        lines.append("|---|---|---|---|---|")
        for label in ff["labels"]:
            s = ff["summaries"][label]
            cwes = ", ".join(s["cwes"]) if s["cwes"] else "-"
            lines.append(
                f"| {label} | {s['hit_count']} | {s['total_risk']} | "
                f"{s['max_level']} | {cwes} |"
            )
        lines.append("")
        lines.append("**Flawfinder-based pairwise similarity**")
        lines.append("")
        lines.append(matrix_to_markdown(ff["labels"], ff["matrix"]))
        lines.append("")

        as_labels, as_full_matrix = read_matrix_csv(out_dir / "attack_surface.csv")
        if as_labels == ff["labels"]:
            as_upper = [
                as_full_matrix[i][j]
                for i in range(len(as_labels))
                for j in range(i + 1, len(as_labels))
            ]
            ff_upper = [
                ff["matrix"][i][j]
                for i in range(len(ff["labels"]))
                for j in range(i + 1, len(ff["labels"]))
            ]
            corr = spearman_corr(as_upper, ff_upper)
            corr_str = f"{corr:.3f}" if corr is not None else "n/a"
            lines.append(
                f"Spearman correlation between our attack-surface similarity "
                f"and Flawfinder's: **{corr_str}**. {_agreement_note(corr)}"
            )
            lines.append("")

    if jplag_crosscheck is not None:
        jp = jplag_crosscheck
        lines.append("## Step 4 — Independent cross-check: JPlag")
        lines.append("")
        lines.append(
            "[JPlag](https://github.com/jplag/JPlag) is an independently "
            "developed plagiarism detector, purpose-built for comparing many "
            "independent solutions to the same assignment - structurally "
            "the same situation as N LLM samples of one spec. Run here to "
            "check whether the lexical/token level above agrees with a "
            "tool that has no knowledge of our winnowing implementation."
        )
        lines.append("")
        lines.append("**JPlag average-similarity matrix**")
        lines.append("")
        lines.append(matrix_to_markdown(jp["labels"], jp["matrix"]))
        lines.append("")

        lw_labels, lw_matrix = read_matrix_csv(out_dir / "lexical_winnowing.csv")
        if lw_labels == jp["labels"]:
            lw_upper = [
                lw_matrix[i][j]
                for i in range(len(lw_labels))
                for j in range(i + 1, len(lw_labels))
            ]
            jp_upper = [
                jp["matrix"][i][j]
                for i in range(len(jp["labels"]))
                for j in range(i + 1, len(jp["labels"]))
            ]
            corr = spearman_corr(lw_upper, jp_upper)
            corr_str = f"{corr:.3f}" if corr is not None else "n/a"
            lines.append(
                f"Spearman correlation between our Type-2 token winnowing "
                f"similarity and JPlag's: **{corr_str}**. {_agreement_note(corr)}"
            )
            lines.append("")

    figures_dir = out_dir / "figures"
    if figures_dir.exists():
        lines.append("### Figures")
        lines.append("")
        for fig in sorted(figures_dir.glob("*.png")):
            lines.append(f"![{fig.stem}](figures/{fig.name})")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory to search recursively.")
    parser.add_argument(
        "--pattern", default="**/new_mkdir.c", help="Glob pattern relative to root."
    )
    parser.add_argument("--judge", type=Path, default=DEFAULT_JUDGE)
    parser.add_argument("--binary-name", default="new_mkdir")
    parser.add_argument("--cc", default="cc -std=c11 -O2")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--python", type=Path, default=None)
    parser.add_argument("--neural", action="store_true")
    parser.add_argument("--cluster-threshold", type=float, default=0.3)
    parser.add_argument("--near-clone-threshold", type=float, default=0.95)
    parser.add_argument(
        "--no-flawfinder",
        action="store_true",
        help="Skip the Flawfinder cross-check pass.",
    )
    parser.add_argument(
        "--no-jplag",
        action="store_true",
        help="Skip the JPlag cross-check pass.",
    )
    parser.add_argument("--jplag-jar", type=Path, default=DEFAULT_JPLAG_JAR)
    parser.add_argument(
        "--jplag-min-tokens",
        type=int,
        default=5,
        help="JPlag -t/--min-tokens; lowered from JPlag's default since it's "
        "tuned for much larger student submissions than these files.",
    )
    args = parser.parse_args(argv)

    root: Path = args.root.resolve()
    out_dir = (
        args.out_dir if args.out_dir is not None
        else REPO_ROOT / "runs" / "diversity" / f"{root.name}-auto"
    ).resolve()
    python_bin = args.python or (
        DEFAULT_VENV_PYTHON if DEFAULT_VENV_PYTHON.exists() else Path(sys.executable)
    )

    print(f"Searching {root} for {args.pattern!r}...")
    unique_paths, duplicate_groups = find_and_dedupe(root, args.pattern)
    if duplicate_groups:
        print(f"Found {len(duplicate_groups)} duplicate group(s); collapsed to unique files.")
    print(f"{len(unique_paths)} unique candidate(s).")

    labels_by_path = {
        p: derive_label(p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p, unique_paths)
        for p in unique_paths
    }

    filter_results = []
    for p in unique_paths:
        print(f"Building + judging {labels_by_path[p]} ({p.relative_to(REPO_ROOT)})...")
        r = build_and_judge(p, args.judge, args.binary_name, args.cc)
        filter_results.append(r)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  -> {status} {r['pass_line'] or r['build_stderr'][:80]}")

    passing_paths = [r["path"] for r in filter_results if r["passed"]]
    print(f"\n{len(passing_paths)}/{len(filter_results)} pass.")

    out_dir.mkdir(parents=True, exist_ok=True)
    flawfinder_crosscheck: dict[str, Any] | None = None
    jplag_crosscheck: dict[str, Any] | None = None
    if len(passing_paths) >= 2:
        run_measure_diversity(
            passing_paths, out_dir, python_bin, args.cluster_threshold, args.neural
        )
        if not args.no_flawfinder:
            flawfinder_bin = find_flawfinder(python_bin)
            print(f"Running Flawfinder cross-check ({flawfinder_bin})...")
            flawfinder_crosscheck = compute_flawfinder_crosscheck(
                passing_paths, labels_by_path, flawfinder_bin, out_dir
            )

        if not args.no_jplag:
            java_bin = find_java()
            if java_bin is None:
                print("warning: no Java runtime found; skipping JPlag cross-check "
                      "(install with e.g. 'brew install openjdk@25').")
            elif not args.jplag_jar.exists():
                print(f"warning: {args.jplag_jar} not found; skipping JPlag "
                      f"cross-check (fetch it with scripts/fetch_jplag.sh).")
            else:
                print(f"Running JPlag cross-check ({java_bin})...")
                jplag_crosscheck = run_jplag(
                    passing_paths, labels_by_path, out_dir, java_bin,
                    args.jplag_jar, args.jplag_min_tokens,
                )
    else:
        flawfinder_crosscheck = None
        jplag_crosscheck = None
        print("Fewer than 2 passing candidates; skipping diversity measurement.")

    report = render_report(
        root,
        args.pattern,
        args.judge,
        duplicate_groups,
        filter_results,
        labels_by_path,
        out_dir,
        args.near_clone_threshold,
        flawfinder_crosscheck,
        jplag_crosscheck,
    )
    report_path = out_dir / "REPORT.md"
    report_path.write_text(report)
    try:
        shown = report_path.relative_to(REPO_ROOT)
    except ValueError:
        shown = report_path
    print(f"\nWrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
