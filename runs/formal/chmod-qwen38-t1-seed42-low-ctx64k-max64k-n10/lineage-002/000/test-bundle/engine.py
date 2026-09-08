#!/usr/bin/env python3
"""
Shared execution core for the new_chmod test suite.

ONE module defines every filesystem interaction in this project:
  - gen/generate.py  (freezing: derives goldens from an offline specification
                      model held outside this suite; it runs no subprocess,
                      but shares the fixture semantics defined here)
  - runner.py        (the judge: runs the candidate and compares)

Because the judge and the freeze step agree on fixture materialization, argv
construction, environment pinning and the post-run snapshot, a golden is
produced under the same conditions the candidate is later judged under. That
equivalence is the whole reason the goldens are trustworthy.

new_chmod's observable behavior is not just bytes on a stream: it *modifies
filesystem metadata*. So unlike the grep suite, execute() takes a snapshot of
every fixture path's mode after the candidate has run, and that snapshot is
compared against the model's prediction. Everything happens inside a per-case
temporary directory; no repository file is ever touched, and a case whose
fixture or operand path would resolve outside that directory is refused rather
than run.
"""
from __future__ import annotations

import base64
import os
import shutil
import signal
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field

SYMLINK_MARKER = "link"


def _b64(value: str | None) -> bytes:
    if value is None:
        return b""
    return base64.b64decode(value)


def _resolves_outside(td: str, relative: str) -> bool:
    """True if a RELATIVE path token, joined onto td and normalized, would land
    outside td (e.g. via a leading or unbalanced '..')."""
    if os.path.isabs(relative):
        return True
    td_norm = os.path.normpath(td)
    normalized = os.path.normpath(os.path.join(td, relative))
    return not (
        normalized == td_norm or normalized.startswith(td_norm + os.sep)
    )


class SandboxEscapeError(ValueError):
    """A case's fixture or operand path would reach outside the per-run temp
    dir. new_chmod writes permission bits, so an escape here could silently
    change the mode of a real file -- this is refused, not clamped."""


def materialize_fixture(fixture: list[dict] | None, td: str) -> None:
    """Create a case's starting filesystem inside td. Entries apply in list
    order, so a symlink's target can be created first; the modes are applied
    last, deepest first, so making a directory restrictive does not block
    writing the files inside it."""
    deferred_modes: list[tuple[str, int]] = []
    for entry in fixture or []:
        if _resolves_outside(td, entry["path"]):
            raise SandboxEscapeError(
                f"fixture path escapes sandbox: {entry['path']!r}"
            )
        path = os.path.normpath(os.path.join(td, entry["path"]))
        parent = os.path.dirname(path) or td
        os.makedirs(parent, exist_ok=True)
        if os.path.lexists(path):
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        kind = entry["type"]
        if kind == "dir":
            os.makedirs(path, exist_ok=True)
            deferred_modes.append((path, int(entry.get("mode", "0755"), 8)))
        elif kind == "file":
            with open(path, "wb") as handle:
                handle.write(_b64(entry.get("contents_b64")))
            deferred_modes.append((path, int(entry.get("mode", "0644"), 8)))
        elif kind == "symlink":
            os.symlink(entry["target"], path)
        else:
            raise ValueError(f"unknown fixture type: {kind!r}")

    for path, mode in sorted(deferred_modes, key=lambda item: -len(item[0])):
        os.chmod(path, mode)


def snapshot_modes(fixture: list[dict] | None, td: str) -> dict[str, str]:
    """Record every fixture path's mode after the candidate ran.

    Paths are visited shallowest-first and each one's mode is recorded *before*
    anything is relaxed, so the recorded value is always the mode the candidate
    left behind. A directory is then granted owner rwx if it needs it, purely so
    the paths beneath it can still be stat'ed -- by then its own mode has
    already been captured, and its children's modes are untouched by that.

    A symlink is recorded as the marker string rather than a mode: its own
    permission bits are not portably meaningful, and the contract says a link
    found during traversal is left alone entirely.
    """
    recorded: dict[str, str] = {}
    entries = [entry["path"] for entry in fixture or []]
    for relative in sorted(entries, key=lambda item: (item.count("/"), item)):
        path = os.path.normpath(os.path.join(td, relative))
        try:
            info = os.lstat(path)
        except OSError:
            recorded[relative] = "missing"
            continue
        if stat.S_ISLNK(info.st_mode):
            recorded[relative] = SYMLINK_MARKER
            continue
        recorded[relative] = f"{stat.S_IMODE(info.st_mode):04o}"
        if stat.S_ISDIR(info.st_mode):
            try:
                os.chmod(path, stat.S_IMODE(info.st_mode) | 0o700)
            except OSError:
                pass
    return recorded


