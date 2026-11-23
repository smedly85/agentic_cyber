#!/usr/bin/env python3
"""py_sort — sort newline-delimited records from stdin in LC_ALL=C bytewise order."""

import sys


def sort_lines(data: bytes) -> bytes:
    """Sort newline-delimited byte records in unsigned lexicographic order.

    Splits *data* on 0x0A, sorts the resulting records (preserving
    duplicates), and re-joins them each terminated by 0x0A.
    Empty input yields empty output.
    """
    if not data:
        return b""
    parts = data.split(b"\n")
    if data.endswith(b"\n"):
        records = parts[:-1]
    else:
        records = parts
    records.sort()
    if not records:
        return b""
    return b"\n".join(records) + b"\n"


def _fail_unrecognized_option(arg: str) -> int:
    """Write GNU-sort-compatible unrecognized-option diagnostic and return exit code."""
    try:
        sys.stderr.write(f"sort: unrecognized option '{arg}'\n")
        sys.stderr.write("Try 'sort --help' for more information.\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    return 2


def _fail_operand(name: str) -> int:
    """Write GNU-sort-compatible cannot-read diagnostic and return exit code."""
    try:
        fh = open(name, "rb")
    except OSError as e:
        msg = e.strerror if e.strerror else str(e)
    else:
        fh.close()
        msg = "Operation not supported"
    try:
        sys.stderr.write(f"sort: cannot read: {name}: {msg}\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    return 2


def main() -> int:
    args = sys.argv[1:]

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            i += 1
            # Everything after -- is an operand (not permitted)
            while i < len(args):
                return _fail_operand(args[i])
            break
        elif arg.startswith("-"):
            return _fail_unrecognized_option(arg)
        else:
            return _fail_operand(arg)
        i += 1

    try:
        data = sys.stdin.buffer.read()
    except (OSError, MemoryError):
        return 2

    try:
        out = sort_lines(data)
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
    except (OSError, MemoryError) as e:
        try:
            sys.stderr.write(f"sort: write error: {e.strerror or 'error'}\n")
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
        return 2

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        try:
            sys.stderr.write("py_sort: internal error\n")
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
        sys.exit(2)
