#!/usr/bin/env python3
"""Bounded fixed-string byte grep (checkpoint 000)."""
import os
import sys


def search_stream(pattern: bytes, stream, outfile, prefix: bytes) -> int:
    """Read newline-delimited lines from stream; write each line containing
    pattern to outfile (with prefix), normalized to end with a single newline.
    Returns the number of lines emitted."""
    count = 0
    while True:
        line = stream.readline()
        if not line:
            break
        if pattern in line:
            if not line.endswith(b'\n'):
                line += b'\n'
            outfile.write(prefix + line)
            count += 1
    return count


def main() -> int:
    args = sys.argv[1:]
    pattern_str = None
    files: list = []
    after_ddash = False
    filename_override = None  # None=default, True=-H, False=-h

    for arg in args:
        if not after_ddash:
            if arg == '--':
                after_ddash = True
                continue
            if arg.startswith('-') and len(arg) > 1:
                if arg.startswith('--'):
                    if arg == '--with-filename':
                        filename_override = True
                    elif arg == '--no-filename':
                        filename_override = False
                    else:
                        sys.stderr.write(f"py_grep: unsupported option: {arg}\n")
                        sys.stderr.write("usage: py_grep PATTERN [FILE...]\n")
                        return 2
                else:
                    for ch in arg[1:]:
                        if ch == 'H':
                            filename_override = True
                        elif ch == 'h':
                            filename_override = False
                        else:
                            sys.stderr.write(f"py_grep: unsupported option: -{ch}\n")
                            sys.stderr.write("usage: py_grep PATTERN [FILE...]\n")
                            return 2
                continue
        if pattern_str is None:
            pattern_str = arg
        else:
            files.append(arg)

    if pattern_str is None:
        sys.stderr.write("py_grep: missing PATTERN\n")
        sys.stderr.write("usage: py_grep PATTERN [FILE...]\n")
        return 2

    pattern = os.fsencode(pattern_str)
    total_matched = 0
    had_error = False
    outfile = sys.stdout.buffer

    if filename_override is True:
        needs_prefix = True
    elif filename_override is False:
        needs_prefix = False
    else:
        needs_prefix = len(files) >= 2

    try:
        if not files:
            stdin_prefix = b'(standard input):' if filename_override is True else b''
            total_matched = search_stream(pattern, sys.stdin.buffer, outfile, stdin_prefix)
        else:
            for path in files:
                prefix = os.fsencode(path) + b':' if needs_prefix else b''
                try:
                    with open(path, 'rb') as f:
                        total_matched += search_stream(pattern, f, outfile, prefix)
                except IsADirectoryError:
                    sys.stderr.write(f"py_grep: {path}: Is a directory\n")
                    had_error = True
                except FileNotFoundError:
                    sys.stderr.write(f"py_grep: {path}: No such file or directory\n")
                    had_error = True
                except PermissionError:
                    sys.stderr.write(f"py_grep: {path}: Permission denied\n")
                    had_error = True
                except OSError as e:
                    reason = e.strerror if e.strerror else 'I/O error'
                    sys.stderr.write(f"py_grep: {path}: {reason}\n")
                    had_error = True
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        had_error = True
    except MemoryError:
        sys.stderr.write("py_grep: out of memory\n")
        had_error = True
    except OSError as e:
        reason = e.strerror if e.strerror else 'I/O error'
        sys.stderr.write(f"py_grep: {reason}\n")
        had_error = True

    if had_error:
        return 2
    return 0 if total_matched > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
