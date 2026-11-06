"""OpenAI-compatible proxy that records every chat completion as a trace.

Clients point their base URL at the proxy instead of the provider. Chat
completions (streaming or not) are relayed unchanged and logged; every other
/v1 endpoint is passed through without logging.

Optional request headers group calls for the profiler and are never forwarded:
  X-Tokenprof-Run   identifies one agent run
  X-Tokenprof-Step  names the agent step that made the call
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .pricing import Pricing
from .trace import TraceWriter

RUN_HEADER = "x-tokenprof-run"
STEP_HEADER = "x-tokenprof-step"

_DROP_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "accept-encoding",
    RUN_HEADER,
    STEP_HEADER,
}
_DROP_RESPONSE_HEADERS = {"content-length", "content-encoding", "transfer-encoding", "connection"}
_MAX_ERROR_BODY = 4000


def create_app(
    upstream: str,
    writer: TraceWriter,
    pricing: Pricing | None = None,
    *,
    inject_stream_usage: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the proxy app.

    upstream: base URL of the OpenAI-compatible API, including the version
        prefix (e.g. "https://api.openai.com/v1" or "http://localhost:11434/v1").
    inject_stream_usage: ask for token usage on streaming requests
        (stream_options.include_usage) when the client did not set stream_options.
    transport: custom httpx transport, used by the tests.
    """
    base_url = upstream.rstrip("/")
    client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(600.0, connect=10.0))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await client.aclose()

    app = FastAPI(title="tokenprof proxy", lifespan=lifespan)

    async def finish(record: dict[str, Any], started: float) -> None:
        record["latency_ms"] = _elapsed_ms(started)
        if pricing is not None:
            record["cost_usd"] = pricing.cost(record["response_model"] or record["model"], record["usage"])
        await writer.write(record)

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        started = time.perf_counter()
        try:
            body = json.loads(await request.body())
        except json.JSONDecodeError:
            return JSONResponse({"error": {"message": "request body is not valid JSON"}}, status_code=400)

        record = _new_record(request, body)
        stream = bool(body.get("stream"))
        if stream and inject_stream_usage and "stream_options" not in body:
            body["stream_options"] = {"include_usage": True}

        upstream_request = client.build_request(
            "POST",
            f"{base_url}/chat/completions",
            headers=_forward_headers(request),
            json=body,
        )
        try:
            upstream_response = await client.send(upstream_request, stream=stream)
        except httpx.HTTPError as exc:
            record["status"] = 502
            record["error"] = f"upstream request failed: {exc!r}"
            await finish(record, started)
            return JSONResponse({"error": {"message": "upstream request failed"}}, status_code=502)

        record["status"] = upstream_response.status_code
        headers = _response_headers(upstream_response)

        if not stream:
            _record_completion(record, upstream_response)
            await finish(record, started)
            return Response(upstream_response.content, upstream_response.status_code, headers=headers)

        async def relay() -> AsyncIterator[bytes]:
            acc = _StreamAccumulator()
            error_body = bytearray()
            try:
                async for chunk in upstream_response.aiter_bytes():
                    if acc.feed(chunk) and record["ttft_ms"] is None:
                        record["ttft_ms"] = _elapsed_ms(started)
                    if upstream_response.status_code >= 400 and len(error_body) < _MAX_ERROR_BODY:
                        error_body.extend(chunk)
                    yield chunk
            except httpx.HTTPError as exc:
                record["error"] = f"stream interrupted: {exc!r}"
            finally:
                await upstream_response.aclose()
                acc.apply(record)
                if error_body:
                    record["error"] = error_body[:_MAX_ERROR_BODY].decode("utf-8", errors="replace")
                await finish(record, started)

        return StreamingResponse(relay(), status_code=upstream_response.status_code, headers=headers)

    @app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def passthrough(path: str, request: Request) -> Response:
        upstream_request = client.build_request(
            request.method,
            f"{base_url}/{path}",
            headers=_forward_headers(request),
            params=request.query_params,
            content=await request.body(),
        )
        try:
            upstream_response = await client.send(upstream_request)
        except httpx.HTTPError:
            return JSONResponse({"error": {"message": "upstream request failed"}}, status_code=502)
        return Response(
            upstream_response.content,
            upstream_response.status_code,
            headers=_response_headers(upstream_response),
        )

    return app


