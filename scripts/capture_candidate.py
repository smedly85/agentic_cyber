#!/usr/bin/env python3
"""Capture an attempt's generated sources, then reclaim the working directory.

Called by scripts/run_experiment.sh once an attempt finishes. It replaces the
Git-based artifact capture the worktree runner used to do:

  * flatten every kept source file into <attempt>/candidate/
  * write the diff artifacts analyze_experiment.py reads
  * check the copied test directories against the repository originals and
    preserve anything the agent touched
  * delete the working directory, which is otherwise a per-attempt copy of the
    whole test suite (tests/sort-test-suite alone is 14M)

Flattening keeps browsing cheap: candidate/new_mkdir.c rather than
candidate/src/new_mkdir/new_mkdir.c. analyze_experiment.py resolves the source
as `<attempt>/candidate/<source_path>`, so the experiment metadata records the
flattened name.

Also usable standalone for retroactive cleanup; see --mode.
"""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import hashlib
import json
import shutil
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def count_diff(baseline: Path | None, candidate: Path) -> tuple[int, int]:
    """Added/deleted line counts, matching the analyzer's difflib approach."""
    baseline_lines = read_lines(baseline) if baseline and baseline.is_file() else []
    candidate_lines = read_lines(candidate)
    added = deleted = 0
    for line in difflib.ndiff(baseline_lines, candidate_lines):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            deleted += 1
    return added, deleted


def is_within(path: Path, parents: list[Path]) -> bool:
    return any(path == parent or parent in path.parents for parent in parents)


def collect_sources(
    workdir: Path,
    keep_globs: list[str],
    excluded: list[Path],
) -> list[Path]:
    found = []
    for path in sorted(workdir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if is_within(path, excluded):
            continue
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in keep_globs):
            found.append(path)
    return found


def flatten_name(relative: Path, taken: set[str]) -> str:
    """Basename, disambiguated by parent directory only when it collides."""
    name = relative.name
    if name not in taken:
        return name
    parent = relative.parent.name or "root"
    mangled = f"{parent}__{name}"
    suffix = 2
    while mangled in taken:
        mangled = f"{parent}__{suffix}__{name}"
        suffix += 1
    return mangled


