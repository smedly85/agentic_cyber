#!/usr/bin/env python3
"""py_grep: bounded fixed-string grep (checkpoint 003)."""
import os
import stat
import sys

_FOLD_TABLE = bytes.maketrans(
    bytes(range(0x41, 0x5B)),  # A-Z
    bytes(range(0x61, 0x7B)),  # a-z
)


def search_stream(data: bytes, pattern: bytes, ignore_case: bool = False) -> list[bytes]:
    """Return lines from data that contain pattern as a fixed byte substring.

    Lines are delimited by 0x0A. A final unterminated line is a line.
    An empty pattern matches every line. Empty input yields no lines.
    """
    if not data:
        return []
    parts = data.split(b'\n')
    if parts[-1] == b'':
        parts = parts[:-1]
    if ignore_case:
        pat = pattern.translate(_FOLD_TABLE)
        return [line for line in parts if pat in line.translate(_FOLD_TABLE)]
    return [line for line in parts if pattern in line]


def traverse(base_fs_path: str, base_display: str, pattern: bytes,
             use_prefix: bool, out, state: dict,
             ignore_case: bool = False) -> None:
    """Iterative pre-order DFS of base_fs_path, searching regular files.
    Skips symlinks, descends into subdirectories in ascending raw-byte order.
    state: dict with 'had_error' (bool) and 'found_match' (bool)."""

    def _listdir(path, display_path):
        try:
            entries = os.listdir(path)
        except PermissionError:
            return None, "py_grep: " + display_path + ": Permission denied\n"
        except FileNotFoundError:
            return None, "py_grep: " + display_path + ": No such file or directory\n"
        except MemoryError:
            return None, "py_grep: " + display_path + ": out of memory\n"
        except OSError:
            return None, "py_grep: " + display_path + ": cannot read\n"
        try:
            entries.sort(key=os.fsencode)
        except MemoryError:
            return None, "py_grep: " + display_path + ": out of memory\n"
        return entries, None

    entries, err = _listdir(base_fs_path, base_display)
    if err:
        state['had_error'] = True
        sys.stderr.write(err)
        return

    stack = [(base_fs_path, base_display, iter(entries))]

    while stack:
        fs_dir, disp_dir, it = stack[-1]
        try:
            entry = next(it)
        except StopIteration:
            stack.pop()
            continue

        fs_path = fs_dir + '/' + entry
        disp_path = disp_dir + '/' + entry

        try:
            st = os.lstat(fs_path)
        except OSError:
            continue

        if stat.S_ISLNK(st.st_mode):
            continue
        elif stat.S_ISDIR(st.st_mode):
            sub_entries, sub_err = _listdir(fs_path, disp_path)
            if sub_err:
                state['had_error'] = True
                sys.stderr.write(sub_err)
            else:
                stack.append((fs_path, disp_path, iter(sub_entries)))
        elif stat.S_ISREG(st.st_mode):
            try:
                with open(fs_path, 'rb') as f:
                    data = f.read()
            except (OSError, MemoryError):
                state['had_error'] = True
                sys.stderr.write("py_grep: " + disp_path + ": cannot read\n")
                continue
            matched = search_stream(data, pattern, ignore_case)
            if matched:
                prefix = (os.fsencode(disp_path) + b':') if use_prefix else b''
                for line in matched:
                    out.write(prefix + line + b'\n')
                state['found_match'] = True
        # else: skip (FIFO, socket, device, etc.)


def main() -> int:
    args = sys.argv[1:]
    pattern = None
    files: list[str] = []
    option_ended = False
    prefix_mode = None  # None = default, 'force' = -H, 'suppress' = -h
    recursive = False
    ignore_case = False

    for arg in args:
        if not option_ended:
            if arg == '--':
                option_ended = True
                continue
            if arg.startswith('-') and arg != '-':
                if arg == '--with-filename':
                    prefix_mode = 'force'
                    continue
                if arg == '--no-filename':
                    prefix_mode = 'suppress'
                    continue
                if arg == '--recursive':
                    recursive = True
                    continue
                if arg == '--ignore-case':
                    ignore_case = True
                    continue
                if arg.startswith('--'):
                    sys.stderr.write("py_grep: unsupported option: " + arg + "\n")
                    sys.stderr.write("usage: py_grep PATTERN [FILE...]\n")
                    return 2
                # short-option cluster: every char after the dash must be H or h
                for ch in arg[1:]:
                    if ch == 'H':
                        prefix_mode = 'force'
                    elif ch == 'h':
                        prefix_mode = 'suppress'
                    elif ch == 'r':
                        recursive = True
                    elif ch == 'i':
                        ignore_case = True
                    else:
                        sys.stderr.write("py_grep: unsupported option: " + arg + "\n")
                        sys.stderr.write("usage: py_grep PATTERN [FILE...]\n")
                        return 2
                continue
        if pattern is None:
            pattern = arg
        else:
            files.append(arg)

    if pattern is None:
        sys.stderr.write("py_grep: missing PATTERN\n")
        sys.stderr.write("usage: py_grep PATTERN [FILE...]\n")
        return 2

    pattern_bytes = os.fsencode(pattern)
    if prefix_mode == 'force':
        use_prefix = True
        stdin_use_prefix = True
    elif prefix_mode == 'suppress':
        use_prefix = False
        stdin_use_prefix = False
    else:
        if not files:
            use_prefix = False
            stdin_use_prefix = False
        else:
            any_dir = False
            for f in files:
                try:
                    st = os.stat(os.fsencode(f))
                    if stat.S_ISDIR(st.st_mode):
                        any_dir = True
                        break
                except (OSError, MemoryError):
                    pass
            use_prefix = (len(files) >= 2) or any_dir
            stdin_use_prefix = False
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
            stdin_prefix = b'(standard input):' if stdin_use_prefix else b''
            for line in search_stream(data, pattern_bytes, ignore_case):
                out.write(stdin_prefix + line + b'\n')
                found_match = True
        else:
            state = {'had_error': False, 'found_match': False}
            for fname in files:
                path = os.fsencode(fname)
                try:
                    st = os.stat(path)
                except FileNotFoundError:
                    sys.stderr.write("py_grep: " + fname + ": No such file or directory\n")
                    state['had_error'] = True
                    continue
                except PermissionError:
                    sys.stderr.write("py_grep: " + fname + ": Permission denied\n")
                    state['had_error'] = True
                    continue
                except (OSError, MemoryError):
                    sys.stderr.write("py_grep: " + fname + ": cannot access\n")
                    state['had_error'] = True
                    continue
                if stat.S_ISDIR(st.st_mode):
                    if recursive:
                        base_fs = fname.rstrip('/') or '/'
                        base_disp = fname.rstrip('/') or '/'
                        traverse(base_fs, base_disp, pattern_bytes,
                                 use_prefix, out, state, ignore_case)
                    else:
                        sys.stderr.write("py_grep: " + fname + ": Is a directory\n")
                        state['had_error'] = True
                    continue
                if not stat.S_ISREG(st.st_mode):
                    sys.stderr.write("py_grep: " + fname + ": cannot read\n")
                    state['had_error'] = True
                    continue
                try:
                    with open(path, 'rb') as f:
                        data = f.read()
                except (OSError, MemoryError):
                    sys.stderr.write("py_grep: " + fname + ": cannot read\n")
                    state['had_error'] = True
                    continue
                matched = search_stream(data, pattern_bytes, ignore_case)
                if matched:
                    prefix = (path + b':') if use_prefix else b''
                    for line in matched:
                        out.write(prefix + line + b'\n')
                    state['found_match'] = True
            had_error = state['had_error']
            found_match = state['found_match']
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
