# tokenprof

**A token profiler for LLM agents.** See where every token goes, find the waste, and fix it.

> Status: early development.

## What it does

1. **Capture**: an OpenAI-compatible proxy logs every call (tokens, cost, latency, agent step).
2. **Visualize**: a token anatomy chart per run: each call's prompt split by content type (system, tool schemas, history, tool outputs), plus its output and the part served from cache.
3. **Diagnose**: automatic waste detectors:
   - repeated context resent across calls
   - large tool outputs the model barely used
   - prompt-cache breakers (dynamic content at the start of the prompt)
   - retries and loops
4. **Suggest**: each finding comes with estimated savings and a fix.

## Quickstart: the logging proxy

```bash
pip install -e .
tokenprof proxy --upstream https://api.openai.com/v1 --out traces.jsonl --pricing pricing.json
```

Point any OpenAI-compatible client at `http://127.0.0.1:8787/v1` instead of the provider. Any OpenAI-compatible upstream works (OpenRouter, Groq, Gemini's OpenAI endpoint, or Ollama at `http://localhost:11434/v1`).

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1")
client.chat.completions.create(
    model="...",
    messages=[{"role": "user", "content": "Olá"}],
    extra_headers={"X-Tokenprof-Run": "run-42", "X-Tokenprof-Step": "plan"},
)
```

Each chat completion (streaming or not) becomes one line in `traces.jsonl`: request, response, token usage (including cached tokens), latency, time to first token and estimated cost. The optional `X-Tokenprof-*` headers group calls by agent run and step; they are not forwarded upstream. API keys are forwarded but never written to the trace. Traces do contain the prompts, so keep them local.

**Gemini and `langchain-openai`.** Current Gemini models return a thought signature on each tool call and reject follow-up requests that drop it, which `langchain-openai` (and so LangGraph) does. `--restore-thought-signatures` makes the proxy remember each signature by tool call id and put it back. It is off by default because it changes requests; each trace records how many signatures it restored, and the trace keeps the request as the client sent it.

Prices change often, so none are built in. `--pricing` takes a JSON file with USD per million tokens; see [`pricing.example.json`](pricing.example.json).

## Roadmap

- [x] Logging proxy with streaming support
- [x] Trace analysis and token anatomy chart per run
- [x] Waste detectors (validated on a demo agent with planted waste)
- [x] `tokenprof analyze traces.jsonl` → HTML report
- [x] Pilot experiment on open-source agent frameworks (tokens before/after, task accuracy)
- [ ] Detector for large static prompts (found in the pilot: smolagents' default system prompt)
- [x] Opt-in proxy mode that restores Gemini `thought_signature`s dropped by `langchain-openai` (LangGraph added to the pilot)
- [ ] PyPI release

## Results

**Pilot on open-source agent frameworks.** Three popular frameworks, used with their defaults, answered 10 order questions against a fake store API (`gemini-3.5-flash-lite`, 2 repetitions). tokenprof found that tool outputs made up 82% (LangGraph), 76% (OpenAI Agents SDK) and 43% (smolagents) of all prompt tokens, mostly unused. Applying its suggestion, returning only the fields the agent needs, gave:

| | Baseline | Fixed |
|---|---|---|
| Correct answers | 60/60 | 60/60 |
| Prompt tokens, LangGraph | 59,582 | 11,676 (**−80.4%**) |
| Prompt tokens, OpenAI Agents SDK | 61,622 | 13,818 (**−77.6%**) |
| Prompt tokens, smolagents | 105,317 | 59,806 (**−43.2%**) |
| Prompt tokens, total | 226,521 | 85,300 (**−62.3%**) |

After the fix, smolagents' default system prompt is 74% of its prompt tokens, so it still spends 4–5× more per task than the other two. LangGraph needed the proxy's `--restore-thought-signatures` mode to run on current Gemini models (see below). This is a small pilot with simple tasks and a synthetic API; see the setup, raw traces and limits in [docs/test-log.md](docs/test-log.md) and [experiments/agents](experiments/agents).

**Detector validation (demo agent with planted waste).** A small support agent looked up 3 orders through a local model (Ollama, `qwen2.5:0.5b`) in two modes: one with a timestamp in the system prompt and a tool that returns the full order record, and one with the fixes tokenprof suggested. tokenprof flagged both planted problems in every run of the wasteful mode and raised no findings on the fixed one.

| | Wasteful | Fixed |
|---|---|---|
| Correct answers | 3/3 | 3/3 |
| Prompt tokens | 10,583 | 1,283 (**−87.9%**) |
| Prompt tokens served from cache | 2.0% | 74.4% |

Details, raw traces and HTML reports: [docs/test-log.md](docs/test-log.md).

**Proxy validation (v0.0.1):** 8/8 unit tests pass, and an end-to-end run against Ollama (`qwen2.5:0.5b`, CPU) logged plain, streaming and streaming tool calls correctly. A streaming tool call split across chunks was rebuilt as `clima({"cidade":"Recife"})`, and a real provider crash (GPU driver failure) was relayed as a 500 and recorded. Full numbers and raw traces are in [docs/test-log.md](docs/test-log.md).
