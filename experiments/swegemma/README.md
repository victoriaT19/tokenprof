# Gemma 4 Developer Agent study

Profiling small Gemma 4 coding agents (E4B and E2B) on the 129 public tasks of the [Gemma 4 Developer Agent competition](https://www.kaggle.com/competitions/gemma-4-developer-agent), with `tokenprof swe`.

**Paper:** [`paper/writeup.md`](paper/writeup.md), *Resolution Rate Is Not Enough: Profiling Small Gemma 4 Coding Agents from Their Traces*.

## What is where

```text
experiments/swegemma/
├── paper/
│   └── writeup.md            the paper (Paper Track submission)
├── results/                  everything measured; every number in the paper comes from here
│   ├── <run>/                one folder per run (see the table below)
│   │   ├── run_meta.json         settings and resolution rate
│   │   ├── run_results.jsonl     one line per task: resolved, patch, test output, errors
│   │   ├── traces.tar.gz         ATIF trajectory + log of every task
│   │   └── submission/           the exact agent config that ran
│   ├── table_e4b.md, table_e2b.md            tokenprof swe comparison tables
│   ├── summary_e4b.json, summary_e2b.json    full tokenprof swe output (anatomy, findings)
│   ├── behaviour_e4b.md, behaviour_e2b.md    behaviour metrics with Fisher's exact tests
│   └── behaviour_e4b_noise.md                baseline vs its unchanged re-run
├── submissions/              agent configs tested: sample, guided, window, full
├── runs/                     run definitions (model, config, budget) used to build each Kaggle job
├── runner_template.py        Kaggle script: installs the harness, starts vLLM, runs the tasks
├── build_kernel.py           turns a run definition into a Kaggle kernel (kaggle kernels push)
├── fetch_run.py              downloads a finished run and packs it into results/<run>/
├── compare.py                resolution task by task, exact McNemar test
├── behaviour.py              behaviour metrics, Fisher's exact test
└── package_submission.py     builds a competition submission.zip from a config
```

## Runs

| Run | Model | Config | Resolved |
|---|---|---|---|
| `base_e4b` | E4B | `sample` (official sample submission) | 10/129 |
| `base_e4b_r2` | E4B | `sample`, unchanged re-run (noise control) | 9/129 |
| `window_e4b` | E4B | `window`: `max_output_tokens` 6144, thinking budget 2048 | 12/129 |
| `guided_e4b` | E4B | `guided`: sample prompt + 6 rules | 12/129 |
| `full_e4b` | E4B | `full`: guided + window | 10/129 |
| `base_e2b` | E2B | `sample` | 6/129 |
| `window_e2b` | E2B | `window` | 9/129 |
| `full_e2b` | E2B | `full` | 7/129 |

All runs: 4× NVIDIA L4 on Kaggle, `swegemma` 0.2.11, vLLM 0.19.1, 100 tool calls and 30 minutes per task.

## Reproducing the numbers

From the repository root, with no GPU needed:

```bash
pip install -e .
tokenprof swe experiments/swegemma/results/base_e4b experiments/swegemma/results/guided_e4b --label base --label guided
python experiments/swegemma/behaviour.py base_e4b guided_e4b
python experiments/swegemma/compare.py base_e4b guided_e4b
```

Running a configuration again needs a Kaggle account with the competition joined and GPU quota:

```bash
cd experiments/swegemma
python build_kernel.py runs/window_e4b.json
kaggle kernels push -p kernels/window_e4b
python fetch_run.py window_e4b
```
