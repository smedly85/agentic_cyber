#!/usr/bin/env python3
"""
Shared execution core for the exhaustive mkdir test suite.

ONE module runs every subprocess in this project:
  - gen/freeze.py  (the oracle: runs GNU mkdir to freeze golden filesystem
                    state)
  - runner.py      (the judge: runs the candidate and compares)
  - diff_fuzz.py   (the fuzzer: runs both live)

Because all three go through engine.execute(), a golden frozen from GNU
mkdir is produced under byte-identical conditions (env, cwd, argv[0],
umask, rlimits, starting fixture) to how the candidate is later judged.
That equivalence is the whole reason goldens are trustworthy.

Unlike sort, mkdir's observable output is mostly FILESYSTEM STATE, not
stdout: which directories now exist, their permission bits (including
setuid/setgid/sticky), and any symlink targets. So execute() takes a
`fixture` (paths to create BEFORE running, so cases can start from
pre-existing directories, files-as-path-components, or symlinks) and
returns a `tree` snapshot (every path under the run's temp dir AFTER
running, with its type/mode/symlink-target) alongside the usual
stdout/stderr/exit_code. The temp dir's umask is pinned (default 0022,
per-case overridable) so mode goldens are reproducible, exactly as env/
locale are pinned.
"""
from __future__ import annotations

import base64
import os
import resource
import signal
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field


# --- schema-v2 fixture/tree helpers ------------------------------------------

def _b64(s: str | None) -> bytes | None:
    if s is None:
        return None
    return base64.b64decode(s)


def _resolves_outside(td: str, rel: str) -> bool:
    """True if a RELATIVE path token, joined onto td and normalized, would
    land outside td (e.g. via a leading or unbalanced '..'). Absolute paths
    (used only for the deliberate abs_targets mechanism) are not relative
    escapes and are checked separately by their caller."""
    if os.path.isabs(rel):
        return False
    td_norm = os.path.normpath(td)
    normalized = os.path.normpath(os.path.join(td, rel))
    return not (normalized == td_norm or normalized.startswith(td_norm + os.sep))


class SandboxEscapeError(ValueError):
    """A case's fixture or operand path would touch the real filesystem
    outside the per-run temp dir. This must never happen -- goldens and
    fuzz probes run real mkdir binaries, and a path that escapes the
    sandbox writes to (or chmods) the actual machine, not a throwaway dir.
    Cases that legitimately want to test outside-td behavior must go
    through abs_targets, which resolves explicitly and only within td."""


def materialize_fixture(fixture: list[dict] | None, td: str) -> None:
    """Create the case's starting filesystem state inside td, BEFORE the
    candidate runs. Entries are applied in list order so a symlink's target
    directory can be created first. If two entries' paths collide after
    normalization (e.g. a mutator produces both "p" and "p/."), the later
    entry wins -- whatever the earlier entry created is removed first,
    rather than raising (a dir-vs-file collision is a well-defined "replace
    it" fixture edit, not a harness error)."""
    import shutil
    for entry in (fixture or []):
        if _resolves_outside(td, entry["path"]):
            raise SandboxEscapeError(
                f"fixture path escapes sandbox: {entry['path']!r}")
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
            os.chmod(path, int(entry.get("mode", "0755"), 8))
        elif kind == "file":
            with open(path, "wb") as fh:
                fh.write(_b64(entry.get("contents_b64")) or b"")
            os.chmod(path, int(entry.get("mode", "0644"), 8))
        elif kind == "symlink":
            os.symlink(entry["target"], path)
        else:
            raise ValueError(f"unknown fixture type: {kind!r}")


def snapshot_tree(td: str) -> list[dict]:
    """Walk td AFTER the run and return every entry's path (relative to td),
    type, permission bits (st_mode & 0o7777, NOT following symlinks), and
    symlink target if applicable. This is the primary golden for mkdir:
    filesystem state, not stdout. Sorted for determinism."""
    out = []
    for root, dirs, files in os.walk(td, followlinks=False):
        dirs.sort()
        files.sort()
        for name in dirs + files:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, td)
            st = os.lstat(full)
            mode = stat.S_IMODE(st.st_mode)
            if stat.S_ISLNK(st.st_mode):
                out.append({"path": rel, "type": "symlink",
                            "mode": mode, "target": os.readlink(full)})
            elif stat.S_ISDIR(st.st_mode):
                out.append({"path": rel, "type": "dir", "mode": mode})
            else:
                out.append({"path": rel, "type": "file", "mode": mode})
    out.sort(key=lambda e: e["path"])
    return out


# --- result ------------------------------------------------------------------

@dataclass
class Result:
    exit_code: int | None          # None if killed by signal
    signal: int | None             # signal number if WIFSIGNALED else None
    signal_name: str | None
    stdout: bytes
    stderr: bytes
    tree: list[dict] = field(default_factory=list)
    timed_out: bool = False
    # sanitizer report text, if an ASan/UBSan diagnostic was seen in stderr
    sanitizer: str | None = None

    @property
    def crashed(self) -> bool:
        return self.signal is not None

    def scan_sanitizer(self) -> "Result":
        text = self.stderr
        markers = (
            b"AddressSanitizer",
            b"UndefinedBehaviorSanitizer",
            b"runtime error:",
            b"LeakSanitizer",
            b"ERROR: libFuzzer",
        )
        for m in markers:
            if m in text:
                idx = text.find(m)
                self.sanitizer = text[idx: idx + 200].decode(
                    "utf-8", "replace"
                )
                break
        return self


# --- environment -------------------------------------------------------------

