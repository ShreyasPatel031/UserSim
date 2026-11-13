# Pre-launch commenter timing (214 days Apr-Oct, 5033 ranked launches; LODO)

Coverage: thread held (any comment row) 93.7% of launches; final top 10 96.6% vs 11+ 91.8%. Launches with any pre-launch outside commenter 20.1%.

Mean distinct commenters per launch by first-comment time (final top 10 vs 11+): >24h before 0.33 vs 0.03; 1-24h before 0.13 vs 0.03; last hour 0.02 vs 0.00; 00:01-00:05 0.05 vs 0.00; maker commented before launch 0.39 vs 0.60

| variant | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |
|---|---|---|---|---|---|---|
| clean_nosite + th_n_pre | 60.1 | 68.7 | 75.3 | - | - | - |
| + split a-d | 59.2 | 69.0 | 75.1 | -0.9 [-2.0, +0.2] | +0.3 [-0.6, +1.1] | -0.1 [-0.4, +0.1] |
| split a-d instead of th_n_pre | 59.0 | 69.0 | 75.2 | -1.1 [-2.3, +0.2] | +0.3 [-0.7, +1.2] | -0.1 [-0.4, +0.2] |
| + span | 61.2 | 68.8 | 75.3 | +1.1 [-0.0, +2.3] | +0.1 [-0.7, +0.8] | +0.0 [-0.2, +0.2] |
| + maker commented before launch | 60.9 | 69.1 | 74.3 | +0.8 [-0.3, +2.0] | +0.4 [-0.4, +1.2] | -0.9 [-1.5, -0.4] |
| + all | 61.1 | 69.0 | 74.7 | +0.9 [-0.5, +2.3] | +0.3 [-0.7, +1.2] | -0.6 [-1.3, +0.0] |

Full-fit ridge coefficients (clean, th_n_pre, a, b, c, d): +0.573, +0.059, +0.139, +0.066, +0.034, +0.053
