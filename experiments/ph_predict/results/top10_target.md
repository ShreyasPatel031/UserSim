# Top 10 / top 5 at 00:05 (214 days Apr-Oct)

Missed in (final top 10, clean rank 11+): 433 launches; clean-rank distribution: 11-15: 263, 16-20: 86, 21-30: 67, 31+: 17
False in (clean 6-10, finished 11+): 330 launches

Standardized differences, day bootstrap 95%: missed-in vs other launches at clean rank 11-20; false-in vs clean 6-10 that stayed top 10

| feature | missed-in minus others (11-20) | false-in minus stayed (6-10) |
|---|---|---|
| clean | +0.00 [-0.04, +0.04] | +0.11 [+0.05, +0.18] |
| npre | +0.19 [+0.12, +0.25] | -0.23 [-0.34, -0.13] |
| hunts | +0.09 [+0.02, +0.15] | -0.11 [-0.21, +0.01] |
| ntopics | +0.16 [+0.06, +0.25] | +0.06 [-0.05, +0.17] |
| team | +0.03 [-0.01, +0.08] | -0.03 [-0.13, +0.08] |
| tag_len | +0.01 [-0.09, +0.10] | +0.10 [+0.00, +0.21] |
| desc_len | -0.03 [-0.11, +0.06] | +0.07 [-0.03, +0.17] |
| video | -0.06 [-0.16, +0.02] | +0.07 [-0.01, +0.16] |
| weekday | +0.16 [+0.03, +0.28] | -0.42 [-0.61, -0.22] |
| n_day | -0.03 [-0.07, +0.00] | +0.26 [+0.20, +0.31] |

| model | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |
|---|---|---|---|---|---|---|
| base: clean_nosite + th_n_pre (ridge) | 60.1 | 68.7 | 75.3 | - | - | - |
| P(t10) logit | 59.7 | 68.8 | 75.6 | -0.5 [-1.7, +0.8] | +0.1 [-0.8, +1.0] | +0.3 [-0.2, +0.9] |
| P(t5) logit | 59.3 | 68.7 | 74.8 | -0.8 [-1.7, +0.2] | +0.0 [-0.8, +0.7] | -0.5 [-1.0, -0.0] |
| P(t10) gbm | 56.1 | 67.4 | 74.9 | -4.0 [-6.5, -1.6] | -1.3 [-2.8, +0.2] | -0.4 [-1.0, +0.2] |
| P(t5) gbm | 56.7 | 68.1 | 74.5 | -3.4 [-5.3, -1.6] | -0.6 [-2.0, +0.7] | -0.7 [-1.4, -0.1] |
