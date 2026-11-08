# Resolution Rate Is Not Enough: Profiling Small Gemma 4 Coding Agents from Their Traces

**tokenprof: an open profiler that turns SWE-agent trajectories into a token anatomy, failure detectors and testable behaviour metrics**

## Abstract

Gemma 4 E2B and E4B can run a coding agent on modest hardware, but they resolve few real issues. To understand why, and to tell whether a configuration change helped, we need to see what the agent did with its context and its turns. We present **tokenprof**, an open-source profiler for the ATIF trajectories that the competition harness writes for every task. From these traces alone, it rebuilds the anatomy of every prompt, fits the unobserved tool-schema overhead, detects compaction, and runs twelve detectors for wasteful or failing behaviour.

On all 129 public tasks, the official sample configuration resolves 10 tasks with E4B and 6 with E2B. The profile finds four problems:

- about 40% of all prompt tokens are a fixed prefix resent on every call;
- 83% of E4B runs read a long file blindly and got only its first 150 lines;
- `edit_file` fails 38% (E4B) to 70% (E2B) of the time;
- the sample's `max_output_tokens: 16384` reserves half the 32k window, which killed 29% of E2B runs with a context error.

We then test three profiler-guided interventions: prompt rules, a context-budget fix, and both. Each changed the behaviour it targeted, significantly (Fisher's exact test, p < 0.01): blind reads dropped from 83% to 54% of runs, and context overflows dropped from 29% to 0% (E2B). However, no resolution difference reached significance (E4B: 10, 12, 12 and 10 tasks; McNemar p ≥ 0.73). Four E4B runs together solved 21 different tasks. At this scale, a leaderboard number cannot tell configurations apart, but a trace profile can.

## 1. Introduction

The Gemma 4 Developer Agent competition asks for an agent that fixes real issues in Python repositories offline. It runs on 4× L4 GPUs, with a single Gemma 4 model and a declarative ADK configuration, and it is scored by the share of tasks whose hidden tests pass. That single number does not say *why* an agent fails. With resolution rates under 10% on about a hundred tasks, it is also too noisy to say whether a change helped. A difference of two or three tasks is what one gets from re-running the same configuration.

For a 2–4B model in a 32k window, waste is a capability problem, not just a cost problem. Every token of boilerplate displaces code the model needs, and every malformed tool call burns a turn. We argue that improving such agents should start where performance engineering starts: with a profiler.

Contributions:

1. **A resource.** `tokenprof swe` reads ATIF trajectories and reports:
   - a per-call prompt anatomy calibrated against reported token counts;
   - twelve detectors;
   - side-by-side comparisons, including the resolution rate with and without each flag.

   Companion scripts run any configuration on Kaggle's 4× L4 machines, test resolution task by task (exact McNemar) and test behaviour metrics (Fisher's exact).
2. **A profile** of Gemma 4 E4B and E2B on all 129 public tasks.
3. **An ablation** of profiler-guided interventions: seven full runs, 903 task attempts, all traces released.
4. **Findings for harness designers**: half-window output reservation, untraced compaction, a forced post-submit call, and a large static task prompt.

## 2. Setup

**Harness.** We use the official `swegemma` harness (v0.2.11) with vLLM 0.19.1 on Kaggle's 4× L4 notebooks, with the scorer's server settings (`max_model_len=32768`, tensor parallel 4, `gemma4` tool and reasoning parsers). Each task runs in a fresh sandbox through Phase 1 (agent) and Phase 2 (hidden tests), six tasks at a time.

**Tasks.** All 129 public tasks: fastapi (67), rich (48), requests (13) and httpx (1).

**Budgets.** Per task: 100 tool calls, 30 minutes and a 300 s command timeout. Budgets never bind for these models: the E4B baseline used a median of 10 tool calls and 143 s.

**Baseline.** The official `sample_submission`, switched to the E4B or E2B quantized model as in the starter notebook. It has a root agent with all 9 harness tools and a read-only `code_analyzer_agent` exposed as an AgentTool. Sampling: temperature 0.2, `max_output_tokens: 16384`, `thinking_budget: 4096`, and thoughts kept in history.

## 3. tokenprof for SWE trajectories

**Input.** One ATIF v1.7 file per task. It holds the system prompt, the task prompt and one step per LLM call: the message (with reasoning when kept), tool calls, the tool observation, and the prompt and completion tokens reported by vLLM. Resolution and harness errors come from the per-task results.

**Prompt anatomy.** The prompt of call *i* is rebuilt as the sum of:

- the system prompt;
- the task prompt, split into its harness sections (problem, budget, rules, instructions, code-intelligence tools, workspace tree);
- a fixed tool-schema and template overhead;
- everything the agent emitted before *i*;
- every tool output before *i*, grouped by tool.

Parts are sized in characters and scaled to sum exactly to the reported `prompt_tokens`, so totals are exact and only the split is estimated. A delegated agent's report is attributed to the AgentTool call that started it, and its own calls are counted separately.

