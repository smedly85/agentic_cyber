#!/usr/bin/env python3
"""Curated case definitions for the new_grep suite.

Every case is written here as *inputs only* -- argv, an optional fixture, an
optional stdin payload, the flags it needs, and its tags. The expected stdout,
exit status and stderr class are never written by hand: gen/generate.py derives
them from tests/reference_generators/grep_reference.py, which is the executable form of the checkpoint
prompt contract. Hand-written expectations drift; derived ones cannot.

Cases are grouped by the checkpoint whose feature they need, and `flags` is what
makes cumulative filtering work: a case listing `["-r", "-i"]` runs only from
the checkpoint where both are implemented, while a case listing `[]` runs at
every checkpoint from 000 onward as regression coverage.
"""

from __future__ import annotations

ALPHA = b"alpha\nbeta\nGamma\ndelta alpha\n"
BETA = b"beta only\nnothing here\n"
MIXED = b"Alpha\nALPHA\nalpha\naLpHa\n"
BINARY = b"pre\x00needle\x00post\nplain\n\xff\xfeneedle\n"
NO_TRAILING = b"first needle\nsecond needle"
CRLF = b"needle here\r\nplain\r\n"


def file_entry(path: str, contents: bytes, mode: str | None = None) -> dict:
    entry = {"path": path, "type": "file", "contents": contents}
    if mode is not None:
        entry["mode"] = mode
    return entry


def dir_entry(path: str, mode: str | None = None) -> dict:
    entry = {"path": path, "type": "dir"}
    if mode is not None:
        entry["mode"] = mode
    return entry


def link_entry(path: str, target: str) -> dict:
    return {"path": path, "type": "symlink", "target": target}


def case(
    name: str,
    args: list[str],
    flags: list[str],
    tags: list[str],
    stdin: bytes | None = None,
    fixture: list[dict] | None = None,
    stdin_modes: list[str] | None = None,
    timeout: int | None = None,
    absent_flags: list[str] | None = None,
) -> dict:
    record = {
        "name": name,
        "args": args,
        "flags": flags,
        "tags": tags,
    }
    # Selected only while none of these flags is implemented, which is how a
    # checkpoint asserts that a later feature is not present yet.
    if absent_flags is not None:
        record["absent_flags"] = absent_flags
    if stdin is not None:
        record["stdin"] = stdin
    if fixture is not None:
        record["fixture"] = fixture
    if stdin_modes is not None:
        record["stdin_modes"] = stdin_modes
    if timeout is not None:
        record["timeout"] = timeout
    return record


# ---------------------------------------------------------------------------
# Checkpoint 000: fixed-string matching, stdin, file operands, exit status
# ---------------------------------------------------------------------------

