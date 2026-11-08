"""Profile SWE-agent trajectories saved in ATIF (Agent Trajectory Interchange Format).

The traces come from harnesses such as `swegemma` (Gemma 4 Developer Agent
competition): one JSON file per task with the system prompt, the task prompt,
and one step per LLM call with its tool calls, the tool observation and the
token usage the inference server reported.

The trace does not store the exact prompt of each call, so its anatomy is
rebuilt: call i's prompt is the system prompt, the task prompt, the tool
schemas and chat template (a fixed overhead), plus everything the agent said
and every tool output from calls before i. Each part is sized by characters and
scaled so the parts add up to the prompt_tokens actually reported. Totals are
exact; the split is an estimate (see `fit_overhead`).
"""

from __future__ import annotations

import json
import re
import tarfile
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EDIT_TOOLS = {"edit_file", "write_file"}
# A run_command that executes code counts as verification (tests, scripts, inline asserts).
_VERIFY = re.compile(r"\b(pytest|unittest|python3?|tox|nox|make test)\b")
# Task prompt sections written by the swegemma harness, in order.
_SECTIONS = [
    ("problem", re.compile(r"^Problem Statement:", re.M)),
    ("hints", re.compile(r"^## Hints:", re.M)),
    ("budget", re.compile(r"^## Task Budget", re.M)),
    ("rules", re.compile(r"^## Execution Environment Rules", re.M)),
    ("instructions", re.compile(r"^## Instructions", re.M)),
    ("code_intel", re.compile(r"^## Code Intelligence Tools", re.M)),
    ("layout", re.compile(r"^## Workspace Layout", re.M)),
]


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    output: str  # raw observation text
    status: str | None  # "ok" / "error" when the observation is a JSON object
    truncated: bool


@dataclass
class LlmCall:
    index: int
    author: str
    prompt_tokens: int
    completion_tokens: int
    message_chars: int  # visible text + reasoning kept in history
    tool_calls: list[ToolCall]


@dataclass
class Run:
    instance_id: str
    repo: str | None
    resolved: bool | None
    system_chars: int
    task_sections: dict[str, int]  # chars of each task prompt section
    calls: list[LlmCall]  # root agent calls only, in order
    texts: list[str] = field(default_factory=list)  # per call: message + tool call arguments
    sub_agent_tokens: int = 0  # prompt + completion of delegated agents (AgentTool)
    error: str | None = None  # agent error reported by the harness (timeout, context overflow...)
    events: dict[str, int] = field(default_factory=dict)  # harness events: continuation_nudge, compaction...
    anatomy: list[dict[str, float]] = field(default_factory=list)  # per call, filled by profile()

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.calls)

    @property
    def task_chars(self) -> int:
        return sum(self.task_sections.values())

    def tool_sequence(self) -> list[tuple[int, ToolCall]]:
        return [(c.index, t) for c in self.calls for t in c.tool_calls]

    def submit_index(self) -> int | None:
        for idx, tool in self.tool_sequence():
            if tool.name == "submit_patch":
                return idx
        return None


@dataclass
class Finding:
    kind: str
    instance_id: str
    calls: list[int]
    tokens: int  # prompt + completion tokens attributable to the problem (0 if behavioural)
    detail: str


# ── Loading ──────────────────────────────────────────────────────────────────