**Fitting what the trace does not show.** Tool schemas never appear in the trace. The first call of every task contains only fixed parts, and only the task prompt's length varies across tasks. So a least-squares fit of first-call tokens against characters gives the overhead as the intercept (1,011 tokens) and the tokenizer's ratio as the slope (3.3 characters per token).

**Compaction.** ADK compacts history past a token threshold, but on our runs this left no event in the trace, and the summarization calls were not recorded either. tokenprof infers compaction from a prompt-size drop of more than 5%, then re-bases the anatomy on a "compacted history" part.

**Detectors.**

| Detector | Signal |
|---|---|
| `unscoped_truncated_read` | `read_file` without a line range returned `is_truncated` (files over 150 lines) |
| `repeated_read` | same file and range read again with no successful edit in between |
| `tool_error` | a non-shell tool returned an error (e.g. `old_string not found`) |
| `thinking_burst` | one call generated more than 2,000 tokens |
| `output_cap_hit` | one call reached `max_output_tokens` (read from the submission); labelled a repetition loop if its text compresses below 15% |
| `context_overflow` | the harness reported a context-window error |
| `continuation_nudge` | the harness had to prompt the agent to continue |
| `post_submit_calls` | LLM calls after `submit_patch` |
| `unverified_submit` | nothing executed between the last edit and `submit_patch` |
| `no_submit`, `submit_without_edit` | no submission, or no change submitted |
| `agent_error` | timeouts and other harness errors |

Unit tests on synthetic trajectories check each detector, the overhead fit (it recovers a planted intercept and slope) and the anatomy sums.

## 4. Profile of the baselines

**Table 1.** Baselines on 129 tasks.

| | E4B | E2B |
|---|---|---|
| Resolved | 10 (7.8%) | 6 (4.7%) |
| LLM calls per task (median) | 11 | 9 |
| Peak prompt per task (median) | 14,449 | 13,430 |
| Prompt / completion tokens | 15.6M / 0.77M | 12.4M / 1.06M |
| `edit_file` success | 62% (181/290) | 30% (85/280) |
| Runs with a context overflow | 9 | 37 |

**Table 2.** Prompt anatomy (share of all prompt tokens).

| Part | E4B | E2B |
|---|---|---|
| Tool outputs (`read_file` alone) | 30.5% (21.0%) | 27.5% (14.9%) |
| Agent history (text + thoughts) | 17.6% | 17.3% |
| Compacted history | 12.1% | 14.8% |
| System prompt | 12.2% | 12.4% |
| Tool schemas + template (fitted) | 10.9% | 11.1% |
| Task prompt (workspace tree alone) | 16.7% (7.7%) | 16.9% (8.0%) |

**Finding 1: a 40% fixed prefix.** The system prompt, tool schemas and task prompt take about 3,700 tokens before the agent acts, and they are resent on every call. Prefix caching makes them cheap to compute, but they still occupy the window. The workspace tree alone is 7.7% of all prompt tokens.

**Finding 2: blind reads and broken edits.** In 107 of 129 E4B runs, the agent called `read_file` without a range on a long file and got its first 150 lines, usually imports. `edit_file` then fails 38% (E4B) and 70% (E2B) of the time.

We classified the 109 failed E4B edits by comparing `old_string` with everything the agent had seen of that file:

| Failure type | Share |
|---|---|
| Mixed lines it had seen with lines it never saw | 39% |
| Matched more than one location | 19% |
| Every line had been seen, but not contiguously | 13% |
| None of the lines had been seen | 13% |
| Other | 15% |

Short `old_string`s help less than one might expect: one-line edits succeed 72% of the time, 2–6 lines 69%, and 16+ lines 47%. Runs with any failed tool call resolved 0% of the time, against 11.2% for runs without one.

**Finding 3: half the window reserved for output.** vLLM rejects requests where the prompt plus `max_output_tokens` exceeds `max_model_len`. With the sample's 16,384, any prompt over 16,384 tokens fails. ADK's compaction threshold (14,336) sits below that line, but compaction runs at intervals, so one large tool output can jump past it. In 37 E2B runs and 9 E4B runs the next call was rejected and the task ended unresolved.

The reservation buys little. Only 10 of 1,673 E4B calls generated more than 4,096 tokens. The calls that reached 16,384 were failures: 14 E2B calls, most of whose text compresses to 2–8% of its size, meaning the model repeated itself until the cap.

**Finding 4: a forced post-submit call.** The harness ends the session when the turn that called `submit_patch` ends, but ADK first sends the tool result back to the model. So nearly every run makes one more full-context call, which accounts for 8.4% of all E4B tokens.

## 5. Profiler-guided interventions

Each intervention targets detector findings:

- **guided** adds six rules to the sample prompt:
  1. locate code with `grep -n`, then call `read_file` with a line range;
  2. don't re-read a range you have already seen;
  3. copy a short, exact `old_string` from the latest read, and re-read the range after a failure;
  4. keep turns short;
  5. run a targeted test or reproduction before submitting;
  6. finish with one sentence.
