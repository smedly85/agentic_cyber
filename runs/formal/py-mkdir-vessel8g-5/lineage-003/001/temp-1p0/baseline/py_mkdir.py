#!/usr/bin/env python3
"""Create directories (mkdir base functionality)."""

import os
import sys


def _stderr(data: bytes) -> None:
    os.write(2, data)


def main() -> None:
    argv = sys.argv[1:]

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
