"""Offline scenarios for the Python ladders; no candidate implementations.

Transfer scenarios reuse the Rust functional contract. Sorting and creation
expectations are captured from GNU, never predicted by this module.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from reference_generators.transfer_cases import directory, file, link
from reference_generators import transfer_cases


def definitions(utility):
    if utility in ("cp", "mv"):
        cases = transfer_cases.definitions(utility)
        for name, args, fixture in (
            ('second-terminator-operand', ['--', '--', 'dst'], [file('--')]),
            ('unknown-after-source', ['src', '--invalid-option', 'dst'], [file('src')]),
            ('self-directory-destination', ['src', '.'], [file('src')]),
            ('destination-directory-link', ['src', 'alias'], [file('src'), directory('dest'), link('alias', 'dest')]),
        ):
            cases.append(dict(name=name, args=args, fixture=fixture, flags=[],
                              tags=['filesystem'], check='golden'))
        if utility == "mv":
            for case in cases:
                # Python MV introduces force before interactive.
                if case["name"].startswith("force-"):
                    case["flags"] = ["-f"]
                elif "-i" in case["flags"]:
                    case["flags"] = ["-f", "-i"]
            cases.append(dict(name="force-single", args=["-f", "src", "dst"],
                              fixture=[file("src"), file("dst", b"old")],
                              flags=["-f"], tags=["filesystem"], check="golden"))
        return cases
    cases = []

    def add(name, args, fixture=(), flags=(), **extra):
        cases.append(dict(name=name, args=args, fixture=list(fixture),
                          flags=list(flags), tags=["filesystem"], check="golden", **extra))

    if utility == "mkdir":
        add("single", ["made"], mode_paths=["made"])
        add("multiple", ["one", "two"], mode_paths=["one", "two"])
        add("missing-parent", ["absent/child"])
        add("existing-directory", ["exists"], [directory("exists")])
        add("existing-file", ["exists"], [file("exists")])
        add("partial-progress", ["first", "exists", "last"], [file("exists")])
        add("spaces", ["directory name"])
        add("terminator", ["--", "-operand", "--"])
        add("bare-dash", ["-"])
        add("no-operands", [])
        add("unknown", ["--invalid-option", "made"])
        add("unknown-after-operand", ["made", "--invalid-option"])
        add("nonutf8-missing-parent", ["missing-\udcff/child"])
        add("link-existing", ["alias"], [directory("target"), link("alias", "target")])
        add("link-parent", ["alias/made"], [directory("target"), link("alias", "target")], mode_paths=["target/made"])
        add("dangling-link", ["alias"], [link("alias", "absent")])
        add("permission", ["locked/made"], [directory("locked", "0555")], needs_non_root=True)
        for mask in ("0000", "0022", "0077", "0777"):
            add("umask-" + mask, ["made"], umask=mask, mode_paths=["made"])
        for name, args in [("parents", ["-p", "a/b/c"]),
                           ("parents-long", ["--parents", "a/b/c"]),
                           ("parents-repeat", ["-p", "-p", "a/b/c", "a/b/c"]),
                           ("parents-after", ["a/b/c", "-p"])]:
            add(name, args, flags=["-p"], mode_paths=["a", "a/b", "a/b/c"])
        add("parents-existing", ["-p", "exists"], [directory("exists", "0700")], ["-p"], mode_paths=["exists"])
        add("parents-file", ["-p", "file/child"], [file("file")], ["-p"])
        add("parents-link", ["-p", "alias/a/b"], [directory("target"), link("alias", "target")], ["-p"])
        add("parents-dot", ["-p", "a/./b/../c/"], flags=["-p"])
        for mask in ("0300", "0777"):
            add("parents-umask-" + mask, ["-p", "a/b/c"], flags=["-p"], umask=mask, mode_paths=["a", "a/b", "a/b/c"])
        modes = ("0000", "0750", "1777", "u=rwx,g=rx,o=", "a=rwX", "=rwx", "u=rw,g=u,o=", "a=rwx,u-w,g-x", "u+r", "u+s,g+s,o+t")
        for index, mode in enumerate(modes):
            for mask in ("0022", "0077"):
                add(f"mode-{index}-{mask}", ["-m", mode, "made"], flags=["-p", "-m"], umask=mask, mode_paths=["made"])
        add("mode-long-equals", ["--mode=0700", "made"], flags=["-p", "-m"], mode_paths=["made"])
        add("mode-long-space", ["--mode", "0751", "made"], flags=["-p", "-m"], mode_paths=["made"])
        add("mode-last", ["-m", "0700", "-m", "0755", "made"], flags=["-p", "-m"], mode_paths=["made"])
        add("mode-after-multiple", ["one", "-m", "0750", "two"], flags=["-p", "-m"], mode_paths=["one", "two"])
        add("mode-parents", ["-p", "-m", "0700", "a/b/c"], flags=["-p", "-m"], umask="0027", mode_paths=["a", "a/b", "a/b/c"])
        add("mode-existing", ["-p", "-m", "0777", "exists"], [directory("exists", "0700")], ["-p", "-m"], mode_paths=["exists"])
        for index, mode in enumerate(("", "888", "u+q", "a++r", "u=r,")):
            add(f"mode-invalid-{index}", ["-m", mode, "made"], flags=["-p", "-m"])
        add("mode-missing", ["-m"], flags=["-p", "-m"])
        return cases

    if utility == "sort":
        from reference_generators.python_sort_cases import public_cases
        return public_cases()
    raise ValueError(utility)


def heldout(utility, public):
    if utility in ("cp", "mv"):
        # The shared dual generator expects this optional field to be present.
        private = transfer_cases.heldout([dict(c, stdin_b64=c.get("stdin_b64", "")) for c in public])
        for case in private:
            if case['dual_of'] == 'second-terminator-operand':
                for entry in case['fixture']:
                    if entry['path'].endswith('/--'):
                        entry['path'] = '--'
        return private
    if utility == "sort":
        from reference_generators.python_sort_heldout import heldout_cases
        return heldout_cases()
    result = []
    for ordinal, original in enumerate(public):
        case = deepcopy(original)
        case.update(name="heldout-" + original["name"], dual_of=original["name"])
        # Work in a distinct subdirectory. Literal option-looking filenames and
        # mode operands stay intact; only fixture path components are renamed.
        prefix = f"private-{utility}-{ordinal:03d}"
        mapping = {}
        for entry in case["fixture"]:
            for part in entry["path"].split("/"):
                if part not in (".", "..", "-", "--"):
                    marker = "-" if part.startswith("-") else "." if part.startswith(".") else ""
                    mapping.setdefault(part, marker + prefix + "-" + part.lstrip(".-"))
        # Also rename creation targets and missing operands, but never mode text.
        mode_next = False
        for arg in case["args"]:
            if mode_next:
                mode_next = False
                continue
            if arg in ("-m", "--mode"):
                mode_next = True
                continue
            if arg and not arg.startswith("-"):
                for part in arg.split("/"):
                    if part not in (".", "..", ""):
                        mapping.setdefault(part, prefix + "-" + part)
        def rename(path):
            return "/".join(mapping.get(p, p) for p in path.split("/"))
        mode_next = False
        args = []
        terminated = False
        for arg in case["args"]:
            if terminated:
                args.append(rename(arg))
            elif arg == '--':
                args.append(arg)
                terminated = True
            elif arg == '--invalid-option':
                args.append('--unknown-' + prefix)
            elif mode_next and len(arg) >= 12:
                args.append(arg + ",u+x")
            else:
                args.append(arg if mode_next or arg.startswith("-") else rename(arg))
            mode_next = arg in ("-m", "--mode")
        case["args"] = args
        for entry in case["fixture"]:
            entry["path"] = rename(entry["path"])
            if entry["type"] == "symlink":
                entry["target"] = rename(entry["target"])
            if entry["type"] == "file" and entry["contents_b64"]:
                entry["contents_b64"] = base64.b64encode((prefix + " payload").encode()).decode()
        case["mode_paths"] = [rename(p) for p in case.get("mode_paths", [])]
        result.append(case)
    return result
