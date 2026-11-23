#!/usr/bin/env python3
"""py_sort — sort newline-delimited records from stdin in LC_ALL=C bytewise order."""

import sys


def sort_lines(data: bytes, reverse: bool = False, ignore_case: bool = False, unique: bool = False) -> bytes:
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
    if not records:
        return b""
    if unique:
        seen = set()
        deduped = []
        for r in records:
            key = _fold_case(r) if ignore_case else r
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        records = deduped
    if ignore_case:
        records.sort(key=lambda r: (_fold_case(r), r), reverse=reverse)
    else:
        records.sort(reverse=reverse)
    return b"\n".join(records) + b"\n"


def _fold_case(record: bytes) -> bytes:
    """Fold ASCII uppercase to lowercase for case-insensitive comparison."""
    return bytes(b + 0x20 if 0x41 <= b <= 0x5A else b for b in record)


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

    reverse = False
    ignore_case = False
    unique = False
    end_of_options = False
    i = 0
    while i < len(args):
        arg = args[i]
        if end_of_options:
            return _fail_operand(arg)
        if arg == "--":
            end_of_options = True
            i += 1
            continue
        if arg.startswith("--"):
            if arg == "--reverse":
                reverse = True
            elif arg == "--ignore-case":
                ignore_case = True
            elif arg == "--unique":
                unique = True
            else:
                return _fail_unrecognized_option(arg)
        elif arg.startswith("-") and len(arg) > 1:
            for ch in arg[1:]:
                if ch == "r":
                    reverse = True
                elif ch == "f":
                    ignore_case = True
                elif ch == "u":
                    unique = True
                else:
                    return _fail_unrecognized_option(arg)
        else:
            return _fail_operand(arg)
        i += 1

    try:
        data = sys.stdin.buffer.read()
    except (OSError, MemoryError):
        return 2

    try:
        out = sort_lines(data, reverse=reverse, ignore_case=ignore_case, unique=unique)
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
