# Resolution Rate Is Not Enough: Profiling Small Gemma 4 Coding Agents from Their Traces

**tokenprof: an open profiler that turns SWE-agent trajectories into a token anatomy, failure detectors and testable behaviour metrics**

## Abstract

Gemma 4 E2B and E4B can run a coding agent on modest hardware, but they resolve few real issues. We present **tokenprof**, an open-source profiler for the ATIF trajectories the competition harness writes for every task. From these traces alone, it rebuilds the anatomy of every prompt, fits the unobserved tool-schema overhead, detects compaction, and runs twelve detectors for wasteful or failing behaviour.

On all 129 public tasks, the official sample configuration resolves 10 tasks with E4B and 6 with E2B. The profile shows that:

- about 40% of all prompt tokens are a fixed prefix resent on every call;
- 83% of E4B runs read a long file blindly and got only its first 150 lines;
- `edit_file` fails 38% (E4B) to 70% (E2B) of the time;
- two of the three code-graph tools were almost never called;
- the sample's `max_output_tokens: 16384` reserves half the 32k window, which killed 29% of E2B runs with a context error.

Three profiler-guided interventions (prompt rules, a context-budget fix, and both) each changed the behaviour they targeted (Fisher's exact test, p < 0.01): blind reads fell from 83% to 54% of runs, and E2B context overflows from 29% to 0%. However, no resolution difference reached significance (E4B: 10, 12, 12 and 10 tasks; McNemar p ≥ 0.73). An unchanged re-run of the baseline solved 9 tasks and showed no significant behaviour change. Run-to-run noise in agentic evaluation is known; our point is practical. When a fixed GPU quota rules out many repeated runs, behaviour metrics from the same traces can be tested even where resolution cannot.

## 1. Introduction

The Gemma 4 Developer Agent competition asks for an offline agent that fixes real issues in Python repositories, using one Gemma 4 model and a declarative ADK configuration on 4× L4 GPUs, scored by the share of tasks whose hidden tests pass. That single number does not say *why* an agent fails. With resolution rates under 10% on about a hundred tasks, it is also too noisy to say whether a change helped. On SWE-bench Verified, single-run pass@1 shifts by 2–6 points between identical runs (Bjarnason et al., 2026). The standard remedies are more runs and paired tests (Miller, 2024), and more runs are exactly what a weekly GPU quota does not allow.

For a 2–4B model in a 32k window, waste is a capability problem: boilerplate displaces code the model needs, and every malformed tool call burns a turn. We argue that improving such agents should start where performance engineering starts: with a profiler. Prior token analyses of coding agents measure the *cost* of frontier models (Bai et al., 2026), and failure taxonomies are built by hand (Liu et al., 2025). We instead rebuild every prompt of a small model from its trace, including the parts the trace omits, and detect failures automatically on every run.

Contributions:

1. **A resource.** `tokenprof swe` reports a per-call prompt anatomy calibrated against reported token counts, twelve detectors, and side-by-side run comparisons. Companion scripts run any configuration on Kaggle's 4× L4 machines and test resolution (exact McNemar) and behaviour (Fisher's exact).
2. **A profile** of Gemma 4 E4B and E2B on all 129 public tasks.
3. **An ablation** of profiler-guided interventions, with an unchanged re-run of the baseline as a noise control: eight full runs, 1,032 task attempts, all traces released.
4. **Findings for harness designers** on output reservation, compaction, the post-submit call and graph-tool use.

## 2. Setup

**Harness.** The official `swegemma` harness (v0.2.11) with vLLM 0.19.1 on Kaggle's 4× L4 notebooks, using the scorer's server settings (`max_model_len=32768`, tensor parallel 4). Each task runs in fresh sandboxes for the agent and for the hidden tests, six tasks at a time.

**Tasks.** All 129 public tasks: fastapi (67), rich (48), requests (13) and httpx (1).

**Budgets.** Per task: 100 tool calls, 30 minutes and a 300 s command timeout. Budgets never bind for these models: the E4B baseline used a median of 10 tool calls and 143 s.

**Baseline.** The official `sample_submission` with the E4B or E2B quantized model: a root agent with all 9 harness tools plus a read-only `code_analyzer_agent` AgentTool; temperature 0.2, `max_output_tokens: 16384`, `thinking_budget: 4096`, thoughts kept in history.

## 3. tokenprof for SWE trajectories

**Input.** One ATIF v1.7 file per task: the system prompt, the task prompt, and one step per LLM call with its message (including kept reasoning), tool calls, observation and the token counts vLLM reported. Resolution and harness errors come from the per-task results.

**Prompt anatomy.** The prompt of call *i* is rebuilt as the system prompt, the task prompt split into its harness sections (problem, budget, rules, instructions, code-intelligence tools, workspace tree), a fixed tool-schema overhead, everything the agent emitted before *i*, and every earlier tool output, grouped by tool. Parts are sized in characters and scaled to sum exactly to the reported `prompt_tokens`, so totals are exact and only the split is estimated. A delegated agent's report is attributed to the AgentTool call that started it, and its own calls are counted separately.

