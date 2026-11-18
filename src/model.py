"""Shared data model for depth mode."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class CGFunction:
    """One source-level function in the normalized call graph.

    `id` is "<relative file>::<qualified name>". For Rust generics several
    monomorphised instances collapse into one source function; `depth` is the
    minimum over them and `instances` lists the backend identities.
    """

    id: str
    name: str
    file: str | None
    def_line: int | None
    depth: int | None
    instances: tuple[str, ...] = ()
    is_entry: bool = False
    is_local: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["instances"] = list(self.instances)
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CGFunction":
        return cls(**{**data, "instances": tuple(data.get("instances", ()))})


@dataclass
class CallGraph:
    backend: str
    entry: str
    functions: list[CGFunction]
    edges: list[tuple[str, str]]
    raw: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "entry": self.entry,
            "functions": [f.to_json() for f in self.functions],
            "edges": [list(e) for e in self.edges],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CallGraph":
        return cls(
            backend=data["backend"],
            entry=data["entry"],
            functions=[CGFunction.from_json(f) for f in data["functions"]],
            edges=[tuple(e) for e in data["edges"]],
        )


class StopReason(str, Enum):
    SUCCESS = "success"
    LOOP_LIMIT = "loop_limit"
    NO_PROGRESS = "no_progress"
    TIMEOUT = "timeout"
    BUDGET_EXHAUSTED = "budget_exhausted"
    AGENT_FAILURE = "agent_execution_failure"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


@dataclass
class CheckResult:
    """Outcome of splice -> signature/toggle checks -> build -> visible suite."""

    ok: bool
    stage: str  # "splice" | "signature" | "additions" | "build" | "tests" | "done"
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
