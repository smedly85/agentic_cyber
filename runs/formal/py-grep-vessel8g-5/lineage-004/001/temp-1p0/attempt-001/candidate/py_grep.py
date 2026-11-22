#!/usr/bin/env python3
"""py_grep — bounded fixed-byte-substring line matcher (checkpoint 000)."""

import os
import sys


def search_stream(data: bytes, pattern: bytes) -> list[bytes]:
    """Return the lines of *data* (delimited by 0x0A) that contain *pattern*
    as a byte substring. A trailing 0x0A does not produce an extra empty line.
    An empty *pattern* matches every line."""
    if not data:
        return []
    parts = data.split(b"\n")
    if parts and parts[-1] == b"":
        parts.pop()
    if not pattern:
        return parts
    return [p for p in parts if pattern in p]


def _write_lines(lines: list[bytes], prefix: bytes) -> None:
    out = sys.stdout.buffer
    for line in lines:
        out.write(prefix + line + b"\n")
    out.flush()


def _diagnose(fname: str, exc: OSError) -> None:
    name = os.fsencode(fname)
    if isinstance(exc, IsADirectoryError):
        msg = b"Is a directory"
    elif isinstance(exc, FileNotFoundError):
        msg = b"No such file or directory"
    elif isinstance(exc, PermissionError):
        msg = b"Permission denied"
    else:
        msg = str(exc).encode("utf-8", "replace")
    try:
        sys.stderr.buffer.write(name + b": " + msg + b"\n")
        sys.stderr.buffer.flush()
    except (OSError, BrokenPipeError):
        pass


def _usage_error(msg: bytes) -> None:
    try:
        sys.stderr.buffer.write(msg + b"\n")
        sys.stderr.buffer.write(b"usage: py_grep PATTERN [FILE...]\n")
        sys.stderr.buffer.flush()
    except (OSError, BrokenPipeError):
        pass
    sys.exit(2)


def main() -> None:
    argv = sys.argv[1:]

    # ---- argument parsing ----
    i = 0
    pattern: bytes | None = None
    files: list[str] = []
    no_options = False
    with_filename = False

    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            no_options = True
            i += 1
            continue
        if not no_options and arg.startswith("-") and len(arg) > 1:
            if arg == "-H" or arg == "--with-filename":
                with_filename = True
                i += 1
                continue
            _usage_error(b"py_grep: unsupported option: " + os.fsencode(arg))
        if pattern is None:
            pattern = os.fsencode(arg)
        else:
            files.append(arg)
        i += 1

    if pattern is None:
        _usage_error(b"py_grep: missing PATTERN")

    need_prefix = with_filename or len(files) >= 2
    found = False
    had_error = False

    # ---- search ----
    if not files:
        data = sys.stdin.buffer.read()
        lines = search_stream(data, pattern)
        if lines:
            prefix = b"(standard input):" if with_filename else b""
            _write_lines(lines, prefix)
            found = True
    else:
        for fname in files:
            try:
                with open(fname, "rb") as f:
                    data = f.read()
            except MemoryError:
                sys.exit(2)
            except OSError as e:
                _diagnose(fname, e)
                had_error = True
                continue
            lines = search_stream(data, pattern)
            if lines:
                prefix = os.fsencode(fname) + b":" if need_prefix else b""
                _write_lines(lines, prefix)
                found = True

    # ---- exit status ----
    if had_error:
        sys.exit(2)
    sys.exit(0 if found else 1)


if __name__ == "__main__":
    try:
        main()
    except (BrokenPipeError, MemoryError):
        os._exit(2)
    except OSError:
        os._exit(2)
