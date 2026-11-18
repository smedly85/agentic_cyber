"""Input program discovery and working copies."""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRS = {".git", "target", "build", "__pycache__", ".agent"}


@dataclass(frozen=True)
class Project:
    root: Path  # directory holding the program (a working copy owned by the pipeline)
    language: str  # "c" | "rust"
    kind: str  # "c_single" | "c_multi" | "rust_single" | "cargo"
    sources: tuple[str, ...]  # paths relative to root (C: .c files; Rust: crate root file)
    crate_name: str | None = None


def _rel_files(root: Path, suffix: str) -> list[str]:
    files = []
    for path in sorted(root.rglob(f"*{suffix}")):
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        files.append(path.relative_to(root).as_posix())
    return files


def discover(root: Path, language: str) -> Project:
    root = root.resolve()
    if language == "c":
        sources = _rel_files(root, ".c")
        if not sources:
            raise ValueError(f"no .c files under {root}")
        return Project(root, "c", "c_single" if len(sources) == 1 else "c_multi", tuple(sources))
    if language == "rust":
        manifest = root / "Cargo.toml"
        if manifest.is_file():
            data = tomllib.loads(manifest.read_text())
            name = data.get("package", {}).get("name", root.name)
            main = "src/main.rs"
            for target in data.get("bin", []):
                if target.get("path"):
                    main = target["path"]
                    break
            if not (root / main).is_file():
                raise ValueError(f"cargo project has no binary root {main}")
            return Project(root, "rust", "cargo", (main,), name.replace("-", "_"))
        sources = _rel_files(root, ".rs")
        if len(sources) != 1:
            raise ValueError(f"expected Cargo.toml or exactly one .rs file under {root}, found {sources}")
        return Project(root, "rust", "rust_single", tuple(sources), Path(sources[0]).stem.replace("-", "_"))
    raise ValueError(f"unknown language {language!r}")


def make_working_copy(input_path: Path, dest: Path) -> Path:
    """Copy the user's program into `dest` (never modify the input)."""
    input_path = input_path.resolve()
    if dest.exists():
        shutil.rmtree(dest)
    if input_path.is_file():
        dest.mkdir(parents=True)
        shutil.copy2(input_path, dest / input_path.name)
    elif input_path.is_dir():
        shutil.copytree(input_path, dest, ignore=shutil.ignore_patterns(*IGNORED_DIRS))
    else:
        raise FileNotFoundError(input_path)
    return dest


def copy_tree(src: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*IGNORED_DIRS))
    return dest