def _new_record(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": request.headers.get(RUN_HEADER),
        "step": request.headers.get(STEP_HEADER),
        "endpoint": "chat.completions",
        "model": body.get("model"),
        "response_model": None,
        "stream": bool(body.get("stream")),
        "status": None,
        "latency_ms": None,
        "ttft_ms": None,
        "usage": None,
        "cost_usd": None,
        "request": copy.deepcopy(body),
        "response": None,
        "error": None,
    }


def _record_completion(record: dict[str, Any], response: httpx.Response) -> None:
    if response.status_code >= 400:
        record["error"] = response.text[:_MAX_ERROR_BODY]
        return
    try:
        data = response.json()
    except json.JSONDecodeError:
        record["error"] = "upstream returned a non-JSON body"
        return
    record["response_model"] = data.get("model")
    record["usage"] = _normalize_usage(data.get("usage"))
    choices = data.get("choices") or [{}]
    message = choices[0].get("message") or {}
    record["response"] = {
        "content": message.get("content"),
        "tool_calls": message.get("tool_calls"),
        "finish_reason": choices[0].get("finish_reason"),
    }


class _StreamAccumulator:
    """Rebuilds the first choice of a streamed completion from its SSE chunks."""

    def __init__(self) -> None:
        self._buffer = b""
        self._content: list[str] = []
        self._tool_calls: dict[int, dict[str, Any]] = {}
        self._finish_reason: str | None = None
        self._usage: dict[str, Any] | None = None
        self._model: str | None = None

    def feed(self, chunk: bytes) -> bool:
        """Consume raw bytes; return True if they carried new output (text or tool calls)."""
        self._buffer += chunk
        saw_output = False
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            saw_output |= self._handle_line(line.strip())
        return saw_output

    def _handle_line(self, line: bytes) -> bool:
        if not line.startswith(b"data:"):
            return False
        data = line[len(b"data:"):].strip()
        if not data or data == b"[DONE]":
            return False
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            return False

        self._model = event.get("model") or self._model
        if event.get("usage"):
            self._usage = event["usage"]

        saw_output = False
        for choice in event.get("choices") or []:
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            if delta.get("content"):
                self._content.append(delta["content"])
                saw_output = True
            for call in delta.get("tool_calls") or []:
                slot = self._tool_calls.setdefault(
                    call.get("index", 0),
                    {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if call.get("id"):
                    slot["id"] = call["id"]
                function = call.get("function") or {}
                slot["function"]["name"] += function.get("name") or ""
                slot["function"]["arguments"] += function.get("arguments") or ""
                saw_output = True
            if choice.get("finish_reason"):
                self._finish_reason = choice["finish_reason"]
        return saw_output

    def apply(self, record: dict[str, Any]) -> None:
        if self._buffer.strip():
            self._handle_line(self._buffer.strip())
            self._buffer = b""
        record["response_model"] = self._model
        record["usage"] = _normalize_usage(self._usage)
        record["response"] = {
            "content": "".join(self._content) if self._content else None,
            "tool_calls": [self._tool_calls[i] for i in sorted(self._tool_calls)] or None,
            "finish_reason": self._finish_reason,
        }


def _normalize_usage(usage: dict[str, Any] | None) -> dict[str, int | None] | None:
    """cached_tokens is None when the provider does not report cache usage at all,
    which is different from reporting that nothing was cached."""
    if not usage:
        return None
    details = usage.get("prompt_tokens_details")
    cached = (details.get("cached_tokens") or 0) if isinstance(details, dict) else None
    return {
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or 0,
        "total_tokens": usage.get("total_tokens") or 0,
        "cached_tokens": cached,
    }


def _forward_headers(request: Request) -> dict[str, str]:
    return {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST_HEADERS}


def _response_headers(response: httpx.Response) -> dict[str, str]:
    return {k: v for k, v in response.headers.items() if k.lower() not in _DROP_RESPONSE_HEADERS}


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
