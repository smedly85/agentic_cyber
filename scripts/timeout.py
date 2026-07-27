#!/usr/bin/env python3
"""A portable subset of GNU coreutils `timeout`.

macOS ships no `timeout`, and Homebrew is not writable on this machine, so
scripts/run_experiment.sh otherwise runs every OpenCode session unbounded and
records timeout_enforced: false. This implements exactly the invocation that
script uses:

    timeout --signal=TERM --kill-after=30 SECONDS COMMAND [ARG...]

Semantics follow GNU: exit 124 on timeout, 125 on usage error, 126 if the
command cannot be executed, 127 if it is not found, otherwise the command's own
exit status (128+N when it died from signal N).
"""

import os
import signal
import subprocess
import sys
import time


def die(message: str, code: int = 125) -> "None":
    print(f"timeout: {message}", file=sys.stderr)
    raise SystemExit(code)


def parse_duration(text: str) -> float:
    # GNU accepts an optional s/m/h/d suffix.
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    scale = 1
    if text and text[-1] in multipliers:
        scale = multipliers[text[-1]]
        text = text[:-1]
    try:
        value = float(text)
    except ValueError:
        die(f"invalid time interval {text!r}")
    if value < 0:
        die(f"invalid time interval {text!r}")
    return value * scale


def parse_signal(name: str) -> int:
    name = name.upper()
    if name.isdigit():
        return int(name)
    if not name.startswith("SIG"):
        name = "SIG" + name
    try:
        return int(getattr(signal, name))
    except AttributeError:
        die(f"unknown signal {name!r}")
    return 0  # unreachable; keeps type checkers quiet


def main(argv: list[str]) -> int:
    term_signal = signal.SIGTERM
    kill_after = None
    args = argv[1:]

    while args and args[0].startswith("-") and args[0] != "--":
        arg = args.pop(0)
        if arg in ("-s", "--signal"):
            if not args:
                die("option requires an argument -- 's'")
            term_signal = parse_signal(args.pop(0))
        elif arg.startswith("--signal="):
            term_signal = parse_signal(arg.split("=", 1)[1])
        elif arg in ("-k", "--kill-after"):
            if not args:
                die("option requires an argument -- 'k'")
            kill_after = parse_duration(args.pop(0))
        elif arg.startswith("--kill-after="):
            kill_after = parse_duration(arg.split("=", 1)[1])
        elif arg in ("-f", "--foreground", "--preserve-status", "-p"):
            # Accepted and ignored: this shim always runs the child in its own
            # session, and always reports 124 for a timeout.
            pass
        else:
            die(f"unrecognized option {arg!r}")

    if args and args[0] == "--":
        args.pop(0)
    if len(args) < 2:
        die("usage: timeout [OPTION]... DURATION COMMAND [ARG]...")

    duration = parse_duration(args.pop(0))

    try:
        # A new session means the whole process tree can be signalled at once.
        # OpenCode spawns helpers, and signalling only the direct child would
        # leave those running and holding the pipe open.
        child = subprocess.Popen(args, start_new_session=True)
    except FileNotFoundError:
        die(f"failed to run command {args[0]!r}: No such file or directory", 127)
    except OSError as exc:
        die(f"failed to run command {args[0]!r}: {exc.strerror}", 126)

    # Captured now, while the child is certainly alive: once it is reaped
    # os.getpgid() fails, and the group still needs signalling because members
    # can outlive the leader.
    try:
        child_pgid = os.getpgid(child.pid)
    except ProcessLookupError:
        child_pgid = None

    def signal_group(sig: int) -> None:
        if child_pgid is not None:
            try:
                os.killpg(child_pgid, sig)
                return
            except (ProcessLookupError, PermissionError):
                pass
        # No group left, or the child changed credentials; fall back to the
        # direct child so a timeout still terminates something.
        try:
            child.send_signal(sig)
        except ProcessLookupError:
            pass

    def sweep_group() -> None:
        """Clear anything still in the group after the direct child is gone.

        The child is not always the last process standing. `sh -c 'cmd &'`
        leaves the background job in the same group, and a non-interactive
        shell sets SIGINT to ignore for exactly those jobs -- so the leader can
        exit on the first signal while a sibling keeps running.
        """
        if child_pgid is None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(child_pgid, sig)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.2)

    timed_out = False
    try:
        if duration > 0:
            try:
                child.wait(timeout=duration)
            except subprocess.TimeoutExpired:
                timed_out = True
                signal_group(term_signal)
                if kill_after is not None:
                    try:
                        child.wait(timeout=kill_after)
                    except subprocess.TimeoutExpired:
                        signal_group(signal.SIGKILL)
                child.wait()
                sweep_group()
        else:
            child.wait()
    except KeyboardInterrupt:
        # Ctrl-C during a sweep has to clear the whole tree, so the next run
        # does not compete with a stray agent helper still holding the model.
        signal_group(signal.SIGINT)
        try:
            child.wait(timeout=kill_after if kill_after is not None else 10)
        except subprocess.TimeoutExpired:
            pass
        sweep_group()
        return 128 + signal.SIGINT

    if timed_out:
        return 124
    status = child.returncode
    return 128 - status if status < 0 else status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
