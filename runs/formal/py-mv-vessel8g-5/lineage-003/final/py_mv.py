#!/usr/bin/env python3
"""mv - move (rename) files and directories."""

import os
import stat
import sys


def move_path(source: str, dest: str) -> None:
    """Perform a single filesystem move. Raises OSError on any failure."""
    src_stat = os.lstat(source)
    src_is_dir = stat.S_ISDIR(src_stat.st_mode)
    src_real = os.path.realpath(source)

    try:
        dst_stat = os.lstat(dest)
    except FileNotFoundError:
        dst_stat = None

    if dst_stat is not None:
        dst_is_dir = stat.S_ISDIR(dst_stat.st_mode)
        dst_real = os.path.realpath(dest)

        if src_real == dst_real:
            raise OSError("same file")

        if src_is_dir and not dst_is_dir:
            raise OSError(
                f"cannot replace non-directory '{dest}' with directory"
            )

        if not src_is_dir and dst_is_dir:
            raise OSError(
                f"cannot replace directory '{dest}' with non-directory"
            )

        if src_is_dir and dst_is_dir:
            if os.listdir(dest):
                raise OSError(
                    f"cannot overwrite non-empty directory '{dest}'"
                )

    if src_is_dir:
        dst_real = os.path.realpath(dest)
        if dst_real == src_real or dst_real.startswith(src_real + os.sep):
            raise OSError("cannot move directory into itself")

    os.rename(source, dest)


def main() -> int:
    args = sys.argv[1:]
    operands: list[str] = []
    seen_ddash = False
    policy = None

    for arg in args:
        if not seen_ddash:
            if arg == '--':
                seen_ddash = True
            elif arg == '-':
                operands.append(arg)
            elif arg == '-f' or arg == '--force':
                policy = 'force'
            elif arg == '-i' or arg == '--interactive':
                policy = 'interactive'
            elif arg.startswith('-'):
                print(f"mv: unknown option: {arg}", file=sys.stderr)
                return 1
            else:
                operands.append(arg)
        else:
            operands.append(arg)

    if len(operands) < 2:
        print("mv: missing operand", file=sys.stderr)
        return 1

    if len(operands) == 2:
        sources = [operands[0]]
        dest_base = operands[1]
    else:
        sources = operands[:-1]
        dest_base = operands[-1]
        try:
            if not os.path.isdir(dest_base):
                print(f"mv: '{dest_base}' is not a directory", file=sys.stderr)
                return 1
        except OSError:
            print(f"mv: '{dest_base}' is not a directory", file=sys.stderr)
            return 1

    dest_is_dir = os.path.isdir(dest_base)

    exit_code = 0
    for source in sources:
        if dest_is_dir:
            name = os.path.basename(source)
            if not name:
                name = source
            effective_dest = os.path.join(dest_base, name)
        else:
            effective_dest = dest_base

        if policy == 'interactive':
            try:
                os.lstat(effective_dest)
            except (FileNotFoundError, OSError):
                pass
            else:
                sys.stderr.write(f"mv: overwrite '{effective_dest}'? ")
                sys.stderr.flush()
                line = sys.stdin.readline()
                if not (line and line[0] in ('y', 'Y')):
                    print(f"mv: not overwriting '{effective_dest}'", file=sys.stderr)
                    exit_code = 1
                    continue

        try:
            move_path(source, effective_dest)
        except OSError as exc:
            print(f"mv: {source}: {exc}", file=sys.stderr)
            exit_code = 1
        except Exception as exc:
            print(f"mv: {source}: {exc}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
