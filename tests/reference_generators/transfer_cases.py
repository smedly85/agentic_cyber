"""Offline fixture definitions for transfer suites, never a utility model."""
from __future__ import annotations

import base64
import copy


def file(path, data=b"payload\x00\xff\n", mode="0644"):
    return {"path": path, "type": "file", "contents_b64": base64.b64encode(data).decode(), "mode": mode}


def directory(path, mode="0755"):
    return {"path": path, "type": "dir", "mode": mode}


def link(path, target):
    return {"path": path, "type": "symlink", "target": target}


def definitions(utility: str) -> list[dict]:
    cases = []

    def add(name, args, fixture=None, flags=(), stdin=b"", **kw):
        cases.append(dict(name=name, args=args, fixture=fixture if fixture is not None else [file("src")],
                          flags=list(flags), tags=["filesystem"], check="golden",
                          stdin_b64=base64.b64encode(stdin).decode(), **kw))

    add("empty", ["src", "dst"], [file("src", b"")])
    add("text", ["src", "dst"], [file("src", b"alpha\nbeta\n")])
    add("binary", ["src", "dst"], [file("src", bytes(range(256)))])
    add("nul", ["src", "dst"], [file("src", b"a\0b\0\0c")])
    add("large", ["src", "dst"], [file("src", bytes(range(256)) * 8192)])
    add("missing-source", ["absent", "dst"], [])
    add("missing-parent", ["src", "absent/dst"])
    add("overwrite", ["src", "dst"], [file("src"), file("dst", b"long old contents\n")])
    add("into-directory", ["src", "dest"], [file("src"), directory("dest")])
    add("multiple", ["a", "b", "dest"], [file("a", b"A"), file("b", b"B"), directory("dest")])
    add("partial", ["a", "missing", "b", "dest"], [file("a", b"A"), file("b", b"B"), directory("dest")])
    add("multiple-nondirectory", ["a", "b", "dst"], [file("a"), file("b"), file("dst")])
    add("multiple-missing-target", ["a", "b", "dst"], [file("a"), file("b")])
    add("same", ["src", "src"])
    add("spaces", ["source name", "target name"], [file("source name")])
    add("dash-operand", ["--", "-operand", "dst"], [file("-operand")])
    add("bare-dash", ["-", "dst"], [file("-")])
    add("terminator", ["--", "src", "dst"])
    # APFS only creates valid UTF-8 names. An invalid-byte missing operand
    # exercises lossless parsing/error handling on both hosts without requiring
    # an impossible Darwin fixture or freezing a Linux-only successful rename.
    add("nonutf8", ["src-\udcff", "dst"], [])
    add("missing-all", [], [])
    add("missing-destination", ["src"])
    add("unknown", ["--invalid-option", "src", "dst"])
    add("unwritable-parent", ["src", "dest/out"], [file("src"), directory("dest", "0555")], needs_non_root=True)
    add("ordinary-modes", ["src", "dst"], [file("src", mode="0600")], mode_paths=["src", "dst"])
    add("overwrite-modes", ["src", "dst"], [file("src", mode="0600"), file("dst", mode="0640")], mode_paths=["src", "dst"])

    if utility == "cp":
        add("directory-unsupported", ["tree", "dst"], [directory("tree"), file("tree/a")])
        add("unreadable-source", ["src", "dst"], [file("src", mode="0000")], needs_non_root=True)
        add("unwritable-destination", ["src", "dst"], [file("src"), file("dst", mode="0444")], needs_non_root=True)
        add("source-link", ["alias", "dst"], [file("src"), link("alias", "src")])
        add("destination-link", ["src", "alias"], [file("src"), file("dst", b"old"), link("alias", "dst")])
        add("dangling-destination", ["src", "alias"], [file("src"), link("alias", "absent")])
        add("same-via-link", ["src", "alias"], [file("src"), link("alias", "src")])
        for name, options in [("force", ["-f"]), ("force-repeat", ["-f", "-f"]), ("force-long", ["--force"])]:
            add(name, options + ["src", "dst"], [file("src"), file("dst", b"old")], ["-f"])
        add("force-recreate", ["-f", "src", "dst"], [file("src"), file("dst", b"old", "0444")], ["-f"], needs_non_root=True, mode_paths=["dst"])
        add("force-source-error", ["-f", "absent", "dst"], [file("dst", b"old")], ["-f"])
    else:
        add("rename-directory", ["tree", "dst"], [directory("tree"), directory("tree/deep"), file("tree/deep/a")])
        add("directory-into-directory", ["tree", "dest"], [directory("tree"), file("tree/a"), directory("dest")])
        add("replace-empty-directory", ["tree", "dest"], [directory("tree"), file("tree/a"), directory("dest/tree")])
        add("nonempty-directory", ["tree", "dest"], [directory("tree"), file("tree/a"), directory("dest/tree"), file("dest/tree/b")])
        add("file-directory-conflict", ["src", "dest"], [file("src"), directory("dest/src")])
        add("directory-file-conflict", ["tree", "dst"], [directory("tree"), file("dst")])
        add("descendant", ["tree", "tree/sub"], [directory("tree"), file("tree/a")])
        add("source-link", ["alias", "dst"], [file("src"), link("alias", "src")])
        add("destination-link", ["src", "alias"], [file("src"), file("dst", b"old"), link("alias", "dst")])

    interactive_flags = ["-f", "-i"] if utility == "cp" else ["-i"]
    for name, response in [("yes", b"yes\n"), ("upper", b"Y\n"), ("prefix", b"yanything\n"),
                           ("no", b"n\n"), ("blank", b"\n"), ("eof", b""), ("space", b" yes\n")]:
        add("ask-" + name, ["-i", "src", "dst"], [file("src"), file("dst", b"old")], interactive_flags, response)
    add("ask-new", ["-i", "src", "dst"], flags=interactive_flags)
    add("ask-repeat", ["-i", "-i", "src", "dst"], [file("src"), file("dst", b"old")], interactive_flags, b"n\n")
    add("ask-long", ["--interactive", "src", "dst"], [file("src"), file("dst", b"old")], interactive_flags, b"y\n")
    add("ask-sequence", ["-i", "a", "b", "dest"], [file("a", b"A"), file("b", b"B"), directory("dest"), file("dest/a", b"old-a"), file("dest/b", b"old-b")], interactive_flags, b"n\ny\n")
    both_flags = ["-f", "-i"] if utility == "cp" else ["-i", "-f"]
    for name, options in [("order-fi", ["-f", "-i"]), ("order-if", ["-i", "-f"]),
                          ("order-long", ["--interactive", "--force"]), ("order-long-reverse", ["--force", "--interactive"])]:
        add(name, options + ["src", "dst"], [file("src"), file("dst", b"old")], both_flags, b"n\n")
    if utility == "mv":
        for name, options in [("force-repeat", ["-f", "-f"]), ("force-long", ["--force"])]:
            add(name, options + ["src", "dst"], [file("src"), file("dst", b"old", "0444")], both_flags)
        add("force-failure", ["-f", "missing", "dst"], [file("dst")], both_flags)
        return cases

    add("ask-recreate-approved", ["-i", "-f", "src", "dst"], [file("src"), file("dst", b"old", "0444")], both_flags, b"y\n", needs_non_root=True)
    add("ask-recreate-declined", ["-f", "-i", "src", "dst"], [file("src"), file("dst", b"old", "0444")], both_flags, b"n\n", needs_non_root=True)
    tree = [directory("tree"), file("tree/a"), directory("tree/deep"), file("tree/deep/b", b"nested"), directory("tree/empty")]
    recursive_flags = ["-f", "-i", "-r"]
    add("tree-empty", ["-r", "tree", "dst"], [directory("tree")], recursive_flags)
    add("tree-simple", ["-r", "tree", "dst"], [directory("tree"), file("tree/a")], recursive_flags)
    add("tree-nested", ["-r", "tree", "dst"], tree, recursive_flags)
    add("tree-existing", ["-r", "tree", "dest"], tree + [directory("dest/tree"), file("dest/tree/retained")], recursive_flags)
    add("tree-long", ["--recursive", "tree", "dst"], tree, recursive_flags)
    add("tree-links", ["-r", "tree", "dst"], tree + [link("tree/to-a", "a"), link("tree/cycle", "."), link("tree/dangling", "absent")], recursive_flags)
    add("tree-operand-link", ["-r", "alias", "dst"], tree + [link("alias", "tree")], recursive_flags)
    add("tree-ask", ["-r", "-i", "tree", "dest"], tree + [directory("dest/tree"), file("dest/tree/a", b"old")], recursive_flags, b"n\n")
    add("tree-force", ["-r", "-f", "tree", "dest"], tree + [directory("dest/tree"), file("dest/tree/a", b"old", "0444")], recursive_flags, needs_non_root=True)
    add("tree-subfailure", ["-r", "tree", "dst"], tree + [file("tree/denied", mode="0000")], recursive_flags, needs_non_root=True)
    add("tree-type-conflict", ["-r", "tree", "dst"], tree + [file("dst")], recursive_flags)
    add("tree-self", ["-r", "tree", "."], [directory("tree")], recursive_flags)
    return cases


