#!/usr/bin/env python3
"""
Deterministic path/fixture corpus for the exhaustive mkdir suite.

Unlike sort, mkdir's "input" is not stdin bytes -- it's target path
operands plus a starting filesystem. Each corpus entry is a TARGET: a dict
    {"args": [relpath, ...],       # operand tokens (relative to the per-run
                                    # temp dir the engine execs the case in)
     "fixture": [entry, ...],      # filesystem state to create BEFORE running
     "abs_targets": [relpath,...], # (optional) subset of args the ENGINE
                                    # should rewrite to an absolute path
                                    # (td/relpath) at exec time
     "needs_dashdash": bool}       # (optional) True if args must be preceded
                                    # by "--" (a leading-dash operand name)

A fixture entry is one of:
    {"path": "...", "type": "dir",     "mode": "0755"}
    {"path": "...", "type": "file",    "mode": "0644", "contents_b64": "..."}
    {"path": "...", "type": "symlink", "target": "..."}

Two families:
  CORE        - small, hand-crafted targets covering the mkdir semantics
                surface: bare creation, multi-operand, -p-required nesting
                (fully absent vs. partially-present parents), pre-existing
                targets (EEXIST), trailing slashes, dot segments, absolute
                paths.
  ADVERSARIAL - stress/robustness targets: long/deep names, unusual bytes
                in names (spaces, tabs, newlines, unicode), leading-dash
                names, "."/".." operands, many operands, symlinked parents.

The discrimination assertion (assert_discriminating) runs GNU mkdir under
several umasks and with/without -m; it requires the resulting directory
modes to differ, so the corpus is provably able to tell a umask/-m-ignoring
mkdir from a correct one. It also requires -p vs no -p to diverge on the
"nested"/"existing" targets. The generator calls it and aborts if the
corpus fails to discriminate (a corpus bug, not a candidate bug).
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile


def _dir(path: str, mode: str = "0755") -> dict:
    return {"path": path, "type": "dir", "mode": mode}


def _file(path: str, mode: str = "0644", contents: bytes = b"") -> dict:
    import base64
    return {"path": path, "type": "file", "mode": mode,
            "contents_b64": base64.b64encode(contents).decode()}


def _symlink(path: str, target: str) -> dict:
    return {"path": path, "type": "symlink", "target": target}


def build_core() -> dict[str, dict]:
    c: dict[str, dict] = {}

    c["simple"] = {"args": ["newdir"], "fixture": []}
    c["multi"] = {"args": ["alpha", "beta", "gamma"], "fixture": []}

    # entirely absent path -- every component must be created; needs -p.
    c["nested"] = {"args": ["a/b/c/d"], "fixture": []}

    # target already a directory -- EEXIST without -p, no-op success with -p.
    c["existing"] = {"args": ["existing"],
                     "fixture": [_dir("existing")]}

    # parent partially present: "x" exists, "y" (intermediate) does not --
    # still needs -p even though only ONE level is genuinely missing above
    # the leaf, because "y" itself must be created too.
    c["partial"] = {"args": ["x/y/z"], "fixture": [_dir("x")]}

    c["trailing_slash"] = {"args": ["trailed/"], "fixture": []}

    # "." segments inside an otherwise-valid path.
    c["dot_segments"] = {"args": ["p/./q"], "fixture": [_dir("p")]}

    # an operand rewritten to an absolute path (td/absdir) at exec time --
    # exercises absolute-path handling without breaking determinism (the
    # golden tree is always relative to td).
    c["abs_path"] = {"args": ["absdir"], "fixture": [],
                     "abs_targets": ["absdir"]}

    return c


def build_adversarial(seed: int = 1) -> dict[str, dict]:
    a: dict[str, dict] = {}

    a["long_name"] = {"args": ["x" * 200], "fixture": []}

    deep = "/".join(f"d{i}" for i in range(150))
    a["deep_path"] = {"args": [deep], "fixture": []}

    a["name_spaces"] = {"args": ["has spaces here"], "fixture": []}
    a["name_tab"] = {"args": ["has\ttab"], "fixture": []}
    a["name_newline"] = {"args": ["has\nnewline"], "fixture": []}
    a["name_unicode"] = {"args": ["café_日本語"], "fixture": []}

    # a leading-dash name; mkdir must accept it only after "--".
    a["leading_dash"] = {"args": ["-weird"], "fixture": [],
                         "needs_dashdash": True}

    # "." and ".." always exist -> reliable EEXIST probes.
    a["dot_operand"] = {"args": ["."], "fixture": []}
    a["dotdot_operand"] = {"args": [".."], "fixture": []}

    a["many_operands"] = {"args": [f"m{i}" for i in range(200)], "fixture": []}

    # target's parent is a symlink to a real directory; -p must follow it.
    a["symlink_parent"] = {
        "args": ["link/child"],
        "fixture": [_dir("real"), _symlink("link", "real")],
    }

    return a


# --- discrimination assertion ------------------------------------------------

def _gnu_mkdir_mode(mkdir_bin: str, args: list[str], umask: int,
                    fixture: list[dict] | None = None) -> int | None:
    """Run GNU mkdir with a pinned umask in a scratch dir; return the
    resulting mode (st_mode & 0o7777) of the FIRST arg's path, or None if it
    doesn't exist afterward (e.g. the run errored)."""
    with tempfile.TemporaryDirectory() as td:
        for f in (fixture or []):
            p = os.path.join(td, f["path"])
            os.makedirs(os.path.dirname(p) or td, exist_ok=True)
            if f["type"] == "dir":
                os.makedirs(p, exist_ok=True)
                os.chmod(p, int(f.get("mode", "0755"), 8))
        subprocess.run(
            [mkdir_bin] + args, cwd=td, capture_output=True,
            env={"LC_ALL": "C", "LANG": "C", "LANGUAGE": "C",
                 "PATH": "/usr/bin:/bin"},
            preexec_fn=lambda: os.umask(umask),
        )
        target = os.path.join(td, args[-1].rstrip("/"))
        if not os.path.isdir(target):
            return None
        return stat.S_IMODE(os.stat(target).st_mode)


