# Ignored-field inputs at 00:30 / 01:00 (214 days Apr-Oct, 5033 launches; LODO ridge, paired day bootstrap)

Commenter follower counts matched for 92.2% of non-team comment rows (store_v3 pull-time values: upper bound, see docstring).

## P030 (00:30 PT)

| variant | top 3 | top 5 | top 10 | diff t3 / t5 / t10 (95%) |
|---|---|---|---|---|
| base: clean + th_n_pre + distinct commenters | 61.2 | 69.9 | 76.4 | - |
| + non-team replies | 61.4 | 69.7 | 76.4 | +0.2 [+0.0, +0.5] / -0.2 [-0.5, +0.0] / +0.0 [+0.0, +0.0] |
| + all replies | 61.5 | 70.5 | 76.3 | +0.3 [-0.6, +1.2] / +0.6 [-0.2, +1.3] / -0.0 [-0.3, +0.2] |
| + commenter followers (sum) | 61.1 | 69.7 | 76.4 | -0.2 [-0.6, +0.3] / -0.2 [-0.6, +0.2] / +0.0 [+0.0, +0.1] |
| + commenter followers (median) | 61.2 | 69.7 | 76.4 | +0.0 [-0.6, +0.6] / -0.2 [-0.6, +0.2] / +0.0 [+0.0, +0.1] |
| + commenters with >= 1k followers | 60.6 | 70.3 | 76.5 | -0.6 [-1.7, +0.5] / +0.4 [-0.2, +1.0] / +0.1 [-0.1, +0.4] |
| + replies + followers (sum) | 61.2 | 69.7 | 76.4 | +0.0 [-0.6, +0.6] / -0.2 [-0.6, +0.2] / +0.0 [+0.0, +0.1] |

## P1 (01:00 PT)

| variant | top 3 | top 5 | top 10 | diff t3 / t5 / t10 (95%) |
|---|---|---|---|---|
| base: clean + th_n_pre + distinct commenters | 61.7 | 70.3 | 76.4 | - |
| + non-team replies | 62.3 | 69.9 | 76.5 | +0.6 [-0.2, +1.6] / -0.4 [-0.9, +0.1] / +0.1 [-0.1, +0.3] |
| + all replies | 62.8 | 71.2 | 76.3 | +1.1 [-0.3, +2.5] / +0.9 [+0.2, +1.7] / -0.1 [-0.6, +0.3] |
| + commenter followers (sum) | 62.0 | 70.7 | 76.6 | +0.3 [-0.5, +1.2] / +0.4 [-0.2, +0.9] / +0.1 [-0.0, +0.4] |
| + commenter followers (median) | 61.8 | 70.3 | 76.4 | +0.2 [-0.3, +0.6] / +0.0 [-0.5, +0.5] / +0.0 [-0.1, +0.1] |
| + commenters with >= 1k followers | 62.5 | 70.7 | 76.7 | +0.8 [-0.5, +2.0] / +0.5 [-0.2, +1.1] / +0.2 [-0.0, +0.5] |
| + replies + followers (sum) | 62.8 | 70.4 | 76.6 | +1.1 [-0.0, +2.3] / +0.1 [-0.6, +0.7] / +0.1 [-0.0, +0.4] |

reviewsRating / reviewsCount at 00:05: not testable on a backtest (13 days of pre-launch review reads; see docstring); logged forward only.
