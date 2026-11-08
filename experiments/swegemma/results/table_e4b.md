| | base | window | guided | full |
|---|---|---|---|---|
| Tasks | 129 | 129 | 129 | 129 |
| Resolved | 10 (7.8%) | 12 (9.3%) | 12 (9.3%) | 10 (7.8%) |
| LLM calls (median per task) | 11 | 12 | 10 | 12 |
| Peak context (median, tokens) | 14,449 | 14,664 | 13,861 | 14,450 |
| Prompt tokens | 15,556,718 | 17,089,174 | 13,739,500 | 16,444,356 |
| Completion tokens | 773,333 | 812,695 | 645,502 | 826,573 |
| Runs with compaction | 70 | 81 | 53 | 72 |

| Finding (runs affected) | base | window | guided | full |
|---|---|---|---|---|
| context_overflow | 9 (solved 0.0% vs 8.3%) | 0 | 6 (solved 0.0% vs 9.8%) | 1 (solved 0.0% vs 7.8%) |
| continuation_nudge | 32 (solved 6.2% vs 8.2%) | 44 (solved 9.1% vs 9.4%) | 18 (solved 5.6% vs 9.9%) | 12 (solved 0.0% vs 8.5%) |
| no_submit | 12 (solved 16.7% vs 6.8%) | 0 | 6 (solved 0.0% vs 9.8%) | 1 (solved 0.0% vs 7.8%) |
| output_cap_hit | 1 (solved 0.0% vs 7.8%) | 2 (solved 0.0% vs 9.4%) | 1 (solved 0.0% vs 9.4%) | 3 (solved 0.0% vs 7.9%) |
| post_submit_calls | 114 (solved 7.0% vs 13.3%) | 125 (solved 9.6% vs 0.0%) | 117 (solved 10.3% vs 0.0%) | 121 (solved 7.4% vs 12.5%) |
| repeated_read | 34 (solved 5.9% vs 8.4%) | 40 (solved 10.0% vs 9.0%) | 9 (solved 0.0% vs 10.0%) | 22 (solved 0.0% vs 9.3%) |
| submit_without_edit | 1 (solved 0.0% vs 7.8%) | 1 (solved 0.0% vs 9.4%) | 1 (solved 0.0% vs 9.4%) | 1 (solved 0.0% vs 7.8%) |
| thinking_burst | 49 (solved 2.0% vs 11.2%) | 50 (solved 4.0% vs 12.7%) | 45 (solved 4.4% vs 11.9%) | 56 (solved 3.6% vs 11.0%) |
| tool_error | 40 (solved 0.0% vs 11.2%) | 46 (solved 4.3% vs 12.0%) | 39 (solved 2.6% vs 12.2%) | 49 (solved 2.0% vs 11.2%) |
| unscoped_truncated_read | 107 (solved 6.5% vs 13.6%) | 115 (solved 7.8% vs 21.4%) | 70 (solved 10.0% vs 8.5%) | 84 (solved 6.0% vs 11.1%) |
| unverified_submit | 18 (solved 5.6% vs 8.1%) | 28 (solved 3.6% vs 10.9%) | 17 (solved 0.0% vs 10.7%) | 25 (solved 0.0% vs 9.6%) |
