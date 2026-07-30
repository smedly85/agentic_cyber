#!/usr/bin/env python3
"""Curated case definitions for the new_chmod suite.

Every case is written here as *inputs only* -- argv, a fixture, the flags it
needs, and its tags. The expected stdout, exit status, stderr class and
resulting mode tree are never written by hand: gen/generate.py derives them from
tests/reference_generators/chmod_reference.py, which is the executable form of the checkpoint prompt
contract. Hand-written expectations drift; derived ones cannot.

Cases are grouped by the checkpoint whose feature they need, and `flags` is what
makes cumulative filtering work: a case listing `["-R", "-c"]` runs only from
the checkpoint where both are implemented, while a case listing `[]` runs at
every checkpoint from 000 onward as regression coverage.
"""

from __future__ import annotations


def file_entry(path: str, mode: str = "0644") -> dict:
    return {"path": path, "type": "file", "mode": mode}


def dir_entry(path: str, mode: str = "0755") -> dict:
    return {"path": path, "type": "dir", "mode": mode}


def link_entry(path: str, target: str) -> dict:
    return {"path": path, "type": "symlink", "target": target}


def case(
    name: str,
    args: list[str],
    flags: list[str],
    tags: list[str],
    fixture: list[dict] | None = None,
    needs_non_root: bool = False,
    timeout: int | None = None,
    absent_flags: list[str] | None = None,
) -> dict:
    record = {
        "name": name,
        "args": args,
        "flags": flags,
        "tags": tags,
        "fixture": fixture if fixture is not None else [],
    }
    # Selected only while none of these flags is implemented, which is how a
    # checkpoint asserts that a later feature is not present yet.
    if absent_flags is not None:
        record["absent_flags"] = absent_flags
    if needs_non_root:
        record["needs_non_root"] = True
    if timeout is not None:
        record["timeout"] = timeout
    return record


ONE_FILE = [file_entry("f", "0600")]

# b sorts after a, and sub sorts after both, so a correct pre-order walk over
# `d` visits d, d/a.txt, d/b.txt, d/sub, d/sub/a.txt, d/sub/z.txt in that order.
TREE = [
    dir_entry("d", "0755"),
    file_entry("d/b.txt", "0644"),
    file_entry("d/a.txt", "0600"),
    dir_entry("d/sub", "0755"),
    file_entry("d/sub/z.txt", "0644"),
    file_entry("d/sub/a.txt", "0755"),
]

# ---------------------------------------------------------------------------
# Checkpoint 000: MODE parsing, operand handling, exit status
# ---------------------------------------------------------------------------

