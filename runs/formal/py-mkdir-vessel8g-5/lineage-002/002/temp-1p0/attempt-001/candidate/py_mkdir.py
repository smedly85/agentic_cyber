#!/usr/bin/env python3
"""Create directories (checkpoint 001: parents)."""
import os
import sys


def main():
    args = sys.argv[1:]
    operands = []
    after_ddash = False
    parents = False

    for arg in args:
        if after_ddash:
            operands.append(arg)
        elif arg == '--':
            after_ddash = True
        elif arg == '-p' or arg == '--parents':
            parents = True
        elif arg.startswith('-') and arg != '-':
            if arg.startswith('--'):
                sys.stderr.write(f"mkdir: unrecognized option '{arg}'\n")
            else:
                sys.stderr.write(f"mkdir: invalid option -- '{arg[1]}'\n")
            sys.stderr.write("Try 'mkdir --help' for more information.\n")
            sys.stderr.flush()
            sys.exit(1)
        else:
            operands.append(arg)

    if not operands:
        sys.stderr.write("mkdir: missing operand\n")
        sys.stderr.write("Try 'mkdir --help' for more information.\n")
        sys.stderr.flush()
        sys.exit(1)

    any_failed = False
    for operand in operands:
        try:
            if parents:
                os.makedirs(operand, mode=0o777, exist_ok=True)
            else:
                os.mkdir(operand, 0o777)
        except OSError as e:
            any_failed = True
            strerror = e.strerror or os.strerror(e.errno) or "Unknown error"
            sys.stderr.write(f"mkdir: cannot create directory '{operand}': {strerror}\n")
            sys.stderr.flush()

    sys.exit(0 if not any_failed else 1)


if __name__ == '__main__':
    main()
