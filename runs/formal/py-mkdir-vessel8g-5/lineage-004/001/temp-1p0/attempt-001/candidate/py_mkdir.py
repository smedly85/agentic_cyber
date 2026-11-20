#!/usr/bin/env python3
"""Create directories."""

import errno
import os
import stat
import sys


def _fail(path, msg):
    print(f"mkdir: cannot create directory '{path}': {msg}", file=sys.stderr)


def mkdir_plain(path):
    """Create a single directory (no parent creation). Returns 0 or 1."""
    try:
        os.mkdir(path, 0o777)
    except OSError as e:
        msg = e.strerror if e.strerror else os.strerror(e.errno)
        _fail(path, msg)
        return 1
    return 0


def mkdir_parents(path):
    """Create path and all missing parent directories. Returns 0 or 1."""
    is_abs = os.path.isabs(path)
    parts = [p for p in path.split('/') if p and p != '.']

    if not parts:
        return 0

    current = ''
    last = len(parts) - 1
    for i, part in enumerate(parts):
        if current == '':
            current = ('/' if is_abs else '') + part
        else:
            current = current + '/' + part

        try:
            st = os.lstat(current)
        except OSError:
            try:
                os.mkdir(current, 0o777)
            except OSError as e:
                msg = e.strerror if e.strerror else os.strerror(e.errno)
                _fail(path, msg)
                return 1
            if i != last:
                try:
                    mode = os.stat(current).st_mode & 0o7777
                    if not (mode & 0o300):
                        os.chmod(current, mode | 0o300)
                except OSError:
                    pass
            continue

        if stat.S_ISDIR(st.st_mode):
            continue
        if stat.S_ISLNK(st.st_mode):
            try:
                if stat.S_ISDIR(os.stat(current).st_mode):
                    continue
            except OSError:
                pass
        _fail(path, "Not a directory")
        return 1

    return 0


def main():
    args = sys.argv[1:]
    operands = []
    seen_ddash = False
    parents = False
    parse_error = None

    for arg in args:
        if not seen_ddash:
            if arg == '--':
                seen_ddash = True
            elif arg == '-p':
                parents = True
            elif arg == '--parents':
                parents = True
            elif arg == '-':
                operands.append(arg)
            elif arg.startswith('-'):
                if arg.startswith('--') and len(arg) > 2:
                    parse_error = f"mkdir: unrecognized option '{arg}'"
                else:
                    parse_error = f"mkdir: invalid option -- '{arg[1]}'"
                break
            else:
                operands.append(arg)
        else:
            operands.append(arg)

    if parse_error is not None:
        print(parse_error, file=sys.stderr)
        print("Try 'mkdir --help' for more information.", file=sys.stderr)
        sys.exit(1)

    if not operands:
        print("mkdir: missing operand", file=sys.stderr)
        print("Try 'mkdir --help' for more information.", file=sys.stderr)
        sys.exit(1)

    exit_code = 0
    for operand in operands:
        if parents:
            rc = mkdir_parents(operand)
        else:
            rc = mkdir_plain(operand)
        if rc != 0:
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