BASE = [
    case("base-stdin-single-match", ["alpha"], [], ["base", "stdin"], stdin=ALPHA),
    case("base-stdin-multi-match", ["a"], [], ["base", "stdin"], stdin=ALPHA),
    case("base-stdin-no-match", ["zeta"], [], ["base", "stdin", "negative"],
         stdin=ALPHA),
    case("base-stdin-empty-input", ["alpha"], [], ["base", "stdin", "negative"],
         stdin=b""),
    case("base-stdin-empty-pattern", [""], [], ["base", "stdin"], stdin=ALPHA),
    case("base-stdin-empty-pattern-empty-input", [""], [],
         ["base", "stdin", "negative"], stdin=b""),
    case("base-stdin-whole-line-pattern", ["beta"], [], ["base", "stdin"],
         stdin=ALPHA),
    case("base-stdin-pattern-longer-than-line", ["alphabetical"], [],
         ["base", "stdin", "negative"], stdin=ALPHA),
    case("base-stdin-case-sensitive-by-default", ["gamma"], [],
         ["base", "stdin", "negative"], stdin=ALPHA),
    case("base-stdin-twice-on-one-line-prints-once", ["a"], [], ["base", "stdin"],
         stdin=b"aa\nb\n"),
    case("base-stdin-blank-lines-kept", [""], [], ["base", "stdin"],
         stdin=b"\n\nx\n"),
    case("base-stdin-no-trailing-newline", ["needle"], [], ["base", "stdin"],
         stdin=NO_TRAILING),
    case("base-stdin-crlf-retains-cr", ["needle"], [], ["base", "stdin"],
         stdin=CRLF),
    case("base-stdin-nul-and-invalid-utf8", ["needle"], [],
         ["base", "stdin", "adversarial"], stdin=BINARY),
    case("base-stdin-pattern-is-a-fixed-string-not-a-regex", ["a.c"], [],
         ["base", "stdin", "adversarial"], stdin=b"abc\na.c\nxaycz\n"),
    case("base-stdin-bracket-pattern-is-literal", ["[abc]"], [],
         ["base", "stdin", "adversarial"], stdin=b"[abc]\nabc\n{abc}\n"),
    case("base-stdin-dash-is-an-operand-name", ["alpha", "-"], [],
         ["base", "negative"], stdin=ALPHA),

    case("base-one-file-no-prefix", ["alpha", "a.txt"], [], ["base", "files"],
         fixture=[file_entry("a.txt", ALPHA)]),
    case("base-one-file-no-match", ["zeta", "a.txt"], [],
         ["base", "files", "negative"], fixture=[file_entry("a.txt", ALPHA)]),
    case("base-two-files-prefixed", ["beta", "a.txt", "b.txt"], [],
         ["base", "files"],
         fixture=[file_entry("a.txt", ALPHA), file_entry("b.txt", BETA)]),
    case("base-two-files-only-one-matches", ["Gamma", "a.txt", "b.txt"], [],
         ["base", "files"],
         fixture=[file_entry("a.txt", ALPHA), file_entry("b.txt", BETA)]),
    case("base-three-files-follow-operand-not-name-order",
         ["e", "c.txt", "a.txt", "b.txt"], [], ["base", "files"],
         fixture=[file_entry("c.txt", b"echo\n"), file_entry("a.txt", b"delta\n"),
                  file_entry("b.txt", b"beta\n")]),
    case("base-file-no-trailing-newline", ["needle", "a.txt"], [],
         ["base", "files"], fixture=[file_entry("a.txt", NO_TRAILING)]),
    case("base-missing-file-is-an-error", ["alpha", "nope.txt"], [],
         ["base", "files", "fault"], fixture=[]),
    case("base-missing-file-still-searches-the-rest",
         ["alpha", "nope.txt", "a.txt"], [], ["base", "files", "fault"],
         fixture=[file_entry("a.txt", ALPHA)]),
    case("base-unreadable-file-is-an-error", ["alpha", "locked.txt"], [],
         ["base", "files", "fault"],
         fixture=[file_entry("locked.txt", ALPHA, mode="0000")]),
    case("base-directory-operand-without-r-is-an-error", ["alpha", "d"], [],
         ["base", "files", "fault"],
         fixture=[dir_entry("d"), file_entry("d/inner.txt", ALPHA)]),
    case("base-symlink-operand-is-followed", ["alpha", "link"], [],
         ["base", "files"],
         fixture=[file_entry("a.txt", ALPHA), link_entry("link", "a.txt")]),
    case("base-terminator-allows-dash-pattern", ["--", "-alpha", "a.txt"], [],
         ["base", "files"], fixture=[file_entry("a.txt", b"x-alpha\ny\n")]),
    case("base-unknown-short-option", ["-Z", "alpha"], [],
         ["base", "usage", "negative"], stdin=ALPHA),
    case("base-unknown-long-option", ["--colour", "alpha"], [],
         ["base", "usage", "negative"], stdin=ALPHA),
    case("base-no-arguments-at-all", [], [], ["base", "usage", "negative"]),

    # A checkpoint's own option must still be unknown BEFORE its checkpoint.
    # Each of these disappears the moment its flag is introduced, so the ladder
    # is tested from above as well as from below: without them a candidate that
    # implemented the whole option set at 000 would satisfy every checkpoint.
    case("base-rejects-H-before-its-checkpoint", ["-H", "alpha"], [],
         ["base", "usage", "negative", "premature"], stdin=ALPHA,
         absent_flags=["-H"]),
    case("base-rejects-with-filename-long-before-its-checkpoint",
         ["--with-filename", "alpha"], [],
         ["base", "usage", "negative", "premature"], stdin=ALPHA,
         absent_flags=["-H"]),
    case("base-rejects-h-before-its-checkpoint", ["-h", "alpha"], [],
         ["base", "usage", "negative", "premature"], stdin=ALPHA,
         absent_flags=["-h"]),
    case("base-rejects-r-before-its-checkpoint", ["-r", "alpha"], [],
         ["base", "usage", "negative", "premature"], stdin=ALPHA,
         absent_flags=["-r"]),
    case("base-rejects-i-before-its-checkpoint", ["-i", "alpha"], [],
         ["base", "usage", "negative", "premature"], stdin=ALPHA,
         absent_flags=["-i"]),
    case("base-rejects-ignore-case-long-before-its-checkpoint",
         ["--ignore-case", "alpha"], [],
         ["base", "usage", "negative", "premature"], stdin=ALPHA,
         absent_flags=["-i"]),
]