def load_run(trace: dict[str, Any], *, instance_id: str, repo: str | None = None,
             resolved: bool | None = None, error: str | None = None) -> Run:
    steps = trace.get("steps") or []
    system = next((s for s in steps if (s.get("extra") or {}).get("event_type") == "system_instruction"), None)
    task = next((s for s in steps if (s.get("extra") or {}).get("event_type") == "task_prompt"), None)
    llm_steps = [s for s in steps if s.get("source") == "agent" and s.get("metrics")]
    root = (llm_steps[0].get("extra") or {}).get("author") if llm_steps else None

    calls, sub_tokens, texts = [], 0, []
    for step in steps:
        extra = step.get("extra") or {}
        if step.get("source") == "system" and step.get("observation") and not extra.get("event_type"):
            # Result of a delegated agent (AgentTool) arriving after its own calls: it goes
            # into the root agent's history as the output of the call that started it.
            content = step["observation"].get("content") if isinstance(step["observation"], dict) else ""
            pending = [t for c in calls[-1:] for t in c.tool_calls if not t.output]
            if pending:
                pending[-1].output = str(content or "")
            elif calls:
                calls[-1].tool_calls.append(ToolCall("agent_tool", {}, str(content or ""), None, False))
            continue
        if step.get("source") != "agent":
            continue
        author = (step.get("extra") or {}).get("author") or ""
        metrics = step.get("metrics")
        if not metrics:
            # Another part (text, tool call) of the previous LLM call: it is in the history too.
            if calls and author == root and (step.get("extra") or {}).get("event_type") != "final":
                calls[-1].message_chars += len(step.get("message") or "")
                calls[-1].tool_calls += _tool_calls(step)
            continue
        if root and author != root:
            sub_tokens += (metrics.get("prompt_tokens") or 0) + (metrics.get("completion_tokens") or 0)
            continue
        calls.append(LlmCall(
            index=len(calls),
            author=author,
            prompt_tokens=metrics.get("prompt_tokens") or 0,
            completion_tokens=metrics.get("completion_tokens") or 0,
            message_chars=len(step.get("message") or "") + len(step.get("reasoning_content") or ""),
            tool_calls=_tool_calls(step),
        ))
        texts.append((step.get("message") or "") + json.dumps(
            [c.get("arguments") for c in step.get("tool_calls") or []], ensure_ascii=False))
    return Run(
        instance_id=instance_id,
        repo=repo,
        resolved=resolved,
        system_chars=len((system or {}).get("message") or ""),
        task_sections=split_task_prompt((task or {}).get("message") or ""),
        calls=calls,
        texts=texts,
        sub_agent_tokens=sub_tokens,
        error=error if error and error != "None" else None,
        events=dict(Counter(
            (s.get("extra") or {}).get("event_type") for s in steps
            if s.get("source") == "system" and (s.get("extra") or {}).get("event_type") not in (
                None, "system_instruction")
        )),
    )


def _tool_calls(step: dict[str, Any]) -> list[ToolCall]:
    calls = step.get("tool_calls") or []
    observation = step.get("observation") or {}
    if isinstance(observation, dict) and isinstance(observation.get("results"), list):
        by_id = {r.get("source_call_id"): r.get("content") or "" for r in observation["results"]}
        outputs = [by_id.get(c.get("tool_call_id"), "") for c in calls]
    else:
        content = observation.get("content") if isinstance(observation, dict) else observation
        outputs = [str(content or "")] + [""] * max(0, len(calls) - 1)
    result = []
    for call, output in zip(calls, outputs):
        parsed = _json(output)
        result.append(ToolCall(
            name=call.get("function_name") or "",
            args=call.get("arguments") if isinstance(call.get("arguments"), dict) else {},
            output=output,
            status=parsed.get("status") if isinstance(parsed, dict) else None,
            truncated=bool(isinstance(parsed, dict) and parsed.get("is_truncated")),
        ))
    return result


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def split_task_prompt(text: str) -> dict[str, int]:
    """Characters per section of a swegemma task prompt; unknown text goes to "header"."""
    marks = sorted((m.start(), name) for name, rx in _SECTIONS if (m := rx.search(text)))
    sections: dict[str, int] = defaultdict(int)
    starts = [0] + [pos for pos, _ in marks]
    names = ["header"] + [name for _, name in marks]
    for name, start, end in zip(names, starts, starts[1:] + [len(text)]):
        sections[name] += end - start
    return {k: v for k, v in sections.items() if v}


