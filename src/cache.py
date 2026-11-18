"""Content-addressed caches.

Two layers, both under `[cache] dir` (default runs/cache):

steps/<kind>/<key>/      deterministic controller steps (call graphs, locate,
                         baseline / verification / hidden-suite evaluations).
                         The key covers every input: image id, a content hash of
                         the program and the suite, the step's arguments and a
                         hash of the pipeline's own code (`code_hash`), so editing the
                         pipeline invalidates exactly these entries.

llm/{exact,seq}/<key>.json
                         model responses, written and read inside the agent
                         container (src/incontainer/llm_cache.py). They do not
                         depend on the pipeline's code, which is what makes "rerun the
                         pipeline without the LLM" possible:
                           exact  key = scope + agent label + model/sampling + messages
                           seq    key = scope + agent label + call index
                         `scope` identifies one agent session independently of
                         where the run is written (see `llm_scope`).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from src import PACKAGE_DIR, REPO_ROOT

IGNORED_DIRS = {".git", "target", "build", "__pycache__", ".agent"}
LLM_MODES = ("off", "record", "auto", "replay")
LLM_MATCH = ("exact", "sequence")

RACY_NS = 2_000_000_000
_tree_memo: dict[tuple, str] = {}
_memo_lock = threading.Lock()
_code_hash: str | None = None


def digest(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def tree_hash(path: Path | None) -> str | None:
    """Content hash of a file or directory tree (paths + bytes + exec bit)."""
    if path is None:
        return None
    path = Path(path)
    if path.is_file():
        files = [path]
        base = path.parent
    else:
        base = path
        files = sorted(
            p for p in path.rglob("*")
            if p.is_file() and not any(part in IGNORED_DIRS for part in p.relative_to(path).parts[:-1])
        )
    # ctime and inode cannot be carried over by copy2/copytree (mtime can), so a
    # rewritten tree never reuses a stale memoized hash.
    stats = [(p, p.stat()) for p in files]
    signature = tuple((str(p), st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size) for p, st in stats)
    memo_key = (str(path.resolve()), signature)
    # File timestamps are coarse (kernel clock ticks), and a tree recreated within
    # one tick can repeat inode+ctime+size. As git does for "racy" files, never
    # trust or store a memo for a tree changed in the last RACY_NS.
    racy = any(time.time_ns() - st.st_ctime_ns < RACY_NS for _, st in stats)
    with _memo_lock:
        if not racy and memo_key in _tree_memo:
            return _tree_memo[memo_key]
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(base).as_posix().encode() + b"\0")
        h.update(b"x" if os.access(p, os.X_OK) else b"-")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    value = h.hexdigest()
    if not racy:
        with _memo_lock:
            _tree_memo[memo_key] = value
    return value


def code_hash() -> str:
    """Hash of the code that runs controller steps (the pipeline, including src/analyzers)."""
    global _code_hash
    if _code_hash is None:
        h = hashlib.sha256()
        roots = [PACKAGE_DIR]  # includes the vendored call-graph analyzers (src/analyzers)
        for root in roots:
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.suffix in (".py", ".rs", ".cpp", ".json") and "__pycache__" not in p.parts:
                    h.update(p.relative_to(REPO_ROOT).as_posix().encode() + b"\0")
                    h.update(hashlib.sha256(p.read_bytes()).digest())
        _code_hash = h.hexdigest()
    return _code_hash


class StepCache:
    """Disk cache for deterministic container steps. Thread-safe (atomic renames)."""

    def __init__(self, root: Path | None, enabled: bool = True):
        self.root = Path(root) if root else None
        self.enabled = bool(enabled and root)
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()

    def _dir(self, kind: str, key: str) -> Path:
        return self.root / "steps" / kind / key[:2] / key

    def get(self, kind: str, key: str) -> tuple[dict[str, Any], Path] | None:
        if not self.enabled:
            return None
        d = self._dir(kind, key)
        value = d / "value.json"
        if value.is_file():
            with self._lock:
                self.hits += 1
            return json.loads(value.read_text()), d
        with self._lock:
            self.misses += 1
        return None

    def put(self, kind: str, key: str, value: Mapping[str, Any], files: Mapping[str, Path] | None = None) -> None:
        """Store `value` plus optional directories/files (name -> source path)."""
        if not self.enabled:
            return
        final = self._dir(kind, key)
        if final.exists():
            return
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=final.parent))
        for name, src in (files or {}).items():
            src = Path(src)
            if src.is_dir():
                shutil.copytree(src, tmp / name, symlinks=True)
            elif src.is_file():
                shutil.copy2(src, tmp / name)
        (tmp / "value.json").write_text(json.dumps(value, default=str))
        try:
            os.rename(tmp, final)
        except OSError:  # another worker stored it first
            shutil.rmtree(tmp, ignore_errors=True)

    def memo(self, kind: str, key_parts: Any, compute: Callable[[], dict[str, Any]], cacheable: Callable[[dict], bool] = lambda v: True) -> dict[str, Any]:
        key = digest(kind, key_parts, code_hash())
        hit = self.get(kind, key)
        if hit is not None:
            return hit[0]  # unmodified: results feed later keys (e.g. a located target)
        value = compute()
        if cacheable(value):
            self.put(kind, key, value)
        return value

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}


def cache_root(config: Mapping[str, Any]) -> Path:
    root = Path(config["cache"]["dir"]).expanduser()
    return root if root.is_absolute() else REPO_ROOT / root


def step_cache(config: Mapping[str, Any]) -> StepCache:
    c = config["cache"]
    return StepCache(cache_root(config), c["enabled"] and c["steps"])


def llm_settings(config: Mapping[str, Any], scope_parts: Any) -> dict[str, Any] | None:
    """Session-level LLM cache settings, or None when off."""
    c = config["cache"]
    if not c["enabled"] or c["llm"] == "off":
        return None
    return {
        "mode": c["llm"],
        "match": c["match"],
        "scope": digest("llm-scope", c["namespace"], scope_parts),
    }
