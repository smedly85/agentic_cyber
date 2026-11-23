#!/usr/bin/env python3
"""py_sort: sort newline-delimited records from stdin in unsigned bytewise
lexicographic ascending order (LC_ALL=C semantics)."""
import sys


def sort_lines(data: bytes) -> bytes:
    """Split data into newline-delimited records, sort them in unsigned
    bytewise ascending order, and return the re-serialized output.

    - Empty input yields empty output.
    - A trailing newline in input does NOT produce an extra empty record.
    - Every output record is terminated by a newline.
    """
    if not data:
        return b""
    parts = data.split(b"\n")
    # A final newline means the last split element is an empty artifact;
    # remove it so "a\nb\n" gives [a, b], not [a, b, ""]
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    parts.sort()
    if not parts:
        return b""
    return b"\n".join(parts) + b"\n"


def main() -> int:
    """Entry point: validate arguments, read stdin, sort, write stdout."""
    args = sys.argv[1:]
    for arg in args:
        if arg == "--":
            continue
        if arg.startswith("-"):
            print(f"sort: unrecognized option '{arg}'", file=sys.stderr)
            print("Try 'sort --help' for more information.", file=sys.stderr)
            return 2
        # File operand: attempt to open; if the file is missing or
        # unreadable the diagnostic matches GNU sort's "cannot read" form.
        try:
            fh = open(arg, "rb")
        except OSError as exc:
            import errno
            msg = exc.strerror if exc.strerror else errno.strerror(exc.errno)
            print(f"sort: cannot read: {arg}: {msg}", file=sys.stderr)
            return 2
        fh.close()
    try:
        data = sys.stdin.buffer.read()
        result = sort_lines(data)
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
    except (MemoryError, OSError) as exc:
        print(f"sort: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