# ---------------------------------------------------------------------------
# Checkpoint 001: -H / --with-filename
# ---------------------------------------------------------------------------

WITH_FILENAME = [
    case("H-stdin-uses-standard-input-name", ["-H", "alpha"], ["-H"],
         ["with-filename", "stdin"], stdin=ALPHA),
    case("H-one-file-is-prefixed", ["-H", "alpha", "a.txt"], ["-H"],
         ["with-filename", "files"], fixture=[file_entry("a.txt", ALPHA)]),
    case("H-two-files-are-prefixed", ["-H", "beta", "a.txt", "b.txt"], ["-H"],
         ["with-filename", "files"],
         fixture=[file_entry("a.txt", ALPHA), file_entry("b.txt", BETA)]),
    case("H-long-option", ["--with-filename", "alpha", "a.txt"], ["-H"],
         ["with-filename", "files"], fixture=[file_entry("a.txt", ALPHA)]),
    case("H-repeated-is-idempotent", ["-H", "-H", "alpha", "a.txt"], ["-H"],
         ["with-filename", "files"], fixture=[file_entry("a.txt", ALPHA)]),
    case("H-no-match-still-exits-1", ["-H", "zeta", "a.txt"], ["-H"],
         ["with-filename", "files", "negative"],
         fixture=[file_entry("a.txt", ALPHA)]),
    case("H-missing-file-is-still-an-error", ["-H", "alpha", "nope.txt"], ["-H"],
         ["with-filename", "files", "fault"], fixture=[]),
    case("H-prefix-on-a-line-containing-a-colon", ["-H", "key", "a.txt"], ["-H"],
         ["with-filename", "files", "adversarial"],
         fixture=[file_entry("a.txt", b"key:value\nother\n")]),
]

# ---------------------------------------------------------------------------
# Checkpoint 002: -h / --no-filename, and its interaction with -H
# ---------------------------------------------------------------------------

NO_FILENAME = [
    case("h-two-files-are-not-prefixed", ["-h", "beta", "a.txt", "b.txt"], ["-h"],
         ["no-filename", "files"],
         fixture=[file_entry("a.txt", ALPHA), file_entry("b.txt", BETA)]),
    case("h-one-file-is-not-prefixed", ["-h", "alpha", "a.txt"], ["-h"],
         ["no-filename", "files"], fixture=[file_entry("a.txt", ALPHA)]),
    case("h-stdin-is-not-prefixed", ["-h", "alpha"], ["-h"],
         ["no-filename", "stdin"], stdin=ALPHA),
    case("h-long-option", ["--no-filename", "beta", "a.txt", "b.txt"], ["-h"],
         ["no-filename", "files"],
         fixture=[file_entry("a.txt", ALPHA), file_entry("b.txt", BETA)]),
    case("h-repeated-is-idempotent", ["-h", "-h", "beta", "a.txt", "b.txt"],
         ["-h"], ["no-filename", "files"],
         fixture=[file_entry("a.txt", ALPHA), file_entry("b.txt", BETA)]),
    case("Hh-last-wins-h", ["-H", "-h", "alpha", "a.txt"], ["-H", "-h"],
         ["no-filename", "files", "interaction"],
         fixture=[file_entry("a.txt", ALPHA)]),
    case("hH-last-wins-H", ["-h", "-H", "alpha", "a.txt"], ["-H", "-h"],
         ["no-filename", "files", "interaction"],
         fixture=[file_entry("a.txt", ALPHA)]),
    case("Hh-combined-last-wins-h", ["-Hh", "alpha", "a.txt"], ["-H", "-h"],
         ["no-filename", "files", "interaction"],
         fixture=[file_entry("a.txt", ALPHA)]),
    case("hH-combined-last-wins-H", ["-hH", "alpha", "a.txt"], ["-H", "-h"],
         ["no-filename", "files", "interaction"],
         fixture=[file_entry("a.txt", ALPHA)]),
    case("Hh-long-then-short", ["--with-filename", "-h", "beta", "a.txt", "b.txt"],
         ["-H", "-h"], ["no-filename", "files", "interaction"],
         fixture=[file_entry("a.txt", ALPHA), file_entry("b.txt", BETA)]),
]

