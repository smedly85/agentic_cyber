#!/usr/bin/env python3
"""py_grep: bounded fixed-string grep (checkpoint 000)."""
import os
import stat
import sys


def search_stream(data: bytes, pattern: bytes) -> list[bytes]:
    """Return lines from data that contain pattern as a fixed byte substring.

    Lines are delimited by 0x0A. A final unterminated line is a line.
    An empty pattern matches every line. Empty input yields no lines.
    """
    if not data:
        return []
    parts = data.split(b'\n')
    if parts[-1] == b'':
        parts = parts[:-1]
    return [line for line in parts if pattern in line]


def main() -> int:
    args = sys.argv[1:]
    pattern = None
    files: list[str] = []
    option_ended = False

    for arg in args:
        if not option_ended:
            if arg == '--':
                option_ended = True
                continue
            if arg.startswith('-') and arg != '-':
                sys.stderr.write("py_grep: unsupported option: " + arg + "\n")
                sys.stderr.write("usage: py_grep PATTERN [FILE...]\n")
                return 2
        if pattern is None:
            pattern = arg
        else:
            files.append(arg)

    if pattern is None:
        sys.stderr.write("py_grep: missing PATTERN\n")
        sys.stderr.write("usage: py_grep PATTERN [FILE...]\n")
        return 2

    pattern_bytes = os.fsencode(pattern)
    use_prefix = len(files) >= 2
    had_error = False
    found_match = False
    out = sys.stdout.buffer

    try:
        if not files:
            # No file operands: search standard input
            try:
                data = sys.stdin.buffer.read()
            except (OSError, MemoryError):
                sys.stderr.write("py_grep: error reading stdin\n")
                return 2
            for line in search_stream(data, pattern_bytes):
                out.write(line + b'\n')
                found_match = True
        else:
            for fname in files:
                path = os.fsencode(fname)
                try:
                    st = os.stat(path)
                except FileNotFoundError:
                    sys.stderr.write("py_grep: " + fname + ": No such file or directory\n")
                    had_error = True
                    continue
                except PermissionError:
                    sys.stderr.write("py_grep: " + fname + ": Permission denied\n")
                    had_error = True
                    continue
                except OSError:
                    sys.stderr.write("py_grep: " + fname + ": cannot access\n")
                    had_error = True
                    continue
                if stat.S_ISDIR(st.st_mode):
                    sys.stderr.write("py_grep: " + fname + ": Is a directory\n")
                    had_error = True
                    continue
                try:
                    with open(path, 'rb') as f:
                        data = f.read()
                except (OSError, MemoryError):
                    sys.stderr.write("py_grep: " + fname + ": cannot read\n")
                    had_error = True
                    continue
                matched = search_stream(data, pattern_bytes)
                prefix = (path + b':') if use_prefix else b''
                for line in matched:
                    out.write(prefix + line + b'\n')
                    found_match = True
    except BrokenPipeError:
        return 2
    except (OSError, MemoryError):
        if not had_error:
            sys.stderr.write("py_grep: I/O error\n")
        return 2
    finally:
        try:
            out.flush()
        except (OSError, BrokenPipeError):
            pass

    if had_error:
        return 2
    return 0 if found_match else 1


if __name__ == '__main__':
    sys.exit(main())