def restore_writable(td: str) -> None:
    """Re-grant traversal on everything under td so TemporaryDirectory can
    remove a tree the candidate deliberately locked down."""
    for root, dirs, files in os.walk(td, topdown=False, followlinks=False):
        for name in dirs + files:
            full = os.path.join(root, name)
            if os.path.islink(full):
                continue
            try:
                current = stat.S_IMODE(os.lstat(full).st_mode)
                os.chmod(full, current | 0o700)
            except OSError:
                pass
    try:
        os.chmod(td, stat.S_IMODE(os.lstat(td).st_mode) | 0o700)
    except OSError:
        pass


@dataclass
class Result:
    exit_code: int | None  # None if killed by a signal
    signal: int | None
    signal_name: str | None
    stdout: bytes
    stderr: bytes
    modes: dict[str, str] = field(default_factory=dict)
    timed_out: bool = False
    sanitizer: str | None = None

    @property
    def crashed(self) -> bool:
        return self.signal is not None

    def scan_sanitizer(self) -> "Result":
        markers = (
            b"AddressSanitizer",
            b"UndefinedBehaviorSanitizer",
            b"runtime error:",
            b"LeakSanitizer",
        )
        for marker in markers:
            if marker in self.stderr:
                index = self.stderr.find(marker)
                self.sanitizer = self.stderr[index: index + 200].decode(
                    "utf-8", "replace"
                )
                break
        return self


def pinned_env(extra: dict | None = None, sanitizer: bool = False) -> dict:
    """Reproducible environment. Locale pinned to C so any diagnostic wording is
    stable; COLUMNS unset so usage wrapping is."""
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["LANGUAGE"] = "C"
    env.pop("COLUMNS", None)
    if sanitizer:
        env.setdefault(
            "ASAN_OPTIONS", "exitcode=99:detect_leaks=0:abort_on_error=0"
        )
        env.setdefault("UBSAN_OPTIONS", "halt_on_error=1:print_stacktrace=0")
    if extra:
        env.update(extra)
    return env


def is_root() -> bool:
    getter = getattr(os, "geteuid", None)
    return bool(getter and getter() == 0)


def case_needs_non_root(case: dict) -> bool:
    """Permission-denied outcomes are a no-op for root, so a case that depends
    on one can only be judged as a non-root user. Cases declare this rather than
    having it inferred: with chmod the denial is usually produced *by the
    candidate*, not by the starting fixture."""
    if case.get("needs_non_root"):
        return True
    for entry in case.get("fixture") or []:
        mode = entry.get("mode")
        if mode is None:
            continue
        if int(mode, 8) & 0o500 != 0o500 and entry.get("type") == "dir":
            return True
    return False


def execute(case: dict, cmd: list[str], sanitizer: bool = False) -> Result:
    """Run `cmd` plus the case's args in an isolated temp dir, after
    materializing the case's fixture, then snapshot what the run left behind.

    new_chmod never reads standard input, so stdin is always /dev/null: an
    implementation that blocks on a read would hang the judge rather than
    quietly pass.
    """
    if case_needs_non_root(case) and is_root():
        return Result(
            exit_code=None,
            signal=None,
            signal_name="SKIP_ROOT",
            stdout=b"",
            stderr=b"skip: permission-denied case needs non-root",
        )

    timeout = case.get("timeout", 10)

    with tempfile.TemporaryDirectory() as td:
        try:
            materialize_fixture(case.get("fixture"), td)

            args = list(case.get("args", []))
            for token in args:
                if token.startswith("-") or token == "--":
                    continue
                if _resolves_outside(td, token):
                    raise SandboxEscapeError(
                        f"operand path escapes sandbox: {token!r}"
                    )

            env = pinned_env(dict(case.get("env") or {}), sanitizer=sanitizer)
            full = ["chmod"] + cmd[1:] + args
            result = _spawn(full, cmd[0], env, td, timeout, sanitizer)
            result.modes = snapshot_modes(case.get("fixture"), td)
            return result
        finally:
            restore_writable(td)


def _spawn(full, exe, env, td, timeout, sanitizer) -> Result:
    proc = subprocess.Popen(
        full,
        executable=exe,
        env=env,
        cwd=td,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return Result(
            exit_code=None,
            signal=None,
            signal_name=None,
            stdout=b"",
            stderr=b"",
            timed_out=True,
        )

    code = proc.returncode
    signal_number = None
    signal_name = None
    exit_code = code
    if code is not None and code < 0:
        signal_number = -code
        exit_code = None
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"SIG{signal_number}"

    result = Result(
        exit_code=exit_code,
        signal=signal_number,
        signal_name=signal_name,
        stdout=out or b"",
        stderr=err or b"",
    )
    if sanitizer:
        result.scan_sanitizer()
    return result
