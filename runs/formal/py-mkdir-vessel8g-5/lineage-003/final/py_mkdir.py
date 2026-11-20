#!/usr/bin/env python3
"""Create directories (mkdir with -p and -m)."""

import os
import stat
import sys


def _stderr(data: bytes) -> None:
    os.write(2, data)


# --- Mode constants ---

_S_IRUSR = 0o400
_S_IWUSR = 0o200
_S_IXUSR = 0o100
_S_IRGRP = 0o040
_S_IWGRP = 0o020
_S_IXGRP = 0o010
_S_IROTH = 0o004
_S_IWOTH = 0o002
_S_IXOTH = 0o001
_S_ISUID = 0o4000
_S_ISGID = 0o2000
_S_ISVTX = 0o1000

_WHO_U = 0o700
_WHO_G = 0o070
_WHO_O = 0o007
_WHO_A = 0o777

_ALL_SPECIAL = 0o7000


def _parse_numeric(s: str) -> int:
    if not s:
        raise ValueError("empty mode")
    if any(c not in '01234567' for c in s):
        raise ValueError(f"invalid mode '{s}'")
    val = int(s, 8)
    if val > 0o7777:
        raise ValueError(f"invalid mode '{s}'")
    return val


def _is_sticky_only(mode_str: str) -> bool:
    """True if the symbolic expression contains only 't' as permissions
    (no r, w, x, X, s, or copy chars). GNU uses base 0755 for this case."""
    has_t = False
    for clause in mode_str.split(','):
        if not clause:
            return False
        i = 0
        while i < len(clause) and clause[i] in 'ugoa':
            i += 1
        if i < len(clause) and clause[i] in '+-=':
            i += 1
        while i < len(clause):
            c = clause[i]
            if c == 't':
                has_t = True
            elif c in 'rwxXs' or c in 'ugo':
                return False
            i += 1
    return has_t


def _parse_mode(mode_str: str, umask: int) -> int:
    """Parse a mode string (numeric or symbolic) and return the resulting mode."""
    if not mode_str:
        raise ValueError("invalid mode ''")
    if mode_str[0] in '01234567':
        return _parse_numeric(mode_str)
    return _parse_symbolic(mode_str, umask)


def _parse_symbolic(mode_str: str, umask: int) -> int:
    base = 0o755 if _is_sticky_only(mode_str) else 0o777
    mode = base
    for clause in mode_str.split(','):
        if not clause:
            raise ValueError(f"invalid mode '{mode_str}'")
        mode = _apply_clause(mode, clause, umask)
    return mode & 0o7777


def _apply_clause(mode: int, clause: str, umask: int) -> int:
    i = 0
    who_omitted = True
    who_sel = 0

    # Parse who (one or more of u, g, o, a)
    while i < len(clause) and clause[i] in 'ugoa':
        who_omitted = False
        who_sel |= {'u': _WHO_U, 'g': _WHO_G, 'o': _WHO_O, 'a': _WHO_A}[clause[i]]
        i += 1

    if who_omitted:
        who_sel = _WHO_A

    # Parse operator
    if i >= len(clause) or clause[i] not in '+-=':
        raise ValueError(f"invalid mode clause '{clause}'")
    op = clause[i]
    i += 1

    # Parse permissions
    perm_rwx = 0
    special = 0
    copy_src = 0
    saw_copy = False

    while i < len(clause):
        c = clause[i]
        if c == 'r':
            perm_rwx |= 0o444
        elif c == 'w':
            perm_rwx |= 0o222
        elif c in 'xX':
            perm_rwx |= 0o111
        elif c == 's':
            if who_sel & _WHO_U:
                special |= _S_ISUID
            if who_sel & _WHO_G:
                special |= _S_ISGID
        elif c == 't':
            special |= _S_ISVTX
        elif c in 'ugo':
            saw_copy = True
            copy_src |= {'u': _WHO_U, 'g': _WHO_G, 'o': _WHO_O}[c]
        else:
            raise ValueError(f"invalid mode clause '{clause}'")
        i += 1

    if saw_copy and (perm_rwx or special):
        raise ValueError(f"invalid mode clause '{clause}'")

    # Compute effective permission bits to modify
    if saw_copy:
        src_rwx = 0
        if copy_src & 0o700:
            src_rwx |= (mode & 0o700) >> 6
        if copy_src & 0o070:
            src_rwx |= (mode & 0o070) >> 3
        if copy_src & 0o007:
            src_rwx |= mode & 0o007

        perm_bits = 0
        if who_sel & 0o700:
            perm_bits |= src_rwx << 6
        if who_sel & 0o070:
            perm_bits |= src_rwx << 3
        if who_sel & 0o007:
            perm_bits |= src_rwx
        spec = 0
    else:
        perm_bits = perm_rwx & who_sel
        spec = special

    # Umask filtering for omitted who (ordinary rwx bits only)
    if who_omitted:
        perm_bits &= ~umask

    # Apply operator
    if op == '+':
        mode |= perm_bits
        mode |= spec
    elif op == '-':
        mode &= ~perm_bits
        mode &= ~spec
    elif op == '=':
        mode &= ~who_sel
        mode |= perm_bits
        if who_sel & _WHO_U:
            mode = (mode & ~_S_ISUID) | (spec & _S_ISUID)
        if who_sel & _WHO_G:
            mode = (mode & ~_S_ISGID) | (spec & _S_ISGID)
        if who_sel & _WHO_O:
            mode = (mode & ~_S_ISVTX) | (spec & _S_ISVTX)

    return mode & 0o7777


