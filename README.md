# tokenprof

**A token profiler for LLM agents.** See where every token goes, find the waste, and fix it.

> **Gemma 4 Developer Agent study.** The paper is [`experiments/swegemma/paper/writeup.md`](experiments/swegemma/paper/writeup.md). Its data, configs and scripts are in [`experiments/swegemma`](experiments/swegemma); see the [layout](#repository-layout) below.

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

## Profiling SWE agents: `tokenprof swe`

Coding-agent harnesses often save one trajectory per task instead of raw API calls. `tokenprof swe` reads ATIF trajectories, such as those written by `swegemma`, the harness of the Gemma 4 Developer Agent competition, and reports three things:

- **Prompt anatomy per call.** Each prompt is split into system prompt, task prompt sections, tool schemas, agent history, each tool's outputs and compacted history. The split is scaled to the token counts the server reported. The tool-schema overhead, which the trace never shows, is fitted from the data.
- **Twelve detectors.** They cover blind truncated reads, repeated reads, failed tool calls, long turns, repetition loops that hit the output cap, context overflows, nudges, calls after `submit_patch`, unverified or missing submissions, and harness errors.
- **Comparison tables** across runs, including the resolution rate with and without each flag.

```bash
tokenprof swe experiments/swegemma/results/base_e4b experiments/swegemma/results/guided_e4b --label base --label guided --md table.md
```

The full study is in [`experiments/swegemma`](experiments/swegemma): eight runs of 129 tasks with Gemma 4 E4B and E2B (one of them an unchanged re-run as a noise control), plus the Kaggle runner, configurations, traces, statistical tests and the [paper](experiments/swegemma/paper/writeup.md).

## Repository layout

```text
tokenprof/
├── src/tokenprof/
│   ├── proxy.py            logging proxy (tokenprof proxy)
│   ├── analyze.py          waste detectors for proxy traces (tokenprof analyze)
│   ├── report.py           HTML report
│   ├── swe.py              ATIF trajectory profiler for SWE agents (tokenprof swe)
│   ├── trace.py, pricing.py, cli.py
├── tests/                  unit tests (pytest)
├── scripts/                demo agent with planted waste, end-to-end proxy check
├── experiments/
│   ├── agents/             pilot: LangGraph, OpenAI Agents SDK and smolagents through the proxy
│   └── swegemma/           Gemma 4 Developer Agent study: paper, runs, configs, scripts
│       └── paper/writeup.md    the paper
└── docs/
    ├── test-log.md         every test and experiment run, with date, setup and numbers
    └── results/            raw traces and HTML reports of the proxy experiments
```

## Roadmap

- [x] Logging proxy with streaming support
- [x] Trace analysis and token anatomy chart per run
- [x] Waste detectors (validated on a demo agent with planted waste)
- [x] `tokenprof analyze traces.jsonl` → HTML report
- [x] Pilot experiment on open-source agent frameworks (tokens before/after, task accuracy)
- [ ] Detector for large static prompts (found in the pilot: smolagents' default system prompt)
- [x] Opt-in proxy mode that restores Gemini `thought_signature`s dropped by `langchain-openai` (LangGraph added to the pilot)
- [x] `tokenprof swe`: profile ATIF trajectories of SWE agents (Gemma 4 Developer Agent study)
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
