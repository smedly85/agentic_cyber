#!/usr/bin/env python3
"""Create directories (mkdir base functionality)."""

import os
import stat
import sys


def _stderr(data: bytes) -> None:
    os.write(2, data)


def _ensure_intermediate(prefix: bytes) -> None:
    if os.path.lexists(prefix):
        if not os.path.isdir(prefix):
            raise NotADirectoryError(prefix)
        return
    os.mkdir(prefix, 0o777)
    st = os.lstat(prefix)
    os.chmod(prefix, stat.S_IMODE(st.st_mode) | 0o700)


def _ensure_final(path: bytes) -> None:
    if os.path.lexists(path):
        if not os.path.isdir(path):
            raise FileExistsError(path)
        return
    os.mkdir(path, 0o777)


def _create_parents(path: bytes) -> None:
    normalized = os.path.normpath(path)
    parts = [p for p in normalized.split(b'/') if p not in (b'', b'.')]
    if len(parts) <= 1:
        return
    prefix = b''
    for comp in parts[:-1]:
        if not prefix:
            prefix = comp
        else:
            prefix = prefix + b'/' + comp
        _ensure_intermediate(prefix)


def main() -> None:
    argv = sys.argv[1:]

    parents = False
    operands: list[str] = []
    saw_terminator = False
    first_error: bytes | None = None

    for arg in argv:
        if saw_terminator:
            operands.append(arg)
        elif arg == '--':
            saw_terminator = True
        elif arg == '-':
            operands.append(arg)
        elif arg == '-p' or arg == '--parents':
            parents = True
        elif arg.startswith('--'):
            first_error = (
                b"mkdir: unrecognized option '"
                + os.fsencode(arg)
                + b"'\nTry 'mkdir --help' for more information.\n"
            )
            break
        elif arg.startswith('-'):
            first_error = (
                b"mkdir: invalid option -- '"
                + os.fsencode(arg[1])
                + b"'\nTry 'mkdir --help' for more information.\n"
            )
            break
        else:
            operands.append(arg)

    if first_error is not None:
        _stderr(first_error)
        sys.exit(1)

    if not operands:
        _stderr(b"mkdir: missing operand\nTry 'mkdir --help' for more information.\n")
        sys.exit(1)

    any_failed = False
    for operand in operands:
        path = os.fsencode(operand)
        try:
            if parents:
                _create_parents(path)
                _ensure_final(path)
            else:
                os.mkdir(path, 0o777)
        except OSError as e:
            if e.errno is not None:
                err_str = os.strerror(e.errno).encode('utf-8')
            else:
                err_str = b"Unknown error"
            msg = (
                b"mkdir: cannot create directory '"
                + os.fsencode(operand)
                + b"': "
                + err_str
                + b"\n"
            )
            _stderr(msg)
            any_failed = True

    sys.exit(1 if any_failed else 0)


if __name__ == '__main__':
    main()
