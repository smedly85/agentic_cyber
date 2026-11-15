#!/usr/bin/env python3
"""py_mv — move/rename (checkpoint 000: base)."""
import os
import sys


def move_path(src, dst):
    """Core filesystem move operation (same-filesystem rename)."""
    os.rename(src, dst)


def _is_within(child, parent):
    """True if child equals parent or is a strict path-descendant."""
    if child == parent:
        return True
    prefix = parent if parent.endswith('/') else parent + '/'
    return child.startswith(prefix)


def _process_one(src, dst):
    """Attempt to move src to dst. Returns True on success."""
    try:
        if not os.path.lexists(src):
            print(f"py_mv: cannot move '{src}': No such file or directory", file=sys.stderr)
            return False

        src_real = os.path.realpath(src)
        dst_real = os.path.realpath(dst)

        if src_real == dst_real:
            print(f"py_mv: '{src}' and '{dst}' are the same file", file=sys.stderr)
            return False

        src_is_dir = os.path.isdir(src) and not os.path.islink(src)
        if src_is_dir and _is_within(dst_real, src_real):
            print(f"py_mv: cannot move '{src}' into a subdirectory of itself, '{dst}'",
                  file=sys.stderr)
            return False

        dst_exists = os.path.lexists(dst)
        dst_is_dir = dst_exists and os.path.isdir(dst) and not os.path.islink(dst)

        if src_is_dir and dst_exists and not dst_is_dir:
            print(f"py_mv: cannot overwrite non-directory '{dst}' with directory '{src}'",
                  file=sys.stderr)
            return False
        if not src_is_dir and dst_is_dir:
            print(f"py_mv: cannot overwrite directory '{dst}' with non-directory '{src}'",
                  file=sys.stderr)
            return False

        move_path(src, dst)
        return True

    except OSError as e:
        msg = e.strerror if e.strerror else str(e)
        print(f"py_mv: cannot move '{src}' to '{dst}': {msg}", file=sys.stderr)
        return False


def main():
    force = False
    operands = []
    after_ddash = False
    for arg in sys.argv[1:]:
        if not after_ddash and arg == '--':
            after_ddash = True
            continue
        if not after_ddash and arg in ('-f', '--force'):
            force = True
            continue
        if not after_ddash and arg.startswith('-') and len(arg) > 1:
            print(f"py_mv: unrecognized option: {arg}", file=sys.stderr)
            sys.exit(1)
        operands.append(arg)

    if len(operands) < 2:
        print("py_mv: missing operand", file=sys.stderr)
        sys.exit(1)

    if len(operands) > 2:
        dest_dir = operands[-1]
        if not os.path.isdir(dest_dir):
            print(f"py_mv: target '{dest_dir}' is not a directory", file=sys.stderr)
            sys.exit(1)
        pairs = []
        for src in operands[:-1]:
            base = os.path.basename(os.path.normpath(src))
            pairs.append((src, os.path.join(dest_dir, base)))
    else:
        src, dst = operands[0], operands[1]
        if os.path.isdir(dst) and not os.path.islink(dst):
            base = os.path.basename(os.path.normpath(src))
            dst = os.path.join(dst, base)
        pairs = [(src, dst)]

    any_failure = False
    for src, dst in pairs:
        if not _process_one(src, dst):
            any_failure = True

    sys.exit(1 if any_failure else 0)


if __name__ == '__main__':
    main()