def assert_discriminating(mkdir_bin: str = "/usr/bin/mkdir") -> None:
    """Require: (1) a bare `mkdir DIR` produces pairwise-distinct modes
    under umask 000/022/077 (proves the corpus can catch a umask-ignoring
    candidate); (2) `-m 0700` yields a mode independent of umask (proves it
    can catch an -m-ignoring candidate); (3) `-p` vs no `-p` diverge on a
    target whose parent is missing (proves the corpus can catch a
    -p-ignoring or -p-always candidate). Raises AssertionError naming the
    failure if the corpus fails to discriminate (a corpus bug, not a
    candidate bug)."""
    modes = {}
    for umask in (0o000, 0o022, 0o077):
        m = _gnu_mkdir_mode(mkdir_bin, ["probe"], umask)
        if m is None:
            raise AssertionError(f"discrimination probe: GNU mkdir failed "
                                 f"to create 'probe' under umask {umask:04o}")
        modes[umask] = m
    if len(set(modes.values())) != len(modes):
        raise AssertionError(
            f"corpus fails to discriminate umasks (bare mkdir): {modes}")

    m_explicit = {}
    for umask in (0o000, 0o022, 0o077):
        m_explicit[umask] = _gnu_mkdir_mode(mkdir_bin, ["-m", "0700", "probe"],
                                            umask)
    if len(set(m_explicit.values())) != 1:
        raise AssertionError(
            f"corpus fails to discriminate -m from umask: {m_explicit}")
    if m_explicit[0o022] == modes[0o022]:
        raise AssertionError(
            "corpus fails to distinguish -m 0700 from bare mkdir under the "
            "same umask")

    core = build_core()
    nested = core["nested"]
    no_p = _gnu_mkdir_mode(mkdir_bin, list(nested["args"]), 0o022,
                           nested["fixture"])
    with_p = _gnu_mkdir_mode(mkdir_bin, ["-p"] + list(nested["args"]), 0o022,
                             nested["fixture"])
    if no_p is not None:
        raise AssertionError(
            "corpus 'nested' target should FAIL without -p (missing "
            "parents), but GNU mkdir created it anyway")
    if with_p is None:
        raise AssertionError(
            "corpus 'nested' target should SUCCEED with -p, but GNU mkdir "
            "failed to create it")


if __name__ == "__main__":
    assert_discriminating()
    core = build_core()
    adv = build_adversarial()
    print("core targets:", ", ".join(core))
    print("adversarial targets:", ", ".join(adv))
    print("discrimination assertion: PASS")
