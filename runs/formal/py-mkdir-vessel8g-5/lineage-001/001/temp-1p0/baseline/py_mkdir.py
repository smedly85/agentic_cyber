#!/usr/bin/env python3
"""mkdir: Create directories (checkpoint 000 base)."""

import os
import sys


def _fail(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.write("Try 'mkdir --help' for more information.\n")
    sys.exit(1)


def main() -> None:
    argv = sys.argv[1:]

    # ---- parse arguments (all before any mutation) ----
    operands: list[str] = []
    seen_ddash = False
    unknown_opt: str | None = None

    for arg in argv:
        if seen_ddash:
            operands.append(arg)
        elif arg == "--":
            seen_ddash = True
        elif arg == "-":
            operands.append(arg)
        elif arg.startswith("-"):
            if unknown_opt is None:
                unknown_opt = arg
        else:
            operands.append(arg)

    if unknown_opt is not None:
        opt = unknown_opt
        if opt.startswith("--"):
            _fail(f"mkdir: unrecognized option '{opt}'")
        else:
            ch = opt[1] if len(opt) > 1 else ""
            _fail(f"mkdir: invalid option -- '{ch}'")

    if not operands:
        _fail("mkdir: missing operand")

    # ---- create directories ----
    all_ok = True
    for operand in operands:
        path = os.fsencode(operand)
        try:
            os.mkdir(path)
        except FileExistsError:
            sys.stderr.write(
                f"mkdir: cannot create directory '{operand}': File exists\n")
            all_ok = False
        except FileNotFoundError:
            sys.stderr.write(
                f"mkdir: cannot create directory '{operand}': "
                f"No such file or directory\n")
            all_ok = False
        except NotADirectoryError:
            sys.stderr.write(
                f"mkdir: cannot create directory '{operand}': "
                f"Not a directory\n")
            all_ok = False
        except PermissionError:
            sys.stderr.write(
                f"mkdir: cannot create directory '{operand}': "
                f"Permission denied\n")
            all_ok = False
        except OSError as e:
            strerror = e.strerror or "error"
            sys.stderr.write(
                f"mkdir: cannot create directory '{operand}': {strerror}\n")
            all_ok = False

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