def capture(
    workdir: Path,
    attempt_dir: Path,
    baseline_dir: Path | None,
    keep_globs: list[str],
    test_dirs: list[str],
) -> dict:
    excluded = [workdir / relative for relative in test_dirs]
    excluded.append(workdir / "build")
    # The runner runs `git init` in the workdir so OpenCode treats it as the
    # project root and its external_directory deny rules take effect. Nothing
    # under .git is agent-authored source, and OpenCode's own snapshots live
    # there, so it never belongs in candidate/.
    excluded.append(workdir / ".git")

    candidate_dir = attempt_dir / "candidate"
    if candidate_dir.exists():
        shutil.rmtree(candidate_dir)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    sources = collect_sources(workdir, keep_globs, excluded)

    manifest: dict[str, str] = {}
    numstat_lines: list[str] = []
    untracked_names: list[str] = []
    name_status_lines: list[str] = []
    taken: set[str] = set()

    for source in sources:
        relative = source.relative_to(workdir)
        flat = flatten_name(relative, taken)
        taken.add(flat)
        manifest[str(relative)] = flat
        shutil.copy2(source, candidate_dir / flat)

        baseline_file = baseline_dir / flat if baseline_dir else None
        if baseline_file is not None and baseline_file.is_file():
            added, deleted = count_diff(baseline_file, source)
            # Analyzer reads columns 0,1 and the final tab-separated field.
            numstat_lines.append(f"{added}\t{deleted}\t{flat}")
            name_status_lines.append(f"M\t{flat}")
        else:
            untracked_names.append(flat)
            name_status_lines.append(f"A\t{flat}")

    (candidate_dir / "manifest.json").write_text(
        json.dumps(
            {"workdir_relative_to_flat": manifest}, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    write_lines(attempt_dir / "diff-numstat.txt", numstat_lines)
    write_lines(attempt_dir / "untracked-files.txt", untracked_names)
    write_lines(attempt_dir / "changed-files.txt", name_status_lines)

    return {
        "files_captured": len(sources),
        "flattened": manifest,
        "collisions_mangled": sorted(
            flat for relative, flat in manifest.items() if Path(relative).name != flat
        ),
    }


def write_lines(path: Path, lines: list[str]) -> None:
    text = "\n".join(lines)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def relative_files(root: Path) -> dict[str, Path]:
    return {
        str(path.relative_to(root)): path
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def check_test_dirs(
    workdir: Path,
    attempt_dir: Path,
    repository: Path,
    test_dirs: list[str],
) -> dict:
    """Compare the per-attempt test copies with the repository originals.

    Every prompt forbids modifying the visible tests, and the continuation
    prompt repeats that instruction each loop. Deleting the copies without
    checking would destroy the evidence that the instruction was violated.
    """
    report: dict[str, dict] = {}
    preserved_root = attempt_dir / "tampered-tests"
    tampered_total = 0

    for relative in test_dirs:
        copy_root = workdir / relative
        source_root = repository / relative
        if not copy_root.is_dir() or not source_root.is_dir():
            continue

        copies = relative_files(copy_root)
        originals = relative_files(source_root)

        modified, added, deleted = [], [], []
        for name, path in copies.items():
            original = originals.get(name)
            if original is None:
                added.append(name)
            elif sha256_file(path) != sha256_file(original):
                modified.append(name)
        deleted = sorted(set(originals) - set(copies))

        for name in modified + added:
            destination = preserved_root / relative / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(copies[name], destination)

        tampered_total += len(modified) + len(added) + len(deleted)
        report[relative] = {
            "modified": sorted(modified),
            "added": sorted(added),
            "deleted": deleted,
        }

    return {
        "clean": tampered_total == 0,
        "tampered_file_count": tampered_total,
        "directories": report,
    }


def prune_legacy_sandbox(run_root: Path) -> int:
    """Reclaim space in sandbox-format runs without breaking their analysis.

    These runs are analyzed as `sandbox_run`, where the analyzer reads
    `<attempt>/workdir/<source_path>` directly. The workdir itself must stay;
    only the copied test suites and build output are removed.
    """
    run_json = run_root / "run.json"
    if not run_json.is_file():
        return 0
    try:
        metadata = json.loads(run_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return 0

    test_dirs = [
        item for item in str(metadata.get("test_dirs", "")).split(",") if item
    ]
    removed = 0
    for workdir in sorted(run_root.rglob("workdir")):
        if not workdir.is_dir():
            continue
        if not (workdir.parent / "COMPLETE").is_file():
            continue
        targets = [workdir / relative for relative in test_dirs]
        targets.append(workdir / "build")
        for target in targets:
            if target.is_dir():
                shutil.rmtree(target)
                removed += 1
        # Drop now-empty parents of the removed test directories.
        for relative in test_dirs:
            parent = (workdir / relative).parent
            while parent != workdir and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("attempt", "prune-legacy"),
        default="attempt",
        help="attempt: capture+prune one attempt. prune-legacy: sandbox runs.",
    )
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--attempt-dir", type=Path)
    parser.add_argument("--baseline-dir", type=Path, default=None)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--keep-glob", action="append", default=[])
    parser.add_argument("--test-dir", action="append", default=[])
    parser.add_argument("--run-root", type=Path, default=None)
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Capture and verify, but do not delete the working directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.mode == "prune-legacy":
        if args.run_root is None:
            raise SystemExit("--run-root is required for --mode prune-legacy")
        removed = prune_legacy_sandbox(args.run_root)
        print(json.dumps({"directories_removed": removed}))
        return 0

    if args.workdir is None or args.attempt_dir is None:
        raise SystemExit("--workdir and --attempt-dir are required")
    if not args.workdir.is_dir():
        raise SystemExit(f"working directory not found: {args.workdir}")

    keep_globs = args.keep_glob or ["*.c", "*.h"]
    result = capture(
        args.workdir,
        args.attempt_dir,
        args.baseline_dir,
        keep_globs,
        args.test_dir,
    )
    integrity = check_test_dirs(
        args.workdir, args.attempt_dir, args.repository, args.test_dir
    )

    pruned = False
    git_marker_removed = False
    if not args.keep_workdir:
        shutil.rmtree(args.workdir)
        pruned = True
    else:
        # The runner creates an empty repository in the workdir purely to move
        # OpenCode's project boundary onto it. Dropping the workdir normally
        # takes it along; when the workdir is kept for inspection the marker is
        # still scratch, and leaving it makes the kept tree look like a real
        # checkout.
        git_marker = args.workdir / ".git"
        if git_marker.is_dir():
            shutil.rmtree(git_marker)
            git_marker_removed = True

    print(
        json.dumps(
            {
                "files_captured": result["files_captured"],
                "collisions_mangled": result["collisions_mangled"],
                "test_dir_integrity": integrity,
                "workdir_pruned": pruned,
                "git_marker_removed": git_marker_removed,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
