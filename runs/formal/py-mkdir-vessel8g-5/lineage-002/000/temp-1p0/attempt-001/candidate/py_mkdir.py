#!/usr/bin/env python3
"""Create directories (checkpoint 000: base)."""
import os
import sys


def main():
    args = sys.argv[1:]
    operands = []
    after_ddash = False

    for arg in args:
        if not after_ddash:
            if arg == '--':
                after_ddash = True
            elif arg.startswith('-') and len(arg) > 1:
                if arg.startswith('--'):
                    sys.stderr.write(f"mkdir: unrecognized option '{arg}'\n")
                else:
                    sys.stderr.write(f"mkdir: invalid option -- '{arg[1]}'\n")
                sys.stderr.write("Try 'mkdir --help' for more information.\n")
                sys.exit(1)
            else:
                operands.append(arg)
        else:
            operands.append(arg)

    if not operands:
        sys.stderr.write("mkdir: missing operand\n")
        sys.stderr.write("Try 'mkdir --help' for more information.\n")
        sys.exit(1)

    any_failed = False
    for operand in operands:
        try:
            os.mkdir(operand, 0o777)
        except OSError as e:
            any_failed = True
            msg = e.strerror or os.strerror(e.errno) or "Unknown error"
            sys.stderr.write(
                f"mkdir: cannot create directory '{operand}': {msg}\n"
            )
        except MemoryError:
            any_failed = True
            sys.stderr.write(
                f"mkdir: cannot create directory '{operand}': Cannot allocate memory\n"
            )
        except Exception as e:
            any_failed = True
            sys.stderr.write(
                f"mkdir: cannot create directory '{operand}': {e}\n"
            )

    sys.exit(1 if any_failed else 0)


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(1)
