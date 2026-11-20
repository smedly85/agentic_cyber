#!/usr/bin/env python3
"""mkdir: Create directories (checkpoint 001)."""

import os
import stat
import sys


def _fail(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.write("Try 'mkdir --help' for more information.\n")
    sys.exit(1)


def _diagnose(operand: str, e: OSError) -> None:
    if isinstance(e, FileExistsError):
        reason = "File exists"
    elif isinstance(e, FileNotFoundError):
        reason = "No such file or directory"
    elif isinstance(e, NotADirectoryError):
        reason = "Not a directory"
    elif isinstance(e, PermissionError):
        reason = "Permission denied"
    else:
        reason = e.strerror or "error"
    sys.stderr.write(f"mkdir: cannot create directory '{operand}': {reason}\n")


def _ensure_owner_wx(path: bytes) -> None:
    st = os.lstat(path)
    mode = stat.S_IMODE(st.st_mode)
    if (mode & 0o300) != 0o300:
        os.chmod(path, mode | 0o300)


def _mkdir_p(operand: str) -> bool:
    raw = os.fsencode(operand)
    parts = [p for p in raw.split(b'/') if p]
    if not parts:
        try:
            os.mkdir(raw)
        except OSError as e:
            _diagnose(operand, e)
            return False
        return True

    last = len(parts) - 1
    for i, part in enumerate(parts):
        prefix = b'/'.join(parts[: i + 1])
        is_final = (i == last)
        try:
            st = os.lstat(prefix)
        except OSError:
            try:
                os.mkdir(prefix, 0o777)
            except OSError as e:
                _diagnose(operand, e)
                return False
            if not is_final:
                try:
                    _ensure_owner_wx(prefix)
                except OSError as e:
                    _diagnose(operand, e)
                    return False
        else:
            if stat.S_ISDIR(st.st_mode):
                continue
            if stat.S_ISLNK(st.st_mode):
                try:
                    st2 = os.stat(prefix)
                except OSError:
                    _diagnose(operand, NotADirectoryError())
                    return False
                if not stat.S_ISDIR(st2.st_mode):
                    _diagnose(operand, NotADirectoryError())
                    return False
            else:
                _diagnose(operand, NotADirectoryError())
                return False
    return True


def main() -> None:
    argv = sys.argv[1:]

    operands: list[str] = []
    seen_ddash = False
    unknown_opt: str | None = None
    parents = False

    for arg in argv:
        if seen_ddash:
            operands.append(arg)
        elif arg == "--":
            seen_ddash = True
        elif arg == "-":
            operands.append(arg)
        elif arg.startswith("-"):
            if arg == "-p" or arg == "--parents":
                parents = True
            elif unknown_opt is None:
                unknown_opt = arg
        else:
            operands.append(arg)

    if unknown_opt is not None:
        opt = unknown_opt
        if opt.startswith("--"):
            _fail(f"mkdir: unrecognized option '{opt}'")
        else:
            ch = opt[1] if len(opt) > 1 else ""
            _fail(f"mkdir: invalid option -- '{ch}'")

    if not operands:
        _fail("mkdir: missing operand")

    all_ok = True
    for operand in operands:
        if parents:
            if not _mkdir_p(operand):
                all_ok = False
        else:
            try:
                os.mkdir(os.fsencode(operand))
            except OSError as e:
                _diagnose(operand, e)
                all_ok = False

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
