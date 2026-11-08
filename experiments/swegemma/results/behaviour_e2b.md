| metric | base_e2b | window_e2b | full_e2b |
|---|---|---|---|
| edit_file succeeded (calls) | 85/280 (30%) | 135/583 (23%) p=0.025 * | 124/475 (26%) p=0.208 |
| read_file with a line range (calls) | 39/416 (9%) | 71/467 (15%) p=0.010 * | 273/680 (40%) p=0.000 ** |
| runs with an unscoped truncated read | 109/129 (84%) | 108/129 (84%) p=1.000 | 102/129 (79%) p=0.333 |
| runs with a repeated read | 55/129 (43%) | 59/129 (46%) p=0.707 | 67/129 (52%) p=0.170 |
| runs with a context overflow | 37/129 (29%) | 0/129 (0%) p=0.000 ** | 0/129 (0%) p=0.000 ** |
| runs with no submission | 39/129 (30%) | 11/129 (9%) p=0.000 ** | 3/129 (2%) p=0.000 ** |
| runs with a nudge | 44/129 (34%) | 47/129 (36%) p=0.794 | 69/129 (53%) p=0.003 ** |
| runs that executed code | 68/129 (53%) | 79/129 (61%) p=0.209 | 95/129 (74%) p=0.001 ** |
| runs resolved | 6/129 (5%) | 9/129 (7%) p=0.596 | 7/129 (5%) p=1.000 |

p-values: two-sided Fisher exact test vs the first run; * p<0.05, ** p<0.01