def load_results_dir(results_dir: str | Path, outcomes: str | Path | None = None) -> list[Run]:
    """Load every trace_<id>.json of a swegemma results directory.

    Traces are read from traces/ or, if absent, from traces.tar.gz (the packed
    form kept in the repository). Resolution comes from `outcomes` (a JSONL file
    with instance_id/task_id and resolved), or from task_results.jsonl,
    run_results.jsonl or ../run_results.jsonl if present.
    """
    results_dir = Path(results_dir)
    candidates = [Path(outcomes)] if outcomes else [
        results_dir / "task_results.jsonl", results_dir / "run_results.jsonl",
        results_dir.parent / "run_results.jsonl"]
    status: dict[str, dict[str, Any]] = {}
    for path in candidates:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    status[row.get("instance_id") or row.get("task_id")] = row
            break
    runs = []
    for name, text in _trace_files(results_dir):
        instance_id = Path(name).stem.removeprefix("trace_")
        row = status.get(instance_id, {})
        resolved = row.get("resolved")
        if isinstance(resolved, str):
            resolved = resolved.lower() == "true"
        trace = json.loads(text)
        runs.append(load_run(trace, instance_id=instance_id, repo=row.get("repo"), resolved=resolved,
                             error=row.get("error_message") or row.get("error") or row.get("runner_error")))
    return runs


def _trace_files(results_dir: Path) -> list[tuple[str, str]]:
    folder = results_dir / "traces"
    if folder.is_dir():
        return [(p.name, p.read_text(encoding="utf-8")) for p in sorted(folder.glob("trace_*.json"))]
    archive = results_dir / "traces.tar.gz"
    if not archive.is_file():
        return []
    with tarfile.open(archive, "r:gz") as tar:
        members = sorted((m for m in tar.getmembers()
                          if m.isfile() and Path(m.name).name.startswith("trace_") and m.name.endswith(".json")),
                         key=lambda m: m.name)
        return [(Path(m.name).name, tar.extractfile(m).read().decode("utf-8")) for m in members]


# ── Anatomy ──────────────────────────────────────────────────────────────────


def fit_overhead(runs: list[Run]) -> tuple[float, float]:
    """Fit first-call prompt tokens = overhead + chars * tokens_per_char.

    The first call of every run holds only the system prompt, the task prompt
    and the tool schemas + chat template, and only the task prompt length
    varies between tasks. A least-squares line over all runs gives the token
    cost of the fixed part (tool schemas + template) as the intercept and the
    tokenizer's tokens per character as the slope.
    """
    points = [(r.system_chars + r.task_chars, r.calls[0].prompt_tokens) for r in runs if r.calls]
    if len(points) < 2 or len({x for x, _ in points}) < 2:
        return 0.0, 1 / 3.5
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    slope = sum((x - mx) * (y - my) for x, y in points) / sum((x - mx) ** 2 for x, _ in points)
    return max(0.0, my - slope * mx), slope


def profile(runs: list[Run], overhead: float | None = None) -> tuple[float, float]:
    """Fill run.anatomy: estimated tokens per prompt part for every call."""
    fitted, slope = fit_overhead(runs)
    overhead = fitted if overhead is None else overhead
    for run in runs:
        run.anatomy = []
        history = 0  # agent messages (text + reasoning + tool call arguments) so far
        outputs: Counter[str] = Counter()  # tool output chars so far, by tool
        compacted = 0.0  # chars-equivalent of the summary + retained events after a compaction
        fixed_chars = run.system_chars + run.task_chars
        compacted_at = set(compactions(run))
        for call in run.calls:
            if call.index in compacted_at:
                # ADK replaced old events with a summary (not recorded in the trace): whatever
                # the prompt holds beyond the fixed part is now "compacted history".
                rest = max(0.0, call.prompt_tokens - overhead - fixed_chars * slope)
                history, compacted = 0, rest / slope if slope else 0.0
                outputs.clear()
            raw: dict[str, float] = {"system": run.system_chars}
            raw.update({f"task:{k}": v for k, v in run.task_sections.items()})
            if compacted:
                raw["compacted_history"] = compacted
            raw["agent_history"] = history
            raw.update({f"tool_output:{k}": v for k, v in outputs.items()})
            budget = max(0.0, call.prompt_tokens - overhead)
            scale = budget / max(1.0, sum(raw.values()))
            parts = {k: v * scale for k, v in raw.items()}
            parts["tool_schemas_and_template"] = min(overhead, call.prompt_tokens)
            run.anatomy.append(parts)
            history += call.message_chars + sum(len(json.dumps(t.args)) for t in call.tool_calls)
            for tool in call.tool_calls:
                outputs[tool.name] += len(tool.output)
    return overhead, slope


