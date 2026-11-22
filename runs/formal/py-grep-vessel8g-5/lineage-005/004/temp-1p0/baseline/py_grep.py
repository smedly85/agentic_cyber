#!/usr/bin/env python3
"""Bounded fixed-string byte grep (checkpoint 000)."""
import os
import stat
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


def _diagnose(path, exc):
    """Write a diagnostic for an I/O error on path to stderr."""
    if isinstance(exc, FileNotFoundError):
        msg = "No such file or directory"
    elif isinstance(exc, PermissionError):
        msg = "Permission denied"
    elif isinstance(exc, IsADirectoryError):
        msg = "Is a directory"
    else:
        msg = exc.strerror if exc.strerror else 'I/O error'
    sys.stderr.write(f"py_grep: {path}: {msg}\n")


def _recursive_traverse(dir_path, pattern, outfile, prefix_enabled):
    """Iterative pre-order DFS. Returns (matched, had_error)."""
    matched = 0
    had_error = False
    stack = [('dir', dir_path)]
    while stack:
        kind, path = stack.pop()
        if kind == 'file':
            prefix = os.fsencode(path) + b':' if prefix_enabled else b''
            try:
                with open(path, 'rb') as f:
                    matched += search_stream(pattern, f, outfile, prefix)
            except OSError as e:
                _diagnose(path, e)
                had_error = True
        elif kind == 'dir':
            try:
                entries = os.listdir(path)
            except OSError as e:
                _diagnose(path, e)
                had_error = True
                continue
            entries.sort(key=lambda name: os.fsencode(name))
            actions = []
            for name in entries:
                child = os.path.join(path, name)
                try:
                    st = os.lstat(child)
                except OSError:
                    continue
                if stat.S_ISLNK(st.st_mode):
                    continue
                elif stat.S_ISDIR(st.st_mode):
                    actions.append(('dir', child))
                elif stat.S_ISREG(st.st_mode):
                    actions.append(('file', child))
            for action in reversed(actions):
                stack.append(action)
    return matched, had_error


def main() -> int:
    args = sys.argv[1:]
    pattern_str = None
    files: list = []
    after_ddash = False
    filename_override = None  # None=default, True=-H, False=-h
    recursive = False

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
                    elif arg == '--recursive':
                        recursive = True
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
                        elif ch == 'r':
                            recursive = True
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
        needs_prefix = False
        if files:
            if any(os.path.isdir(f) for f in files):
                needs_prefix = True
            elif len(files) >= 2:
                needs_prefix = True

    try:
        if not files:
            stdin_prefix = b'(standard input):' if filename_override is True else b''
            total_matched = search_stream(pattern, sys.stdin.buffer, outfile, stdin_prefix)
        else:
            for path in files:
                try:
                    st = os.lstat(path)
                except OSError as e:
                    _diagnose(path, e)
                    had_error = True
                    continue

                if stat.S_ISLNK(st.st_mode):
                    try:
                        st = os.stat(path)
                    except OSError as e:
                        _diagnose(path, e)
                        had_error = True
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        if recursive:
                            m, err = _recursive_traverse(path, pattern, outfile, needs_prefix)
                            total_matched += m
                            had_error = had_error or err
                        else:
                            sys.stderr.write(f"py_grep: {path}: Is a directory\n")
                            had_error = True
                    elif stat.S_ISREG(st.st_mode):
                        prefix = os.fsencode(path) + b':' if needs_prefix else b''
                        try:
                            with open(path, 'rb') as f:
                                total_matched += search_stream(pattern, f, outfile, prefix)
                        except OSError as e:
                            _diagnose(path, e)
                            had_error = True
                    else:
                        sys.stderr.write(f"py_grep: {path}: Is a directory\n")
                        had_error = True
                elif stat.S_ISDIR(st.st_mode):
                    if recursive:
                        m, err = _recursive_traverse(path, pattern, outfile, needs_prefix)
                        total_matched += m
                        had_error = had_error or err
                    else:
                        sys.stderr.write(f"py_grep: {path}: Is a directory\n")
                        had_error = True
                elif stat.S_ISREG(st.st_mode):
                    prefix = os.fsencode(path) + b':' if needs_prefix else b''
                    try:
                        with open(path, 'rb') as f:
                            total_matched += search_stream(pattern, f, outfile, prefix)
                    except OSError as e:
                        _diagnose(path, e)
                        had_error = True
                else:
                    prefix = os.fsencode(path) + b':' if needs_prefix else b''
                    try:
                        with open(path, 'rb') as f:
                            total_matched += search_stream(pattern, f, outfile, prefix)
                    except OSError as e:
                        _diagnose(path, e)
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