def _create_dir_with_mode(path: bytes, desired_mode: int) -> None:
    """Create a directory and set its mode exactly to desired_mode."""
    os.mkdir(path, 0o777)
    os.chmod(path, desired_mode)


def _ensure_intermediate(prefix: bytes, umask: int) -> None:
    if os.path.lexists(prefix):
        if not os.path.isdir(prefix):
            raise NotADirectoryError(prefix)
        return
    os.mkdir(prefix, 0o777)
    st = os.lstat(prefix)
    os.chmod(prefix, stat.S_IMODE(st.st_mode) | 0o700)


def _ensure_final(path: bytes, umask: int, mode: int | None) -> None:
    if os.path.lexists(path):
        if not os.path.isdir(path):
            raise FileExistsError(path)
        return
    if mode is not None:
        _create_dir_with_mode(path, mode)
    else:
        os.mkdir(path, 0o777)


def _create_parents(path: bytes, umask: int) -> None:
    normalized = os.path.normpath(path)
    parts = [p for p in normalized.split(b'/') if p not in (b'', b'.')]
    if len(parts) <= 1:
        return
    prefix = b''
    for comp in parts[:-1]:
        if not prefix:
            prefix = comp
        else:
            prefix = prefix + b'/' + comp
        _ensure_intermediate(prefix, umask)


def main() -> None:
    argv = sys.argv[1:]

    parents = False
    mode_str: str | None = None
    operands: list[str] = []
    saw_terminator = False
    error: bytes | None = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if saw_terminator:
            operands.append(arg)
        elif arg == '--':
            saw_terminator = True
        elif arg == '-':
            operands.append(arg)
        elif arg == '-p' or arg == '--parents':
            parents = True
        elif arg == '-m':
            i += 1
            if i >= len(argv):
                error = (b"mkdir: option requires an argument -- 'm'\n"
                         b"Try 'mkdir --help' for more information.\n")
                break
            mode_str = argv[i]
        elif arg.startswith('-m') and len(arg) > 2 and not arg.startswith('--'):
            mode_str = arg[2:]
        elif arg == '--mode':
            i += 1
            if i >= len(argv):
                error = (b"mkdir: option '--mode' requires an argument\n"
                         b"Try 'mkdir --help' for more information.\n")
                break
            mode_str = argv[i]
        elif arg.startswith('--mode='):
            mode_str = arg[7:]
        elif arg.startswith('--'):
            error = (
                b"mkdir: unrecognized option '"
                + os.fsencode(arg)
                + b"'\nTry 'mkdir --help' for more information.\n"
            )
            break
        elif arg.startswith('-'):
            error = (
                b"mkdir: invalid option -- '"
                + os.fsencode(arg[1])
                + b"'\nTry 'mkdir --help' for more information.\n"
            )
            break
        else:
            operands.append(arg)
        i += 1

    if error is not None:
        _stderr(error)
        sys.exit(1)

    if not operands:
        _stderr(b"mkdir: missing operand\nTry 'mkdir --help' for more information.\n")
        sys.exit(1)

    # Validate and compute mode before any mutation
    computed_mode: int | None = None
    if mode_str is not None:
        try:
            umask_val = os.umask(0)
            os.umask(umask_val)
            computed_mode = _parse_mode(mode_str, umask_val)
        except ValueError:
            _stderr(b"mkdir: invalid mode '"
                    + os.fsencode(mode_str)
                    + b"'\n")
            sys.exit(1)

    # Get umask for intermediate directory creation
    umask_val = os.umask(0)
    os.umask(umask_val)

    any_failed = False
    for operand in operands:
        path = os.fsencode(operand)
        try:
            if parents:
                _create_parents(path, umask_val)
                _ensure_final(path, umask_val, computed_mode)
            else:
                if computed_mode is not None:
                    _create_dir_with_mode(path, computed_mode)
                else:
                    os.mkdir(path, 0o777)
        except OSError as e:
            if e.errno is not None:
                err_str = os.strerror(e.errno).encode('utf-8')
            else:
                err_str = b"Unknown error"
            msg = (
                b"mkdir: cannot create directory '"
                + os.fsencode(operand)
                + b"': "
                + err_str
                + b"\n"
            )
            _stderr(msg)
            any_failed = True

    sys.exit(1 if any_failed else 0)


if __name__ == '__main__':
    main()
