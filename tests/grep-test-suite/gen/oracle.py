#!/usr/bin/env python3
"""Run a real GNU grep as the oracle for one new_grep case.

**Offline only. Never copied into an agent-visible bundle.**
`scripts/stage_test_bundle.py` builds a stage bundle from an explicit allowlist
that does not include `gen/`, so nothing here can reach a sandbox.

Why a real grep is a valid oracle
---------------------------------
The suite used to state that GNU grep could not serve as ground truth because
`new_grep`'s PATTERN is a literal byte string rather than a regular expression.
That reasoning was incomplete: `grep -F` (`--fixed-strings`) treats PATTERN as a
literal substring, which is exactly `new_grep`'s matching contract. Verified
against the live binary rather than assumed -- see "Oracle contract" in the
suite README for the recorded probe results.

Three invocation-level adjustments make a live grep speak `new_grep`'s contract.
Each was confirmed empirically, and each is a flag or an environment pin rather
than a fudge of the output:

``-a``    `new_grep` treats NUL bytes as ordinary data. Plain `grep -F`
          suppresses a matching line in a file containing NUL and reports
          "binary file matches" instead -- on stdout in grep 3.0, on stderr in
          3.12. `-a`/`--text` restores line output with the NUL bytes intact,
          and changes nothing for a file that has none (probe 2: byte-identical
          stdout and exit status for text input).

``-F``    PATTERN is a literal byte string: `.`, `*`, `[`, `^`, `$` and `\\` are
          data (probe 1).

``LC_ALL=C``
          `new_grep`'s `-i` folds ASCII `A`-`Z` only. Under `C.UTF-8` a live
          grep also folds multibyte pairs (probe 5 saw U+00C9/U+00E9 fold), which
          would violate the contract. `C` gives exactly ASCII folding, and it
          also keeps a file of invalid UTF-8 from being classed as binary.

`-r` is deliberately NOT passed through
---------------------------------------
GNU grep's own `-r` walk follows raw `readdir` order. Probe 4 saw two different
orders for the same tree on two hosts, and neither matched `new_grep`'s
contract (pre-order, ascending byte order of entry name). Freezing goldens from
`grep -r` would bake one filesystem's directory order into the benchmark.

So the traversal is computed here -- from the contract -- and the oracle is
invoked once per resulting file, non-recursively. Every byte of every emitted
line still comes from the live grep; only the order in which files are visited
comes from the contract. That is the one thing `grep -r` is not authoritative
about.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE_ROOT.parent))

from reference_generators import grep_reference as reference  # noqa: E402

# The environment every oracle invocation runs under. LC_ALL pins ASCII-only
# folding; the rest keeps a user's locale settings from leaking in through the
# back door (LC_CTYPE alone is enough to re-enable multibyte folding).
ORACLE_ENV = {"LC_ALL": "C", "LANG": "C", "LC_CTYPE": "C", "LC_COLLATE": "C"}

# Cases the live oracle cannot produce, with the reason each one is exempt.
# These are genuine, unavoidable disagreements between GNU grep and new_grep's
# stated contract -- not something a flag or a locale pin fixes -- so the
# specification model stays authoritative for them and generation records why.
# Anything NOT listed here must agree with the oracle byte for byte, and
# generation fails loudly when it does not.
MODEL_ONLY: dict[str, str] = {
    "base-stdin-dash-is-an-operand-name":
        "GNU grep reads standard input for the operand '-'; new_grep's contract "
        "makes '-' an ordinary pathname, so the two disagree by design and no "
        "flag reconciles them",
}

# Why an argument-grammar case is model-only. new_grep implements five options
# and rejects everything else; GNU grep implements dozens, so a case asserting
# that an option is REJECTED is a statement about new_grep's bounded option set
# rather than about fixed-string matching. Every `absent_flags` case is of this
# kind: at checkpoint 000 `-H` must be an unknown option, and no real grep will
# ever say so.
GRAMMAR_REASON = (
    "argument-grammar case: it asserts which options new_grep accepts or "
    "rejects, which is a property of the bounded utility rather than of "
    "fixed-string matching -- GNU grep implements a different option set"
)


class OracleFailure(RuntimeError):
    """The oracle could not be run for a case at all."""


@dataclass
class Result:
    stdout: bytes
    subjects: list[str]
    exit_code: int


def model_only_reason(definition: dict) -> str | None:
    """Why this case must keep its model-derived golden, or None."""
    if definition["name"] in MODEL_ONLY:
        return MODEL_ONLY[definition["name"]]
    if definition.get("absent_flags"):
        return GRAMMAR_REASON
    try:
        reference.parse_args(list(definition["args"]),
                            _implemented(definition))
    except reference.UsageError:
        return GRAMMAR_REASON
    return None


def _implemented(definition: dict) -> set[str] | None:
    absent = set(definition.get("absent_flags") or [])
    if not absent:
        return None
    return set(reference.FEATURE_FLAG.values()) - absent


# ---------------------------------------------------------------------------
# Fixture materialization
# ---------------------------------------------------------------------------


def materialize(fixture: list[dict] | None, root: Path) -> None:
    """Write a case's fixture to a real filesystem.

    Directories are created before their contents and modes are applied after
    everything inside them exists, so a 0000 directory does not lock out its own
    population step.
    """
    entries = list(fixture or [])
    for entry in entries:
        target = root / entry["path"].rstrip("/")
        if entry["type"] == "dir":
            target.mkdir(parents=True, exist_ok=True)
        elif entry["type"] == "file":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(entry.get("contents", b""))
        elif entry["type"] == "symlink":
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(entry["target"], target)
        else:
            raise OracleFailure(f"unknown fixture type: {entry['type']!r}")

    # Deepest first: a parent's mode must not be applied before its children.
    for entry in sorted(entries, key=lambda e: -e["path"].count("/")):
        if entry["type"] == "symlink" or "mode" not in entry:
            continue
        os.chmod(root / entry["path"].rstrip("/"), int(entry["mode"], 8))


def restore_modes(fixture: list[dict] | None, root: Path) -> None:
    """Make the tree deletable again after a 0000 entry."""
    for entry in reversed(list(fixture or [])):
        if entry["type"] == "symlink":
            continue
        path = root / entry["path"].rstrip("/")
        if path.exists():
            os.chmod(path, 0o755 if entry["type"] == "dir" else 0o644)


# ---------------------------------------------------------------------------
# Contract-ordered traversal (see the module docstring)
# ---------------------------------------------------------------------------


def walk(root: Path, operand: str) -> list[str]:
    """Files under `operand`, pre-order, ascending byte order of entry name.

    Symlinks met during the walk are skipped rather than followed, which is both
    new_grep's contract and what GNU grep -r does (probe 4 confirmed a symlink
    to a file is not read and a symlink to a directory is not descended).
    """
    found: list[str] = []

    def descend(relative: str) -> None:
        directory = root / relative
        try:
            names = os.listdir(directory)
        except OSError as error:
            raise OracleFailure(f"cannot list {relative}: {error}") from error
        for name in sorted(names,
                           key=lambda n: n.encode("utf-8", "surrogateescape")):
            child = f"{relative.rstrip('/')}/{name}" if relative else name
            full = root / child
            if full.is_symlink():
                continue
            if full.is_dir():
                descend(child)
            else:
                found.append(child)

    descend(operand)
    return found


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


def _invoke(binary: str, arguments: list[str], *, cwd: Path,
            stdin: bytes | None) -> tuple[int, bytes, bytes]:
    try:
        completed = subprocess.run(
            [binary, *arguments], cwd=cwd,
            input=stdin if stdin is not None else b"",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, **ORACLE_ENV}, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleFailure(f"cannot run {binary}: {error}") from error
    if completed.returncode not in (0, 1, 2):
        raise OracleFailure(
            f"{binary} exited {completed.returncode} "
            f"(args={arguments!r}); a signal or a broken build"
        )
    return completed.returncode, completed.stdout, completed.stderr


def _base_arguments(options: reference.Options, prefix: bool) -> list[str]:
    """The flags that make a live grep speak new_grep's contract.

    -H/-h is resolved to the decision the contract already made rather than
    replayed argument by argument: both implementations let the last one win
    (probe 6), so passing the outcome is equivalent and keeps the prefix a
    single decision made in one place.
    """
    arguments = ["-a", "-F"]
    if options.ignore_case:
        arguments.append("-i")
    arguments.append("-H" if prefix else "-h")
    return arguments


def run_case(binary: str, definition: dict, root: Path) -> Result:
    """Derive one case's expected stdout, subjects and exit status from grep."""
    options = reference.parse_args(list(definition["args"]))
    filesystem = {}  # only needed for the prefix decision, built from fixture
    for entry in definition.get("fixture") or []:
        kind = entry["type"]
        filesystem[entry["path"].rstrip("/")] = reference.Entry(
            kind=kind,
            contents=entry.get("contents", b""),
            target=entry.get("target", ""),
        )
    prefix = reference.prefix_filenames(options, filesystem)
    arguments = _base_arguments(options, prefix)
    pattern = options.pattern.decode("utf-8", "surrogateescape")

    # No operands: standard input. GNU grep labels it "(standard input)" under
    # -H, which is the same name the contract uses (probe 6).
    if not options.operands:
        code, out, err = _invoke(
            binary, [*arguments, "-e", pattern, "--"],
            cwd=root, stdin=definition.get("stdin") or b"",
        )
        return Result(out, ["stdin"] if err else [], code)

    stdout = bytearray()
    subjects: list[str] = []
    selected = False
    errored = False

    for operand in options.operands:
        target = root / operand.rstrip("/")
        if options.recursive and target.is_dir() and not target.is_symlink():
            members = walk(root, operand.rstrip("/"))
            for member in members:
                code, out, err = _invoke(
                    binary, [*arguments, "-e", pattern, "--", member],
                    cwd=root, stdin=None,
                )
                stdout.extend(out)
                selected |= code == 0
                if code == 2 or err:
                    errored = True
                    subjects.append(member)
            continue

        code, out, err = _invoke(
            binary, [*arguments, "-e", pattern, "--", operand],
            cwd=root, stdin=None,
        )
        stdout.extend(out)
        selected |= code == 0
        if code == 2 or err:
            errored = True
            subjects.append(operand)

    if errored:
        return Result(bytes(stdout), subjects, reference.EXIT_ERROR)
    return Result(
        bytes(stdout), subjects,
        reference.EXIT_MATCH if selected else reference.EXIT_NO_MATCH,
    )


