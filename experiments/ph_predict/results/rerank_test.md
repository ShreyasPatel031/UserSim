# Re-rank test: keep published top positions, re-order the rest by a readable early-activity score

Published line = mrep LODO (P030 hunter-only replies; P1 full-team replies). Re-rank score = non-negative ridge on z(th_n_pre), z(distinct non-hunter commenters <= T), z(total comments <= T), z(hunter-only replies <= T); weights fit month-forward on earlier months only (April keeps the published order, diff 0). Paired bootstrap 4000; 95% intervals.

## P030 (00:30 PT), 214 days; published (mrep) top 3/5/10 = 63.1 / 69.3 / 76.0

| variant | days | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |
|---|---|---|---|---|---|---|---|
| keep 1-3, re-order 4-15 | all | 63.1 | 65.5 | 71.5 | +0.0 [+0.0, +0.0] | -3.8 [-5.6, -2.1] | -4.5 [-5.6, -3.4] |
| keep 1-3, re-order 4-15 | last 107 | 63.9 | 64.5 | 72.0 | +0.0 [+0.0, +0.0] | -5.0 [-7.9, -2.2] | -5.9 [-7.7, -4.0] |
| keep 1, re-order 2-15 | all | 57.0 | 63.2 | 71.6 | -6.1 [-9.0, -3.3] | -6.2 [-8.1, -4.2] | -4.4 [-5.6, -3.3] |
| keep 1, re-order 2-15 | last 107 | 56.1 | 61.3 | 72.2 | -7.8 [-11.8, -3.7] | -8.2 [-11.2, -5.0] | -5.6 [-7.4, -3.8] |

Month-forward weights for the last month (2026-10): z_npre 0.207, z_nu 0.405, z_nc 0.011, z_mrep_h 0.000

Rule 5 check P030 keep 3: does not qualify (top 5 lo -5.6, top 10 lo -5.6, top 3 +0.0 [+0.0, +0.0])
Rule 5 check P030 keep 1: does not qualify (top 5 lo -8.1, top 10 lo -5.6, top 3 -6.1 [-9.0, -3.3])

## P1 (01:00 PT), 214 days; published (mrep) top 3/5/10 = 63.6 / 71.6 / 76.6

| variant | days | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |
|---|---|---|---|---|---|---|---|
| keep 1-3, re-order 4-15 | all | 63.6 | 66.6 | 71.9 | +0.0 [+0.0, +0.0] | -5.0 [-6.8, -3.2] | -4.7 [-5.9, -3.6] |
| keep 1-3, re-order 4-15 | last 107 | 63.6 | 65.0 | 72.4 | +0.0 [+0.0, +0.0] | -6.5 [-9.3, -3.7] | -6.3 [-8.0, -4.5] |
| keep 1, re-order 2-15 | all | 57.6 | 64.3 | 71.9 | -5.9 [-8.9, -3.0] | -7.3 [-9.4, -5.2] | -4.8 [-6.0, -3.6] |
| keep 1, re-order 2-15 | last 107 | 55.8 | 61.5 | 72.1 | -7.8 [-11.8, -3.4] | -10.1 [-13.3, -6.9] | -6.6 [-8.5, -4.9] |

Month-forward weights for the last month (2026-10): z_npre 0.232, z_nu 0.381, z_nc 0.068, z_mrep_h 0.000

Rule 5 check P1 keep 3: does not qualify (top 5 lo -6.8, top 10 lo -5.9, top 3 +0.0 [+0.0, +0.0])
Rule 5 check P1 keep 1: does not qualify (top 5 lo -9.4, top 10 lo -6.0, top 3 -5.9 [-8.9, -3.0])

## Verdict

No variant qualifies under rule 5; nothing deployed. Re-ordering positions 4-15 by early activity alone loses 4-5 points of top 5 and top 10 at both cuts (intervals well below 0, worse on the last 107 days). The activity-only score drops the model prior (clean_nosite, the largest mrep weight at 0.54-0.56), and for positions 4-15 that prior carries most of the signal. Re-ordering 2-15 also costs about 6 points of top 3. clean_nosite_tb (the reference point) is not the published 00:30/01:00 line, and the comparison is paired against mrep, which already blends the same activity inputs with the prior.