BASE = [
    case("base-octal-three-digits", ["644", "f"], [], ["base", "octal"],
         fixture=ONE_FILE),
    case("base-octal-four-digits-setuid", ["4755", "f"], [], ["base", "octal"],
         fixture=ONE_FILE),
    case("base-octal-four-digits-sticky", ["1777", "d"], [], ["base", "octal"],
         fixture=[dir_entry("d", "0755")]),
    case("base-octal-zero", ["0", "f"], [], ["base", "octal"],
         fixture=[file_entry("f", "0644")]),
    case("base-octal-leading-zero", ["0700", "f"], [], ["base", "octal"],
         fixture=ONE_FILE),
    case("base-octal-no-change-is-success", ["644", "f"], [], ["base", "octal"],
         fixture=[file_entry("f", "0644")]),

    case("base-symbolic-u-plus-x", ["u+x", "f"], [], ["base", "symbolic"],
         fixture=[file_entry("f", "0644")]),
    case("base-symbolic-empty-class-means-all", ["+x", "f"], [],
         ["base", "symbolic"], fixture=[file_entry("f", "0644")]),
    case("base-symbolic-a-is-all", ["a+w", "f"], [], ["base", "symbolic"],
         fixture=[file_entry("f", "0444")]),
    case("base-symbolic-minus", ["go-rwx", "f"], [], ["base", "symbolic"],
         fixture=[file_entry("f", "0777")]),
    case("base-symbolic-equals-affects-only-its-classes", ["u=rw", "f"], [],
         ["base", "symbolic"], fixture=[file_entry("f", "0777")]),
    case("base-symbolic-equals-empty-clears", ["o=", "f"], [],
         ["base", "symbolic"], fixture=[file_entry("f", "0777")]),
    case("base-symbolic-multiple-clauses-apply-in-order",
         ["u=rw,go=r", "f"], [], ["base", "symbolic"],
         fixture=[file_entry("f", "0777")]),
    case("base-symbolic-later-clause-overrides-earlier", ["a+x,u-x", "f"], [],
         ["base", "symbolic"], fixture=[file_entry("f", "0644")]),
    case("base-symbolic-plus-nothing-is-a-no-op", ["u+", "f"], [],
         ["base", "symbolic"], fixture=[file_entry("f", "0644")]),
    case("base-symbolic-repeated-class-letters", ["uuu+x", "f"], [],
         ["base", "symbolic", "adversarial"], fixture=[file_entry("f", "0644")]),

    case("base-X-does-not-add-x-to-a-plain-file", ["a+X", "f"], [],
         ["base", "symbolic"], fixture=[file_entry("f", "0644")]),
    case("base-X-adds-x-when-one-is-already-set", ["a+X", "f"], [],
         ["base", "symbolic"], fixture=[file_entry("f", "0744")]),
    case("base-X-always-adds-x-to-a-directory", ["a+X", "d"], [],
         ["base", "symbolic"], fixture=[dir_entry("d", "0644")]),

    case("base-symbolic-leaves-setuid-alone", ["u+x", "f"], [],
         ["base", "symbolic", "special-bits"],
         fixture=[file_entry("f", "4644")]),
    case("base-symbolic-equals-leaves-sticky-alone", ["a=rx", "d"], [],
         ["base", "symbolic", "special-bits"],
         fixture=[dir_entry("d", "1777")]),
    case("base-octal-clears-special-bits", ["755", "f"], [],
         ["base", "octal", "special-bits"], fixture=[file_entry("f", "4755")]),

    case("base-two-operands-both-change", ["600", "a", "b"], [],
         ["base", "operands"],
         fixture=[file_entry("a", "0644"), file_entry("b", "0777")]),
    case("base-directory-operand-is-not-descended", ["700", "d"], [],
         ["base", "operands"], fixture=TREE),
    case("base-symlink-operand-is-followed", ["700", "link"], [],
         ["base", "operands"],
         fixture=[file_entry("target", "0644"), link_entry("link", "target")]),
    case("base-terminator-allows-dash-mode", ["--", "-w", "f"], [],
         ["base", "operands"], fixture=[file_entry("f", "0666")]),

    case("base-missing-operand-is-an-error", ["644", "nope"], [],
         ["base", "fault"], fixture=[]),
    case("base-missing-operand-still-attempts-the-rest",
         ["600", "nope", "f"], [], ["base", "fault"],
         fixture=[file_entry("f", "0644")]),
    case("base-operand-under-a-plain-file-is-an-error", ["600", "f/x"], [],
         ["base", "fault"], fixture=[file_entry("f", "0644")]),

    case("base-invalid-symbolic-permission-letter", ["u+z", "f"], [],
         ["base", "usage", "negative"], fixture=ONE_FILE),
    case("base-invalid-symbolic-missing-operator", ["ug", "f"], [],
         ["base", "usage", "negative"], fixture=ONE_FILE),
    case("base-invalid-symbolic-trailing-comma", ["u+x,", "f"], [],
         ["base", "usage", "negative"], fixture=ONE_FILE),
    case("base-invalid-octal-too-long", ["77777", "f"], [],
         ["base", "usage", "negative"], fixture=ONE_FILE),
    case("base-invalid-empty-mode", ["", "f"], [],
         ["base", "usage", "negative"], fixture=ONE_FILE),
    case("base-unknown-short-option", ["-Z", "644", "f"], [],
         ["base", "usage", "negative"], fixture=ONE_FILE),
    case("base-unknown-long-option", ["--recurse", "644", "f"], [],
         ["base", "usage", "negative"], fixture=ONE_FILE),

    # A checkpoint's own option must still be unknown BEFORE its checkpoint.
    # Each of these disappears the moment its flag is introduced, so the ladder
    # is tested from above as well as from below: without them a candidate that
    # implemented the whole option set at 000 would satisfy every checkpoint.
    case("base-rejects-R-before-its-checkpoint", ["-R", "644", "f"], [],
         ["base", "usage", "negative", "premature"], fixture=ONE_FILE,
         absent_flags=["-R"]),
    case("base-rejects-recursive-long-before-its-checkpoint",
         ["--recursive", "644", "f"], [],
         ["base", "usage", "negative", "premature"], fixture=ONE_FILE,
         absent_flags=["-R"]),
    case("base-rejects-c-before-its-checkpoint", ["-c", "644", "f"], [],
         ["base", "usage", "negative", "premature"], fixture=ONE_FILE,
         absent_flags=["-c"]),
    case("base-rejects-v-before-its-checkpoint", ["-v", "644", "f"], [],
         ["base", "usage", "negative", "premature"], fixture=ONE_FILE,
         absent_flags=["-v"]),
    case("base-rejects-f-before-its-checkpoint", ["-f", "644", "f"], [],
         ["base", "usage", "negative", "premature"], fixture=ONE_FILE,
         absent_flags=["-f"]),
    case("base-rejects-quiet-long-before-its-checkpoint",
         ["--quiet", "644", "f"], [],
         ["base", "usage", "negative", "premature"], fixture=ONE_FILE,
         absent_flags=["-f"]),
    case("base-no-arguments-at-all", [], [], ["base", "usage", "negative"],
         fixture=[]),
    case("base-mode-without-operand", ["644"], [],
         ["base", "usage", "negative"], fixture=ONE_FILE),
    case("base-s-is-not-a-symbolic-permission-letter", ["u+s", "f"], [],
         ["base", "usage", "negative", "special-bits"], fixture=ONE_FILE),
    case("base-t-is-not-a-symbolic-permission-letter", ["+t", "d"], [],
         ["base", "usage", "negative", "special-bits"],
         fixture=[dir_entry("d", "0755")]),
]