# ---------------------------------------------------------------------------
# Fitness: does this binary, on this filesystem, behave the way the contract
# needs BEFORE anything is regenerated?
# ---------------------------------------------------------------------------
#
# The right version string is not enough. Every probe below corresponds to a
# way a live grep or a live filesystem was observed to disagree with the
# contract, and each one, left unchecked, would have silently frozen a wrong
# golden rather than failed:
#
#   * Git-for-Windows grep 3.0 opens files in text mode: a CR before the line
#     terminator is dropped from its output, so `base-stdin-crlf-retains-cr`
#     would freeze `needle here\n` instead of `needle here\r\n`.
#   * The same build aborts (SIGABRT) under `LC_ALL=C -i`, which is the exact
#     combination checkpoint 004 is frozen under.
#   * On a filesystem that ignores mode 0000 -- any NTFS checkout -- the two
#     unreadable-file cases would freeze a successful read where the contract
#     says EACCES, turning a fault case into a passing one.
#   * As root, permission bits are ignored for the same reason.


def precheck(binary: str, workdir: Path) -> list[str]:
    """Every reason this binary/filesystem pair must not freeze goldens.

    Empty list means fit. Reported all at once, like oracle_contract.verify, so
    one run tells the whole story.
    """
    problems: list[str] = []
    probe = workdir / "precheck"
    probe.mkdir(parents=True, exist_ok=True)

    def grep(arguments: list[str], stdin: bytes | None = None):
        try:
            return _invoke(binary, arguments, cwd=probe, stdin=stdin)
        except OracleFailure as error:
            problems.append(f"probe failed to run: {error}")
            return None

    # 1. -F makes PATTERN a literal byte string. This is the whole premise of
    #    using grep as new_grep's oracle, so it is checked rather than assumed.
    (probe / "meta.txt").write_bytes(b"a.c\nabc\n[x]\nx\n^s\ns\ne$\ne\n")
    for pattern, expected in (("a.c", b"a.c\n"), ("[x]", b"[x]\n"),
                              ("^s", b"^s\n"), ("e$", b"e$\n")):
        got = grep(["-a", "-F", "-h", "-e", pattern, "--", "meta.txt"])
        if got and got[1] != expected:
            problems.append(
                f"-F did not treat {pattern!r} as literal bytes: got "
                f"{got[1]!r}, want {expected!r}. PATTERN must not be a regex."
            )

    # 2. -a makes NUL ordinary data, and changes nothing for text.
    (probe / "nul.txt").write_bytes(b"alpha\nbe\x00ta\n")
    got = grep(["-a", "-F", "-h", "-e", "ta", "--", "nul.txt"])
    if got and got[1] != b"be\x00ta\n":
        problems.append(
            f"-a did not print the NUL-bearing line verbatim: got {got[1]!r}. "
            "new_grep's contract has no binary-file suppression."
        )
    (probe / "text.txt").write_bytes(b"alpha\nbeta\n")
    plain = grep(["-F", "-h", "-e", "a", "--", "text.txt"])
    texty = grep(["-a", "-F", "-h", "-e", "a", "--", "text.txt"])
    if plain and texty and (plain[0], plain[1]) != (texty[0], texty[1]):
        problems.append(
            "-a changed the result for a plain text file "
            f"({plain[1]!r} vs {texty[1]!r}); it must only disable binary "
            "suppression."
        )

    # 3. An unterminated final line is still emitted with a newline.
    (probe / "nonl.txt").write_bytes(b"first\nlast-no-newline")
    got = grep(["-a", "-F", "-h", "-e", "last", "--", "nonl.txt"])
    if got and got[1] != b"last-no-newline\n":
        problems.append(
            f"a match on an unterminated final line produced {got[1]!r}; the "
            "contract requires every emitted line to end with a newline."
        )

    # 4. Byte fidelity. A CR before the terminator is data, not formatting.
    (probe / "crlf.txt").write_bytes(b"needle here\r\nplain\r\n")
    got = grep(["-a", "-F", "-h", "-e", "needle", "--", "crlf.txt"])
    if got and got[1] != b"needle here\r\n":
        problems.append(
            f"CR was not preserved: got {got[1]!r}, want b'needle here\\r\\n'. "
            "This build is not byte-exact (a text-mode build such as "
            "Git-for-Windows grep drops CR), so it cannot freeze byte-level "
            "goldens."
        )

    # 5. LC_ALL=C folds ASCII A-Z and nothing else. The multibyte pair is the
    #    one a UTF-8 locale folds, so this catches a leaked LC_CTYPE too.
    (probe / "fold.txt").write_bytes(
        b"ASCII-Iota\nascii-iota\nCAFE-\xc3\x89\ncafe-\xc3\xa9\n"
    )
    got = grep(["-a", "-F", "-i", "-h", "-e", "IOTA", "--", "fold.txt"])
    if got and got[1] != b"ASCII-Iota\nascii-iota\n":
        problems.append(
            f"-i under LC_ALL=C did not fold ASCII as expected: got {got[1]!r}."
        )
    # U+00C9 / U+00E9 are the pair a UTF-8 locale folds together and LC_ALL=C
    # does not. Written as bytes so this file's own encoding cannot change the
    # probe: the uppercase line must match and the lowercase one must not.
    multibyte = b"\xc3\x89".decode("utf-8")
    got = grep(["-a", "-F", "-i", "-h", "-e", multibyte, "--", "fold.txt"])
    if got and got[1] != b"CAFE-\xc3\x89\n":
        problems.append(
            f"-i folded a multibyte pair: got {got[1]!r}, want only the "
            "uppercase line. new_grep folds A-Z only, so the oracle must run "
            "under LC_ALL=C with no LC_CTYPE leaking in."
        )

    # 6. The stdin label under -H is the name the contract uses.
    got = grep(["-a", "-F", "-H", "-e", "alpha", "--"], stdin=b"alpha\n")
    if got and got[1] != b"(standard input):alpha\n":
        problems.append(
            f"-H labelled standard input {got[1]!r}; the contract calls it "
            "'(standard input)'."
        )

    problems.extend(filesystem_precheck(probe))
    return problems