**Fitting what the trace does not show.** Tool schemas never appear in the trace. Every task's first call holds only fixed parts, and only the task prompt's length varies, so a least-squares fit of first-call tokens against characters gives the overhead as the intercept (1,011 tokens) and the tokenizer's ratio as the slope (3.3 characters per token).

**Compaction.** ADK compacts history past a token threshold without leaving a trace event or recording its summarization calls. tokenprof infers it from a prompt-size drop above 5% and re-bases the anatomy on a "compacted history" part.

**Detectors.**

| Detector | Signal |
|---|---|
| `unscoped_truncated_read` | `read_file` without a line range returned `is_truncated` (files over 150 lines) |
| `repeated_read` | same file and range read again with no successful edit in between |
| `tool_error` | a non-shell tool returned an error (e.g. `old_string not found`) |
| `thinking_burst` | one call generated more than 2,000 tokens |
| `output_cap_hit` | a call hit `max_output_tokens`; a repetition loop if its text compresses below 15% |
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

**Finding 1: a 40% fixed prefix.** The system prompt, tool schemas and task prompt take about 3,700 tokens before the agent acts and are resent on every call. Prefix caching makes them cheap to compute, but they still occupy the window; the workspace tree alone is 7.7% of all prompt tokens.

**Finding 2: blind reads and broken edits.** In 107 of 129 E4B runs, the agent called `read_file` without a range on a long file and got its first 150 lines, usually imports. `edit_file` then fails 38% (E4B) and 70% (E2B) of the time.

We classified the 109 failed E4B edits by comparing `old_string` with everything the agent had seen of that file:

| Failure type | Share |
|---|---|
| Mixed lines it had seen with lines it never saw | 39% |
| Matched more than one location | 19% |
| Every line had been seen, but not contiguously | 13% |
| None of the lines had been seen | 13% |
| Other | 15% |

Shorter `old_string`s help less than expected (one line: 72% success; 2–6 lines: 69%; 16+: 47%). Runs with a failed tool call resolved 0% of the time, against 11.2% without one.

**Finding 3: half the window reserved for output.** vLLM rejects a request when prompt plus `max_output_tokens` exceeds `max_model_len`, so with the sample's 16,384 any prompt over 16,384 tokens fails. Compaction (threshold 14,336) runs only at intervals, so one large tool output can jump past that line. In 37 E2B runs and 9 E4B runs the next call was rejected and the task ended unresolved.

The reservation buys little. Only 10 of 1,673 E4B calls generated more than 4,096 tokens. The calls that reached 16,384 were failures: 14 E2B calls, most of whose text compresses to 2–8% of its size, meaning the model repeated itself until the cap.

**Finding 4: a forced post-submit call.** The session ends only after the turn that called `submit_patch`, and ADK first returns the tool result to the model, so nearly every run makes one more full-context call: 8.4% of all E4B tokens.

**Finding 5: the graph tools are barely used.** Of the three code-graph tools, only `search_similar_code` sees real use: 105 E4B calls across 55 runs, costing 4.5% of all prompt tokens (9.1% for E2B). `get_code_neighbors` and `get_code_subgraph` were called 7 and 2 times by the E4B root agent, and 16 and 5 times by the sub-agent. Offline, the search expects symbol names and falls back to word overlap for phrases, yet 19% of E4B queries and 34% of E2B queries were phrases such as "File Form parameter validation". The grep-first rules halved graph use (63 → 30 runs) without lowering resolution: small models need symbol-first prompting or training to benefit from the graph.

## 5. Profiler-guided interventions

Each intervention targets detector findings:

- **guided** adds six rules to the sample prompt: locate code with `grep -n` and read a line range; don't re-read; copy a short, exact `old_string` from the latest read; keep turns short; run a targeted test before submitting; finish with one sentence.
- **window** sets `max_output_tokens: 6144` and `thinking_budget: 2048`, which leaves about 26.6k tokens for the prompt.
- **full** applies both.

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

**Noise control.** We re-ran the E4B baseline unchanged. It resolved 9 tasks against 10 (8 shared; McNemar p = 1.00). No behaviour metric in Table 4 differed significantly between the two (all p ≥ 0.08; e.g. blind truncated reads 83% vs 86%, edit success 62% vs 63%), so the shifts in Table 4 are not what re-running alone produces. The control also exposes noisy metrics: context overflows went from 9 to 16 runs, which makes window's drop to 0 more telling. Across all five E4B runs, 21 different tasks were solved at least once, against 9 to 12 per run.

**Reading the results.**

- *The interventions did what they were designed to do*: navigation rules changed navigation; the budget fix removed overflows and missing submissions.
- *None moved the bottleneck.* Edit fidelity never improved, and full made it worse. The model can locate code but cannot reliably reproduce the text it wants to replace.
- *Resolution cannot see these effects*; behaviour metrics over hundreds of tool calls can.

