"""Trace analysis: where the tokens of each call go, and where they are wasted.

Token counts per part of the prompt are estimates: each part is sized by its
character count and then scaled so the parts add up to the prompt_tokens the
provider actually reported for that call. Totals are therefore exact; the
split between parts is approximate.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

PARTS = ("system", "tool_schemas", "user", "assistant", "tool_output")
_CHARS_PER_TOKEN = 3.5
# Some frameworks send tool results as user text instead of role "tool"
# (smolagents' ToolCallingAgent: "Observation: ...").
_OBSERVATION_PREFIXES = ("Observation:",)
_WORD = re.compile(r"[\wÀ-ÿ]{4,}")


@dataclass
class Call:
    record: dict[str, Any]
    run_id: str
    index: int
    messages: list[dict[str, Any]]
    message_tokens: list[int]
    tools_tokens: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int | None  # None: the provider did not report cache usage

    @property
    def step(self) -> str | None:
        return self.record.get("step")

    def parts(self) -> dict[str, int]:
        totals = dict.fromkeys(PARTS, 0)
        totals["tool_schemas"] = self.tools_tokens
        part = {"system": "system", "developer": "system", "assistant": "assistant"}
        for message, tokens in zip(self.messages, self.message_tokens):
            key = "tool_output" if _is_tool_output(message) else part.get(message.get("role"), "user")
            totals[key] += tokens
        return totals


@dataclass
class Finding:
    kind: str
    run_id: str
    calls: list[int]
    wasted_tokens: int
    detail: str
    suggestion: str


@dataclass
class Analysis:
    runs: dict[str, list[Call]]
    findings: list[Finding] = field(default_factory=list)

    @property
    def calls(self) -> list[Call]:
        return [call for calls in self.runs.values() for call in calls]

    def totals(self) -> dict[str, Any]:
        calls = self.calls
        prompt = sum(c.prompt_tokens for c in calls)
        completion = sum(c.completion_tokens for c in calls)
        cached = sum(c.cached_tokens or 0 for c in calls)
        costs = [c.record.get("cost_usd") for c in calls]
        by_kind: dict[str, int] = defaultdict(int)
        for finding in self.findings:
            by_kind[finding.kind] += finding.wasted_tokens
        return {
            "runs": len(self.runs),
            "calls": len(calls),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cached_tokens": cached,
            "cache_reported": any(c.cached_tokens is not None for c in calls),
            "cost_usd": sum(costs) if costs and all(c is not None for c in costs) else None,
            "wasted_by_kind": dict(by_kind),
        }


def analyze(records: list[dict[str, Any]], *, min_tool_tokens: int = 1000) -> Analysis:
    """Group successful chat completions by run and run every detector."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("endpoint") == "chat.completions" and record.get("status") == 200:
            grouped[record.get("run_id") or "(no run)"].append(record)

    runs = {}
    for run_id, run_records in grouped.items():
        run_records.sort(key=lambda r: r.get("ts") or "")
        runs[run_id] = [_build_call(r, run_id, i) for i, r in enumerate(run_records)]

    analysis = Analysis(runs)
    for run_id, calls in runs.items():
        analysis.findings += _uncached_resend(run_id, calls)
        analysis.findings += _cache_breakers(run_id, calls)
        analysis.findings += _unused_tool_outputs(run_id, calls, min_tool_tokens)
        analysis.findings += _repeats(run_id, calls)
    analysis.findings.sort(key=lambda f: f.wasted_tokens, reverse=True)
    return analysis


def _build_call(record: dict[str, Any], run_id: str, index: int) -> Call:
    request = record.get("request") or {}
    messages = request.get("messages") or []
    tools = request.get("tools")
    raw_messages = [_estimate(_message_text(m)) for m in messages]
    raw_tools = _estimate(json.dumps(tools, ensure_ascii=False)) if tools else 0

    usage = record.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens") or (sum(raw_messages) + raw_tools)
    scale = prompt_tokens / max(1, sum(raw_messages) + raw_tools)
    return Call(
        record=record,
        run_id=run_id,
        index=index,
        messages=messages,
        message_tokens=[round(t * scale) for t in raw_messages],
        tools_tokens=round(raw_tools * scale),
        prompt_tokens=prompt_tokens,
        completion_tokens=usage.get("completion_tokens") or 0,
        cached_tokens=usage.get("cached_tokens"),
    )


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    text = content or ""
    if message.get("tool_calls"):
        text += json.dumps(message["tool_calls"], ensure_ascii=False)
    return text


def _is_tool_output(message: dict[str, Any]) -> bool:
    if message.get("role") == "tool":
        return True
    return message.get("role") == "user" and _message_text(message).lstrip().startswith(_OBSERVATION_PREFIXES)


def _estimate(text: str) -> int:
    return max(1, round(len(text) / _CHARS_PER_TOKEN)) if text else 0


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _shared_prefix(previous: Call, current: Call) -> int:
    """Number of leading messages the current call resends unchanged."""
    count = 0
    for old, new in zip(previous.messages, current.messages):
        if _fingerprint(old) != _fingerprint(new):
            break
        count += 1
    return count


def _resent_tokens(previous: Call, current: Call) -> int:
    same_tools = _fingerprint(previous.record["request"].get("tools")) == _fingerprint(
        current.record["request"].get("tools")
    )
    prefix = _shared_prefix(previous, current)
    return (current.tools_tokens if same_tools else 0) + sum(current.message_tokens[:prefix])


# ── Detectors ────────────────────────────────────────────────────────────────