# ---------------------------------------------------------------------------
# Checkpoint 001: -R / --recursive
# ---------------------------------------------------------------------------

RECURSIVE = [
    case("R-octal-over-a-tree", ["-R", "700", "d"], ["-R"],
         ["recursive"], fixture=TREE),
    case("R-long-option", ["--recursive", "700", "d"], ["-R"],
         ["recursive"], fixture=TREE),
    case("R-repeated-is-idempotent", ["-R", "-R", "700", "d"], ["-R"],
         ["recursive"], fixture=TREE),
    case("R-symbolic-is-evaluated-per-file", ["-R", "u+x", "d"], ["-R"],
         ["recursive", "symbolic"], fixture=TREE),
    case("R-X-distinguishes-directories-from-files", ["-R", "a+X", "d"],
         ["-R"], ["recursive", "symbolic"], fixture=TREE),
    case("R-regular-file-operand-behaves-as-before", ["-R", "600", "f"],
         ["-R"], ["recursive"], fixture=[file_entry("f", "0644")]),
    case("R-empty-directory", ["-R", "700", "empty"], ["-R"],
         ["recursive"], fixture=[dir_entry("empty", "0755")]),
    case("R-nested-empty-directory", ["-R", "750", "outer"], ["-R"],
         ["recursive"],
         fixture=[dir_entry("outer", "0755"), dir_entry("outer/inner", "0700")]),
    case("R-skips-symlinks-during-traversal", ["-R", "700", "d"], ["-R"],
         ["recursive", "adversarial"],
         fixture=TREE + [link_entry("d/loop", "."),
                         link_entry("d/c.txt", "a.txt")]),
    case("R-trailing-slash-does-not-double", ["-R", "700", "d/"], ["-R"],
         ["recursive", "adversarial"], fixture=TREE),
    case("R-directory-and-file-operands-together",
         ["-R", "700", "d", "top"], ["-R"], ["recursive"],
         fixture=TREE + [file_entry("top", "0644")]),
    case("R-missing-operand-is-an-error", ["-R", "700", "nope"], ["-R"],
         ["recursive", "fault"], fixture=[]),
    case("R-missing-operand-still-walks-the-rest",
         ["-R", "700", "nope", "d"], ["-R"], ["recursive", "fault"],
         fixture=TREE),
    case("R-unreadable-subdirectory-is-an-error", ["-R", "g+w", "d"], ["-R"],
         ["recursive", "fault"],
         fixture=[dir_entry("d", "0755"), dir_entry("d/locked", "0000"),
                  file_entry("d/locked/hidden", "0644")],
         needs_non_root=True),
    case("R-invalid-mode-is-still-rejected", ["-R", "u+z", "d"], ["-R"],
         ["recursive", "usage", "negative"], fixture=TREE),
]

