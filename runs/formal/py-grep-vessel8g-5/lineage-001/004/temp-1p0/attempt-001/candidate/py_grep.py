#!/usr/bin/env python3
"""Bounded fixed-string grep: search lines for a byte substring."""

import os
import stat
import sys

_ASCII_FOLD_TABLE = bytes.maketrans(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    b"abcdefghijklmnopqrstuvwxyz",
)


def _ascii_fold(data: bytes) -> bytes:
    """Fold ASCII A-Z to a-z; all other bytes (including >= 0x80) unchanged."""
    return data.translate(_ASCII_FOLD_TABLE)


def search_stream(stream, pattern, ignore_case=False):
    """Read a binary stream, yielding each 0x0A-delimited line (without the
    delimiter) that contains *pattern*.  An empty pattern matches every line.
    A final unterminated line (no trailing 0x0A) is still a line."""
    if ignore_case:
        folded_pattern = _ascii_fold(pattern)
    else:
        folded_pattern = None

    buf = b""
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            idx = buf.index(b"\n")
            line = buf[:idx]
            buf = buf[idx + 1:]
            if (folded_pattern in _ascii_fold(line)) if ignore_case else (pattern in line):
                yield line
    if buf:
        if (folded_pattern in _ascii_fold(buf)) if ignore_case else (pattern in buf):
            yield buf


def _diagnostic(msg: str) -> None:
    sys.stderr.buffer.write(msg.encode("utf-8", "replace"))
    sys.stderr.buffer.flush()


def _join_path(base: bytes, rel: bytes) -> bytes:
    if not rel:
        return base
    if not base:
        return rel
    if base.endswith(b"/"):
        return base + rel
    return base + b"/" + rel


def _recursive_traverse(
    base: bytes, pattern: bytes, out, prefix: bool, ignore_case: bool = False
) -> tuple[bool, bool]:
    """Iterative pre-order DFS over base.  Returns (any_matched, any_error)."""
    any_matched = False
    any_error = False
    stack: list[bytes] = [base]
    while stack:
        path = stack.pop()
        try:
            st = os.lstat(path)
        except (OSError, MemoryError):
            continue
        if stat.S_ISLNK(st.st_mode):
            continue
        elif stat.S_ISDIR(st.st_mode):
            try:
                entries = os.listdir(path)
            except MemoryError:
                any_error = True
                _diagnostic(
                    f"py_grep: {path.decode('utf-8', 'replace')}: Memory error\n"
                )
                continue
            except OSError as exc:
                any_error = True
                reason = getattr(exc, "strerror", None) or str(exc)
                _diagnostic(
                    f"py_grep: {path.decode('utf-8', 'replace')}: {reason}\n"
                )
                continue
            entries.sort()
            for entry in reversed(entries):
                stack.append(_join_path(path, entry))
        elif stat.S_ISREG(st.st_mode):
            try:
                with open(path, "rb") as fh:
                    for line in search_stream(fh, pattern, ignore_case):
                        if prefix:
                            out.write(path + b":" + line + b"\n")
                        else:
                            out.write(line + b"\n")
                        any_matched = True
            except PermissionError:
                any_error = True
                _diagnostic(
                    f"py_grep: {path.decode('utf-8', 'replace')}: Permission denied\n"
                )
            except MemoryError:
                any_error = True
                _diagnostic(
                    f"py_grep: {path.decode('utf-8', 'replace')}: Memory error\n"
                )
            except OSError as exc:
                any_error = True
                reason = getattr(exc, "strerror", None) or str(exc)
                _diagnostic(
                    f"py_grep: {path.decode('utf-8', 'replace')}: {reason}\n"
                )
        # else: skip (fifo, socket, device, etc.)
    return any_matched, any_error


