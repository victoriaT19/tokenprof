"""Self-contained HTML report: summary, waste findings and token anatomy per run."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import PureWindowsPath

from .analyze import PARTS, Analysis, Call

KIND_LABELS = {
    "uncached_resend": "Uncached resend",
    "cache_breaker": "Cache breaker",
    "unused_tool_output": "Unused tool output",
    "repeated_call": "Repeated call",
    "repeated_tool_call": "Repeated tool call (loop)",
}
PART_LABELS = {
    "system": "System",
    "tool_schemas": "Tool schemas",
    "user": "User",
    "assistant": "Assistant (history)",
    "tool_output": "Tool output",
    "output": "Output",
}

_ROW_HEIGHT = 22
_LABEL_WIDTH = 150
_CHART_WIDTH = 640

_CSS = """
:root {
  --bg: #ffffff; --fg: #1d1d1f; --muted: #6e6e73; --line: #e3e3e8; --card: #f6f6f8;
  --system: #6c5ce7; --tool_schemas: #a29bfe; --user: #0984e3; --assistant: #74b9ff;
  --tool_output: #e17055; --output: #00b894; --cached: #1d1d1f;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #141416; --fg: #f2f2f5; --muted: #a1a1a8; --line: #2c2c31; --card: #1e1e22;
    --system: #8e83f0; --tool_schemas: #b8b2ff; --user: #3aa0f0; --assistant: #8ccaff;
    --tool_output: #f0866b; --output: #2fd3a6; --cached: #f2f2f5;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 40px 0 12px; }
h3 { font-size: 15px; margin: 24px 0 8px; }
.muted { color: var(--muted); }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 24px; }
.card { background: var(--card); border-radius: 10px; padding: 14px 16px; }
.card b { display: block; font-size: 22px; font-variant-numeric: tabular-nums; }
.card span { color: var(--muted); font-size: 13px; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 13px; }
td.num, th.num { text-align: right; }
.finding { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; }
.finding .head { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.finding .fix { color: var(--muted); margin-top: 4px; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; color: var(--muted); margin: 8px 0 4px; }
.legend i { display: inline-block; width: 11px; height: 11px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
.chart { margin-bottom: 8px; }
svg text { fill: var(--fg); font-size: 12px; }
"""


def render_report(analysis: Analysis, source: str = "") -> str:
    totals = analysis.totals()
    prompt = totals["prompt_tokens"]
    wasted = min(prompt, sum(totals["wasted_by_kind"].values()))

    cards = [
        (f"{totals['calls']}", f"calls in {totals['runs']} run(s)"),
        (_fmt(prompt), "prompt tokens"),
        (_fmt(totals["completion_tokens"]), "output tokens"),
        (_pct(totals["cached_tokens"], prompt), "of prompt tokens cached")
        if totals["cache_reported"]
        else ("n/a", "cache usage not reported by the provider"),
        (_fmt(wasted), f"est. wasted prompt tokens ({_pct(wasted, prompt)})"),
    ]
    if totals["cost_usd"] is not None:
        cards.append((f"${totals['cost_usd']:.4f}", "estimated cost"))

    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>tokenprof report</title><style>{_CSS}</style></head><body><main>",
        "<h1>tokenprof report</h1>",
        # Only the file name: reports get shared, and a full path exposes the user's folders.
        f"<div class='muted'>{escape(PureWindowsPath(source).name)} · generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</div>",
        "<div class='cards'>",
        *(f"<div class='card'><b>{escape(v)}</b><span>{escape(label)}</span></div>" for v, label in cards),
        "</div>",
        _waste_table(totals["wasted_by_kind"], prompt),
        _findings(analysis),
        "<h2>Token anatomy per call</h2>",
        "<p class='muted'>Each bar is one call: its prompt split by content type, then its output. "
        "The outlined region at the start of a bar is the part served from cache. "
        "Totals are as reported by the provider; the split between parts is estimated from text length.</p>",
        _legend(),
        *(_run_chart(run_id, calls) for run_id, calls in analysis.runs.items()),
        "</main></body></html>",
    ]
    return "\n".join(parts)


def _waste_table(by_kind: dict[str, int], prompt: int) -> str:
    if not by_kind:
        return "<h2>Waste</h2><p>No waste detected.</p>"
    rows = "".join(
        f"<tr><td>{escape(KIND_LABELS.get(kind, kind))}</td><td class='num'>{_fmt(tokens)}</td>"
        f"<td class='num'>{_pct(tokens, prompt)}</td></tr>"
        for kind, tokens in sorted(by_kind.items(), key=lambda kv: kv[1], reverse=True)
    )
    return (
        "<h2>Waste by type</h2><table><tr><th>Type</th><th class='num'>Tokens</th>"
        f"<th class='num'>% of prompt tokens</th></tr>{rows}</table>"
        "<p class='muted'>Types can overlap (a large unused tool output is also resent context), "
        "so the total above is capped at the prompt total.</p>"
    )


def _findings(analysis: Analysis, limit: int = 50) -> str:
    if not analysis.findings:
        return ""
    items = []
    for finding in analysis.findings[:limit]:
        calls = ", ".join(str(i) for i in finding.calls[:12]) + (" …" if len(finding.calls) > 12 else "")
        items.append(
            "<div class='finding'><div class='head'>"
            f"<b>{escape(KIND_LABELS.get(finding.kind, finding.kind))}</b>"
            f"<span class='muted'>run {escape(finding.run_id)} · calls {escape(calls)} · "
            f"~{_fmt(finding.wasted_tokens)} tokens</span></div>"
            f"<div>{escape(finding.detail)}</div><div class='fix'>Fix: {escape(finding.suggestion)}</div></div>"
        )
    more = f"<p class='muted'>{len(analysis.findings) - limit} more not shown.</p>" if len(analysis.findings) > limit else ""
    return f"<h2>Findings</h2>{''.join(items)}{more}"


def _legend() -> str:
    keys = (*PARTS, "output")
    items = "".join(f"<span><i style='background:var(--{k})'></i>{escape(PART_LABELS[k])}</span>" for k in keys)
    return f"<div class='legend'>{items}</div>"


def _run_chart(run_id: str, calls: list[Call]) -> str:
    widest = max((c.prompt_tokens + c.completion_tokens for c in calls), default=1) or 1
    scale = (_CHART_WIDTH - _LABEL_WIDTH - 10) / widest
    height = len(calls) * _ROW_HEIGHT + 6
    rows = []
    for row, call in enumerate(calls):
        y = row * _ROW_HEIGHT + 3
        label = f"#{call.index}" + (f" {call.step}" if call.step else "")
        rows.append(f"<text x='0' y='{y + 14}'>{escape(label[:20])}</text>")
        x = float(_LABEL_WIDTH)
        segments = [*call.parts().items(), ("output", call.completion_tokens)]
        for part, tokens in segments:
            if tokens <= 0:
                continue
            width = tokens * scale
            title = f"{PART_LABELS[part]}: ~{tokens} tokens"
            rows.append(
                f"<rect x='{x:.1f}' y='{y}' width='{max(width, 0.5):.1f}' height='{_ROW_HEIGHT - 6}' "
                f"style='fill:var(--{part})'><title>{escape(title)}</title></rect>"
            )
            x += width
        if call.cached_tokens:
            rows.append(
                f"<rect x='{_LABEL_WIDTH}' y='{y - 1}' width='{call.cached_tokens * scale:.1f}' "
                f"height='{_ROW_HEIGHT - 4}' style='fill:none;stroke:var(--cached);stroke-width:1.5;stroke-dasharray:3 2'>"
                f"<title>Cached: {call.cached_tokens} tokens</title></rect>"
            )
    svg = (
        f"<svg viewBox='0 0 {_CHART_WIDTH} {height}' style='width:100%;max-width:{_CHART_WIDTH}px;height:auto' role='img' "
        f"aria-label='Token anatomy for run {escape(run_id)}'>{''.join(rows)}</svg>"
    )
    return f"<h3>Run {escape(run_id)}</h3><div class='chart'>{svg}</div>"


def _fmt(n: int) -> str:
    return f"{n:,}"


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "0%"
