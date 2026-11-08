| metric | base_e4b | base_e4b_r2 |
|---|---|---|
| edit_file succeeded (calls) | 181/290 (62%) | 200/317 (63%) p=0.867 |
| read_file with a line range (calls) | 286/606 (47%) | 265/630 (42%) p=0.076 |
| runs with an unscoped truncated read | 107/129 (83%) | 111/129 (86%) p=0.606 |
| runs with a repeated read | 34/129 (26%) | 39/129 (30%) p=0.581 |
| runs with a context overflow | 9/129 (7%) | 16/129 (12%) p=0.206 |
| runs with no submission | 12/129 (9%) | 16/129 (12%) p=0.549 |
| runs with a nudge | 32/129 (25%) | 32/129 (25%) p=1.000 |
| runs that executed code | 106/129 (82%) | 109/129 (84%) p=0.739 |
| runs resolved | 10/129 (8%) | 9/129 (7%) p=1.000 |

p-values: two-sided Fisher exact test vs the first run; * p<0.05, ** p<0.01
