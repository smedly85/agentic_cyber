#!/usr/bin/env python3
"""
Shared execution core for the new_grep test suite.

ONE module runs every subprocess in this project:
  - gen/generate.py  (freezing: derives goldens from an offline specification
                      model held outside this suite; it runs no subprocess,
                      but shares the fixture semantics defined here)
  - runner.py        (the judge: runs the candidate and compares)

Because the judge and the freeze step agree on fixture materialization, argv
construction, environment pinning and line semantics, a golden is produced
under the same conditions the candidate is later judged under. That equivalence
is the whole reason the goldens are trustworthy.

grep's observable output is bytes on stdout, a diagnostic class on stderr, and
an exit status. Nothing on the filesystem changes, so unlike the mkdir and
chmod suites there is no post-run tree snapshot. What execute() does provide is
a `fixture`: files, directories and symlinks created inside a per-case temp dir
BEFORE the candidate runs, so cases can exercise file operands, recursive
traversal, unreadable files and missing paths without touching anything real.
"""
from __future__ import annotations

import base64
import os
import shutil
import signal
import stat
import subprocess
import tempfile
from dataclasses import dataclass


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
    dir. new_grep only ever reads, so an escape cannot corrupt the machine the
    way mkdir or chmod could -- but it would make the case's result depend on
    the host, which is just as fatal to a frozen golden."""


def materialize_fixture(fixture: list[dict] | None, td: str) -> None:
    """Create a case's starting filesystem inside td. Entries apply in list
    order, so a symlink's target can be created first, and a directory whose
    mode must end up restrictive can be filled before it is locked down."""
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

    # Applied last, deepest first, so making a directory unreadable does not
    # block writing the files inside it.
    for path, mode in sorted(deferred_modes, key=lambda item: -len(item[0])):
        os.chmod(path, mode)


def restore_writable(td: str) -> None:
    """Re-grant traversal on everything under td so TemporaryDirectory can
    remove a fixture that deliberately locked a path down."""
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


@dataclass
class Result:
    exit_code: int | None  # None if killed by a signal
    signal: int | None
    signal_name: str | None
    stdout: bytes
    stderr: bytes
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
    """Reproducible environment. Locale pinned to C so byte comparison and any
    diagnostic wording are stable; COLUMNS unset so usage wrapping is."""
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
    """chmod-based unreadability is a no-op for root, so those cases can only
    be judged as a non-root user."""
    for entry in case.get("fixture") or []:
        mode = entry.get("mode")
        if mode is None:
            continue
        if int(mode, 8) & 0o444 == 0:
            return True
    return False


def execute(
    case: dict,
    cmd: list[str],
    stdin_mode: str = "pipe",
    sanitizer: bool = False,
) -> Result:
    """Run `cmd` plus the case's args in an isolated temp dir, after
    materializing the case's fixture. `stdin_mode` selects how the case's
    stdin bytes are delivered: "pipe" (a pipe), "redirect" (a seekable regular
    file), or "none" (/dev/null)."""
    if case_needs_non_root(case) and is_root():
        return Result(
            exit_code=None,
            signal=None,
            signal_name="SKIP_ROOT",
            stdout=b"",
            stderr=b"skip: unreadable fixture needs non-root",
        )

    timeout = case.get("timeout", 10)
    stdin_bytes = _b64(case.get("stdin_b64")) if "stdin_b64" in case else None

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
            full = ["grep"] + cmd[1:] + args
            return _spawn(
                full, cmd[0], env, td, timeout, stdin_bytes, stdin_mode,
                sanitizer,
            )
        finally:
            restore_writable(td)


def _spawn(
    full, exe, env, td, timeout, stdin_bytes, stdin_mode, sanitizer
) -> Result:
    stdin_handle = subprocess.DEVNULL
    stdin_file = None
    payload = None

    if stdin_bytes is not None:
        if stdin_mode == "redirect":
            # A seekable regular file rather than a pipe: an implementation that
            # only works on one of the two is a real defect.
            stdin_file = tempfile.TemporaryFile()
            stdin_file.write(stdin_bytes)
            stdin_file.seek(0)
            stdin_handle = stdin_file
        elif stdin_mode == "none":
            stdin_handle = subprocess.DEVNULL
        else:
            stdin_handle = subprocess.PIPE
            payload = stdin_bytes

    try:
        proc = subprocess.Popen(
            full,
            executable=exe,
            env=env,
            cwd=td,
            stdin=stdin_handle,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            out, err = proc.communicate(input=payload, timeout=timeout)
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
    finally:
        if stdin_file is not None:
            stdin_file.close()

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
