#!/usr/bin/env python3
"""Filesystem fixture execution and semantic snapshots; no utility implementation."""
from __future__ import annotations

import base64
import hashlib
import os
import signal
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath


class SandboxEscapeError(ValueError):
    pass


def safe_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise SandboxEscapeError("invalid path")
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive or "\\" in value:
        raise SandboxEscapeError("absolute or foreign path")
    depth = 0
    for part in value.split("/"):
        if part == "..":
            depth -= 1
        elif part not in ("", "."):
            depth += 1
        if depth < 0:
            raise SandboxEscapeError("unbalanced parent path")
    target = root / value
    resolved = Path(os.path.realpath(target))
    if resolved != root and root not in resolved.parents:
        raise SandboxEscapeError("path resolves outside case root")
    return target


def validate_case(case: dict, root: Path) -> None:
    entries = case.get("fixture", [])
    names = set()
    links = set()
    for entry in entries:
        path = safe_path(root, entry["path"])
        relative = os.path.normpath(entry["path"])
        if relative == "." or relative in names:
            raise ValueError("duplicate fixture or root replacement")
        names.add(relative)
        if entry["type"] not in ("file", "dir", "symlink"):
            raise ValueError("unsupported fixture object")
        if entry["type"] == "symlink":
            links.add(relative)
            target = entry["target"]
            if PurePosixPath(target).is_absolute() or PureWindowsPath(target).drive:
                raise SandboxEscapeError("absolute link target")
            safe_path(root, str(path.parent.relative_to(root) / target))
        if "contents_b64" in entry:
            base64.b64decode(entry["contents_b64"], validate=True)
        if "mode" in entry and not 0 <= int(entry["mode"], 8) <= 0o777:
            raise ValueError("only ordinary permission bits are in scope")
    for name in names:
        if any(str(parent) in links for parent in Path(name).parents):
            raise SandboxEscapeError("fixture has a symlink ancestor")
    # Options are harmless relative tokens too; validate ALL args, including
    # dash-prefixed operands and every token after the terminator.
    for value in case["args"]:
        safe_path(root, value)
    for name in case.get("mode_paths", []):
        safe_path(root, name)
    base64.b64decode(case.get("stdin_b64", ""), validate=True)


def materialize_fixture(fixture: list[dict], root: Path) -> None:
    validate_case({"fixture": fixture, "args": []}, root)
    modes = []
    for entry in fixture:
        path = safe_path(root, entry["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if entry["type"] == "dir":
            path.mkdir(exist_ok=True)
        elif entry["type"] == "file":
            path.write_bytes(base64.b64decode(entry.get("contents_b64", ""), validate=True))
        else:
            path.symlink_to(entry["target"])
            # Earlier links cannot turn an otherwise lexical target into an escape.
            safe_path(root, entry["path"])
            continue
        modes.append((path, int(entry.get("mode", "0755" if entry["type"] == "dir" else "0644"), 8)))
    for path, mode in sorted(modes, key=lambda item: -len(item[0].parts)):
        path.chmod(mode)


def snapshot_tree(root: Path, mode_paths: list[str] = ()) -> dict:
    output = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir(), key=lambda p: os.fsencode(p.name)):
            name = str(path.relative_to(root))
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                record = {"type": "symlink", "target": os.readlink(path)}
            elif stat.S_ISDIR(info.st_mode):
                record = {"type": "dir"}
                # Capture first, relax only for inspection/cleanup; never follow links.
                record_mode = stat.S_IMODE(info.st_mode)
                path.chmod(record_mode | 0o700)
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                record_mode = stat.S_IMODE(info.st_mode)
                path.chmod(record_mode | 0o400)
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(65536), b""):
                        digest.update(chunk)
                record = ({"type": "file", "contents_b64": ""} if info.st_size == 0
                          else {"type": "file", "sha256": digest.hexdigest()})
            else:
                record = {"type": "unsupported"}
            if name in mode_paths and not stat.S_ISLNK(info.st_mode):
                record["mode"] = format(stat.S_IMODE(info.st_mode), "04o")
            output[name] = record
    return dict(sorted(output.items()))


def restore_writable(root: Path) -> None:
    for directory, dirs, files in os.walk(root, topdown=True, followlinks=False):
        for path in [Path(directory), *(Path(directory) / n for n in dirs + files)]:
            if not path.is_symlink():
                try:
                    path.chmod(stat.S_IMODE(path.lstat().st_mode) | 0o700)
                except OSError:
                    pass


@dataclass
class Result:
    exit_code: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    modes: dict = field(default_factory=dict)
    signal_name: str | None = None
    timed_out: bool = False
    sanitizer: str | None = None

    @property
    def crashed(self):
        return self.signal_name is not None and self.signal_name != "SKIP_ROOT"


def execute(case: dict, cmd: list[str], sanitizer: bool = False) -> Result:
    if sanitizer:
        raise ValueError("this functional suite has no sanitizer backend")
    if case.get("needs_non_root") and os.geteuid() == 0:
        return Result(None, signal_name="SKIP_ROOT")
    executable = str(Path(cmd[0]).resolve(strict=True))
    with tempfile.TemporaryDirectory(prefix="filesystem-case-") as temp:
        root = Path(temp).resolve()
        validate_case(case, root)
        try:
            materialize_fixture(case.get("fixture", []), root)
            for arg in case["args"]:
                safe_path(root, arg)
            env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C",
                   "LANGUAGE": "C", "TZ": "UTC", "HOME": str(root), "TMPDIR": str(root)}
            proc = subprocess.Popen(
                [executable, *cmd[1:], *case["args"]], cwd=root, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                umask=0o022, start_new_session=True,
            )
            try:
                out, err = proc.communicate(
                    base64.b64decode(case.get("stdin_b64", "")), timeout=case.get("timeout", 10))
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                return Result(None, timed_out=True)
            result = Result(proc.returncode, out, err)
            if proc.returncode < 0:
                result.signal_name = signal.Signals(-proc.returncode).name
            result.modes = snapshot_tree(root, case.get("mode_paths", []))
            return result
        finally:
            restore_writable(root)
