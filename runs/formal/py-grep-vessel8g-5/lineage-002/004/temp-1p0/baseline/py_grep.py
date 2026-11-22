#!/usr/bin/env python3
"""Bounded fixed-substring grep over lines."""
import sys
import os


def search_stream(pattern: bytes, stream, prefix: bytes) -> int:
    """Read lines from stream; write each line containing pattern to stdout
    with the given prefix and a trailing newline. Return the number of
    matched lines."""
    out = sys.stdout.buffer
    count = 0
    while True:
        line = stream.readline()
        if not line:
            break
        content = line[:-1] if line.endswith(b'\n') else line
        if pattern in content:
            out.write(prefix + content + b'\n')
            count += 1
    return count


def traverse_dir(base: str, pattern: bytes, do_prefix: bool) -> tuple:
    """Iterative pre-order DFS over a directory tree.
    Returns (match_count, had_error)."""
    count = 0
    had_error = False
    stack = [base]
    while stack:
        path = stack.pop()
        try:
            if os.path.islink(path):
                continue
            if not os.path.isdir(path):
                if os.path.isfile(path):
                    if do_prefix:
                        prefix = path.encode('utf-8', 'surrogateescape') + b':'
                    else:
                        prefix = b''
                    with open(path, 'rb') as f:
                        count += search_stream(pattern, f, prefix)
                continue
        except OSError as e:
            _diagnose(path, e)
            had_error = True
            continue
        try:
            entries = os.listdir(path)
        except OSError as e:
            _diagnose(path, e)
            had_error = True
            continue
        entries.sort(key=lambda n: n.encode('utf-8', 'surrogateescape'))
        for entry in reversed(entries):
            stack.append(os.path.join(path, entry))
    return count, had_error


def _diagnose(name: str, err: OSError) -> None:
    sys.stderr.write(f"py_grep: {name}: {err.strerror or 'error'}\n")


def main() -> int:
    args = sys.argv[1:]

    operands: list[str] = []
    filename_mode = None  # None=unspecified, True=force-with, False=force-without
    recursive = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--':
            operands.extend(args[i + 1:])
            break
        if arg == '--with-filename':
            filename_mode = True
            i += 1
            continue
        if arg == '--no-filename':
            filename_mode = False
            i += 1
            continue
        if arg == '--recursive':
            recursive = True
            i += 1
            continue
        if arg.startswith('--'):
            sys.stderr.write(f"py_grep: unsupported option: {arg}\n")
            return 2
        if arg.startswith('-') and arg != '-':
            valid = True
            for c in arg[1:]:
                if c == 'H':
                    filename_mode = True
                elif c == 'h':
                    filename_mode = False
                elif c == 'r':
                    recursive = True
                else:
                    sys.stderr.write(f"py_grep: unsupported option: {arg}\n")
                    return 2
                    break
            i += 1
            continue
        operands.append(arg)
        i += 1

    if not operands:
        sys.stderr.write("py_grep: missing PATTERN\n")
        return 2

    pattern = operands[0].encode('utf-8', 'surrogateescape')
    file_operands = operands[1:]

    total_matches = 0
    had_error = False

    try:
        if not file_operands:
            try:
                stdin_prefix = b'(standard input):' if filename_mode is True else b''
                total_matches += search_stream(pattern, sys.stdin.buffer, stdin_prefix)
            except OSError:
                had_error = True
        else:
            # Determine global prefix decision
            if filename_mode is False:
                do_prefix = False
            elif filename_mode is True:
                do_prefix = True
            else:
                any_dir = any(
                    os.path.isdir(op) for op in file_operands
                )
                do_prefix = any_dir or len(file_operands) >= 2

            for operand in file_operands:
                name_bytes = operand.encode('utf-8', 'surrogateescape')

                # Directory operand with -r: traverse
                if os.path.isdir(operand) and recursive:
                    base = operand
                    while len(base) > 1 and base.endswith('/'):
                        base = base[:-1]
                    sub_count, sub_err = traverse_dir(base, pattern, do_prefix)
                    total_matches += sub_count
                    if sub_err:
                        had_error = True
                    continue

                # Regular file operand (or symlink-to-file): search
                if do_prefix:
                    prefix = name_bytes + b':'
                else:
                    prefix = b''
                try:
                    with open(operand, 'rb') as f:
                        total_matches += search_stream(pattern, f, prefix)
                except OSError as e:
                    _diagnose(operand, e)
                    had_error = True
    except MemoryError:
        had_error = True

    sys.stdout.buffer.flush()

    if had_error:
        return 2
    return 0 if total_matches > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