# ---------------------------------------------------------------------------
# Checkpoint 003: -r / --recursive
# ---------------------------------------------------------------------------

TREE = [
    dir_entry("t"),
    file_entry("t/b.txt", b"beta needle\nplain\n"),
    file_entry("t/a.txt", b"alpha needle\n"),
    dir_entry("t/sub"),
    file_entry("t/sub/z.txt", b"deep needle\n"),
    file_entry("t/sub/a.txt", b"also needle\n"),
]

RECURSIVE = [
    case("r-directory-is-traversed-in-name-order", ["-r", "needle", "t"], ["-r"],
         ["recursive", "files"], fixture=TREE),
    case("r-long-option", ["--recursive", "needle", "t"], ["-r"],
         ["recursive", "files"], fixture=TREE),
    case("r-repeated-is-idempotent", ["-r", "-r", "needle", "t"], ["-r"],
         ["recursive", "files"], fixture=TREE),
    case("r-regular-file-operand-is-not-prefixed", ["-r", "alpha", "a.txt"],
         ["-r"], ["recursive", "files"], fixture=[file_entry("a.txt", ALPHA)]),
    case("r-empty-directory-selects-nothing", ["-r", "needle", "empty"], ["-r"],
         ["recursive", "files", "negative"], fixture=[dir_entry("empty")]),
    case("r-nested-empty-directory", ["-r", "needle", "outer"], ["-r"],
         ["recursive", "files", "negative"],
         fixture=[dir_entry("outer"), dir_entry("outer/inner")]),
    case("r-skips-symlinks-during-traversal", ["-r", "needle", "t"], ["-r"],
         ["recursive", "files"],
         fixture=TREE + [link_entry("t/loop", "."),
                         link_entry("t/c.txt", "a.txt")]),
    case("r-trailing-slash-does-not-double", ["-r", "needle", "t/"], ["-r"],
         ["recursive", "files", "adversarial"], fixture=TREE),
    case("r-directory-and-file-operands-together",
         ["-r", "needle", "t", "top.txt"], ["-r"], ["recursive", "files"],
         fixture=TREE + [file_entry("top.txt", b"top needle\n")]),
    case("r-unreadable-file-in-tree-is-an-error", ["-r", "needle", "t"], ["-r"],
         ["recursive", "files", "fault"],
         fixture=TREE + [file_entry("t/locked.txt", b"locked needle\n",
                                    mode="0000")]),
    case("r-missing-directory-is-an-error", ["-r", "needle", "nope"], ["-r"],
         ["recursive", "files", "fault"], fixture=[]),
    case("r-no-match-in-a-populated-tree", ["-r", "absent", "t"], ["-r"],
         ["recursive", "files", "negative"], fixture=TREE),
    case("rh-combined-suppresses-prefixes", ["-rh", "needle", "t"], ["-r", "-h"],
         ["recursive", "no-filename", "interaction"], fixture=TREE),
    case("rH-combined-keeps-prefixes", ["-rH", "needle", "t"], ["-r", "-H"],
         ["recursive", "with-filename", "interaction"], fixture=TREE),
    case("r-H-on-a-single-regular-file", ["-r", "-H", "alpha", "a.txt"],
         ["-r", "-H"], ["recursive", "with-filename", "interaction"],
         fixture=[file_entry("a.txt", ALPHA)]),
]