- **window** sets `max_output_tokens: 6144` and `thinking_budget: 2048`, which leaves about 26.6k tokens for the prompt.
- **full** applies both.

All runs use the same 129 tasks and budgets.

**Table 3.** Resolution. McNemar p-values compare each run with its baseline, task by task.

| | base | window | guided | full |
|---|---|---|---|---|
| E4B resolved (both / base-only / run-only) | 10 | 12 (7/3/5), p=0.73 | 12 (7/3/5), p=0.73 | 10 (7/3/3), p=1.00 |
| E2B resolved | 6 | 9 (6/0/3), p=0.25 | not run | 7 (5/1/2), p=1.00 |
| E4B prompt tokens | 15.6M | 17.1M | 13.7M (−12%) | 16.4M |

**Table 4.** Behaviour, E4B. Fisher's exact test against the baseline; \* p < 0.05, \*\* p < 0.01.

| | base | window | guided | full |
|---|---|---|---|---|
| Ranged `read_file` (calls) | 47% | 46% | 63%\*\* | 59%\*\* |
| Runs with a blind truncated read | 83% | 89% | 54%\*\* | 65%\*\* |
| Runs with a repeated read | 26% | 31% | 7%\*\* | 17% |
| Runs with a context overflow | 7% | 0%\*\* | 5% | 1%\* |
| Runs with no submission | 9% | 0%\*\* | 5% | 1%\*\* |
| Runs with a nudge | 25% | 34% | 14%\* | 9%\*\* |
| `edit_file` success (calls) | 62% | 58% | 61% | 53%\* |

For E2B, both window and full removed every context overflow (29% → 0%\*\*) and cut runs with no submission from 30% to 9%\*\* and 2%\*\*. full also raised ranged reads from 9% to 40%\*\* and the share of runs that executed code from 53% to 74%\*\*.

**Noise.** Re-running the E4B baseline unchanged gave [R2: resolved, overlap, McNemar p, and the behaviour rows for base vs base]. Across the four E4B configurations, 21 different tasks were solved at least once, against 10 to 12 per run.

**Reading the results.**

- *The interventions did what they were designed to do.* Navigation rules changed navigation, and the budget fix removed overflows and missing submissions.
- *None of them moved the bottleneck.* Edit fidelity did not improve under any configuration, and full made it worse: more edits attempted, more failed. The model can locate code and keep its context in check, but it cannot reliably reproduce the exact text it wants to replace.
- *Resolution cannot detect these effects.* Behaviour metrics computed over hundreds of tool calls show them clearly, while resolution over about ten solved tasks does not.

## 6. Discussion

**For harness designers.**

- Reserving 16k of a 32k window for output mostly lets degenerate loops run longer. A smaller default cap, or a cap that adapts to the remaining window, would remove a whole class of failures.
- Compaction should leave an event in the trace, and its LLM calls should be counted.
- `submit_patch` could end the session without one more model call.
- The workspace tree could be served on demand by a tool instead of resent every turn.

**For agent designers.** Small models fail at the interface: they read blindly, edit from memory and stop early. Prompt rules fix the first and the last, but not the second. Promising next steps are an edit interface that tolerates small copy errors, such as line-anchored replacement, or fine-tuning on exact-copy edits, which the competition's LoRA support allows.

**For evaluation.** With fewer than about 15 solved tasks, report task-level overlap and a paired test, and judge a change by the behaviour it targets.

## 7. Limitations

- We use the 129 public tasks, not the hidden set, and run most configurations once.
- The anatomy split is apportioned by characters: exact in total, estimated per part.
- Compaction is inferred from prompt drops, and its summarization calls are invisible.
- The guided rules were written after seeing the baseline profile, so behaviour gains on the same tasks may overstate gains on new ones.
- We did not run guided on E2B for lack of GPU quota.

## 8. Related work

SWE-bench (Jimenez et al., 2024) defined issue resolution verified by tests; the competition harness follows its protocol. SWE-agent (Yang et al., 2024) showed that the agent–computer interface matters: a windowed file viewer and guarded edit commands change resolution rates. Our truncated-read and failed-edit findings are the same phenomenon, measured from traces for small models. Agentless (Xia et al., 2024) showed that a fixed localize–repair–validate pipeline competes with free-form agents, consistent with small agents wasting turns on navigation. vLLM (Kwon et al., 2023) provides the paged attention and prefix caching the harness uses. [verify references]

## 9. Reproducibility

The profiler, Kaggle runner, configurations, comparison scripts and all seven runs' traces are at [repository link]. Profiling and comparing runs:

```bash
pip install -e .
tokenprof swe experiments/swegemma/results/base_e4b experiments/swegemma/results/full_e4b --label base --label full --md table.md
python experiments/swegemma/behaviour.py base_e4b guided_e4b
python experiments/swegemma/compare.py base_e4b guided_e4b
```
