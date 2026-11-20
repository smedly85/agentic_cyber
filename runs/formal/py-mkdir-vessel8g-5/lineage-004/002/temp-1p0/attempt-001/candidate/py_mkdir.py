#!/usr/bin/env python3
"""Create directories."""

import os
import stat
import sys


def _fail(path, msg):
    print(f"mkdir: cannot create directory '{path}': {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Numeric mode parsing
# ---------------------------------------------------------------------------

def _parse_numeric(s):
    """Parse a numeric mode string. Returns (value, num_digits).
    Raises ValueError on failure."""
    if not s:
        raise ValueError
    for ch in s:
        if ch not in '01234567':
            raise ValueError
    value = int(s, 8)
    if value > 0o7777:
        raise ValueError
    return value, len(s)


# ---------------------------------------------------------------------------
# Symbolic mode evaluation
# ---------------------------------------------------------------------------

def _parse_who(who_str):
    """Return (mask, explicit) for a who string like 'ug', 'a', 'o', or ''."""
    if not who_str:
        return 0o777, False
    mask = 0
    if 'u' in who_str:
        mask |= 0o700
    if 'g' in who_str:
        mask |= 0o070
    if 'o' in who_str:
        mask |= 0o007
    if 'a' in who_str:
        mask = 0o777
    return mask, True


def _perm_bits_from_chars(chars, who_str, who_explicit):
    """Compute the bit mask from permission characters (rwxXst)."""
    bits = 0
    for ch in chars:
        if ch == 'r':
            bits |= 0o444
        elif ch == 'w':
            bits |= 0o222
        elif ch == 'x' or ch == 'X':
            bits |= 0o111
        elif ch == 's':
            if who_explicit:
                if 'u' in who_str:
                    bits |= 0o4000
                if 'g' in who_str:
                    bits |= 0o2000
            else:
                bits |= 0o6000
        elif ch == 't':
            bits |= 0o1000
        else:
            raise ValueError(f"bad permission char {ch}")
    return bits


def _eval_symbolic(mode_str, umask):
    """Evaluate a symbolic mode expression.
    Returns (mode_0_7777, special_bits_addressed_mask)."""
    # GNU special-bit-only behavior: expressions containing only t
    # (no r, w, x, X, s) use 0755 as the ordinary-permission starting point,
    # so +t / a+t yield 0755+sticky regardless of umask.
    has_ordinary = any(c in mode_str for c in 'rwxX')
    sticky_only = ('t' in mode_str) and ('s' not in mode_str)
    if not has_ordinary and sticky_only:
        mode = 0o755
    else:
        mode = 0o777
    special_addressed = 0

    for clause in mode_str.split(','):
        if not clause:
            raise ValueError("empty clause")

        # Parse who
        i = 0
        while i < len(clause) and clause[i] in 'ugoa':
            i += 1
        who_str = clause[:i]
        who_mask, who_explicit = _parse_who(who_str)

        if i >= len(clause):
            raise ValueError("no operator")
        op = clause[i]
        if op not in '+-=':
            raise ValueError(f"bad operator {op}")
        i += 1

        if i >= len(clause):
            # Empty permissions (e.g. "o=", "a=", "=")
            if op != '=':
                raise ValueError("empty permissions with non-= op")
            perm_chars = ''
            is_copy = False
            copy_src = ''
        else:
            rest = clause[i:]
            # Check for permission-copy (single u/g/o with =)
            if len(rest) == 1 and rest in 'ugo' and op == '=':
                is_copy = True
                copy_src = rest
                perm_chars = ''
            else:
                is_copy = False
                copy_src = ''
                perm_chars = rest
                # Validate permission characters
                for ch in perm_chars:
                    if ch not in 'rwxXstugo':
                        raise ValueError(f"bad char {ch}")
                    if ch in 'ugo':
                        raise ValueError("copy only valid as sole perm with =")

        if is_copy:
            # Copy source class rwx to target classes
            if copy_src == 'u':
                src_bits = (mode >> 6) & 0o7
            elif copy_src == 'g':
                src_bits = (mode >> 3) & 0o7
            else:
                src_bits = mode & 0o7
            if who_mask & 0o700:
                mode = (mode & ~0o700) | (src_bits << 6)
            if who_mask & 0o070:
                mode = (mode & ~0o070) | (src_bits << 3)
            if who_mask & 0o007:
                mode = (mode & ~0o007) | src_bits
            continue

        # Compute permission bits
        perm_bits = _perm_bits_from_chars(perm_chars, who_str, who_explicit)
        ordinary = perm_bits & 0o777
        special = perm_bits & 0o7000
        has_s = 's' in perm_chars
        has_t = 't' in perm_chars

        if op == '+':
            if who_explicit:
                mode |= (ordinary & who_mask)
            else:
                mode |= (ordinary & ~umask & 0o777)
            mode |= special
            special_addressed |= special

        elif op == '-':
            if who_explicit:
                mode &= ~(ordinary & who_mask)
            else:
                mode &= ~(ordinary & ~umask & 0o777)
            mode &= ~special
            special_addressed |= special

        elif op == '=':
            if who_explicit:
                mode = (mode & ~who_mask) | (ordinary & who_mask)
            else:
                mode = (mode & ~0o777) | (ordinary & ~umask & 0o777)
            # Set special bits that were requested
            mode |= special
            special_addressed |= special
            # Sticky clearing: if who covers o and t was not requested, clear sticky
            covers_o = ('o' in who_str) or ('a' in who_str) or (not who_explicit)
            if covers_o and not has_t:
                mode &= ~0o1000
                special_addressed |= 0o1000

    return mode & 0o7777, special_addressed


# ---------------------------------------------------------------------------
# Mode resolution and application
# ---------------------------------------------------------------------------

def _resolve_mode(mode_str):
    """Validate and classify a mode string. Returns a spec tuple.
    Raises ValueError if invalid."""
    if not mode_str:
        raise ValueError("empty mode")
    # Try numeric
    if all(c in '01234567' for c in mode_str):
        value, ndigits = _parse_numeric(mode_str)
        return ('numeric', value, ndigits)
    # Must be symbolic – validate by dry-run with umask 0
    _eval_symbolic(mode_str, 0)
    return ('symbolic', mode_str)


def _apply_mode_to_path(path, mode_spec, umask):
    """Apply a mode spec to an already-created directory."""
    current = os.lstat(path).st_mode & 0o7777
    kind = mode_spec[0]

    if kind == 'numeric':
        _, value, ndigits = mode_spec
        if ndigits <= 4:
            final = (value & 0o777) | (current & 0o7000) | (value & 0o7000)
        else:
            final = value & 0o7777
        os.chmod(path, final & 0o7777)
    else:
        _, mode_str = mode_spec
        mode, special_addr = _eval_symbolic(mode_str, umask)
        # Special bits: use evaluated where addressed, preserve current elsewhere
        final_special = (mode & 0o7000 & special_addr) | (current & 0o7000 & ~special_addr)
        final = (mode & 0o777) | (final_special & 0o7000)
        os.chmod(path, final & 0o7777)


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------

def mkdir_plain(path, mode_spec, umask):
    """Create a single directory (no parent creation). Returns 0 or 1."""
    try:
        os.mkdir(path, 0o777)
    except OSError as e:
        msg = e.strerror if e.strerror else os.strerror(e.errno)
        _fail(path, msg)
        return 1
    if mode_spec is not None:
        try:
            _apply_mode_to_path(path, mode_spec, umask)
        except OSError:
            pass
    return 0


def mkdir_parents(path, mode_spec, umask):
    """Create path and all missing parent directories. Returns 0 or 1."""
    is_abs = os.path.isabs(path)
    parts = [p for p in path.split('/') if p and p != '.']

    if not parts:
        return 0

    current = ''
    last = len(parts) - 1
    for i, part in enumerate(parts):
        if current == '':
            current = ('/' if is_abs else '') + part
        else:
            current = current + '/' + part

        try:
            st = os.lstat(current)
        except OSError:
            # Does not exist – create it
            try:
                os.mkdir(current, 0o777)
            except OSError as e:
                msg = e.strerror if e.strerror else os.strerror(e.errno)
                _fail(path, msg)
                return 1
            if i != last:
                # Intermediate: ensure owner write+search
                try:
                    m = os.lstat(current).st_mode & 0o7777
                    if not (m & 0o300):
                        os.chmod(current, m | 0o300)
                except OSError:
                    pass
            else:
                # Final: apply explicit mode if given
                if mode_spec is not None:
                    try:
                        _apply_mode_to_path(current, mode_spec, umask)
                    except OSError:
                        pass
            continue

        # Path component exists
        if stat.S_ISDIR(st.st_mode):
            continue
        if stat.S_ISLNK(st.st_mode):
            try:
                if stat.S_ISDIR(os.stat(current).st_mode):
                    continue
            except OSError:
                pass
        _fail(path, "Not a directory")
        return 1

    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    operands = []
    seen_ddash = False
    parents = False
    mode_str = None
    parse_error = None

    i = 0
    while i < len(args):
        arg = args[i]
        if not seen_ddash:
            if arg == '--':
                seen_ddash = True
            elif arg == '-p':
                parents = True
            elif arg == '--parents':
                parents = True
            elif arg == '-m':
                if i + 1 >= len(args):
                    parse_error = "mkdir: invalid mode ''"
                    break
                i += 1
                mode_str = args[i]
            elif arg.startswith('-m') and len(arg) > 2:
                mode_str = arg[2:]
            elif arg == '--mode':
                if i + 1 >= len(args):
                    parse_error = "mkdir: invalid mode ''"
                    break
                i += 1
                mode_str = args[i]
            elif arg.startswith('--mode='):
                mode_str = arg[7:]
            elif arg == '-':
                operands.append(arg)
            elif arg.startswith('-'):
                if arg.startswith('--') and len(arg) > 2:
                    parse_error = f"mkdir: unrecognized option '{arg}'"
                else:
                    parse_error = f"mkdir: invalid option -- '{arg[1]}'"
                break
            else:
                operands.append(arg)
        else:
            operands.append(arg)
        i += 1

    if parse_error is not None:
        print(parse_error, file=sys.stderr)
        print("Try 'mkdir --help' for more information.", file=sys.stderr)
        sys.exit(1)

    if not operands:
        print("mkdir: missing operand", file=sys.stderr)
        print("Try 'mkdir --help' for more information.", file=sys.stderr)
        sys.exit(1)

    # Validate mode before any mutation
    mode_spec = None
    if mode_str is not None:
        try:
            mode_spec = _resolve_mode(mode_str)
        except ValueError:
            print(f"mkdir: invalid mode '{mode_str}'", file=sys.stderr)
            sys.exit(1)

    umask = os.umask(0)
    os.umask(umask)

    exit_code = 0
    for operand in operands:
        if parents:
            rc = mkdir_parents(operand, mode_spec, umask)
        else:
            rc = mkdir_plain(operand, mode_spec, umask)
        if rc != 0:
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
