#!/usr/bin/env python3
"""Observe the umask in the process that actually execs GNU mkdir.

**Offline only. Never copied into an agent-visible bundle.**

Why this exists
---------------
A GNU regeneration produced mode 01755 for `single-m-+t-simple-0000`, `-0022`
and `-0077` alike, while the committed goldens hold 01777 for all three.

An earlier version of this script measured the umask with *helper* subprocesses
(`sh -c umask`) and showed 0000/0022/0077 arriving correctly. That proves the
mechanism can set a umask; it does **not** prove the mkdir subprocess ran under
it, because it never observed the process that execs mkdir. This version does:
it interposes a wrapper that records `umask` and `argv` immediately before
`exec`ing the real binary, and runs that wrapper through every path that
matters.

It also verifies the binary's *version* before measuring anything. That is a
guard, not the explanation for the discrepancy: the earlier 01755 readings were
confirmed to come from the pinned `/tmp/coreutils-9.11/src/mkdir` reporting
"mkdir (GNU coreutils) 9.11". The check exists so a future run cannot quietly
measure a different build; it does not account for these numbers.

So the open question is narrower than it first looked. 0755 is 0777 & ~0022,
but at umask 0000 no umask-based masking can yield 0755 -- yet `-m +t` produced
01755 there too. Either the umask never reaches mkdir (section 2 settles that
directly) or the departure point for a symbolic `-m` is not `a=rwx`. The bare
`mkdir` row of the matrix discriminates: if it varies 0777/0755/0700 while
`-m +t` stays 01755, the umask is arriving and `-m` is the outlier.

Usage (inside the pinned container, as an unprivileged user):

    python3 tests/reference_generators/umask_diagnostic.py \\
        --mkdir-bin /tmp/coreutils-9.11/src/mkdir

    # measure a deliberately different build:
    python3 tests/reference_generators/umask_diagnostic.py \\
        --mkdir-bin /usr/bin/mkdir --allow-version-mismatch
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

UMASKS = (0o000, 0o022, 0o077)

# The mode expressions to characterize. `-m +t` is the one the goldens disagree
# on; the rest are controls that between them identify where 0755 comes from.
#
# The reasoning the matrix has to settle: 0755 is 0777 & ~0022, but under umask
# 0000 NO umask-based masking can produce 0755. So if `-m +t` yields 01755 even
# at umask 0000, the 0755 is not coming from the umask, and only two
# explanations remain -- the umask is not reaching mkdir at all (which the
# pre-exec instrumentation tests directly), or the departure point for a
# symbolic -m is not a=rwx as documented.
#
#   None        bare mkdir, no -m. THE decisive control: its mode must vary
#               0777 / 0755 / 0700 across the three umasks. If it does, the
#               umask demonstrably reaches mkdir and the -m path is the outlier.
#               If it does not, the umask never arrived and nothing else in the
#               table means anything.
#   "a=rwx"     explicit who, no sticky. Documented departure point, isolated.
#   "+t"        the disputed expression: no who, so umask governs which bits
#               are affected -- but the sticky bit is not in any umask.
#   "a+t"       same change with an explicit who, so umask cannot apply.
#   "a=rwx,+t"  departure stated explicitly, then sticky added.
#   "1777"      octal: umask-independent by definition. If this is not 1777,
#               something outside mode parsing is rewriting the mode.
#   "-t"        removes a bit the new directory never had, so the result IS
#               the departure point with no change applied. This is what
#               names the 0755 base directly.
MODE_EXPRESSIONS: tuple[str | None, ...] = (
    None, "a=rwx", "-t", "+t", "a+t", "a=rwx,+t", "1777",
)

WRAPPER = """#!/bin/sh
# Records the umask of THIS process -- the one that is about to exec the real
# binary -- then execs it unchanged. `umask` is a shell builtin, so the value
# printed is this process's own, not a child's.
printf 'umask=%s argv=%s\\n' "$(umask)" "$*" >> "{log}"
exec "{real}" "$@"
"""


def make_wrapper(directory: Path, real: str, tag: str) -> tuple[Path, Path]:
    """(wrapper, log). One log per tag so concurrent runs cannot interleave."""
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / f"{tag}.log"
    wrapper = directory / f"mkdir-{tag}"
    wrapper.write_text(WRAPPER.format(log=log.as_posix(), real=real),
                       encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper, log


def read_log(log: Path) -> list[str]:
    if not log.is_file():
        return []
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line]


def version_line(binary: str) -> str:
    try:
        completed = subprocess.run([binary, "--version"], capture_output=True,
                                   timeout=20)
    except (OSError, subprocess.SubprocessError) as error:
        return f"<cannot run --version: {error}>"
    text = completed.stdout.decode("utf-8", "replace").strip()
    return text.splitlines()[0] if text else ""


def direct_shell_matrix(mkdir_bin: str) -> list[tuple[str, str, str, str]]:
    """The control experiment, with no Python between the umask and mkdir.

    A subshell sets the umask, reports it back, runs mkdir, and stats the
    result -- the same shape as running it by hand.
    """
    rows = []
    for expression in MODE_EXPRESSIONS:
        for umask in UMASKS:
            with tempfile.TemporaryDirectory() as scratch:
                target = f"{scratch}/d"
                # `expression is None` means no -m at all: the control that
                # shows whether the umask reaches mkdir independently of any
                # mode-parsing question.
                mode_args = "" if expression is None else f'-m "{expression}" '
                script = (
                    f'umask {umask:04o}\n'
                    f'printf "before=%s " "$(umask)"\n'
                    f'"{mkdir_bin}" {mode_args}"{target}" 2>&1 || '
                    f'{{ printf "mkdir-failed"; exit 0; }}\n'
                    f'printf "mode=%s" "$(stat -c %a "{target}" '
                    f'2>/dev/null || stat -f %Lp "{target}")"\n'
                )
                completed = subprocess.run(["sh", "-c", script],
                                           capture_output=True, text=True)
                rows.append((expression, f"{umask:04o}",
                             completed.stdout.strip(),
                             completed.stderr.strip()))
    return rows


def frozen_case(suite_root: Path, name: str) -> dict | None:
    for path in sorted((suite_root / "suites").glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        cases = payload["cases"] if isinstance(payload, dict) else payload
        for case in cases:
            if case.get("name") == name:
                return case
    return None


def engine_run(suite_root: Path, wrapper: Path, case: dict) -> str:
    sys.path.insert(0, str(suite_root))
    import engine  # noqa: E402

    result = engine.execute(case, [str(wrapper)])
    dirs = [e for e in (result.tree or []) if e.get("type") == "dir"]
    if not dirs:
        return f"<no directory: rc={result.exit_code} err={result.stderr[:80]!r}>"
    return ",".join(f"{e['path']}={e['mode']:05o}" for e in dirs)


def runner_run(suite_root: Path, wrapper: Path, case: dict) -> str:
    """The candidate-evaluation path, not the freeze path."""
    sys.path.insert(0, str(suite_root))
    import runner  # noqa: E402

    verdict, detail = runner.run_one(case, [str(wrapper)], False, False)
    return f"{verdict} {detail}".strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mkdir-bin", default=None,
                        help="GNU mkdir to measure; resolved via "
                             "oracle_contract when omitted")
    parser.add_argument("--suite-root", type=Path,
                        default=Path(__file__).resolve().parents[1] / "mkdir-test-suite")
    parser.add_argument("--allow-version-mismatch", action="store_true",
                        help="measure a binary that is not the pinned version")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from reference_generators import oracle_contract

    config = args.suite_root / "config.json"
    mkdir_bin = args.mkdir_bin or oracle_contract.resolve("mkdir", config)

    print(f"mkdir binary : {mkdir_bin}")
    print(f"version      : {version_line(mkdir_bin)}")
    pinned = oracle_contract.required_version("mkdir", args.suite_root, config)
    print(f"pinned       : GNU coreutils {pinned}")
    problems = oracle_contract.verify("mkdir", args.suite_root, mkdir_bin, config)
    if problems:
        for problem in problems:
            print(f"  !! {problem}")
        if not args.allow_version_mismatch:
            print("\nRefusing to measure: every number below would describe a "
                  "binary the goldens did not come from.\nPass "
                  "--allow-version-mismatch to measure anyway.")
            return 2
        print("\n  (measuring anyway at your request)\n")

    current = os.umask(0o022)
    os.umask(current)
    print(f"this process : umask {current:04o}")

    print("\n== 1. direct shell, no Python between umask and mkdir ==")
    print(f"{'-m':>10}  {'umask':>5}  result")
    for expression, umask, out, err in direct_shell_matrix(mkdir_bin):
        label = "(no -m)" if expression is None else expression
        print(f"{label:>10}  {umask:>5}  {out}{('  stderr=' + err) if err else ''}")

    workspace = Path(tempfile.mkdtemp(prefix="umask-diag-"))
    print(f"\n== 2. umask observed IN the process that execs mkdir ==")
    print(f"   (wrapper logs under {workspace})")

    wrapper, log = make_wrapper(workspace, mkdir_bin, "direct")
    for umask in UMASKS:
        with tempfile.TemporaryDirectory() as scratch:
            subprocess.run(["sh", "-c",
                            f'umask {umask:04o}; "{wrapper}" -m +t "{scratch}/d"'],
                           capture_output=True)
    print("   via direct shell:")
    for line in read_log(log):
        print(f"     {line}")

    print("   via engine.execute on the real frozen cases:")
    for name in ("single-m-+t-simple-0000", "single-m-+t-simple-0022",
                 "single-m-+t-simple-0077", "quirk-sticky-symbolic"):
        case = frozen_case(args.suite_root, name)
        if case is None:
            print(f"     {name:26s} <not found>")
            continue
        case_wrapper, case_log = make_wrapper(workspace, mkdir_bin, f"engine-{name}")
        produced = engine_run(args.suite_root, case_wrapper, case)
        declared = case.get("umask", "(absent -> 0022)")
        frozen = {e["path"]: f"{e['mode']:05o}" for e in (case.get("tree") or [])
                  if e.get("type") == "dir"}
        print(f"     {name:26s} declared={declared:>20}")
        for line in read_log(case_log):
            print(f"       exec saw : {line}")
        print(f"       engine got: {produced}")
        print(f"       frozen    : {frozen}")

    print("   via the candidate-evaluation runner path:")
    for name in ("single-m-+t-simple-0000", "single-m-+t-simple-0077"):
        case = frozen_case(args.suite_root, name)
        if case is None:
            continue
        case_wrapper, case_log = make_wrapper(workspace, mkdir_bin, f"runner-{name}")
        verdict = runner_run(args.suite_root, case_wrapper, case)
        print(f"     {name:26s} verdict={verdict[:70]}")
        for line in read_log(case_log):
            print(f"       exec saw : {line}")

    print("\nRead this as: if 'exec saw' shows the declared umask on every line, "
          "the\numask reaches mkdir and any remaining mode difference is GNU "
          "behavior, not\na suite defect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