# ---------------------------------------------------------------------------
# Checkpoint 004: -i / --ignore-case
# ---------------------------------------------------------------------------

IGNORE_CASE = [
    case("i-stdin-folds-ascii", ["-i", "gamma"], ["-i"],
         ["ignore-case", "stdin"], stdin=ALPHA),
    case("i-stdin-uppercase-pattern", ["-i", "ALPHA"], ["-i"],
         ["ignore-case", "stdin"], stdin=MIXED),
    case("i-stdin-mixed-case-pattern", ["-i", "aLpHa"], ["-i"],
         ["ignore-case", "stdin"], stdin=MIXED),
    case("i-long-option", ["--ignore-case", "GAMMA"], ["-i"],
         ["ignore-case", "stdin"], stdin=ALPHA),
    case("i-repeated-is-idempotent", ["-i", "-i", "GAMMA"], ["-i"],
         ["ignore-case", "stdin"], stdin=ALPHA),
    case("i-empty-pattern-still-matches-everything", ["-i", ""], ["-i"],
         ["ignore-case", "stdin"], stdin=MIXED),
    case("i-no-match-even-folded", ["-i", "omega"], ["-i"],
         ["ignore-case", "stdin", "negative"], stdin=ALPHA),
    # A fold implemented as `byte | 0x20` -- or as tolower() in a non-C locale --
    # also maps '[' to '{' and ']' to '}'. Only A-Z may fold, so the bracket
    # pattern must not match the brace line.
    case("i-folds-only-ascii-letters", ["-i", "[ABC]"], ["-i"],
         ["ignore-case", "stdin", "adversarial"],
         stdin=b"[abc]\n{abc}\nABC\n"),
    case("i-high-bytes-pass-through-unfolded", ["-i", "COLE"], ["-i"],
         ["ignore-case", "stdin", "adversarial"],
         stdin=b"\xc3\x89cole\n\xc3\xa9COLE\nplain\n"),
    case("i-nul-bytes-survive-folding", ["-i", "NEEDLE"], ["-i"],
         ["ignore-case", "stdin", "adversarial"], stdin=BINARY),
    case("i-one-file", ["-i", "GAMMA", "a.txt"], ["-i"],
         ["ignore-case", "files"], fixture=[file_entry("a.txt", ALPHA)]),
    case("i-two-files-are-prefixed", ["-i", "BETA", "a.txt", "b.txt"], ["-i"],
         ["ignore-case", "files"],
         fixture=[file_entry("a.txt", ALPHA), file_entry("b.txt", BETA)]),
    case("iH-combined", ["-iH", "GAMMA", "a.txt"], ["-i", "-H"],
         ["ignore-case", "with-filename", "interaction"],
         fixture=[file_entry("a.txt", ALPHA)]),
    case("ih-combined", ["-ih", "BETA", "a.txt", "b.txt"], ["-i", "-h"],
         ["ignore-case", "no-filename", "interaction"],
         fixture=[file_entry("a.txt", ALPHA), file_entry("b.txt", BETA)]),
    case("ri-combined-over-a-tree", ["-ri", "NEEDLE", "t"], ["-r", "-i"],
         ["ignore-case", "recursive", "interaction"], fixture=TREE),
    case("rhi-combined-over-a-tree", ["-rhi", "NEEDLE", "t"],
         ["-r", "-h", "-i"], ["ignore-case", "recursive", "no-filename",
                              "interaction"], fixture=TREE),
    case("i-missing-file-is-still-an-error", ["-i", "ALPHA", "nope.txt"], ["-i"],
         ["ignore-case", "files", "fault"], fixture=[]),
]

GROUPS = {
    "base": BASE,
    "with_filename": WITH_FILENAME,
    "no_filename": NO_FILENAME,
    "recursive": RECURSIVE,
    "ignore_case": IGNORE_CASE,
}
