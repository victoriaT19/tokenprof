# Experiment: tokenprof on open-source agent frameworks

Popular agent frameworks, used with their defaults, answer 10 questions about orders in a fake store. Every call goes through the tokenprof proxy. The baseline is analyzed, the fixes tokenprof suggests are applied, and the run is repeated to compare prompt tokens and accuracy.

## Setup

- **Model:** `gemini-3.5-flash-lite` (Gemini API free tier, OpenAI-compatible endpoint).
- **Store:** [`store.py`](store.py): 40 orders, 8 customers and 40 products, generated with a fixed seed. Tools: `get_order`, `list_customer_orders`, `get_product`.
- **Tasks:** [`tasks.py`](tasks.py): 10 questions whose expected answers are computed from the store. Numeric answers are matched within R$ 0.01; text answers by substring.
- **Tool styles:** `full` returns whole API records (the usual first integration); `compact` returns only the fields an agent needs (the fix tokenprof suggests for unused tool output).

## Run

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

Put `GEMINI_API_KEY` in `tokenprof/.env`, then from PowerShell:

```powershell
.\run_batch.ps1 -Style full -Name baseline
.\run_batch.ps1 -Style compact -Name fixed
tokenprof analyze ..\..\docs\results\<date>-exp-baseline.jsonl --out baseline.html
```

`run_batch.ps1` starts the proxy, runs every framework twice, and writes the trace and the graded answers to `docs/results/`.

## Frameworks

| Framework | Version | Status |
|---|---|---|
| smolagents (`ToolCallingAgent`) | 1.26.0 | included |
| OpenAI Agents SDK (`OpenAIChatCompletionsModel`) | 0.24.0 | included |
| LangGraph (`create_react_agent` + `langchain-openai`) | 1.2.20 / 1.7.4 | excluded: current Gemini models reject its follow-up requests (400, missing `thought_signature` on function calls); the older model that does not require it is no longer available to new API users |

## Results (2026-11-06)

| | Baseline (`full`) | Fixed (`compact`) |
|---|---|---|
| Correct answers | 40/40 | 40/40 |
| Prompt tokens per task, OpenAI Agents SDK | 3,081 | 691 (−77.6%) |
| Prompt tokens per task, smolagents | 5,266 | 2,990 (−43.2%) |
| Prompt tokens, total | 166,939 | 73,624 (−55.9%) |

Full numbers, findings and limits are in [`docs/test-log.md`](../../docs/test-log.md).