## 6. Discussion

**For harness designers.**

- Reserving 16k of a 32k window for output mostly lets degenerate loops run longer; a smaller or adaptive cap removes a whole class of failures.
- Compaction should leave a trace event and count its LLM calls.
- `submit_patch` could end the session without another model call.
- The workspace tree could be a tool instead of being resent every turn.

**For agent designers.** Small models fail at the interface: they read blindly, edit from memory and stop early. Prompt rules fix the first and the last, but not the second. This matches Diff-XYZ, where search-replace edits suit large models but not small ones (Glukhov et al., 2025). Promising next steps are an edit interface that tolerates copy errors, such as line-anchored replacement, or LoRA fine-tuning on exact-copy edits. Since tool outputs are the largest prompt share, masking old observations (Lindenbauer et al., 2025) is a cheap way to cut history.

**For evaluation.** With fewer than about 15 solved tasks, report task-level overlap and a paired test, and judge a change by the behaviour it targets. One baseline re-run is a cheap control for which metrics are stable.

## 7. Limitations

- We use the 129 public tasks, not the hidden set. Each intervention ran once; only the E4B baseline was repeated.
- The anatomy split is apportioned by characters: exact in total, estimated per part.
- Compaction is inferred from prompt drops, and its summarization calls are invisible.
- The guided rules were written after seeing the baseline profile, so behaviour gains on the same tasks may overstate gains on new ones.

## 8. Related work

**Benchmarks and interfaces.** SWE-bench (Jimenez et al., 2024) defined test-verified issue resolution. SWE-agent (Yang et al., 2024) showed that the agent–computer interface changes resolution rates. Our read and edit findings are that phenomenon, measured automatically for small models.

**Evaluation noise.** Bjarnason et al. (2026) ran about 60,000 SWE-bench Verified trajectories and found that improvements of 2–3 points can be noise. Miller (2024) recommends paired, question-level tests. We confirm it with a controlled re-run and add a complement for compute-limited settings: testing the targeted behaviour.

**Trajectories and tokens.** Liu et al. (2025) built a manual taxonomy of 150 failed issues across localization, repair and validation. Bai et al. (2026) analyzed token consumption of eight frontier models on SWE-bench Verified, finding that input tokens dominate cost and that repeated file views mark expensive runs. tokenprof works per call from the trajectory alone, recovers what the trace omits (tool schemas, compaction), and targets small models, for which the 32k window, not price, is the binding constraint.

**Context and small models.** Lindenbauer et al. (2025) showed that masking old observations is as effective as LLM summarization for SWE agents. For small models, training data (SWE-Gym, Pan et al., 2024; SWE-smith, Yang et al., 2025) is the usual lever, and SWE-Protégé (2026) reports pervasive action looping in 7B agents, consistent with the repetition loops we detect. The traces we profile use ATIF, the trajectory format of the Harbor framework.

## 9. Reproducibility

The profiler, Kaggle runner, configurations, comparison scripts and all eight runs' traces are at <https://github.com/victoriaT19/tokenprof> (study in `experiments/swegemma`). The study's README lists the commands that rebuild every table from the released traces, without a GPU.

## References

- Jimenez, C. E., et al. SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024.
- Yang, J., et al. SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. NeurIPS 2024.
- Bjarnason, B. H., Silva, A., and Monperrus, M. On Randomness in Agentic Evals. arXiv:2602.07150, 2026.
- Miller, E. Adding Error Bars to Evals: A Statistical Approach to Language Model Evaluations. arXiv:2411.00640, 2024.
- Bai, L., et al. How Do AI Agents Spend Your Money? Analyzing and Predicting Token Consumption in Agentic Coding Tasks. arXiv:2604.22750, 2026.
- Liu, S., et al. An Empirical Study on Failures in Automated Issue Solving. arXiv:2509.13941, 2025.
- Glukhov, E., et al. Diff-XYZ: A Benchmark for Evaluating Diff Understanding. arXiv:2510.12487, 2025.
- Lindenbauer, T., et al. The Complexity Trap: Simple Observation Masking Is as Efficient as LLM Summarization for Agent Context Management. NeurIPS 2025 (arXiv:2508.21433).
- Pan, J., et al. Training Software Engineering Agents and Verifiers with SWE-Gym. arXiv:2412.21139, 2024.
- Yang, J., et al. SWE-smith: Scaling Data for Software Engineering Agents. NeurIPS 2025 (arXiv:2504.21798).
- SWE-Protégé. arXiv:2602.22124, 2026.
- Harbor framework: Agent Trajectory Interchange Format (ATIF). https://harborframework.com/docs/trajectory-format
- Markowitz, E., Perozzi, B., Rózemberczki, B., et al. Google - The Gemma 4 Developer Agent Competition. Kaggle, 2026.