# ---------------------------------------------------------------------------
# Checkpoint 002: -c / --changes
# ---------------------------------------------------------------------------

CHANGES = [
    case("c-reports-a-change", ["-c", "755", "f"], ["-c"],
         ["changes"], fixture=[file_entry("f", "0644")]),
    case("c-says-nothing-when-unchanged", ["-c", "644", "f"], ["-c"],
         ["changes"], fixture=[file_entry("f", "0644")]),
    case("c-long-option", ["--changes", "755", "f"], ["-c"],
         ["changes"], fixture=[file_entry("f", "0644")]),
    case("c-repeated-is-idempotent", ["-c", "-c", "755", "f"], ["-c"],
         ["changes"], fixture=[file_entry("f", "0644")]),
    case("c-renders-setuid-with-execute", ["-c", "4755", "f"], ["-c"],
         ["changes", "special-bits"], fixture=[file_entry("f", "0644")]),
    case("c-renders-setgid-without-execute", ["-c", "2644", "f"], ["-c"],
         ["changes", "special-bits"], fixture=[file_entry("f", "0644")]),
    case("c-renders-sticky-with-execute", ["-c", "1777", "d"], ["-c"],
         ["changes", "special-bits"], fixture=[dir_entry("d", "0755")]),
    case("c-renders-sticky-without-execute", ["-c", "1666", "d"], ["-c"],
         ["changes", "special-bits"], fixture=[dir_entry("d", "0755")]),
    case("c-reports-only-the-operands-that-changed",
         ["-c", "644", "a", "b"], ["-c"], ["changes"],
         fixture=[file_entry("a", "0600"), file_entry("b", "0644")]),
    case("c-says-nothing-about-a-failed-operand", ["-c", "755", "nope"],
         ["-c"], ["changes", "fault"], fixture=[]),
    case("c-symbolic-change", ["-c", "u+x", "f"], ["-c"],
         ["changes", "symbolic"], fixture=[file_entry("f", "0644")]),
    case("Rc-reports-in-traversal-order", ["-R", "-c", "700", "d"],
         ["-R", "-c"], ["changes", "recursive", "interaction"], fixture=TREE),
    case("Rc-combined-short-options", ["-Rc", "700", "d"], ["-R", "-c"],
         ["changes", "recursive", "interaction"], fixture=TREE),
    case("cR-combined-short-options", ["-cR", "700", "d"], ["-R", "-c"],
         ["changes", "recursive", "interaction"], fixture=TREE),
    case("Rc-reports-nothing-for-an-already-correct-tree",
         ["-R", "-c", "755", "d"], ["-R", "-c"],
         ["changes", "recursive", "interaction"],
         fixture=[dir_entry("d", "0755"), file_entry("d/a.txt", "0755")]),
]

# ---------------------------------------------------------------------------
# Checkpoint 003: -v / --verbose, and its interaction with -c
# ---------------------------------------------------------------------------

VERBOSE = [
    case("v-reports-a-change", ["-v", "755", "f"], ["-v"],
         ["verbose"], fixture=[file_entry("f", "0644")]),
    case("v-reports-a-retained-mode", ["-v", "644", "f"], ["-v"],
         ["verbose"], fixture=[file_entry("f", "0644")]),
    case("v-long-option", ["--verbose", "644", "f"], ["-v"],
         ["verbose"], fixture=[file_entry("f", "0644")]),
    case("v-repeated-is-idempotent", ["-v", "-v", "644", "f"], ["-v"],
         ["verbose"], fixture=[file_entry("f", "0644")]),
    case("v-mixes-changed-and-retained-in-operand-order",
         ["-v", "644", "a", "b"], ["-v"], ["verbose"],
         fixture=[file_entry("a", "0600"), file_entry("b", "0644")]),
    case("v-says-nothing-about-a-failed-operand", ["-v", "755", "nope", "f"],
         ["-v"], ["verbose", "fault"], fixture=[file_entry("f", "0644")]),
    case("cv-last-wins-verbose", ["-c", "-v", "644", "f"], ["-c", "-v"],
         ["verbose", "interaction"], fixture=[file_entry("f", "0644")]),
    case("vc-last-wins-changes", ["-v", "-c", "644", "f"], ["-c", "-v"],
         ["verbose", "interaction"], fixture=[file_entry("f", "0644")]),
    case("cv-combined-last-wins-verbose", ["-cv", "644", "f"], ["-c", "-v"],
         ["verbose", "interaction"], fixture=[file_entry("f", "0644")]),
    case("vc-combined-last-wins-changes", ["-vc", "644", "f"], ["-c", "-v"],
         ["verbose", "interaction"], fixture=[file_entry("f", "0644")]),
    case("cv-long-then-short", ["--changes", "-v", "644", "f"], ["-c", "-v"],
         ["verbose", "interaction"], fixture=[file_entry("f", "0644")]),
    case("Rv-reports-every-file-in-the-tree", ["-R", "-v", "0644", "d"],
         ["-R", "-v"], ["verbose", "recursive", "interaction"], fixture=TREE),
    case("Rv-combined-short-options", ["-Rv", "700", "d"], ["-R", "-v"],
         ["verbose", "recursive", "interaction"], fixture=TREE),
]

