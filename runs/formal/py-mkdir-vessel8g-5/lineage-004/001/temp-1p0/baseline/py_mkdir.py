#!/usr/bin/env python3
"""Create directories."""

import os
import sys


def main():
    args = sys.argv[1:]
    operands = []
    seen_ddash = False
    error = None

    for arg in args:
        if not seen_ddash:
            if arg == '--':
                seen_ddash = True
            elif arg == '-':
                operands.append(arg)
            elif arg.startswith('-'):
                if arg.startswith('--') and len(arg) > 2:
                    error = f"mkdir: unrecognized option '{arg}'"
                else:
                    error = f"mkdir: invalid option -- '{arg[1]}'"
                break
            else:
                operands.append(arg)
        else:
            operands.append(arg)

    if error is not None:
        print(error, file=sys.stderr)
        print("Try 'mkdir --help' for more information.", file=sys.stderr)
        sys.exit(1)

    if not operands:
        print("mkdir: missing operand", file=sys.stderr)
        print("Try 'mkdir --help' for more information.", file=sys.stderr)
        sys.exit(1)

    exit_code = 0
    for operand in operands:
        try:
            os.mkdir(operand)
        except OSError as e:
            err_str = e.strerror if e.strerror else str(e)
            print(f"mkdir: cannot create directory '{operand}': {err_str}", file=sys.stderr)
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
