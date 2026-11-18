"""Plugin interfaces (structural Protocols).

Host-side plugins are referenced from config.toml by built-in name or by
"package.module:Class". In-container plugins (language, test runner,
feedback) are referenced by import path and loaded inside the image; see
src/incontainer/lang.py and src/incontainer/run_tests.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from src.model import CallGraph, CGFunction
from src.project import Project


@runtime_checkable
class CallGraphBackend(Protocol):
    """Host plugin. Computes depths from `main` (usually inside a container)."""

    name: str

    def build(self, project: Project, config: Mapping[str, Any], keep_dir: Path | None = None) -> CallGraph: ...


@runtime_checkable
class Selector(Protocol):
    """Host plugin. Returns eligible functions, filtered and ordered. No-arg constructor."""

    def select(self, graph: CallGraph, config: Mapping[str, Any]) -> list[CGFunction]: ...


@runtime_checkable
class Generator(Protocol):
    """Host plugin, constructed with the resolved config.

    run_session(request) receives image, project, suite, context, target,
    start_text, prompt_vars, repair, session_dir (and mock_outputs in tests)
    and returns at least {"final_text", "agents", "timed_out",
    "infrastructure_error"}.
    """

    def run_session(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class LanguageModule(Protocol):
    """In-container module (plugins.language): locate, extract, splice, check.

    list_functions(project, ctx) -> [target]
    locate(project, ctx, key) -> target
    splice(project, ctx, target, edited) -> outcome with .ok .stage .message .additions

    A target is {"language", "key", "name", "file", "start", "end", "line",
    "original_text", "signature", ...}.
    """


@runtime_checkable
class TestRunner(Protocol):
    """In-container plugin (plugins.test_runner), no-arg constructor."""

    def run(self, suite: Path, project: Path, report: Path) -> Mapping[str, Any]: ...


@runtime_checkable
class FeedbackFormatter(Protocol):
    """In-container plugin (plugins.feedback), no-arg constructor."""

    def format(self, result: Mapping[str, Any]) -> str: ...