def _uncached_resend(run_id: str, calls: list[Call]) -> list[Finding]:
    """Context resent unchanged from the previous call and billed at full price.

    Only judged on calls whose provider reports cache usage: without it there is
    no way to tell a cache hit from a full-price resend.
    """
    wasted, affected = 0, []
    for previous, current in zip(calls, calls[1:]):
        if current.cached_tokens is None:
            continue
        uncached = max(0, _resent_tokens(previous, current) - current.cached_tokens)
        if uncached:
            wasted += uncached
            affected.append(current.index)
    if not wasted:
        return []
    resent_total = sum(_resent_tokens(p, c) for p, c in zip(calls, calls[1:]))
    return [
        Finding(
            kind="uncached_resend",
            run_id=run_id,
            calls=affected,
            wasted_tokens=wasted,
            detail=(
                f"{resent_total} tokens were resent unchanged from the previous call; "
                f"{wasted} of them were not served from cache and were billed at full price."
            ),
            suggestion=(
                "Keep the start of the prompt stable so prompt caching can work, "
                "and compact old history into a summary."
            ),
        )
    ]


def _cache_breakers(run_id: str, calls: list[Call]) -> list[Finding]:
    """The first message changes slightly between calls (e.g. a timestamp), so no
    prefix can ever be cached."""
    findings = []
    for previous, current in zip(calls, calls[1:]):
        if not previous.messages or not current.messages:
            continue
        old, new = _message_text(previous.messages[0]), _message_text(current.messages[0])
        if old == new:
            continue
        matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
        if matcher.ratio() < 0.8:
            continue
        changed = [_whole_words(new, j1, j2) for op, _, _, j1, j2 in matcher.get_opcodes() if op != "equal"]
        snippet = " … ".join(dict.fromkeys(s for s in changed if s))[:80]
        findings.append(
            Finding(
                kind="cache_breaker",
                run_id=run_id,
                calls=[current.index],
                wasted_tokens=max(0, current.prompt_tokens - (current.cached_tokens or 0)),
                detail=f"The first message changed between calls {previous.index} and {current.index} (new text: \"{snippet}\"), so nothing from that point on can be served from cache.",
                suggestion="Move dynamic content out of the start of the prompt, next to the latest user message.",
            )
        )
    return findings


def _whole_words(text: str, start: int, end: int) -> str:
    """Widen text[start:end] to whitespace boundaries, so "9" becomes "10:00:09"."""
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return text[start:end].strip()


def _unused_tool_outputs(run_id: str, calls: list[Call], min_tokens: int) -> list[Finding]:
    """Large tool outputs that the model barely used but that ride along in every later call."""
    findings = []
    seen: set[str] = set()
    for call in calls:
        for message, tokens in zip(call.messages, call.message_tokens):
            if not _is_tool_output(message) or tokens < min_tokens:
                continue
            key = _fingerprint(message)
            if key in seen:
                continue
            seen.add(key)

            later = calls[call.index:]
            carried_in = [c.index for c in later if any(_fingerprint(m) == key for m in c.messages)]
            used_text = " ".join(_response_text(c) for c in later)
            words = set(_WORD.findall(_message_text(message).lower()))
            used = words & set(_WORD.findall(used_text.lower()))
            usage = len(used) / max(1, len(words))
            if usage >= 0.1:
                continue
            findings.append(
                Finding(
                    kind="unused_tool_output",
                    run_id=run_id,
                    calls=carried_in,
                    wasted_tokens=tokens * len(carried_in),
                    detail=(
                        f"A ~{tokens}-token tool output was sent in {len(carried_in)} call(s), "
                        f"but only {usage:.0%} of its words show up in the model's responses."
                    ),
                    suggestion="Return only the fields the agent needs, or summarize the output before passing it to the model.",
                )
            )
    return findings


def _repeats(run_id: str, calls: list[Call]) -> list[Finding]:
    """Identical requests and identical tool calls repeated within a run."""
    findings = []
    first_seen: dict[str, int] = {}
    for call in calls:
        request = call.record["request"]
        key = _fingerprint([request.get("model"), request.get("messages"), request.get("tools")])
        if key in first_seen:
            findings.append(
                Finding(
                    kind="repeated_call",
                    run_id=run_id,
                    calls=[first_seen[key], call.index],
                    wasted_tokens=call.prompt_tokens + call.completion_tokens,
                    detail=f"Call {call.index} is identical to call {first_seen[key]}.",
                    suggestion="Cache the result of the first call instead of repeating it.",
                )
            )
        else:
            first_seen[key] = call.index

    tool_calls_seen: dict[str, int] = {}
    for call in calls:
        for tool_call in ((call.record.get("response") or {}).get("tool_calls") or []):
            function = tool_call.get("function") or {}
            key = _fingerprint([function.get("name"), _normalize_args(function.get("arguments"))])
            if key in tool_calls_seen:
                findings.append(
                    Finding(
                        kind="repeated_tool_call",
                        run_id=run_id,
                        calls=[tool_calls_seen[key], call.index],
                        wasted_tokens=call.prompt_tokens + call.completion_tokens,
                        detail=(
                            f"The agent called {function.get('name')} with the same arguments in calls "
                            f"{tool_calls_seen[key]} and {call.index}."
                        ),
                        suggestion="Detect loops: return the earlier result, or stop the agent when it repeats an action.",
                    )
                )
            else:
                tool_calls_seen[key] = call.index
    return findings


def _response_text(call: Call) -> str:
    response = call.record.get("response") or {}
    text = response.get("content") or ""
    if response.get("tool_calls"):
        text += json.dumps(response["tool_calls"], ensure_ascii=False)
    return text


def _normalize_args(arguments: Any) -> Any:
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return arguments.strip()
    return arguments
