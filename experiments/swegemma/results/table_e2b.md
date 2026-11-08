| | base | window | full |
|---|---|---|---|
| Tasks | 129 | 129 | 129 |
| Resolved | 6 (4.7%) | 9 (7.0%) | 7 (5.4%) |
| LLM calls (median per task) | 9 | 11 | 13 |
| Peak context (median, tokens) | 13,430 | 14,822 | 14,820 |
| Prompt tokens | 12,429,798 | 18,308,688 | 21,105,120 |
| Completion tokens | 1,057,959 | 1,688,182 | 1,351,539 |
| Runs with compaction | 60 | 87 | 97 |

| Finding (runs affected) | base | window | full |
|---|---|---|---|
| agent_error | 1 (solved 0.0% vs 4.7%) | 10 (solved 0.0% vs 7.6%) | 3 (solved 0.0% vs 5.6%) |
| context_overflow | 37 (solved 0.0% vs 6.5%) | 0 | 0 |
| continuation_nudge | 44 (solved 0.0% vs 7.1%) | 47 (solved 4.3% vs 8.5%) | 69 (solved 1.4% vs 10.0%) |
| no_submit | 39 (solved 0.0% vs 6.7%) | 11 (solved 0.0% vs 7.6%) | 3 (solved 0.0% vs 5.6%) |
| output_cap_hit | 14 (solved 0.0% vs 5.2%) | 17 (solved 0.0% vs 8.0%) | 12 (solved 0.0% vs 6.0%) |
| post_submit_calls | 68 (solved 8.8% vs 0.0%) | 93 (solved 8.6% vs 2.8%) | 99 (solved 6.1% vs 3.3%) |
| repeated_read | 55 (solved 1.8% vs 6.8%) | 59 (solved 6.8% vs 7.1%) | 67 (solved 1.5% vs 9.7%) |
| submit_without_edit | 2 (solved 0.0% vs 4.7%) | 2 (solved 0.0% vs 7.1%) | 1 (solved 0.0% vs 5.5%) |
| thinking_burst | 50 (solved 2.0% vs 6.3%) | 55 (solved 3.6% vs 9.5%) | 63 (solved 3.2% vs 7.6%) |
| tool_error | 68 (solved 1.5% vs 8.2%) | 75 (solved 1.3% vs 14.8%) | 76 (solved 3.9% vs 7.5%) |
| unscoped_truncated_read | 109 (solved 3.7% vs 10.0%) | 108 (solved 6.5% vs 9.5%) | 102 (solved 4.9% vs 7.4%) |
| unverified_submit | 36 (solved 0.0% vs 6.5%) | 51 (solved 5.9% vs 7.7%) | 46 (solved 0.0% vs 8.4%) |