# ---------------------------------------------------------------------------
# Checkpoint 004: -f / --silent / --quiet
# ---------------------------------------------------------------------------

SILENT = [
    case("f-suppresses-a-missing-operand", ["-f", "755", "nope"], ["-f"],
         ["silent", "fault"], fixture=[]),
    case("f-suppresses-but-still-attempts-the-rest",
         ["-f", "600", "nope", "f"], ["-f"], ["silent", "fault"],
         fixture=[file_entry("f", "0644")]),
    case("f-long-option-silent", ["--silent", "755", "nope"], ["-f"],
         ["silent", "fault"], fixture=[]),
    case("f-long-option-quiet", ["--quiet", "755", "nope"], ["-f"],
         ["silent", "fault"], fixture=[]),
    case("f-repeated-is-idempotent", ["-f", "-f", "755", "nope"], ["-f"],
         ["silent", "fault"], fixture=[]),
    case("f-does-not-suppress-an-invalid-mode", ["-f", "u+z", "f"], ["-f"],
         ["silent", "usage", "negative"], fixture=ONE_FILE),
    case("f-does-not-suppress-an-unknown-option", ["-f", "-Z", "755", "f"],
         ["-f"], ["silent", "usage", "negative"], fixture=ONE_FILE),
    case("f-does-not-suppress-a-missing-file-operand", ["-f", "755"], ["-f"],
         ["silent", "usage", "negative"], fixture=ONE_FILE),
    case("f-on-a-run-with-no-failures", ["-f", "600", "f"], ["-f"],
         ["silent"], fixture=[file_entry("f", "0644")]),
    case("cf-still-reports-the-successes", ["-c", "-f", "600", "nope", "f"],
         ["-c", "-f"], ["silent", "changes", "interaction"],
         fixture=[file_entry("f", "0644")]),
    case("cf-combined-short-options", ["-cf", "600", "nope", "f"],
         ["-c", "-f"], ["silent", "changes", "interaction"],
         fixture=[file_entry("f", "0644")]),
    case("vf-still-reports-retained-modes", ["-v", "-f", "644", "nope", "f"],
         ["-v", "-f"], ["silent", "verbose", "interaction"],
         fixture=[file_entry("f", "0644")]),
    case("Rf-suppresses-a-missing-operand-mid-walk",
         ["-R", "-f", "700", "nope", "d"], ["-R", "-f"],
         ["silent", "recursive", "interaction"], fixture=TREE),
    case("Rvf-over-a-tree-with-a-missing-operand",
         ["-R", "-v", "-f", "700", "nope", "d"], ["-R", "-v", "-f"],
         ["silent", "verbose", "recursive", "interaction"], fixture=TREE),
    case("Rf-suppresses-an-unreadable-subdirectory",
         ["-R", "-f", "g+w", "d"], ["-R", "-f"],
         ["silent", "recursive", "fault"],
         fixture=[dir_entry("d", "0755"), dir_entry("d/locked", "0000"),
                  file_entry("d/locked/hidden", "0644")],
         needs_non_root=True),
]

GROUPS = {
    "base": BASE,
    "recursive": RECURSIVE,
    "changes": CHANGES,
    "verbose": VERBOSE,
    "silent": SILENT,
}
