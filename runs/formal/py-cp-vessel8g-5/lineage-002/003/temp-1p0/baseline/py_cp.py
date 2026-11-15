#!/usr/bin/env python3
"""py_cp — checkpoint 000: basic file copy utility."""
import os
import stat
import sys


def parse_args(argv):
    operands = []
    after_ddash = False
    force = False
    interactive = False
    for token in argv:
        if not after_ddash and token == '--':
            after_ddash = True
            continue
        if after_ddash:
            operands.append(token)
        else:
            if token in ('-f', '--force'):
                force = True
            elif token in ('-i', '--interactive'):
                interactive = True
            elif token.startswith('-') and token != '-':
                return None, None, None, f"unknown option: {token}"
            else:
                operands.append(token)
    return operands, force, interactive, None


def copy_path(src, dst, force=False):
    src_fd = os.open(src, os.O_RDONLY)
    try:
        src_stat = os.fstat(src_fd)
        try:
            dst_fd = os.open(dst, os.O_WRONLY | os.O_TRUNC)
        except OSError as open_err:
            try:
                dst_info = os.lstat(dst)
            except OSError:
                dst_info = None

            if dst_info is not None:
                if stat.S_ISDIR(dst_info.st_mode):
                    raise open_err
                elif force:
                    os.unlink(dst)
                    dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                    mode = stat.S_IMODE(src_stat.st_mode) & ~0o022
                    os.fchmod(dst_fd, mode)
                else:
                    raise open_err
            else:
                dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                mode = stat.S_IMODE(src_stat.st_mode) & ~0o022
                os.fchmod(dst_fd, mode)
        try:
            while True:
                chunk = os.read(src_fd, 131072)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    n = os.write(dst_fd, view)
                    view = view[n:]
        finally:
            os.close(dst_fd)
    finally:
        os.close(src_fd)


def main():
    operands, force, interactive, err = parse_args(sys.argv[1:])
    if err is not None:
        print(f"py_cp: {err}", file=sys.stderr)
        sys.exit(1)

    if len(operands) < 2:
        print("py_cp: missing required operand", file=sys.stderr)
        sys.exit(1)

    multi = len(operands) > 2
    if multi:
        dest_dir = operands[-1]
        sources = operands[:-1]
        try:
            st = os.stat(dest_dir)
        except OSError:
            print(f"py_cp: {dest_dir}: Not a directory", file=sys.stderr)
            sys.exit(1)
        if not stat.S_ISDIR(st.st_mode):
            print(f"py_cp: {dest_dir}: Not a directory", file=sys.stderr)
            sys.exit(1)
        into_dir = True
    else:
        sources = [operands[0]]
        dest_dir = operands[1]
        try:
            st = os.stat(dest_dir)
            into_dir = stat.S_ISDIR(st.st_mode)
        except OSError:
            into_dir = False

    exit_status = 0

    for src in sources:
        dst = os.path.join(dest_dir, os.path.basename(src)) if into_dir else dest_dir
        try:
            src_stat = os.stat(src)
            if not stat.S_ISREG(src_stat.st_mode):
                print(f"py_cp: {src}: Not a regular file", file=sys.stderr)
                exit_status = 1
                continue
            dst_exists = False
            try:
                dst_stat = os.stat(dst)
                dst_exists = True
                if not stat.S_ISREG(dst_stat.st_mode):
                    print(f"py_cp: {dst}: Not a regular file", file=sys.stderr)
                    exit_status = 1
                    continue
                if (src_stat.st_dev == dst_stat.st_dev
                        and src_stat.st_ino == dst_stat.st_ino):
                    print(f"py_cp: '{src}' and '{dst}' are the same file",
                          file=sys.stderr)
                    exit_status = 1
                    continue
            except FileNotFoundError:
                if os.path.lexists(dst) and not force:
                    print(f"py_cp: {dst}: Dangling symbolic link",
                          file=sys.stderr)
                    exit_status = 1
                    continue
            except PermissionError:
                print(f"py_cp: {dst}: Permission denied", file=sys.stderr)
                exit_status = 1
                continue

            if interactive and dst_exists:
                sys.stderr.write(f"py_cp: overwrite '{dst}'? (y/n) ")
                sys.stderr.flush()
                answer = sys.stdin.readline()
                if not answer or answer[0] not in ('y', 'Y'):
                    exit_status = 1
                    continue

            copy_path(src, dst, force=force)
        except (OSError, MemoryError) as e:
            print(f"py_cp: {src}: {e.strerror or e}", file=sys.stderr)
            exit_status = 1

    sys.exit(exit_status)


if __name__ == "__main__":
    main()
