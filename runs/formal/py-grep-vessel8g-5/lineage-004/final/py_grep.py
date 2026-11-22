#!/usr/bin/env python3
"""py_grep — bounded fixed-byte-substring line matcher (checkpoint 000)."""

import os
import sys


def search_stream(data: bytes, pattern: bytes, ignore_case: bool = False) -> list[bytes]:
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
    if ignore_case:
        pat = _fold_ascii(pattern)
        return [p for p in parts if pat in _fold_ascii(p)]
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


def _join_path(base: str, name: str) -> str:
    """Join a directory path and entry name, avoiding doubled separators."""
    if base == "/":
        return "/" + name
    if base.endswith("/"):
        return base + name
    return base + "/" + name


_ASCII_FOLD = bytes.maketrans(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ", b"abcdefghijklmnopqrstuvwxyz")


def _fold_ascii(data: bytes) -> bytes:
    return data.translate(_ASCII_FOLD)


def _traverse(dirpath: str, pattern: bytes, need_prefix: bool, ignore_case: bool = False) -> tuple[bool, bool]:
    """Pre-order traversal: entries in ascending raw-byte order.
    Searches regular files, descends into directories, skips symlinks.
    Returns (found_any, had_error)."""
    found = False
    had_error = False

    try:
        entries = os.listdir(dirpath)
    except OSError as e:
        _diagnose(dirpath, e)
        return False, True

    entries.sort(key=os.fsencode)

    for name in entries:
        full = _join_path(dirpath, name)
        try:
            if os.path.islink(full):
                continue
            if os.path.isdir(full):
                f, e = _traverse(full, pattern, need_prefix, ignore_case)
                found = found or f
                had_error = had_error or e
            elif os.path.isfile(full):
                try:
                    with open(full, "rb") as fh:
                        data = fh.read()
                except MemoryError:
                    raise
                except OSError as e:
                    _diagnose(full, e)
                    had_error = True
                    continue
                lines = search_stream(data, pattern, ignore_case)
                if lines:
                    prefix = os.fsencode(full) + b":" if need_prefix else b""
                    _write_lines(lines, prefix)
                    found = True
        except OSError:
            continue
    return found, had_error


def main() -> None:
    argv = sys.argv[1:]

    # ---- argument parsing ----
    i = 0
    pattern: bytes | None = None
    files: list[str] = []
    no_options = False
    filename_mode: bool | None = None
    recursive: bool = False
    ignore_case: bool = False

    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            no_options = True
            i += 1
            continue
        if not no_options and arg.startswith("-") and len(arg) > 1:
            if arg == "--with-filename":
                filename_mode = True
                i += 1
                continue
            if arg == "--no-filename":
                filename_mode = False
                i += 1
                continue
            if arg == "--recursive":
                recursive = True
                i += 1
                continue
            if arg == "--ignore-case":
                ignore_case = True
                i += 1
                continue
            # short option (possibly clustered)
            if arg.startswith("--"):
                _usage_error(b"py_grep: unsupported option: " + os.fsencode(arg))
            cluster = arg[1:]  # strip leading '-'
            for ch in cluster:
                if ch == "H":
                    filename_mode = True
                elif ch == "h":
                    filename_mode = False
                elif ch == "r":
                    recursive = True
                elif ch == "i":
                    ignore_case = True
                else:
                    _usage_error(b"py_grep: unsupported option: " + os.fsencode("-" + ch))
            i += 1
            continue
        if pattern is None:
            pattern = os.fsencode(arg)
        else:
            files.append(arg)
        i += 1

    if pattern is None:
        _usage_error(b"py_grep: missing PATTERN")

    if filename_mode is True:
        need_prefix = True
    elif filename_mode is False:
        need_prefix = False
    else:
        any_dir = any(os.path.isdir(f) for f in files) if recursive else False
        need_prefix = len(files) >= 2 or any_dir

    found = False
    had_error = False

    # ---- search ----
    if not files:
        data = sys.stdin.buffer.read()
        lines = search_stream(data, pattern, ignore_case)
        if lines:
            prefix = b"(standard input):" if need_prefix else b""
            _write_lines(lines, prefix)
            found = True
    else:
        for fname in files:
            if recursive and os.path.isdir(fname):
                try:
                    f, e = _traverse(fname, pattern, need_prefix, ignore_case)
                except RecursionError:
                    _diagnose(fname, OSError("Maximum recursion depth exceeded"))
                    e = True
                found = found or f
                had_error = had_error or e
                continue
            try:
                with open(fname, "rb") as f:
                    data = f.read()
            except MemoryError:
                sys.exit(2)
            except OSError as e:
                _diagnose(fname, e)
                had_error = True
                continue
            lines = search_stream(data, pattern, ignore_case)
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
