#!/usr/bin/env python3
"""GNU mv — checkpoint 000 (base)."""
import os
import stat
import sys


class MoveError(Exception):
    """Raised when a move operation fails."""
    pass


def _is_directory(path):
    """Return True if path exists and is a directory (following symlinks)."""
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except OSError:
        return False


def _same_file(a, b):
    """Return True if two paths refer to the same underlying file."""
    try:
        sa = os.stat(a)
        sb = os.stat(b)
    except OSError:
        return False
    return (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino)


def _is_inside(child, parent):
    """Return True if child is the same as or inside the parent directory."""
    try:
        child_real = os.path.realpath(child)
        parent_real = os.path.realpath(parent)
    except OSError:
        return False
    if child_real == parent_real:
        return True
    return child_real.startswith(parent_real + os.sep)


def move_path(source, destination):
    """Core move: relocate source to destination on the same filesystem.

    Raises MoveError with a diagnostic identifying the affected operand.
    """
    # --- Source must exist ---
    try:
        src_lstat = os.lstat(source)
    except FileNotFoundError:
        raise MoveError(f"cannot stat '{source}': No such file or directory")
    except OSError as e:
        raise MoveError(f"cannot stat '{source}': {e.strerror}")

    src_is_dir = stat.S_ISDIR(src_lstat.st_mode)

    # --- Destination status ---
    try:
        dst_lstat = os.lstat(destination)
        dst_exists = True
    except FileNotFoundError:
        dst_lstat = None
        dst_exists = False
    except OSError as e:
        raise MoveError(f"cannot stat '{destination}': {e.strerror}")

    dst_is_dir = dst_exists and stat.S_ISDIR(dst_lstat.st_mode)

    # --- Identical source and destination ---
    if _same_file(source, destination):
        raise MoveError(f"cannot move '{source}' to itself")

    # --- Directory moved into itself or its descendants ---
    if src_is_dir and _is_inside(destination, source):
        raise MoveError(
            f"cannot move '{source}' into a subdirectory of itself, '{destination}'"
        )

    # --- Type compatibility at effective destination ---
    if dst_exists:
        if src_is_dir and not dst_is_dir:
            raise MoveError(
                f"cannot move '{source}' to '{destination}': "
                f"target is not a directory"
            )
        if not src_is_dir and dst_is_dir:
            raise MoveError(
                f"cannot move '{source}' to '{destination}': "
                f"target is a directory"
            )
        if src_is_dir and dst_is_dir:
            try:
                if os.listdir(destination):
                    raise MoveError(
                        f"cannot move '{source}' to '{destination}': "
                        f"target directory is not empty"
                    )
            except MoveError:
                raise
            except OSError as e:
                raise MoveError(
                    f"cannot move '{source}' to '{destination}': {e.strerror}"
                )

    # --- Perform the rename (atomic on same filesystem) ---
    try:
        os.rename(source, destination)
    except OSError as e:
        raise MoveError(
            f"cannot move '{source}' to '{destination}': {e.strerror}"
        )


def main():
    args = sys.argv[1:]

    # --- Parse arguments: options before --, operands after ---
    operands = []
    seen_ddash = False
    for arg in args:
        if not seen_ddash:
            if arg == "--":
                seen_ddash = True
                continue
            if arg.startswith("-") and len(arg) > 1:
                print(f"py_mv: unrecognized option: {arg}", file=sys.stderr)
                sys.exit(1)
        operands.append(arg)

    # --- Invocation-wide validation (before any filesystem change) ---
    if len(operands) < 2:
        print("py_mv: missing destination operand", file=sys.stderr)
        sys.exit(1)

    # --- Determine (source, destination) pairs ---
    if len(operands) == 2:
        src = operands[0]
        dst = operands[1]
        if _is_directory(dst):
            name = os.path.basename(os.path.normpath(src))
            dst = os.path.join(dst, name)
        pairs = [(src, dst)]
    else:
        dst_root = operands[-1]
        if not _is_directory(dst_root):
            print(f"py_mv: target '{dst_root}': Not a directory", file=sys.stderr)
            sys.exit(1)
        pairs = []
        for src in operands[:-1]:
            name = os.path.basename(os.path.normpath(src))
            pairs.append((src, os.path.join(dst_root, name)))

    # --- Execute moves in operand order ---
    exit_code = 0
    for src, dst in pairs:
        try:
            move_path(src, dst)
        except MoveError as e:
            print(f"py_mv: {e}", file=sys.stderr)
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
