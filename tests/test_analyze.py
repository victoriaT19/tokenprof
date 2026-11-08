import json

from tokenprof.analyze import analyze
from tokenprof.cli import main
from tokenprof.report import render_report

TOOLS = [{"type": "function", "function": {"name": "buscar_pedido", "parameters": {"type": "object"}}}]
BIG_OUTPUT = json.dumps({"status": "entregue", "extra": " ".join(f"campo{i} valor{i}" for i in range(600))})
TOOL_CALL = {"id": "call_1", "type": "function", "function": {"name": "buscar_pedido", "arguments": '{"id": 42}'}}


def record(run, ts, messages, usage, response, tools=TOOLS):
    return {
        "endpoint": "chat.completions",
        "status": 200,
        "run_id": run,
        "step": None,
        "ts": ts,
        "request": {"model": "m", "messages": messages, "tools": tools},
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "cached_tokens": usage[2]},
        "response": response,
    }


def wasteful_run():
    """Timestamp in the system prompt, a large unused tool output and a repeated tool call."""
    user = {"role": "user", "content": "Qual o status do pedido 42?"}
    assistant = {"role": "assistant", "content": None, "tool_calls": [TOOL_CALL]}
    tool = {"role": "tool", "tool_call_id": "call_1", "content": BIG_OUTPUT}
    return [
        record("r1", "1", [{"role": "system", "content": "Você é um assistente. Agora: 10:00:01"}, user],
               (100, 10, 0), {"content": None, "tool_calls": [TOOL_CALL]}),
        record("r1", "2", [{"role": "system", "content": "Você é um assistente. Agora: 10:00:05"}, user, assistant, tool],
               (2500, 10, 0), {"content": None, "tool_calls": [TOOL_CALL]}),
        record("r1", "3", [{"role": "system", "content": "Você é um assistente. Agora: 10:00:09"}, user, assistant, tool, assistant, tool],
               (4900, 8, 0), {"content": "Seu pedido foi entregue.", "tool_calls": None}),
    ]


def clean_run():
    """Stable prefix fully served from cache, small tool output that gets used."""
    system = {"role": "system", "content": "Você é um assistente."}
    user = {"role": "user", "content": "Qual o status do pedido 7?"}
    assistant = {"role": "assistant", "content": None, "tool_calls": [TOOL_CALL]}
    tool = {"role": "tool", "tool_call_id": "call_1", "content": '{"status": "entregue"}'}
    return [
        record("r2", "1", [system, user], (60, 10, 0), {"content": None, "tool_calls": [TOOL_CALL]}),
        record("r2", "2", [system, user, assistant, tool], (90, 6, 60), {"content": "Pedido entregue.", "tool_calls": None}),
    ]


def kinds(analysis, run_id):
    return {f.kind for f in analysis.findings if f.run_id == run_id}


def test_wasteful_run_triggers_every_planted_problem():
    analysis = analyze(wasteful_run(), min_tool_tokens=200)
    assert kinds(analysis, "r1") == {"uncached_resend", "cache_breaker", "unused_tool_output", "repeated_tool_call"}

    breakers = sorted((f for f in analysis.findings if f.kind == "cache_breaker"), key=lambda f: f.calls)
    assert [f.calls for f in breakers] == [[1], [2]]
    assert '"10:00:05"' in breakers[0].detail
    assert '"10:00:09"' in breakers[1].detail

    unused = next(f for f in analysis.findings if f.kind == "unused_tool_output")
    assert unused.calls == [1, 2]


def test_tool_outputs_sent_as_user_observations_are_recognized():
    """smolagents sends tool calls as assistant text and tool results as user 'Observation:' text."""
    system = {"role": "system", "content": "Você é um assistente."}
    user = {"role": "user", "content": [{"type": "text", "text": "New task: Qual o status do pedido 42?"}]}
    calling = {"role": "assistant", "content": [{"type": "text", "text": "Calling tools: [{'name': 'buscar_pedido'}]"}]}
    observation = {"role": "user", "content": [{"type": "text", "text": "Observation: " + BIG_OUTPUT}]}
    run = [
        record("s1", "1", [system, user], (60, 10, None), {"content": None, "tool_calls": [TOOL_CALL]}),
        record("s1", "2", [system, user, calling, observation], (2400, 8, None),
               {"content": None, "tool_calls": [{**TOOL_CALL, "function": {"name": "final_answer", "arguments": '{"answer": "entregue"}'}}]}),
    ]
    analysis = analyze(run, min_tool_tokens=200)
    assert "unused_tool_output" in kinds(analysis, "s1")
    assert analysis.calls[1].parts()["tool_output"] > analysis.calls[1].parts()["user"]


def test_clean_run_has_no_findings():
    analysis = analyze(clean_run(), min_tool_tokens=200)
    assert kinds(analysis, "r2") == set()


def test_identical_requests_are_flagged():
    first = clean_run()[0]
    analysis = analyze([first, {**first, "ts": "9"}])
    assert "repeated_call" in kinds(analysis, "r2")


def test_unreported_cache_is_not_treated_as_a_miss():
    """Some providers (e.g. Gemini's OpenAI-compatible endpoint) omit cache usage entirely."""
    run = clean_run()
    for r in run:
        r["usage"]["cached_tokens"] = None
    analysis = analyze(run)
    assert kinds(analysis, "r2") == set()
    assert analysis.totals()["cache_reported"] is False
    assert "cache usage not reported" in render_report(analysis)


def test_part_estimates_add_up_to_reported_prompt_tokens():
    analysis = analyze(wasteful_run() + clean_run())
    for call in analysis.calls:
        assert abs(sum(call.parts().values()) - call.prompt_tokens) <= len(call.messages) + 1


def test_failed_calls_and_other_endpoints_are_ignored():
    failed = {**clean_run()[0], "status": 500}
    other = {**clean_run()[0], "endpoint": "embeddings"}
    assert analyze([failed, other]).calls == []


def test_report_renders_findings_and_charts():
    html = render_report(analyze(wasteful_run() + clean_run(), min_tool_tokens=200), source="t.jsonl")
    assert "Cache breaker" in html
    assert "Unused tool output" in html
    assert html.count("<svg") == 2


def test_cli_analyze_writes_report(tmp_path, capsys):
    traces = tmp_path / "traces.jsonl"
    traces.write_text("\n".join(json.dumps(r) for r in wasteful_run()), encoding="utf-8")
    out = tmp_path / "report.html"
    main(["analyze", str(traces), "--out", str(out), "--min-tool-tokens", "200"])
    assert out.exists()
    assert "estimated waste" in capsys.readouterr().out


def test_report_never_shows_the_full_path_of_the_trace_file():
    analysis = analyze(clean_run())
    for source in (r"C:\Users\someone\Documents\proj\traces.jsonl", "/home/someone/proj/traces.jsonl", "traces.jsonl"):
        html = render_report(analysis, source=source)
        assert "traces.jsonl" in html
        assert "someone" not in html and "Users" not in html and "home" not in html
