"""LLM response cache around a mini-swe-agent model (runs inside the agent container).

Modes (session["llm_cache"]["mode"]):
  record  call the model; store every response
  auto    serve a cached response when one matches; otherwise call and store
  replay  serve cached responses only; a miss raises CacheMiss and the agent
          stops (no model is ever called)

Match (session["llm_cache"]["match"]) chooses the lookup key:
  exact     scope + agent label + model/sampling + the conversation so far.
            A hit means the model would see exactly the same input.
  sequence  scope + agent label + call index. Replays the recorded actions
            even when tool observations differ, which is what you want when
            testing a pipeline change without an LLM.

Both keys are always written, so either match works for later replays.
Format errors (e.g. finish_reason=length) are cached as well and re-raised on
replay, so replayed trajectories follow the recorded ones.
Entries live in /src/cache (host: <cache dir>/llm).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from minisweagent.exceptions import InterruptAgentFlow

CACHE_ROOT = Path("/src/cache")
STATS = Path("/src/out/llm-cache.jsonl")


class CacheMiss(RuntimeError):
    pass


def _digest(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _strip(messages: list[dict]) -> list[dict]:
    """The model-visible part of the conversation (no timestamps / extras)."""
    keep = ("role", "content", "tool_calls", "tool_call_id", "name")
    return [{k: m.get(k) for k in keep if m.get(k) is not None} for m in messages]


class CachedModel:
    def __init__(self, inner: Any, settings: dict[str, Any], label: str, model_id: Any):
        self.__dict__.update(_inner=inner, _settings=settings, _label=label, _model_id=model_id, _calls=0, hits=0, misses=0)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["_inner"], name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__dict__:
            self.__dict__[name] = value
        else:
            setattr(self.__dict__["_inner"], name, value)

    # ------------------------------------------------------------------ keys
    def _keys(self, messages: list[dict], kwargs: dict) -> tuple[str, str]:
        scope = self._settings["scope"]
        exact = _digest("exact", scope, self._label, self._model_id, _strip(messages), kwargs)
        seq = _digest("seq", scope, self._label, self._calls)
        return exact, seq

    @staticmethod
    def _path(kind: str, key: str) -> Path:
        return CACHE_ROOT / kind / key[:2] / f"{key}.json"

    def _load(self, kind: str, key: str) -> dict | None:
        path = self._path(kind, key)
        return json.loads(path.read_text()) if path.is_file() else None

    def _store(self, entry: dict, exact: str, seq: str) -> None:
        blob = json.dumps(entry, default=str)
        for kind, key in (("exact", exact), ("seq", seq)):
            path = self._path(kind, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            with os.fdopen(fd, "w") as fh:
                fh.write(blob)
            os.replace(tmp, path)

    def _log(self, outcome: str, exact: str, seq: str) -> None:
        with STATS.open("a") as fh:
            fh.write(json.dumps({"label": self._label, "call": self._calls, "outcome": outcome, "exact": exact[:16], "seq": seq[:16]}) + "\n")

    # ------------------------------------------------------------------ query
    def query(self, messages: list[dict], **kwargs) -> dict:
        mode, match = self._settings["mode"], self._settings["match"]
        exact, seq = self._keys(messages, kwargs)
        try:
            if mode in ("auto", "replay"):
                entry = self._load("exact" if match == "exact" else "seq", exact if match == "exact" else seq)
                if entry is not None:
                    self.hits += 1
                    self._log("hit", exact, seq)
                    return self._serve(entry)
                if mode == "replay":
                    self._log("miss", exact, seq)
                    raise CacheMiss(f"no cached response for {self._label} call {self._calls} ({match} match)")
            self.misses += 1
            try:
                message = self._inner.query(messages, **kwargs)
            except InterruptAgentFlow as exc:  # e.g. FormatError: cache it too
                cls = type(exc)
                self._store({"exception": f"{cls.__module__}:{cls.__qualname__}", "messages": list(exc.messages)}, exact, seq)
                self._log("stored-exception", exact, seq)
                raise
            self._store({"message": message}, exact, seq)
            self._log("stored", exact, seq)
            return message
        finally:
            self.__dict__["_calls"] += 1

    @staticmethod
    def _serve(entry: dict) -> dict:
        if "exception" in entry:
            module, _, name = entry["exception"].partition(":")
            raise getattr(importlib.import_module(module), name)(*entry["messages"])
        message = entry["message"]
        message.setdefault("extra", {})["llm_cache"] = "hit"
        return message


def wrap(model: Any, session: dict[str, Any], role: str, label: str) -> Any:
    settings = session.get("llm_cache")
    if not settings:
        return model
    spec = session["models"][role]
    model_id = {
        "model": spec["model"],
        "model_class": session["model_class"],
        "sampling": session["sampling"].get(role, {}),
    }
    return CachedModel(model, settings, label, model_id)
