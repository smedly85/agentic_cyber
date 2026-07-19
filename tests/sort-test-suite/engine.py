#!/usr/bin/env python3
"""
Shared execution core for the exhaustive sort test suite.

ONE module runs every subprocess in this project:
  - gen/freeze.py  (the oracle: runs /usr/bin/sort to freeze golden outputs)
  - runner.py      (the judge: runs the candidate and compares)
  - diff_fuzz.py   (the fuzzer: runs both live)

Because all three go through engine.execute(), a golden frozen from GNU
sort is produced under byte-identical conditions (env, cwd, argv[0],
rlimits, fault injection, stdin delivery) to how the candidate is later
judged. That equivalence is the whole reason goldens are trustworthy.

Everything is BYTES. Unlike the legacy runner/run_tests.py (text=True),
this can express NUL bytes, invalid UTF-8, and -z (NUL-terminated)
records, all of which are core sort behaviors.
"""
from __future__ import annotations

import base64
import os
import resource
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field


# --- schema-v2 case field decode helpers ------------------------------------

def _b64(s: str | None) -> bytes | None:
    if s is None:
        return None
    return base64.b64decode(s)


def case_stdin_bytes(case: dict) -> bytes | None:
    """Return the case's stdin as bytes, from either stdin_b64 or stdin."""
    if case.get("stdin_b64") is not None:
        return _b64(case["stdin_b64"])
    s = case.get("stdin")
    if s is None:
        return None
    return s.encode()


def case_files_bytes(case: dict) -> dict[str, bytes]:
    """Materialization map name->bytes, merging files_b64 and legacy files."""
    out: dict[str, bytes] = {}
    for name, contents in (case.get("files") or {}).items():
        out[name] = contents.encode()
    for name, b in (case.get("files_b64") or {}).items():
        out[name] = base64.b64decode(b)
    return out


# --- result ------------------------------------------------------------------

@dataclass
class Result:
    exit_code: int | None          # None if killed by signal
    signal: int | None             # signal number if WIFSIGNALED else None
    signal_name: str | None
    stdout: bytes
    stderr: bytes
    outfiles: dict[str, bytes] = field(default_factory=dict)
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
                # capture a short excerpt for the report
                idx = text.find(m)
                self.sanitizer = text[idx: idx + 200].decode(
                    "utf-8", "replace"
                )
                break
        return self


# --- environment -------------------------------------------------------------

def pinned_env(extra: dict | None = None, sanitizer: bool = False) -> dict:
    """Reproducible environment. Locale pinned to C; COLUMNS unset so
    usage/--help wrapping is stable; TMPDIR is set per-case by the caller."""
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["LANGUAGE"] = "C"
    env.pop("COLUMNS", None)
    # Deterministic obsolete-syntax behavior unless a case overrides it.
    env.pop("POSIXLY_CORRECT", None)
    env.pop("_POSIX2_VERSION", None)
    if sanitizer:
        env.setdefault("ASAN_OPTIONS", "exitcode=99:detect_leaks=0:abort_on_error=0")
        env.setdefault("UBSAN_OPTIONS", "halt_on_error=1:print_stacktrace=0")
    if extra:
        env.update(extra)
    return env


# --- fault injection ---------------------------------------------------------

class _Faults:
    """Resolves the case['faults'] dict into concrete preexec / fd / path
    setup applied inside a per-case working directory `td`."""

    def __init__(self, faults: dict, td: str):
        self.f = faults or {}
        self.td = td

    def preexec(self):
        """Return a callable for subprocess preexec_fn, or None. Applied in
        the child after fork, before exec."""
        rl = self.f.get("rlimit_nofile")
        if rl is None:
            return None

        def _apply():
            resource.setrlimit(resource.RLIMIT_NOFILE, (rl, rl))
        return _apply

    def stdout_target(self, stack):
        """Return (file_object_or_PIPE, capture_bool). When routing stdout
        to a real target (e.g. /dev/full) we cannot also capture it."""
        tgt = self.f.get("stdout")
        if tgt is None:
            return subprocess.PIPE, True
        if tgt == "/dev/full":
            fh = stack.enter_context(open("/dev/full", "wb"))
            return fh, False
        if tgt == "closed-pipe":
            # handled specially in execute(): a pipe whose read end we
            # close immediately to provoke EPIPE/SIGPIPE.
            return "CLOSED_PIPE", False
        raise ValueError(f"unknown stdout fault target: {tgt!r}")

    def apply_fs(self):
        """Set up filesystem-level faults inside td. Returns cleanup list
        of (path, mode) to restore so the TemporaryDirectory can be removed."""
        restore = []
        for name in self.f.get("unreadable", []):
            p = os.path.join(self.td, name)
            if not os.path.exists(p):
                open(p, "wb").close()
            os.chmod(p, 0o000)
            restore.append((p, 0o600))
        for name in self.f.get("dir_input", []):
            os.makedirs(os.path.join(self.td, name), exist_ok=True)
        if self.f.get("unwritable_dir_output"):
            d = os.path.join(self.td, "ro_out_dir")
            os.makedirs(d, exist_ok=True)
            os.chmod(d, 0o500)
            restore.append((d, 0o700))
        return restore

    def tmpdir(self):
        """Return a TMPDIR value (path) for the env, or None to leave the
        engine default (the case working dir)."""
        t = self.f.get("tmpdir")
        if t is None:
            return None
        if t == "missing":
            return os.path.join(self.td, "no_such_tmp")
        if t == "unwritable":
            d = os.path.join(self.td, "ro_tmp")
            os.makedirs(d, exist_ok=True)
            os.chmod(d, 0o500)
            return d
        raise ValueError(f"unknown tmpdir fault: {t!r}")