def main() -> None:
    args = sys.argv[1:]
    i = 0
    pattern_str = None
    no_more_options = False
    show_filename = None
    recursive = False
    ignore_case = False
    files: list[str] = []

    while i < len(args):
        token = args[i]
        if not no_more_options and token.startswith("-") and len(token) > 1:
            if token == "--":
                no_more_options = True
            elif token.startswith("--"):
                if token == "--with-filename":
                    show_filename = True
                elif token == "--no-filename":
                    show_filename = False
                elif token == "--recursive":
                    recursive = True
                elif token == "--ignore-case":
                    ignore_case = True
                else:
                    _diagnostic(
                        f"py_grep: unrecognized option '{token}'\n"
                        "Usage: py_grep PATTERN [FILE...]\n"
                    )
                    sys.exit(2)
            else:
                for ch in token[1:]:
                    if ch == "H":
                        show_filename = True
                    elif ch == "h":
                        show_filename = False
                    elif ch == "r":
                        recursive = True
                    elif ch == "i":
                        ignore_case = True
                    else:
                        _diagnostic(
                            f"py_grep: unrecognized option '{token}'\n"
                            "Usage: py_grep PATTERN [FILE...]\n"
                        )
                        sys.exit(2)
        else:
            if pattern_str is None:
                pattern_str = token
            else:
                files.append(token)
        i += 1

    if pattern_str is None:
        _diagnostic("py_grep: no PATTERN supplied\n"
                    "Usage: py_grep PATTERN [FILE...]\n")
        sys.exit(2)

    pattern = os.fsencode(pattern_str)
    matched = False
    had_error = False

    if show_filename is True:
        prefix = True
    elif show_filename is False:
        prefix = False
    else:
        if recursive and files:
            has_dir = any(
                os.path.isdir(os.fsencode(f)) for f in files
            )
            prefix = (len(files) >= 2) or has_dir
        else:
            prefix = (len(files) >= 2)

    out = sys.stdout.buffer
    stdin_name = b"(standard input)"

    if not files:
        for line in search_stream(sys.stdin.buffer, pattern, ignore_case):
            if prefix:
                out.write(stdin_name + b":" + line + b"\n")
            else:
                out.write(line + b"\n")
            matched = True
    else:
        for name in files:
            path = os.fsencode(name)
            if os.path.isdir(path) and recursive:
                m, e = _recursive_traverse(path, pattern, out, prefix, ignore_case)
                if m:
                    matched = True
                if e:
                    had_error = True
                continue
            try:
                if os.path.isdir(path):
                    _diagnostic(f"py_grep: {name}: Is a directory\n")
                    had_error = True
                    continue
                with open(path, "rb") as fh:
                    for line in search_stream(fh, pattern, ignore_case):
                        if prefix:
                            out.write(path + b":" + line + b"\n")
                        else:
                            out.write(line + b"\n")
                        matched = True
            except PermissionError:
                _diagnostic(f"py_grep: {name}: Permission denied\n")
                had_error = True
            except FileNotFoundError:
                _diagnostic(f"py_grep: {name}: No such file or directory\n")
                had_error = True
            except (OSError, MemoryError) as exc:
                reason = getattr(exc, "strerror", None) or str(exc)
                _diagnostic(f"py_grep: {name}: {reason}\n")
                had_error = True

    out.flush()

    if had_error:
        sys.exit(2)
    sys.exit(0 if matched else 1)


if __name__ == "__main__":
    try:
        main()
    except (OSError, MemoryError) as exc:
        reason = getattr(exc, "strerror", None) or str(exc)
        try:
            sys.stderr.buffer.write(f"py_grep: {reason}\n".encode("utf-8", "replace"))
            sys.stderr.buffer.flush()
        except Exception:
            pass
        sys.exit(2)
    except Exception as exc:
        try:
            sys.stderr.buffer.write(
                f"py_grep: internal error: {exc}\n".encode("utf-8", "replace")
            )
            sys.stderr.buffer.flush()
        except Exception:
            pass
        sys.exit(2)