def compactions(run: Run, min_drop: float = 0.05) -> list[int]:
    """Calls whose prompt shrank by more than min_drop vs the previous call.

    ADK's event compaction does not always leave an event in the trace, but it
    shows up as a sudden drop in the reported prompt size.
    """
    return [b.index for a, b in zip(run.calls, run.calls[1:])
            if b.prompt_tokens < a.prompt_tokens * (1 - min_drop)]


# ── Detectors ────────────────────────────────────────────────────────────────


def repetition(text: str) -> float:
    """Compressed size / raw size: near 0 means the text repeats itself (a generation loop)."""
    raw = text.encode()
    return len(zlib.compress(raw)) / len(raw) if raw else 1.0


def detect(run: Run, *, thinking_threshold: int = 2000, max_output_tokens: int | None = None) -> list[Finding]:
    findings: list[Finding] = []
    seq = run.tool_sequence()
    submit = run.submit_index()
    ratio = _tokens_per_char(run)

    # 1. Unscoped reads of long files: read_file with no line range came back truncated,
    #    so the agent got the top of the file (often not the code it needed).
    for idx, tool in seq:
        if tool.name == "read_file" and tool.truncated and not (
                tool.args.get("start_line") or tool.args.get("end_line")):
            later = len([c for c in run.calls if c.index > idx])
            tokens = round(len(tool.output) * ratio)
            findings.append(Finding(
                "unscoped_truncated_read", run.instance_id, [idx], tokens * max(1, later),
                f"read_file({tool.args.get('filepath')}) without a line range returned only the first "
                f"lines (~{tokens} tokens), resent in {later} later call(s).",
            ))

    # 2. Re-reads: the same file read again with no edit to it in between.
    last_read: dict[str, int] = {}
    for idx, tool in seq:
        path = str(tool.args.get("filepath") or "")
        if tool.name in EDIT_TOOLS and tool.status != "error":
            for key in [k for k in last_read if k.rsplit(":", 2)[0] == path]:
                del last_read[key]
        elif tool.name == "read_file" and path:
            key = f"{path}:{tool.args.get('start_line')}:{tool.args.get('end_line')}"
            if key in last_read:
                findings.append(Finding(
                    "repeated_read", run.instance_id, [last_read[key], idx], round(len(tool.output) * ratio),
                    f"{path} (same range) read again at call {idx} with no edit since call {last_read[key]}.",
                ))
            last_read[key] = idx

    # 3. Output cap: the call stopped because it hit max_output_tokens (often a repetition
    #    loop, or a huge write_file whose tool call got cut off). Thinking bursts: one call
    #    spends far more completion tokens than usual.
    for call in run.calls:
        if max_output_tokens and call.completion_tokens >= 0.98 * max_output_tokens:
            text = run.texts[call.index] if call.index < len(run.texts) else ""
            ratio = repetition(text)
            kind = "repetition loop" if ratio < 0.15 else "long generation"
            findings.append(Finding(
                "output_cap_hit", run.instance_id, [call.index], call.completion_tokens,
                f"call {call.index} hit max_output_tokens ({max_output_tokens}): {kind} "
                f"(compresses to {ratio:.0%} of its size).",
            ))
        elif call.completion_tokens > thinking_threshold:
            findings.append(Finding(
                "thinking_burst", run.instance_id, [call.index], call.completion_tokens - thinking_threshold,
                f"call {call.index} generated {call.completion_tokens} tokens in one turn "
                f"(threshold {thinking_threshold}); long turns risk cutting off the tool call.",
            ))

    # 4. Failed tool calls (edit mismatch, command errors) and the turns spent on them.
    for idx, tool in seq:
        if tool.status == "error" and tool.name != "run_command":
            call = run.calls[idx]
            findings.append(Finding(
                "tool_error", run.instance_id, [idx], call.prompt_tokens + call.completion_tokens,
                f"{tool.name} failed at call {idx}: {_error_message(tool.output)}",
            ))

    # 5. Calls after submit_patch: the harness ends the session only when the turn ends,
    #    so a final full-context call (or more) is spent on a closing message.
    if submit is not None:
        after = [c for c in run.calls if c.index > submit]
        if after:
            findings.append(Finding(
                "post_submit_calls", run.instance_id, [c.index for c in after],
                sum(c.prompt_tokens + c.completion_tokens for c in after),
                f"{len(after)} LLM call(s) after submit_patch.",
            ))

    # 6. Harness-level failures: the context window overflowed (prompt + max_output_tokens
    #    above the server's max_model_len), or a time/turn budget ran out.
    if run.error:
        last = run.calls[-1] if run.calls else None
        if "ContextWindowExceeded" in run.error or "maximum context length" in run.error:
            findings.append(Finding(
                "context_overflow", run.instance_id, [last.index + 1] if last else [], 0,
                f"the next call was rejected: prompt + max_output_tokens exceeded the context window "
                f"(last accepted prompt: {last.prompt_tokens if last else 0} tokens).",
            ))
        else:
            findings.append(Finding("agent_error", run.instance_id, [], 0, run.error[:160]))
    if run.events.get("continuation_nudge"):
        findings.append(Finding(
            "continuation_nudge", run.instance_id, [], 0,
            f"the harness had to nudge the agent {run.events['continuation_nudge']} time(s) "
            f"(turn ended with no tool call).",
        ))

    # 7. Behavioural: patch submitted without running anything after the last edit,
    #    or no submission at all.
    edits = [idx for idx, t in seq if t.name in EDIT_TOOLS]
    if submit is None:
        findings.append(Finding("no_submit", run.instance_id, [], 0, "the run ended without submit_patch."))
    elif not edits:
        findings.append(Finding("submit_without_edit", run.instance_id, [submit], 0,
                                "submit_patch was called but no file was edited."))
    else:
        verified = any(t.name == "run_command" and _VERIFY.search(str(t.args.get("command") or ""))
                       for idx, t in seq if edits[-1] <= idx <= submit and t.name == "run_command")
        if not verified:
            findings.append(Finding("unverified_submit", run.instance_id, [edits[-1], submit], 0,
                                    "nothing was executed between the last edit and submit_patch."))
    return findings


