#!/usr/bin/env python3
"""py_sort — sort newline-delimited byte records from stdin in C-locale order."""

import sys


def sort_lines(data: bytes, reverse: bool = False) -> bytes:
    """Sort newline-separated byte records in unsigned bytewise lexicographic
    ascending order, preserving duplicates.

    - Records may contain NUL bytes, be empty, or be any arbitrary byte string.
    - Empty input produces empty output.
    - A final nonempty unterminated record (no trailing newline) is still a record.
    - Every output record is followed by a newline byte.
    """
    if not data:
        return b""

    records = data.split(b"\n")
    if data.endswith(b"\n"):
        records = records[:-1]

    if not records:
        return b""

    records.sort(reverse=reverse)
    return b"\n".join(records) + b"\n"


def main() -> int:
    args = sys.argv[1:]

    reverse = False
    past_options = False
    for arg in args:
        if past_options:
            sys.stderr.write(
                f"sort: cannot read: {arg}: No such file or directory\n"
            )
            return 2

        if arg == "--":
            past_options = True
            continue

        if arg.startswith("--") and len(arg) > 2:
            if arg == "--reverse":
                reverse = True
                continue
            sys.stderr.write(
                f"sort: unrecognized option '{arg}'\n"
                "Try 'sort --help' for more information.\n"
            )
            return 2

        if arg.startswith("-") and len(arg) > 1:
            for ch in arg[1:]:
                if ch == 'r':
                    reverse = True
                else:
                    sys.stderr.write(
                        f"sort: unrecognized option '{ch}'\n"
                        "Try 'sort --help' for more information.\n"
                    )
                    return 2
            continue

        sys.stderr.write(
            f"sort: cannot read: {arg}: No such file or directory\n"
        )
        return 2

    try:
        data = sys.stdin.buffer.read()
    except (OSError, MemoryError) as exc:
        sys.stderr.write(f"sort: {exc}\n")
        return 2

    try:
        result = sort_lines(data, reverse=reverse)
    except MemoryError:
        sys.stderr.write("sort: out of memory\n")
        return 2

    try:
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
    except (OSError, MemoryError) as exc:
        sys.stderr.write(f"sort: {exc}\n")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
