#!/usr/bin/env python3
"""py_mv: move files and directories (checkpoint 000: base)."""

import os
import stat
import sys


class _MoveError(Exception):
    """Per-source move failure."""
    pass


def move_path(source, destination):
    """Perform the core filesystem move (rename) operation."""
    os.rename(source, destination)


def _parse_operands(argv):
    """Split argv into (force, operands); accept -f/--force before --."""
    operands = []
    force = False
    seen_separator = False
    for arg in argv:
        if not seen_separator and arg == "--":
            seen_separator = True
            continue
        if not seen_separator:
            if arg in ("-f", "--force"):
                force = True
                continue
            if arg.startswith("-") and arg != "-":
                raise ValueError(f"unknown option -- {arg}")
        operands.append(arg)
    return force, operands


def _resolve_effective_dest(source, dest, is_multi):
    """Return the path to which source should be moved."""
    basename = os.path.basename(source)
    if is_multi:
        return os.path.join(dest, basename)
    try:
        st = os.lstat(dest)
    except OSError:
        return dest
    if stat.S_ISDIR(st.st_mode):
        return os.path.join(dest, basename)
    return dest


def _check_and_move(src, eff_dest, src_stat, force=False):
    """Validate compatibility and perform the move; raises _MoveError."""
    src_is_dir = stat.S_ISDIR(src_stat.st_mode)

    # Check if effective destination exists
    try:
        dest_stat = os.lstat(eff_dest)
    except OSError:
        dest_stat = None

    if dest_stat is not None:
        # Identical source and destination (same inode)
        if src_stat.st_dev == dest_stat.st_dev and src_stat.st_ino == dest_stat.st_ino:
            raise _MoveError(f"'{src}' and '{eff_dest}' are the same file")

        dest_is_dir = stat.S_ISDIR(dest_stat.st_mode)
        if src_is_dir and not dest_is_dir:
            raise _MoveError(
                f"cannot replace non-directory '{eff_dest}' with directory '{src}'"
            )
        if not src_is_dir and dest_is_dir:
            raise _MoveError(
                f"cannot replace directory '{eff_dest}' with non-directory '{src}'"
            )
        if src_is_dir and dest_is_dir:
            # Replacing a directory is only OK if dest is empty
            try:
                if os.listdir(eff_dest):
                    raise _MoveError(
                        f"cannot overwrite non-empty directory '{eff_dest}'"
                    )
            except _MoveError:
                raise
            except OSError:
                pass

        if dest_stat is not None and not force:
            if not stat.S_ISDIR(dest_stat.st_mode) and not (dest_stat.st_mode & stat.S_IWUSR):
                raise _MoveError(
                    f"cannot overwrite write-protected file '{eff_dest}'"
                )

    # Moving a directory into itself or its descendant
    if src_is_dir:
        src_abs = os.path.abspath(src)
        dest_abs = os.path.abspath(eff_dest)
        if dest_abs == src_abs:
            raise _MoveError(f"'{src}' and '{eff_dest}' are the same file")
        if dest_abs.startswith(src_abs + os.sep):
            raise _MoveError(
                f"cannot move directory '{src}' into its subdirectory '{eff_dest}'"
            )

    # Perform the move
    try:
        move_path(src, eff_dest)
    except OSError as e:
        errno_msg = os.strerror(e.errno) if e.errno else str(e)
        raise _MoveError(
            f"cannot move '{src}' to '{eff_dest}': {errno_msg}"
        ) from e


def main():
    # Parse operands
    try:
        force, operands = _parse_operands(sys.argv[1:])
    except ValueError as e:
        print(f"py_mv: {e}", file=sys.stderr)
        return 1

    # Invocation-wide validation
    if len(operands) < 2:
        if len(operands) == 0:
            print("py_mv: missing operand", file=sys.stderr)
        else:
            print("py_mv: missing destination operand", file=sys.stderr)
        return 1

    sources = operands[:-1]
    dest = operands[-1]
    is_multi = len(sources) > 1

    # Multi-source: dest must be an existing directory
    if is_multi:
        try:
            st = os.lstat(dest)
        except OSError:
            print(
                f"py_mv: cannot move to '{dest}': No such file or directory",
                file=sys.stderr,
            )
            return 1
        if not stat.S_ISDIR(st.st_mode):
            print(f"py_mv: target '{dest}' is not a directory", file=sys.stderr)
            return 1

    # Process sources in operand order
    exit_code = 0
    for src in sources:
        # Check source exists
        try:
            src_stat = os.lstat(src)
        except OSError as e:
            errno_msg = os.strerror(e.errno) if e.errno else str(e)
            print(f"py_mv: cannot stat '{src}': {errno_msg}", file=sys.stderr)
            exit_code = 1
            continue

        # Compute effective destination
        eff_dest = _resolve_effective_dest(src, dest, is_multi)

        # Validate and perform the move
        try:
            _check_and_move(src, eff_dest, src_stat, force)
        except _MoveError as e:
            print(f"py_mv: {e}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
