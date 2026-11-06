import json

import httpx
from fastapi.testclient import TestClient

from tokenprof.pricing import ModelPrice, Pricing
from tokenprof.proxy import _StreamAccumulator, create_app
from tokenprof.trace import TraceWriter, read_traces

UPSTREAM = "https://llm.example/v1"
PRICING = Pricing({"test-model": ModelPrice(input_per_mtok=1.0, output_per_mtok=2.0, cached_input_per_mtok=0.1)})


def sse(*events: dict) -> bytes:
    lines = [f"data: {json.dumps(e)}\n\n" for e in events]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


def make_client(tmp_path, handler, **kwargs):
    writer = TraceWriter(tmp_path / "traces.jsonl")
    app = create_app(UPSTREAM, writer, PRICING, transport=httpx.MockTransport(handler), **kwargs)
    return TestClient(app), writer.path


def test_non_streaming_call_is_relayed_and_logged(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "model": "test-model-2025",
                "choices": [{"message": {"role": "assistant", "content": "Oi!"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "total_tokens": 1500,
                    "prompt_tokens_details": {"cached_tokens": 400},
                },
            },
        )

    client, path = make_client(tmp_path, handler)
    with client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "Olá"}]},
            headers={"Authorization": "Bearer secret", "X-Tokenprof-Run": "run-1", "X-Tokenprof-Step": "plan"},
        )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Oi!"

    assert seen["url"] == f"{UPSTREAM}/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer secret"
    assert "x-tokenprof-run" not in seen["headers"]
    assert "x-tokenprof-step" not in seen["headers"]

    [record] = read_traces(path)
    assert record["run_id"] == "run-1"
    assert record["step"] == "plan"
    assert record["status"] == 200
    assert record["response"]["content"] == "Oi!"
    assert record["usage"] == {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500, "cached_tokens": 400}
    # 600 uncached * $1 + 400 cached * $0.1 + 500 output * $2, per million tokens
    assert abs(record["cost_usd"] - (600 * 1.0 + 400 * 0.1 + 500 * 2.0) / 1e6) < 1e-12
    assert "secret" not in path.read_text(encoding="utf-8")


def test_streaming_call_is_relayed_unchanged_and_reassembled(tmp_path):
    body = sse(
        {"model": "test-model", "choices": [{"index": 0, "delta": {"role": "assistant"}}]},
        {"model": "test-model", "choices": [{"index": 0, "delta": {"content": "Bom "}}]},
        {"model": "test-model", "choices": [{"index": 0, "delta": {"content": "dia"}, "finish_reason": "stop"}]},
        {"model": "test-model", "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}},
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client, path = make_client(tmp_path, handler)
    with client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "stream": True, "messages": [{"role": "user", "content": "Oi"}]},
        )

    assert response.status_code == 200
    assert response.content == body
    assert seen["body"]["stream_options"] == {"include_usage": True}

    [record] = read_traces(path)
    assert record["stream"] is True
    assert record["response"]["content"] == "Bom dia"
    assert record["response"]["finish_reason"] == "stop"
    assert record["usage"]["total_tokens"] == 12
    # No prompt_tokens_details in the upstream usage: cache usage is unknown, not zero.
    assert record["usage"]["cached_tokens"] is None
    assert record["ttft_ms"] is not None
    # The trace keeps the request as the client sent it.
    assert "stream_options" not in record["request"]


def test_stream_usage_injection_can_be_disabled(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=sse(), headers={"content-type": "text/event-stream"})

    client, _ = make_client(tmp_path, handler, inject_stream_usage=False)
    with client:
        client.post("/v1/chat/completions", json={"model": "test-model", "stream": True, "messages": []})

    assert "stream_options" not in seen["body"]


def test_upstream_failure_returns_502_and_is_logged(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client, path = make_client(tmp_path, handler)
    with client:
        response = client.post("/v1/chat/completions", json={"model": "test-model", "messages": []})

    assert response.status_code == 502
    [record] = read_traces(path)
    assert record["status"] == 502
    assert "connection refused" in record["error"]


def test_upstream_error_status_is_relayed_and_logged(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    client, path = make_client(tmp_path, handler)
    with client:
        response = client.post("/v1/chat/completions", json={"model": "test-model", "messages": []})

    assert response.status_code == 429
    [record] = read_traces(path)
    assert record["status"] == 429
    assert "rate limited" in record["error"]


def test_other_endpoints_pass_through_without_logging(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{UPSTREAM}/models"
        return httpx.Response(200, json={"data": [{"id": "test-model"}]})

    client, path = make_client(tmp_path, handler)
    with client:
        response = client.get("/v1/models")

    assert response.json() == {"data": [{"id": "test-model"}]}
    assert not path.exists()


def test_accumulator_handles_lines_split_across_chunks_and_tool_calls():
    body = sse(
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "busca", "arguments": '{"q":'}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ' "pizza"}'}}]}, "finish_reason": "tool_calls"}]},
    )
    acc = _StreamAccumulator()
    saw_output = [acc.feed(body[i : i + 7]) for i in range(0, len(body), 7)]
    record = {}
    acc.apply(record)

    assert any(saw_output)
    assert record["response"]["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "busca", "arguments": '{"q": "pizza"}'}}
    ]
    assert record["response"]["finish_reason"] == "tool_calls"


def test_pricing_falls_back_to_longest_prefix():
    pricing = Pricing({"model": ModelPrice(1, 1), "model-large": ModelPrice(5, 5)})
    assert pricing.lookup("model-large-2025-01-01") == ModelPrice(5, 5)
    assert pricing.lookup("model-mini") == ModelPrice(1, 1)
    assert pricing.lookup("other") is None
    assert pricing.cost("other", {"prompt_tokens": 10}) is None
