#!/usr/bin/env python3
"""mkdir: Create directories (checkpoint 002)."""

import os
import stat
import sys


def _fail(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.write("Try 'mkdir --help' for more information.\n")
    sys.exit(1)


def _invalid_mode(value: str) -> None:
    sys.stderr.write(f"mkdir: invalid mode '{value}'\n")
    sys.exit(1)


def _missing_mode_arg(short: bool) -> None:
    if short:
        sys.stderr.write("mkdir: option requires an argument -- 'm'\n")
    else:
        sys.stderr.write("mkdir: option '--mode' requires an argument\n")
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


def _get_umask() -> int:
    umask = os.umask(0)
    os.umask(umask)
    return umask


# --- Symbolic mode parsing ---

def _parse_symbolic(expr: str) -> int:
    """Parse a full symbolic mode expression; return final mode int."""
    umask = _get_umask()
    ordinary = 0o777
    special = 0
    for clause in expr.split(','):
        if not clause:
            raise ValueError("empty clause")
        ordinary, special = _apply_clause(clause, ordinary, special, umask)

    # GNU special-bit-only rule: if the expression contains only s/t
    # (no r/w/x/X) and every clause uses omitted-who or who=a,
    # the ordinary result is 0755 regardless of umask.
    if not any(c in expr for c in 'rwxX') and any(c in expr for c in 'st'):
        all_omitted_or_a = True
        for clause in expr.split(','):
            if not clause:
                continue
            i = 0
            while i < len(clause) and clause[i] in 'ugoa':
                if clause[i] in 'ugo':
                    all_omitted_or_a = False
                    break
                i += 1
            if not all_omitted_or_a:
                break
        if all_omitted_or_a:
            ordinary = 0o755

    return ordinary | special


def _apply_clause(clause: str, ordinary: int, special: int, umask: int):
    i = 0
    who_set = set()
    while i < len(clause) and clause[i] in 'ugoa':
        who_set.add(clause[i])
        i += 1

    who_explicit = bool(who_set)
    if 'a' in who_set:
        who_mask = 0o777
    elif who_explicit:
        who_mask = 0
        if 'u' in who_set:
            who_mask |= 0o700
        if 'g' in who_set:
            who_mask |= 0o070
        if 'o' in who_set:
            who_mask |= 0o007
    else:
        who_mask = 0o777

    rest = clause[i:]
    if not rest or rest[0] not in '+-=':
        raise ValueError(f"bad clause: {clause!r}")
    op = rest[0]
    rest = rest[1:]

    # Special bits cleared on '=' for this who
    eq_clear = 0
    if 'u' in who_set or 'a' in who_set or not who_explicit:
        eq_clear |= 0o4000
    if 'g' in who_set or 'a' in who_set or not who_explicit:
        eq_clear |= 0o2000
    if 'o' in who_set or 'a' in who_set or not who_explicit:
        eq_clear |= 0o1000

    if not rest:
        if op == '=':
            ordinary &= ~who_mask
            special &= ~eq_clear
        return ordinary, special

    # Permission copy (single u/g/o after operator)
    if len(rest) == 1 and rest in 'ugo':
        return _apply_copy(op, rest, who_mask, who_explicit, ordinary, umask, eq_clear, special)

    # Regular permission chars
    req_r = 'r' in rest
    req_w = 'w' in rest
    req_x = ('x' in rest) or ('X' in rest)
    req_s = 's' in rest
    req_t = 't' in rest

    if not (req_r or req_w or req_x or req_s or req_t):
        raise ValueError(f"bad permission: {clause!r}")

    ord_bits = 0
    if req_r:
        ord_bits |= 0o444
    if req_w:
        ord_bits |= 0o222
    if req_x:
        ord_bits |= 0o111
    ord_bits &= who_mask

    spec_bits = 0
    if req_s:
        if 'u' in who_set:
            spec_bits |= 0o4000
        if 'g' in who_set:
            spec_bits |= 0o2000
        if 'a' in who_set or not who_explicit:
            spec_bits |= 0o6000
    if req_t:
        if 'o' in who_set or 'a' in who_set or not who_explicit:
            spec_bits |= 0o1000

    if op == '+':
        if who_explicit:
            ordinary |= ord_bits
        else:
            ordinary |= (ord_bits & ~umask)
        special |= spec_bits
    elif op == '-':
        if who_explicit:
            ordinary &= ~ord_bits
        else:
            ordinary &= ~(ord_bits & ~umask)
        special &= ~spec_bits
    else:  # '='
        if who_explicit:
            ordinary = (ordinary & ~who_mask) | ord_bits
        else:
            ordinary = ord_bits & ~umask
        special = (special & ~eq_clear) | spec_bits

    return ordinary, special


def _apply_copy(op, source, who_mask, who_explicit, ordinary, umask, eq_clear, special):
    if source == 'u':
        pattern = (ordinary >> 6) & 0o7
    elif source == 'g':
        pattern = (ordinary >> 3) & 0o7
    else:
        pattern = ordinary & 0o7

    target = 0
    if who_mask & 0o700:
        target |= pattern << 6
    if who_mask & 0o070:
        target |= pattern << 3
    if who_mask & 0o007:
        target |= pattern

    if op == '+':
        if who_explicit:
            ordinary |= target
        else:
            ordinary |= (target & ~umask)
    elif op == '-':
        if who_explicit:
            ordinary &= ~target
        else:
            ordinary &= ~(target & ~umask)
    else:
        if who_explicit:
            ordinary = (ordinary & ~who_mask) | target
        else:
            ordinary = target & ~umask
        special &= ~eq_clear

    return ordinary, special


# --- Numeric mode parsing ---

def _parse_numeric(value: str) -> tuple[int, bool]:
    """Return (mode_value, enforce_exact). enforce_exact=True means 5+ digits."""
    mode = int(value, 8)
    if mode > 0o7777:
        raise ValueError(f"out of range: {value}")
    enforce_exact = len(value) >= 5
    return mode, enforce_exact


# --- Unified mode parser ---

def _parse_mode(value: str) -> tuple[int, bool]:
    """Parse mode string. Returns (mode_int, enforce_exact).
    enforce_exact: True if we must chmod to the exact value (5+ digit numeric
    or symbolic). False if 4-or-fewer digit numeric (preserve inherited special)."""
    if not value:
        raise ValueError("empty mode")
    if all(c in '01234567' for c in value):
        return _parse_numeric(value)
    mode = _parse_symbolic(value)
    return mode, True


# --- Directory creation ---

def _create_dir(path_bytes: bytes, mode: int | None, enforce_exact: bool,
                umask: int) -> None:
    """Create a single directory. mode=None means use default (0o777 & ~umask)."""
    if mode is None:
        os.mkdir(path_bytes, 0o777)
    else:
        os.mkdir(path_bytes, 0o777)
        if enforce_exact:
            os.chmod(path_bytes, mode)
        else:
            # Preserve inherited special bits (e.g. setgid from parent)
            st = os.lstat(path_bytes)
            inherited_special = st.st_mode & 0o7000
            requested_special = mode & 0o7000
            # Keep requested special bits + inherited bits not explicitly set
            final = (mode & 0o777) | requested_special | (inherited_special & ~requested_special)
            os.chmod(path_bytes, final)


def _mkdir_p(operand: str, mode: int | None, enforce_exact: bool,
             umask: int) -> bool:
    raw = os.fsencode(operand)
    parts = [p for p in raw.split(b'/') if p]
    if not parts:
        # Empty or just slashes — try to create at cwd
        try:
            _create_dir(raw, mode, enforce_exact, umask)
        except OSError as e:
            _diagnose(operand, e)
            return False
        return True

    last = len(parts) - 1
    for i, part in enumerate(parts):
        prefix = b'/'.join(parts[:i + 1])
        is_final = (i == last)
        try:
            st = os.lstat(prefix)
        except OSError:
            try:
                if is_final and mode is not None:
                    _create_dir(prefix, mode, enforce_exact, umask)
                else:
                    _create_dir(prefix, None, False, umask)
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


def _mkdir_simple(operand: str, mode: int | None, enforce_exact: bool,
                  umask: int) -> bool:
    raw = os.fsencode(operand)
    try:
        _create_dir(raw, mode, enforce_exact, umask)
    except OSError as e:
        _diagnose(operand, e)
        return False
    return True


def main() -> None:
    argv = sys.argv[1:]

    operands: list[str] = []
    seen_ddash = False
    unknown_opt: str | None = None
    parents = False
    mode_str: str | None = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if seen_ddash:
            operands.append(arg)
        elif arg == "--":
            seen_ddash = True
        elif arg == "-":
            operands.append(arg)
        elif arg.startswith("--"):
            if arg == "--parents" or arg == "-p":
                parents = True
            elif arg == "--mode":
                if i + 1 >= len(argv):
                    _missing_mode_arg(False)
                i += 1
                mode_str = argv[i]
            elif arg.startswith("--mode="):
                mode_str = arg[len("--mode="):]
            elif unknown_opt is None:
                unknown_opt = arg
        elif arg.startswith("-"):
            if arg == "-p":
                parents = True
            elif arg.startswith("-m") and len(arg) > 2:
                mode_str = arg[2:]
            elif arg == "-m":
                if i + 1 >= len(argv):
                    _missing_mode_arg(True)
                i += 1
                mode_str = argv[i]
            elif unknown_opt is None:
                unknown_opt = arg
        else:
            operands.append(arg)
        i += 1

    if unknown_opt is not None:
        opt = unknown_opt
        if opt.startswith("--"):
            _fail(f"mkdir: unrecognized option '{opt}'")
        else:
            ch = opt[1] if len(opt) > 1 else ""
            _fail(f"mkdir: invalid option -- '{ch}'")

    if not operands:
        _fail("mkdir: missing operand")

    # Parse mode before any mutation
    mode: int | None = None
    enforce_exact = False
    if mode_str is not None:
        try:
            mode, enforce_exact = _parse_mode(mode_str)
        except (ValueError, TypeError):
            _invalid_mode(mode_str)

    umask = _get_umask()

    all_ok = True
    for operand in operands:
        if parents:
            if not _mkdir_p(operand, mode, enforce_exact, umask):
                all_ok = False
        else:
            if not _mkdir_simple(operand, mode, enforce_exact, umask):
                all_ok = False

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