def _tokens_per_char(run: Run) -> float:
    chars = run.system_chars + run.task_chars
    return run.calls[0].prompt_tokens / chars if run.calls and chars else 1 / 3.5


def _error_message(output: str) -> str:
    parsed = _json(output)
    if isinstance(parsed, dict):
        return str(parsed.get("error_message") or parsed.get("error") or parsed.get("error_type"))[:120]
    return output[:120]


# ── Aggregation ──────────────────────────────────────────────────────────────


def max_output_from_submission(results_dir: str | Path) -> int | None:
    """max_output_tokens declared in the submission next to a results directory, if any."""
    roots = [Path(results_dir) / "submission", Path(results_dir).parent / "submission"]
    root = next((r for r in roots if r.exists()), None)
    values = []
    for path in list(root.rglob("*.yaml")) + list(root.rglob("*.yml")) if root else []:
        values += [int(v) for v in re.findall(r"^\s*max_output_tokens:\s*(\d+)", path.read_text(encoding="utf-8"), re.M)]
    return max(values) if values else None


def summarize(runs: list[Run], *, label: str = "", thinking_threshold: int = 2000,
              max_output_tokens: int | None = None) -> dict[str, Any]:
    overhead, slope = profile(runs)
    findings = [f for run in runs for f in detect(run, thinking_threshold=thinking_threshold,
                                                  max_output_tokens=max_output_tokens)]
    by_run: dict[str, set[str]] = defaultdict(set)
    for f in findings:
        by_run[f.instance_id].add(f.kind)

    prompt = sum(r.prompt_tokens for r in runs)
    completion = sum(r.completion_tokens for r in runs)
    anatomy: dict[str, float] = defaultdict(float)
    for run in runs:
        for parts in run.anatomy:
            for key, value in parts.items():
                anatomy[key] += value
    tools = Counter(t.name for r in runs for _, t in r.tool_sequence())
    tool_runs = Counter(name for r in runs for name in {t.name for _, t in r.tool_sequence()})

    kinds = sorted({f.kind for f in findings})
    flags = {}
    known = [r for r in runs if r.resolved is not None]
    for kind in kinds:
        with_flag = [r for r in known if kind in by_run[r.instance_id]]
        without = [r for r in known if kind not in by_run[r.instance_id]]
        flags[kind] = {
            "runs": sum(1 for r in runs if kind in by_run[r.instance_id]),
            "occurrences": sum(1 for f in findings if f.kind == kind),
            "tokens": sum(f.tokens for f in findings if f.kind == kind),
            "resolved_with": _rate(with_flag),
            "resolved_without": _rate(without),
        }
    return {
        "label": label,
        "runs": len(runs),
        "resolved": sum(1 for r in runs if r.resolved),
        "resolution_rate": _rate(known),
        "llm_calls": sum(len(r.calls) for r in runs),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "sub_agent_tokens": sum(r.sub_agent_tokens for r in runs),
        "median_calls": _median([len(r.calls) for r in runs]),
        "median_peak_context": _median([max((c.prompt_tokens for c in r.calls), default=0) for r in runs]),
        "runs_with_compaction": sum(1 for r in runs if compactions(r)),
        "runs_with_error": sum(1 for r in runs if r.error),
        "fitted_overhead_tokens": round(overhead),
        "fitted_chars_per_token": round(1 / slope, 2) if slope else None,
        "anatomy_share": {k: v / prompt for k, v in sorted(anatomy.items(), key=lambda kv: -kv[1])} if prompt else {},
        "tool_calls": dict(tools.most_common()),
        "tool_used_in_runs": dict(tool_runs.most_common()),
        "findings": flags,
        "per_run": [
            {
                "instance_id": r.instance_id,
                "resolved": r.resolved,
                "calls": len(r.calls),
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "peak_context": max((c.prompt_tokens for c in r.calls), default=0),
                "flags": sorted(by_run[r.instance_id]),
            }
            for r in runs
        ],
        "finding_list": [f.__dict__ for f in findings],
    }


