#!/usr/bin/env python3
"""py_mv - GNU mv compatible move utility, checkpoint 000."""

import os
import stat
import sys


def _parse_operands(argv):
    """Split argv into literal operands. Returns (operands, error_or_None)."""
    operands = []
    seen_dd = False
    for arg in argv:
        if not seen_dd and arg == "--":
            seen_dd = True
            continue
        if not seen_dd and arg.startswith("-") and len(arg) > 1:
            return None, f"py_mv: unknown option -- {arg}"
        operands.append(arg)
    return operands, None


def _lstat(path):
    """Return (st_result, error_or_None)."""
    try:
        return os.lstat(path), None
    except FileNotFoundError:
        return None, f"py_mv: cannot stat '{path}': No such file or directory"
    except PermissionError:
        return None, f"py_mv: cannot stat '{path}': Permission denied"
    except OSError as exc:
        return None, f"py_mv: cannot stat '{path}': {exc.strerror or exc}"


def _prevalidate(src, dest):
    """Pre-validate a single move. Returns (ok, error_or_None)."""
    src_st, err = _lstat(src)
    if err:
        return False, err

    try:
        dest_st = os.lstat(dest)
    except FileNotFoundError:
        dest_st = None
    except PermissionError:
        return False, f"py_mv: cannot stat '{dest}': Permission denied"
    except OSError as exc:
        return False, f"py_mv: cannot stat '{dest}': {exc.strerror or exc}"

    # Identical source and destination (via real path)
    try:
        if os.path.realpath(src) == os.path.realpath(dest):
            return False, f"py_mv: '{src}' and '{dest}' are the same file"
    except OSError:
        pass

    src_is_dir = stat.S_ISDIR(src_st.st_mode)

    if dest_st is not None:
        dest_is_dir = stat.S_ISDIR(dest_st.st_mode)
        if src_is_dir and not dest_is_dir:
            return False, (f"py_mv: cannot move directory '{src}' "
                          f"to non-directory '{dest}'")
        if not src_is_dir and dest_is_dir:
            return False, (f"py_mv: cannot move non-directory '{src}' "
                          f"to directory '{dest}'")
        if src_is_dir and dest_is_dir:
            try:
                if os.listdir(dest):
                    return False, (f"py_mv: cannot move '{src}' to '{dest}': "
                                  f"Directory not empty")
            except PermissionError:
                return False, f"py_mv: cannot read '{dest}': Permission denied"
            except OSError as exc:
                return False, f"py_mv: cannot read '{dest}': {exc.strerror or exc}"

    # Directory moved into itself or its subtree
    if src_is_dir:
        try:
            src_real = os.path.realpath(src)
            dest_real = os.path.realpath(dest)
            if dest_real == src_real or dest_real.startswith(src_real + "/"):
                return False, (f"py_mv: cannot move '{src}' into a subdirectory "
                              f"of itself, '{dest}'")
        except OSError:
            pass

    return True, None


def move_path(src, dest):
    """Core filesystem move via rename. Returns (ok, error_or_None)."""
    try:
        os.rename(src, dest)
        return True, None
    except FileNotFoundError:
        return False, f"py_mv: cannot move '{src}' to '{dest}': No such file or directory"
    except PermissionError:
        return False, f"py_mv: cannot move '{src}' to '{dest}': Permission denied"
    except IsADirectoryError:
        return False, f"py_mv: cannot move '{src}' to '{dest}': Is a directory"
    except NotADirectoryError:
        return False, f"py_mv: cannot move '{src}' to '{dest}': Not a directory"
    except OSError as exc:
        return False, f"py_mv: cannot move '{src}' to '{dest}': {exc.strerror or exc}"


def main():
    argv = sys.argv[1:]

    if not argv:
        print("py_mv: missing operand", file=sys.stderr)
        sys.exit(1)

    operands, err = _parse_operands(argv)
    if err:
        print(err, file=sys.stderr)
        sys.exit(1)

    if len(operands) < 2:
        print("py_mv: missing operand", file=sys.stderr)
        sys.exit(1)

    # Build the list of (src, dest) pairs
    if len(operands) >= 3:
        dest_dir = operands[-1]
        sources = operands[:-1]

        dest_st, err = _lstat(dest_dir)
        if err:
            print(err, file=sys.stderr)
            sys.exit(1)
        if not stat.S_ISDIR(dest_st.st_mode):
            print(f"py_mv: invalid target directory: '{dest_dir}': Not a directory",
                  file=sys.stderr)
            sys.exit(1)

        moves = []
        for src in sources:
            base = os.path.basename(src)
            moves.append((src, os.path.join(dest_dir, base)))
    else:
        src = operands[0]
        dest = operands[1]
        try:
            dest_st = os.lstat(dest)
            if stat.S_ISDIR(dest_st.st_mode):
                base = os.path.basename(src)
                dest = os.path.join(dest, base)
        except (FileNotFoundError, PermissionError, OSError):
            pass
        moves = [(src, dest)]

    # Execute in operand order; continue after per-source failures
    any_failed = False
    for src, dest in moves:
        ok, err = _prevalidate(src, dest)
        if not ok:
            print(err, file=sys.stderr)
            any_failed = True
            continue
        ok, err = move_path(src, dest)
        if not ok:
            print(err, file=sys.stderr)
            any_failed = True

    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