def pinned_env(extra: dict | None = None, sanitizer: bool = False) -> dict:
    """Reproducible environment. Locale pinned to C; COLUMNS unset so
    usage/--help wrapping is stable."""
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["LANGUAGE"] = "C"
    env.pop("COLUMNS", None)
    if sanitizer:
        env.setdefault("ASAN_OPTIONS", "exitcode=99:detect_leaks=0:abort_on_error=0")
        env.setdefault("UBSAN_OPTIONS", "halt_on_error=1:print_stacktrace=0")
    if extra:
        env.update(extra)
    return env


# --- fault injection ---------------------------------------------------------

class _Faults:
    """Resolves the case['faults'] dict into concrete preexec / permission
    setup applied inside a per-case working directory `td`. Most mkdir error
    conditions (EEXIST, ENOENT, ENOTDIR) are expressible via `fixture` alone
    and need no fault plumbing; `faults` covers what fixture can't express:
    permission-based EACCES and fd exhaustion."""

    def __init__(self, faults: dict, td: str):
        self.f = faults or {}
        self.td = td

    def preexec(self):
        rl = self.f.get("rlimit_nofile")
        if rl is None:
            return None

        def _apply():
            resource.setrlimit(resource.RLIMIT_NOFILE, (rl, rl))
        return _apply

    def apply_fs(self) -> list[tuple[str, int]]:
        """Apply filesystem-level permission faults inside td. Returns a
        restore list of (path, mode) to chmod back afterward so the
        TemporaryDirectory can be removed."""
        restore = []
        parent = self.f.get("readonly_parent")
        if parent:
            p = os.path.join(self.td, parent)
            os.makedirs(p, exist_ok=True)
            os.chmod(p, 0o500)
            restore.append((p, 0o700))
        if self.f.get("unwritable_cwd"):
            os.chmod(self.td, 0o500)
            restore.append((self.td, 0o700))
        return restore

    def needs_root_skip(self) -> bool:
        """chmod-based EACCES faults are no-ops for root (root bypasses
        permission checks), so those cases must be skipped when running as
        this user."""
        return bool(self.f.get("readonly_parent") or self.f.get("unwritable_cwd"))


# --- execution ---------------------------------------------------------------

def is_root() -> bool:
    return os.geteuid() == 0


def execute(
    case: dict,
    cmd: list[str],
    sanitizer: bool = False,
) -> Result:
    """Run `cmd` (the binary + any prefix args) with the case's args in an
    isolated temp dir, after materializing the case's starting fixture.
    Returns a Result with bytes stdout/stderr, exit/signal info, and a full
    post-run filesystem `tree` snapshot."""
    faults = case.get("faults") or {}
    fh_probe = _Faults(faults, "")
    if fh_probe.needs_root_skip() and is_root():
        return Result(exit_code=None, signal=None, signal_name="SKIP_ROOT",
                      stdout=b"", stderr=b"skip: permission fault needs non-root")

    timeout = case.get("timeout", 10)
    umask = int(case.get("umask", "0022"), 8)

    with tempfile.TemporaryDirectory() as td:
        restore: list[tuple[str, int]] = []
        try:
            materialize_fixture(case.get("fixture"), td)

            fh = _Faults(faults, td)
            restore = fh.apply_fs()

            env = pinned_env(dict(case.get("env") or {}), sanitizer=sanitizer)

            argv0 = "mkdir"
            args = list(case.get("args", []))
            abs_targets = set(case.get("abs_targets") or [])
            # Safety: any non-flag token NOT explicitly routed through
            # abs_targets must resolve inside td. Goldens and fuzz probes
            # run real mkdir binaries; a path that escapes the sandbox
            # (e.g. a mutator-injected leading "..") would create/chmod
            # real paths on the actual machine, not a throwaway dir.
            for tok in args:
                if tok == "--" or tok.startswith("-") or tok in abs_targets:
                    continue
                if tok == "..":
                    # td's own parent -- a deliberate, provably-safe probe:
                    # it always exists, so mkdir can only ever fail EEXIST
                    # there, never create/modify anything outside td.
                    continue
                if _resolves_outside(td, tok):
                    raise SandboxEscapeError(
                        f"operand path escapes sandbox: {tok!r}")
            if abs_targets:
                args = [os.path.join(td, a) if a in abs_targets else a
                       for a in args]
            full = [argv0] + cmd[1:] + args

            rl_preexec = fh.preexec()

            def preexec_fn():
                os.umask(umask)
                if rl_preexec:
                    rl_preexec()

            res = _spawn(full, cmd[0], env, td, timeout, preexec_fn,
                        sanitizer)
            if not res.timed_out:
                res.tree = snapshot_tree(td)
            return res
        finally:
            for p, mode in restore:
                try:
                    os.chmod(p, mode)
                except OSError:
                    pass


def _spawn(full, exe, env, td, timeout, preexec_fn, sanitizer) -> Result:
    proc = subprocess.Popen(
        full,
        executable=exe,
        env=env,
        cwd=td,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=preexec_fn,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return Result(exit_code=None, signal=None, signal_name=None,
                      stdout=b"", stderr=b"", timed_out=True)

    rc = proc.returncode
    sig = None
    signame = None
    exit_code = rc
    if rc is not None and rc < 0:
        sig = -rc
        exit_code = None
        try:
            signame = signal.Signals(sig).name
        except ValueError:
            signame = f"SIG{sig}"

    res = Result(
        exit_code=exit_code,
        signal=sig,
        signal_name=signame,
        stdout=out if out is not None else b"",
        stderr=err if err is not None else b"",
    )
    if sanitizer:
        res.scan_sanitizer()
    return res