def _rate(runs: list[Run]) -> float | None:
    return sum(1 for r in runs if r.resolved) / len(runs) if runs else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def render_markdown(summaries: list[dict[str, Any]]) -> str:
    """Side-by-side table of several summaries (e.g. baseline vs fixed)."""
    def pct(v: float | None) -> str:
        return "—" if v is None else f"{v:.1%}"

    head = "| | " + " | ".join(s["label"] or f"run {i}" for i, s in enumerate(summaries)) + " |"
    sep = "|---" * (len(summaries) + 1) + "|"
    rows = [
        ("Tasks", lambda s: str(s["runs"])),
        ("Resolved", lambda s: f"{s['resolved']} ({pct(s['resolution_rate'])})"),
        ("LLM calls (median per task)", lambda s: str(s["median_calls"])),
        ("Peak context (median, tokens)", lambda s: f"{s['median_peak_context']:,.0f}" if s["median_peak_context"] else "—"),
        ("Prompt tokens", lambda s: f"{s['prompt_tokens']:,}"),
        ("Completion tokens", lambda s: f"{s['completion_tokens']:,}"),
        ("Runs with compaction", lambda s: str(s["runs_with_compaction"])),
    ]
    lines = [head, sep] + ["| " + name + " | " + " | ".join(fn(s) for s in summaries) + " |" for name, fn in rows]
    kinds = sorted({k for s in summaries for k in s["findings"]})
    if kinds:
        lines += ["", "| Finding (runs affected) | " + " | ".join(s["label"] for s in summaries) + " |", sep]
        for kind in kinds:
            cells = []
            for s in summaries:
                f = s["findings"].get(kind)
                cells.append("0" if not f else f"{f['runs']} (solved {pct(f['resolved_with'])} vs {pct(f['resolved_without'])})")
            lines.append(f"| {kind} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
