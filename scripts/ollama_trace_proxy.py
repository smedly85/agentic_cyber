#!/usr/bin/env python3
"""Transparent, opt-in metadata tracing proxy for native Ollama HTTP calls.

The proxy deliberately has no model-specific behavior: it forwards request
bytes once, streams response bytes as they arrive, and records only request
metadata plus the terminal Ollama response fields.  Raw prompts are retained
only in the explicitly supplied trace directory.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
COMPLETION_FIELDS = (
    "done",
    "done_reason",
    "eval_count",
    "prompt_eval_count",
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def content_character_length(message: Any, key: str) -> int:
    if not isinstance(message, dict):
        return 0
    value = message.get(key, "")
    return len(value) if isinstance(value, str) else 0


def request_metadata(
    request_id: str,
    method: str,
    path: str,
    body: bytes,
    raw_request_path: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    parsed: dict[str, Any] | None = None
    parse_error: str | None = None
    try:
        value = json.loads(body)
        if isinstance(value, dict):
            parsed = value
        else:
            parse_error = "request JSON is not an object"
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        parse_error = str(error)

    options = parsed.get("options") if parsed else None
    if not isinstance(options, dict):
        options = {}
    messages = parsed.get("messages") if parsed else None
    if not isinstance(messages, list):
        messages = []
    message_metadata = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            message_metadata.append(
                {"index": index, "role": None, "content_character_length": 0}
            )
            continue
        message_metadata.append(
            {
                "index": index,
                "role": message.get("role"),
                "content_character_length": content_character_length(
                    message, "content"
                ),
            }
        )

    event: dict[str, Any] = {
        "event": "request",
        "request_id": request_id,
        "timestamp": utc_timestamp(),
        "method": method,
        "path": path,
        "raw_request_path": raw_request_path,
        "request_body_byte_length": len(body),
        "model": parsed.get("model") if parsed else None,
        "stream": parsed.get("stream") if parsed else None,
        "think": parsed.get("think") if parsed else None,
        "options": {
            key: options[key]
            for key in ("temperature", "num_predict", "top_p", "top_k", "seed")
            if key in options
        },
        "message_count": len(messages),
        "messages": message_metadata,
    }
    if parse_error:
        event["request_json_error"] = parse_error
    return event, parsed


def completion_metadata(
    request_id: str,
    status: int,
    final_object: dict[str, Any] | None,
    *,
    streaming: bool,
    aggregate_thinking_length: int = 0,
    aggregate_content_length: int = 0,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event": "response",
        "request_id": request_id,
        "timestamp": utc_timestamp(),
        "http_status": status,
        "stream": streaming,
    }
    if final_object is None:
        event["response_json_error"] = "no JSON response object was captured"
        return event

    for key in COMPLETION_FIELDS:
        event[key] = final_object.get(key)
    message = final_object.get("message")
    final_thinking = content_character_length(message, "thinking")
    final_content = content_character_length(message, "content")
    if streaming:
        event["message_thinking_character_length"] = aggregate_thinking_length
        event["message_content_character_length"] = aggregate_content_length
        event["final_frame_message_thinking_character_length"] = final_thinking
        event["final_frame_message_content_character_length"] = final_content
    else:
        event["message_thinking_character_length"] = final_thinking
        event["message_content_character_length"] = final_content
    if "error" in final_object:
        event["ollama_error"] = final_object["error"]
    if status >= 400:
        event["http_error"] = {
            "status": status,
            "ollama_error": final_object.get("error"),
        }
    return event


class TraceStore:
    def __init__(self, trace_dir: Path):
        self.trace_dir = trace_dir
        self.requests_dir = trace_dir / "requests"
        self.responses_dir = trace_dir / "responses"
        self.requests_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.responses_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.trace_path = trace_dir / "trace.jsonl"
        self._lock = threading.Lock()
        self._sequence = 0

    def next_id(self) -> str:
        with self._lock:
            request_id = f"request-{self._sequence:03d}"
            self._sequence += 1
            return request_id

    def write_raw_request(self, request_id: str, body: bytes) -> Path:
        path = self.requests_dir / f"{request_id}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
        return path

    def append(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            with self.trace_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)

    def write_response(self, request_id: str, event: dict[str, Any]) -> None:
        path = self.responses_dir / f"{request_id}-metadata.json"
        path.write_text(
            json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


class OllamaTraceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], upstream: str, store: TraceStore):
        super().__init__(address, OllamaTraceHandler)
        parsed = urlsplit(upstream)
        self.upstream_host = parsed.hostname or ""
        self.upstream_port = parsed.port or 80
        self.upstream_authority = parsed.netloc
        self.store = store


class OllamaTraceHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: OllamaTraceServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        self._forward()

    def do_POST(self) -> None:
        self._forward()

    def do_PUT(self) -> None:
        self._forward()

    def do_DELETE(self) -> None:
        self._forward()

    def do_HEAD(self) -> None:
        self._forward()

    def do_OPTIONS(self) -> None:
        self._forward()

    def _read_request_body(self) -> bytes:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            raise ValueError("chunked request bodies are not supported")
        raw_length = self.headers.get("Content-Length", "0")
        length = int(raw_length)
        if length < 0:
            raise ValueError("negative Content-Length")
        return self.rfile.read(length)

    def _upstream_headers(self) -> list[tuple[str, str]]:
        headers = []
        for name, value in self.headers.raw_items():
            lowered = name.lower()
            if lowered in HOP_BY_HOP_HEADERS or lowered == "host":
                continue
            headers.append((name, value))
        headers.append(("Host", self.server.upstream_authority))
        headers.append(("Connection", "close"))
        return headers

    def _send_proxy_error(self, request_id: str, status: int, detail: str) -> None:
        body = json.dumps({"error": detail}, separators=(",", ":")).encode("utf-8")
        event = {
            "event": "proxy_error",
            "request_id": request_id,
            "timestamp": utc_timestamp(),
            "http_status": status,
            "proxy_error": detail,
        }
        self.server.store.append(event)
        self.server.store.write_response(request_id, event)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def _forward(self) -> None:
        request_id = self.server.store.next_id()
        try:
            body = self._read_request_body()
        except (ValueError, OSError) as error:
            self._send_proxy_error(request_id, 400, str(error))
            return

        raw_path = self.server.store.write_raw_request(request_id, body)
        relative_path = raw_path.relative_to(self.server.store.trace_dir).as_posix()
        request_event, parsed_request = request_metadata(
            request_id, self.command, self.path, body, relative_path
        )
        self.server.store.append(request_event)

        connection = http.client.HTTPConnection(
            self.server.upstream_host, self.server.upstream_port, timeout=3600
        )
        try:
            connection.putrequest(
                self.command, self.path, skip_host=True, skip_accept_encoding=True
            )
            for name, value in self._upstream_headers():
                connection.putheader(name, value)
            connection.endheaders(body if body else None)
            upstream = connection.getresponse()
        except (OSError, http.client.HTTPException) as error:
            connection.close()
            self._send_proxy_error(request_id, 502, f"upstream request failed: {error}")
            return

        self.send_response_only(upstream.status, upstream.reason)
        has_content_length = False
        for name, value in upstream.getheaders():
            lowered = name.lower()
            if lowered in HOP_BY_HOP_HEADERS:
                continue
            if lowered == "content-length":
                has_content_length = True
            self.send_header(name, value)
        if not has_content_length:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()

        streaming = bool(parsed_request and parsed_request.get("stream") is True)
        response_buffer = bytearray()
        ndjson_pending = bytearray()
        final_object: dict[str, Any] | None = None
        aggregate_thinking = 0
        aggregate_content = 0

        try:
            while True:
                chunk = upstream.read1(65536)
                if not chunk:
                    break
                if self.command != "HEAD":
                    self.wfile.write(chunk)
                    self.wfile.flush()
                if streaming:
                    ndjson_pending.extend(chunk)
                    while b"\n" in ndjson_pending:
                        line, _, remainder = ndjson_pending.partition(b"\n")
                        ndjson_pending = bytearray(remainder)
                        try:
                            frame = json.loads(line)
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            continue
                        if isinstance(frame, dict):
                            final_object = frame
                            message = frame.get("message")
                            aggregate_thinking += content_character_length(
                                message, "thinking"
                            )
                            aggregate_content += content_character_length(
                                message, "content"
                            )
                else:
                    response_buffer.extend(chunk)
        finally:
            upstream.close()
            connection.close()

        if streaming and ndjson_pending.strip():
            try:
                frame = json.loads(ndjson_pending)
            except (UnicodeDecodeError, json.JSONDecodeError):
                frame = None
            if isinstance(frame, dict):
                final_object = frame
                message = frame.get("message")
                aggregate_thinking += content_character_length(message, "thinking")
                aggregate_content += content_character_length(message, "content")
        elif not streaming:
            try:
                value = json.loads(response_buffer)
                if isinstance(value, dict):
                    final_object = value
            except (UnicodeDecodeError, json.JSONDecodeError):
                final_object = None

        response_event = completion_metadata(
            request_id,
            upstream.status,
            final_object,
            streaming=streaming,
            aggregate_thinking_length=aggregate_thinking,
            aggregate_content_length=aggregate_content,
        )
        self.server.store.append(response_event)
        self.server.store.write_response(request_id, response_event)


def contained_trace_dir(trace_dir: Path, allowed_root: Path) -> Path:
    root = allowed_root.resolve(strict=True)
    resolved = trace_dir.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"trace directory {resolved} is outside allowed root {root}"
        ) from error
    return resolved


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--allowed-root", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    upstream = urlsplit(args.upstream)
    if (
        upstream.scheme != "http"
        or upstream.hostname not in {"127.0.0.1", "localhost", "::1"}
        or upstream.path not in {"", "/"}
        or upstream.query
        or upstream.fragment
    ):
        raise SystemExit(
            "--upstream must be an HTTP loopback root such as http://127.0.0.1:11434"
        )

    trace_dir = contained_trace_dir(args.trace_dir, args.allowed_root)
    store = TraceStore(trace_dir)
    server = OllamaTraceServer(("127.0.0.1", 0), args.upstream.rstrip("/"), store)
    ready_file = args.ready_file.resolve(strict=False)
    try:
        ready_file.relative_to(args.allowed_root.resolve(strict=True))
    except ValueError as error:
        server.server_close()
        raise SystemExit("--ready-file must be inside --allowed-root") from error
    # This file is consumed by Bash even when the proxy runs under native
    # Windows Python. Write bytes so newline translation cannot leave a CR in
    # OLLAMA_API_BASE.
    ready_file.write_bytes(f"http://127.0.0.1:{server.server_address[1]}\n".encode())
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
