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

    def signal_group(sig: int) -> None:
        try:
            os.killpg(os.getpgid(child.pid), sig)
        except (ProcessLookupError, PermissionError):
            # Already reaped, or the child changed credentials; fall back to
            # the direct child so a timeout still terminates something.
            try:
                child.send_signal(sig)
            except ProcessLookupError:
                pass

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
        else:
            child.wait()
    except KeyboardInterrupt:
        signal_group(signal.SIGINT)
        child.wait()
        return 128 + signal.SIGINT

    if timed_out:
        return 124
    status = child.returncode
    return 128 - status if status < 0 else status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
