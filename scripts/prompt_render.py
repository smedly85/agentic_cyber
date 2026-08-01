#!/usr/bin/env python3
"""Expand the shared automation notice into an agent-visible prompt.

**The single expansion point.** `prompts/_shared/automation_notice.md` is the
one canonical copy of the notice; nothing else in the repository may restate it.
Every prompt OpenCode is shown -- checkpoint 000, every feature checkpoint, and
every repair continuation -- is passed through `render()` first, so the notice
reaches the model without any prompt file carrying its own copy to drift from.

Why rendering, rather than pasting the notice into the twenty manifest prompts:

  * one source of truth. Twenty copies is exactly the drift the notice's own
    header warns about, and the experimental design calls this text constant
    across every prompt.
  * the task files stay byte-for-byte as they were, so a prompt diff still
    shows a task change rather than boilerplate.
  * the notice is versioned in the configuration fingerprint through
    `lineage_plan.automation_notice_sha256`, so editing it invalidates a resume
    the same way editing a checkpoint prompt does.

The rendered text is what is written to the durable experiment copy
(`experiment.json` -> `prompt_copy`), what is copied into the sandbox, and what
is handed to `opencode run`. Those are the same bytes by construction: they all
come from this one rendered file.

Placement rule, applied in this order:

  1. already rendered -- the notice text is present -> unchanged (idempotent, so
     re-rendering a rendered prompt is safe).
  2. `[AUTOMATION_NOTICE]` placeholder present -> substituted in place, which is
     how the three templates position it.
  3. otherwise -> prepended, which is how the manifest prompts written before
     the notice existed receive it without being edited.

Whatever the path, the result contains the notice exactly once and never
contains the literal placeholder.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

PLACEHOLDER = "[AUTOMATION_NOTICE]"
NOTICE_RELATIVE = "prompts/_shared/automation_notice.md"

# The file opens with an HTML comment addressed to whoever maintains the notice
# -- which templates carry it, what changing it means for comparability. That is
# repository documentation, not an instruction to the model, and it names other
# prompt files, so it is stripped before the text reaches a session.
_LEADING_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)

# The three templates mark their placeholder with an HTML comment explaining
# that the notice is a harness addition and must not be inlined. That comment
# names the placeholder, so it has to be removed BEFORE substitution or it
# would receive a second copy of the notice -- and, in the repair template,
# whose body is itself sent to the model, it would put repository maintenance
# instructions in front of the agent. Only comments naming the placeholder are
# dropped; ordinary comments in a prompt are left alone.
_MARKER_COMMENT = re.compile(r"[ \t]*<!--.*?-->[ \t]*\n?", re.DOTALL)


class RenderError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"prompt_render: {message}")


def notice_path(repo: Path) -> Path:
    return repo / NOTICE_RELATIVE


def notice_source(repo: Path) -> str:
    path = notice_path(repo)
    if not path.is_file():
        raise RenderError(f"shared automation notice not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RenderError(f"cannot read {path}: {error}") from error


def notice_text(repo: Path) -> str:
    """The agent-visible notice: the file without its maintainer comment."""
    body = _LEADING_COMMENT.sub("", notice_source(repo)).strip()
    if not body:
        raise RenderError(
            f"{NOTICE_RELATIVE} has no body once its comment header is removed"
        )
    return body


def notice_sha256(repo: Path) -> str:
    """Hash of the notice FILE, not of the rendered body.

    Deliberately the whole file: the maintainer comment states what changing
    the wording means for comparability, so an edit to it is still an edit to a
    documented experimental condition and should move the fingerprint.
    """
    return hashlib.sha256(
        notice_source(repo).encode("utf-8")
    ).hexdigest()


def strip_marker_comments(text: str) -> str:
    """Drop the HTML comments that annotate the placeholder."""
    return _MARKER_COMMENT.sub(
        lambda match: "" if PLACEHOLDER in match.group(0) else match.group(0),
        text,
    )


def render(prompt_text: str, notice: str) -> str:
    """Return `prompt_text` with the notice present exactly once."""
    prompt_text = strip_marker_comments(prompt_text)
    if notice in prompt_text:
        rendered = prompt_text.replace(PLACEHOLDER, "").lstrip("\n")
    elif PLACEHOLDER in prompt_text:
        rendered = prompt_text.replace(PLACEHOLDER, notice)
    else:
        rendered = f"{notice}\n\n{prompt_text.lstrip()}"

    if PLACEHOLDER in rendered:
        raise RenderError("placeholder survived rendering")
    occurrences = rendered.count(notice)
    if occurrences != 1:
        raise RenderError(
            f"the notice must appear exactly once, found {occurrences}"
        )
    return rendered


def render_file(repo: Path, prompt: Path) -> str:
    if not prompt.is_file():
        raise RenderError(f"prompt not found: {prompt}")
    try:
        text = prompt.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RenderError(f"cannot read {prompt}: {error}") from error
    return render(text, notice_text(repo))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--prompt", type=Path,
                        help="prompt file to render; omit with --emit notice")
    parser.add_argument("--output", type=Path,
                        help="write here instead of stdout")
    parser.add_argument("--emit", choices=("prompt", "notice", "sha256"),
                        default="prompt")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()

    if args.emit == "sha256":
        print(notice_sha256(repo))
        return 0
    if args.emit == "notice":
        text = notice_text(repo)
    else:
        if args.prompt is None:
            raise RenderError("--prompt is required with --emit prompt")
        text = render_file(repo, args.prompt)

    if args.output is None:
        # LF explicitly: a CRLF-translated prompt would differ from the durable
        # copy byte for byte, which is the one thing this tool guarantees.
        try:
            sys.stdout.reconfigure(newline="\n")
        except (AttributeError, ValueError):        # pragma: no cover
            pass
        print(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RenderError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
