#!/usr/bin/env python3
"""Bounded fixed-string grep: search lines for a byte substring."""

import os
import sys


def search_stream(stream, pattern):
    """Read a binary stream, yielding each 0x0A-delimited line (without the
    delimiter) that contains *pattern*.  An empty pattern matches every line.
    A final unterminated line (no trailing 0x0A) is still a line."""
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
            if pattern in line:
                yield line
    if buf:
        if pattern in buf:
            yield buf


def _diagnostic(msg: str) -> None:
    sys.stderr.buffer.write(msg.encode("utf-8", "replace"))
    sys.stderr.buffer.flush()


def main() -> None:
    args = sys.argv[1:]
    i = 0
    pattern_str = None
    no_more_options = False
    with_filename = False
    files: list[str] = []

    while i < len(args):
        token = args[i]
        if not no_more_options and token.startswith("-") and len(token) > 1:
            if token == "--":
                no_more_options = True
            elif token.startswith("--"):
                if token == "--with-filename":
                    with_filename = True
                else:
                    _diagnostic(
                        f"py_grep: unrecognized option '{token}'\n"
                        "Usage: py_grep PATTERN [FILE...]\n"
                    )
                    sys.exit(2)
            else:
                for ch in token[1:]:
                    if ch != "H":
                        _diagnostic(
                            f"py_grep: unrecognized option '{token}'\n"
                            "Usage: py_grep PATTERN [FILE...]\n"
                        )
                        sys.exit(2)
                with_filename = True
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
    prefix = (len(files) >= 2) or with_filename
    out = sys.stdout.buffer
    stdin_name = b"(standard input)"

    if not files:
        for line in search_stream(sys.stdin.buffer, pattern):
            if with_filename:
                out.write(stdin_name + b":" + line + b"\n")
            else:
                out.write(line + b"\n")
            matched = True
    else:
        for name in files:
            path = os.fsencode(name)
            try:
                if os.path.isdir(path):
                    _diagnostic(f"py_grep: {name}: Is a directory\n")
                    had_error = True
                    continue
                with open(path, "rb") as fh:
                    for line in search_stream(fh, pattern):
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
