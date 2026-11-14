#!/usr/bin/env python3
"""py_cp — checkpoint 000: basic file copy."""

import os
import stat
import sys


class _CopyError(Exception):
    """Per-source copy failure carrying a user-facing message."""


def _get_umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _copy_bytes(src_fd, dst_fd):
    """Transfer all bytes from src_fd to dst_fd at the fd level."""
    while True:
        chunk = os.read(src_fd, 1 << 20)
        if not chunk:
            break
        pos = 0
        while pos < len(chunk):
            pos += os.write(dst_fd, chunk[pos:])


def copy_path(source, destination):
    """Core filesystem operation: copy file contents from source to destination.

    Pre-conditions (validated by caller):
      source is a regular file (or symlink resolving to one);
      destination is an existing regular file, a symlink to one, or a new
      path whose parent exists; source and destination are not the same file.

    Post-conditions:
      destination holds a byte-for-byte copy of source;
      source is unmodified;
      new files get rwx = source_rwx & ~umask;
      existing files retain their rwx.
    """
    umask = _get_umask()

    try:
        src_fd = os.open(source, os.O_RDONLY)
    except PermissionError:
        raise _CopyError(f"cannot read: {source}")
    except OSError as exc:
        raise _CopyError(f"cannot open: {source}: {exc.strerror or exc}")

    dst_fd = None
    try:
        try:
            os.stat(destination)
        except FileNotFoundError:
            # New file (dangling symlinks and missing parents rejected by caller)
            try:
                dst_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o777)
            except OSError as exc:
                raise _CopyError(f"cannot create: {destination}: {exc.strerror or exc}")
            src_st = os.stat(source)
            os.fchmod(dst_fd, stat.S_IMODE(src_st.st_mode) & ~umask)
        else:
            # Existing regular file (or symlink to one)
            try:
                dst_fd = os.open(destination, os.O_WRONLY | os.O_TRUNC)
            except OSError as exc:
                raise _CopyError(f"cannot open: {destination}: {exc.strerror or exc}")

        _copy_bytes(src_fd, dst_fd)
        os.close(dst_fd)
        dst_fd = None
    finally:
        if dst_fd is not None:
            try:
                os.close(dst_fd)
            except OSError:
                pass
        try:
            os.close(src_fd)
        except OSError:
            pass


def _parse_operands(argv):
    """Return the operand list, enforcing option and terminator rules.

    Before --: bare '-' is a filename; any other '-'-prefixed token is an
    unknown option.  After --: every token is a literal operand.
    """
    operands = []
    literal = False
    for arg in argv:
        if not literal:
            if arg == "--":
                literal = True
            elif arg == "-":
                operands.append(arg)
            elif arg.startswith("-") and len(arg) > 1:
                raise _CopyError(f"unknown option: {arg}")
            else:
                operands.append(arg)
        else:
            operands.append(arg)
    return operands


def _validate_source(source):
    """Return os.stat(source) or raise _CopyError if not a regular file."""
    try:
        st = os.stat(source)
    except FileNotFoundError:
        raise _CopyError(f"no such file: {source}")
    except PermissionError:
        raise _CopyError(f"permission denied: {source}")
    except OSError as exc:
        raise _CopyError(f"cannot access: {source}: {exc.strerror or exc}")
    if stat.S_ISDIR(st.st_mode):
        raise _CopyError(f"is a directory: {source}")
    if not stat.S_ISREG(st.st_mode):
        raise _CopyError(f"not a regular file: {source}")
    return st


def _validate_destination(destination):
    """Return stat if destination is an existing regular file, else None (new).

    Raises _CopyError for dangling symlinks, directories, missing parents,
    or incompatible types.
    """
    try:
        st = os.stat(destination)
    except FileNotFoundError:
        if os.path.islink(destination):
            raise _CopyError(f"dangling symlink: {destination}")
        parent = os.path.dirname(destination) or "."
        try:
            os.stat(parent)
        except (OSError, ValueError):
            raise _CopyError(f"no such file or directory: {destination}")
        return None
    except PermissionError:
        raise _CopyError(f"permission denied: {destination}")
    except OSError as exc:
        raise _CopyError(f"cannot access: {destination}: {exc.strerror or exc}")
    if stat.S_ISDIR(st.st_mode):
        raise _CopyError(f"is a directory: {destination}")
    if not stat.S_ISREG(st.st_mode):
        raise _CopyError(f"incompatible destination: {destination}")
    return st


def main():
    try:
        operands = _parse_operands(sys.argv[1:])
    except _CopyError as exc:
        print(f"py_cp: {exc}", file=sys.stderr)
        return 1

    if len(operands) < 2:
        print("py_cp: missing operand", file=sys.stderr)
        return 1

    multi = len(operands) > 2
    if multi:
        dest_dir = operands[-1]
        try:
            st = os.stat(dest_dir)
        except (OSError, ValueError):
            print(f"py_cp: not a directory: {dest_dir}", file=sys.stderr)
            return 1
        if not stat.S_ISDIR(st.st_mode):
            print(f"py_cp: not a directory: {dest_dir}", file=sys.stderr)
            return 1
        sources = operands[:-1]
    else:
        sources = [operands[0]]

    # Compute (source, destination) pairs
    pairs = []
    for src in sources:
        base = os.path.basename(src)
        if multi:
            dest = os.path.join(dest_dir, base)
        else:
            dest = operands[1]
            try:
                st = os.stat(dest)
                if stat.S_ISDIR(st.st_mode):
                    dest = os.path.join(dest, base)
            except (OSError, ValueError):
                pass
        pairs.append((src, dest))

    # Process in operand order; per-source failures do not halt the run
    had_error = False
    for src, dest in pairs:
        try:
            src_st = _validate_source(src)
            dst_st = _validate_destination(dest)
            if dst_st is not None and src_st.st_dev == dst_st.st_dev \
                    and src_st.st_ino == dst_st.st_ino:
                raise _CopyError(f"source and destination are the same file: {src}")
            copy_path(src, dest)
        except _CopyError as exc:
            print(f"py_cp: {exc}", file=sys.stderr)
            had_error = True
        except OSError as exc:
            print(f"py_cp: {exc.strerror or exc}", file=sys.stderr)
            had_error = True

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
