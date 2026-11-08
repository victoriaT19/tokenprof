| metric | base_e4b | window_e4b | guided_e4b | full_e4b |
|---|---|---|---|---|
| edit_file succeeded (calls) | 181/290 (62%) | 184/317 (58%) p=0.282 | 178/290 (61%) p=0.864 | 204/386 (53%) p=0.015 * |
| read_file with a line range (calls) | 286/606 (47%) | 298/649 (46%) p=0.651 | 307/484 (63%) p=0.000 ** | 326/556 (59%) p=0.000 ** |
| runs with an unscoped truncated read | 107/129 (83%) | 115/129 (89%) p=0.208 | 70/129 (54%) p=0.000 ** | 84/129 (65%) p=0.002 ** |
| runs with a repeated read | 34/129 (26%) | 40/129 (31%) p=0.491 | 9/129 (7%) p=0.000 ** | 22/129 (17%) p=0.096 |
| runs with a context overflow | 9/129 (7%) | 0/129 (0%) p=0.003 ** | 6/129 (5%) p=0.596 | 1/129 (1%) p=0.019 * |
| runs with no submission | 12/129 (9%) | 0/129 (0%) p=0.000 ** | 6/129 (5%) p=0.221 | 1/129 (1%) p=0.003 ** |
| runs with a nudge | 32/129 (25%) | 44/129 (34%) p=0.133 | 18/129 (14%) p=0.040 * | 12/129 (9%) p=0.001 ** |
| runs that executed code | 106/129 (82%) | 111/129 (86%) p=0.496 | 113/129 (88%) p=0.297 | 109/129 (84%) p=0.739 |
| runs resolved | 10/129 (8%) | 12/129 (9%) p=0.824 | 12/129 (9%) p=0.824 | 10/129 (8%) p=1.000 |

p-values: two-sided Fisher exact test vs the first run; * p<0.05, ** p<0.01