def heldout(visible: list[dict]) -> list[dict]:
    """Structural duals with independent concrete names, content and sizes."""
    result = []
    for ordinal, original in enumerate(visible):
        case = copy.deepcopy(original)
        case["dual_of"] = original["name"]
        case["name"] = "heldout-" + original["name"]
        # A containing directory keeps relative link targets unchanged, including
        # cycles. A literal '-' must stay at the case root: prefixing it would
        # stop testing whether the program treats bare '-' as a filename.
        prefix = f"private-{ordinal:03d}"
        def private_path(path):
            return path if path == "-" else prefix + "/" + path

        after = False
        args = []
        for arg in case["args"]:
            if arg == "--":
                after = True
                args.append(arg)
            elif not after and arg == "--invalid-option":
                args.append(f"--unknown-private-{ordinal}")
            elif after or not arg.startswith("-") or arg == "-":
                args.append(private_path(arg))
            else:
                args.append(arg)
        case["args"] = args
        # Preserve distinct affirmative shapes: full word, arbitrary prefix,
        # and single letter. Other nonblank answers retain their first byte.
        answer = base64.b64decode(case["stdin_b64"])
        if answer:
            lines = answer.splitlines(keepends=True)
            answer = b"".join(
                b"YES\n" if line == b"yes\n" else
                b"Y\n" if line == b"y\n" else
                line if line in (b"\n", b"\r\n") else
                line[:1] + f"private-answer-{ordinal}".encode() + b"\n"
                for line in lines)
            case["stdin_b64"] = base64.b64encode(answer).decode()
        for entry in case["fixture"]:
            entry["path"] = private_path(entry["path"])
            if entry["type"] == "file":
                data = base64.b64decode(entry["contents_b64"])
                if data:
                    entry["contents_b64"] = base64.b64encode(data[::-1] + f"hidden-{ordinal}".encode()).decode()
        case["fixture"].insert(0, directory(prefix))
        case["mode_paths"] = [private_path(p) for p in case.get("mode_paths", [])]
        result.append(case)
    return result