def filesystem_precheck(root: Path) -> list[str]:
    """The fixture capabilities the fault cases depend on.

    A missing capability here does not make a golden merely stale; it makes it
    WRONG in the direction that looks like a pass, which is why this refuses
    rather than warns.
    """
    problems: list[str] = []

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        problems.append(
            "running as root: permission bits are ignored, so the "
            "unreadable-file cases would freeze a successful read where the "
            "contract requires EACCES. Regenerate as an ordinary user."
        )

    locked = root / "locked-probe.txt"
    locked.write_bytes(b"alpha\n")
    try:
        os.chmod(locked, 0o000)
        try:
            locked.read_bytes()
            problems.append(
                "this filesystem ignores mode 0000 (the probe file was still "
                "readable), so the unreadable-file cases cannot be produced "
                "here. Regenerate on a POSIX filesystem."
            )
        except OSError:
            pass
    finally:
        os.chmod(locked, 0o644)

    link = root / "link-probe"
    try:
        os.symlink(locked.name, link)
        link.unlink()
    except OSError as error:
        problems.append(
            f"cannot create a symbolic link here ({error}), so the "
            "symlink cases cannot be produced. Regenerate on a filesystem "
            "that supports symlinks."
        )

    return problems


def _main(argv: list[str] | None = None) -> int:
    """`python3 gen/oracle.py --oracle-bin BIN` -- the precheck, standalone.

    Separate from gen/generate.py so selfcheck.sh can ask "is this host fit to
    regenerate?" without regenerating anything.
    """
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description=precheck.__doc__)
    parser.add_argument("--oracle-bin", required=True)
    arguments = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as temp:
        problems = precheck(arguments.oracle_bin, Path(temp))
    for problem in problems:
        print(f"oracle precheck: {problem}", file=sys.stderr)
    if not problems:
        print(f"oracle precheck: {arguments.oracle_bin} is fit to freeze "
              "this suite's goldens")
    return 2 if problems else 0


if __name__ == "__main__":
    raise SystemExit(_main())