# --- execution ---------------------------------------------------------------

def is_root() -> bool:
    return os.geteuid() == 0


def execute(
    case: dict,
    cmd: list[str],
    stdin_mode: str = "pipe",
    sanitizer: bool = False,
    extra_argv: list[str] | None = None,
) -> Result:
    """Run `cmd` (the binary + any prefix args) with the case's args in an
    isolated temp dir. stdin_mode is one of "file"|"pipe"|"redirect" (see
    legacy run_tests.py for the rationale). extra_argv is appended after the
    case args (used by the "file" stdin mode to append the input filename).

    Returns a Result with bytes stdout/stderr and any declared output files.
    """
    faults = case.get("faults") or {}
    if faults.get("unreadable") and is_root():
        # chmod 000 is a no-op for root; caller (runner) should skip such
        # cases. Signal via a sentinel Result.
        return Result(exit_code=None, signal=None, signal_name="SKIP_ROOT",
                      stdout=b"", stderr=b"skip: unreadable fault as root")

    timeout = case.get("timeout", 10)
    args = list(case.get("args", []))
    stdin_bytes = case_stdin_bytes(case) or b""
    files = case_files_bytes(case)

    with tempfile.TemporaryDirectory() as td:
        import contextlib
        stack = contextlib.ExitStack()
        restore = []
        try:
            # materialize declared files
            for name, contents in files.items():
                path = os.path.join(td, name)
                os.makedirs(os.path.dirname(path) or td, exist_ok=True)
                with open(path, "wb") as fh:
                    fh.write(contents)

            fh = _Faults(faults, td)
            restore = fh.apply_fs()

            env_extra = dict(case.get("env") or {})
            tmp = fh.tmpdir()
            env_extra.setdefault("TMPDIR", tmp if tmp else td)
            env = pinned_env(env_extra, sanitizer=sanitizer)

            argv0 = "sort"
            full = [argv0] + cmd[1:] + args + (extra_argv or [])

            # stdin delivery
            input_bytes = None
            stdin_fh = None
            if stdin_mode == "file":
                in_path = os.path.join(td, "in")
                with open(in_path, "wb") as f:
                    f.write(stdin_bytes)
                full = full + ["in"]
                stdin_fh = subprocess.DEVNULL
            elif stdin_mode == "pipe":
                input_bytes = stdin_bytes
            elif stdin_mode == "redirect":
                sp = os.path.join(td, ".stdin")
                with open(sp, "wb") as f:
                    f.write(stdin_bytes)
                stdin_fh = stack.enter_context(open(sp, "rb"))
            else:
                raise ValueError(stdin_mode)

            stdout_tgt, capture_out = fh.stdout_target(stack)

            return _spawn(
                full, cmd[0], env, td, timeout,
                input_bytes, stdin_fh, stdout_tgt, capture_out,
                fh.preexec(), case, sanitizer,
            )
        finally:
            for p, mode in restore:
                try:
                    os.chmod(p, mode)
                except OSError:
                    pass
            stack.close()


def _spawn(full, exe, env, td, timeout, input_bytes, stdin_fh,
           stdout_tgt, capture_out, preexec, case, sanitizer) -> Result:
    closed_pipe = stdout_tgt == "CLOSED_PIPE"
    popen_kwargs = dict(
        executable=exe,
        env=env,
        cwd=td,
        stderr=subprocess.PIPE,
        preexec_fn=preexec,
    )
    if stdin_fh is not None:
        popen_kwargs["stdin"] = stdin_fh
    else:
        popen_kwargs["stdin"] = subprocess.PIPE

    if closed_pipe:
        # Provoke EPIPE: give sort a pipe, close the read end right away.
        r_fd, w_fd = os.pipe()
        popen_kwargs["stdout"] = w_fd
        capture_out = False
    elif capture_out:
        popen_kwargs["stdout"] = subprocess.PIPE
    else:
        popen_kwargs["stdout"] = stdout_tgt

    proc = subprocess.Popen(full, **popen_kwargs)
    if closed_pipe:
        os.close(w_fd)
        os.close(r_fd)  # nothing reads it -> writer gets EPIPE

    try:
        out, err = proc.communicate(input=input_bytes, timeout=timeout)
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

    outfiles = {}
    for spec_name in ("output_file",):
        spec = case.get(spec_name)
        if spec:
            p = os.path.join(td, spec["path"])
            if os.path.exists(p):
                with open(p, "rb") as f:
                    outfiles[spec["path"]] = f.read()

    res = Result(
        exit_code=exit_code,
        signal=sig,
        signal_name=signame,
        stdout=out if out is not None else b"",
        stderr=err if err is not None else b"",
        outfiles=outfiles,
    )
    if sanitizer:
        res.scan_sanitizer()
    return res
