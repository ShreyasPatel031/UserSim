# Learning curve of the comment-based 00:30 lines over 2026 history, and the 2025-comments what-if

Test days 2026-04-01..2026-10-24 (comment dumps end Oct 25). Paired 95% bootstrap over days. Diffs are vs the same line with all history.

## (1) Ridge lines on the clean_nosite OOF base (only the blend weights see N days; the base model is unchanged)

| line | N days | top 3 | top 5 | top 10 | diff vs all (t3 / t5 / t10) |
|---|---|---|---|---|---|
| mrep | 60 | 63.0 | 69.4 | 75.7 | -0.0 [-0.5, +0.5] / -0.1 [-0.5, +0.2] / -0.4 [-0.8, -0.1] |
| mrep | 100 | 62.6 | 69.7 | 76.0 | -0.3 [-0.8, +0.0] / +0.2 [+0.0, +0.5] / -0.1 [-0.3, +0.1] |
| mrep | 150 | 62.8 | 69.5 | 76.0 | -0.2 [-0.5, +0.0] / +0.0 [+0.0, +0.0] / -0.1 [-0.2, +0.0] |
| mrep | all | 63.0 | 69.5 | 76.1 | - |
| clean+th | 60 | 59.7 | 68.9 | 75.0 | -0.2 [-0.8, +0.3] / +0.0 [-0.4, +0.4] / +0.0 [-0.1, +0.1] |
| clean+th | 100 | 60.1 | 68.9 | 75.0 | +0.2 [+0.0, +0.5] / +0.0 [+0.0, +0.0] / -0.0 [-0.1, +0.0] |
| clean+th | 150 | 59.7 | 68.8 | 75.0 | -0.2 [-0.5, +0.0] / -0.1 [-0.3, +0.0] / -0.0 [-0.1, +0.0] |
| clean+th | all | 59.9 | 68.9 | 75.0 | - |

## (2) LightGBM arm-2 model with the 00:30 comment inputs inside (th_n_pre, distinct commenters, total comments, hunter replies)

207 days, 4874 launches with every run present. Reference = mrep (LODO ridge on the clean_nosite base, as published at 00:30): 63.1 / 69.5 / 76.0; clean+th_n_pre 60.1 / 68.8 / 75.2.

| model | N 2026 days | top 3 | top 5 | top 10 | diff vs same model, all days (t3 / t5 / t10) | diff vs mrep (t3 / t5 / t10) |
|---|---|---|---|---|---|---|
| 2026 rows only, comments inside | 60 | 62.2 | 68.0 | 74.8 | -0.6 [-3.2, +1.8] / -1.9 [-3.6, -0.3] / -1.0 [-1.9, -0.2] | -1.0 [-3.5, +1.6] / -1.4 [-3.3, +0.4] / -1.2 [-2.2, -0.2] |
| 2026 rows only, comments inside | 100 | 61.0 | 68.8 | 76.0 | -1.8 [-3.7, -0.0] / -1.2 [-2.4, +0.1] / +0.2 [-0.5, +0.9] | -2.1 [-4.5, +0.3] / -0.7 [-2.3, +1.1] / +0.0 [-0.8, +0.8] |
| 2026 rows only, comments inside | 150 | 61.8 | 69.8 | 75.7 | -1.0 [-2.6, +0.6] / -0.2 [-1.2, +0.8] / -0.1 [-0.6, +0.5] | -1.3 [-3.4, +0.8] / +0.3 [-1.4, +1.9] / -0.3 [-1.0, +0.4] |
| 2026 rows only, comments inside | all | 62.8 | 70.0 | 75.8 | - | -0.3 [-2.4, +1.8] / +0.5 [-1.1, +2.1] / -0.2 [-0.9, +0.5] |
| + 2025 rows (comments missing) | 60 | 61.5 | 67.9 | 75.0 | -2.4 [-4.8, +0.0] / -1.3 [-3.0, +0.5] / -1.4 [-2.3, -0.6] | -1.6 [-4.0, +0.8] / -1.5 [-3.3, +0.2] / -1.0 [-1.9, +0.0] |
| + 2025 rows (comments missing) | 100 | 60.9 | 68.5 | 75.6 | -3.1 [-5.6, -0.5] / -0.7 [-2.1, +0.9] / -0.9 [-1.6, -0.1] | -2.3 [-4.8, +0.3] / -1.0 [-2.7, +0.9] / -0.4 [-1.3, +0.5] |
| + 2025 rows (comments missing) | 150 | 60.4 | 69.4 | 75.8 | -3.5 [-5.8, -1.3] / +0.2 [-1.4, +1.8] / -0.7 [-1.5, +0.1] | -2.7 [-5.3, -0.2] / -0.1 [-1.9, +1.8] / -0.2 [-1.0, +0.7] |
| + 2025 rows (comments missing) | all | 63.9 | 69.2 | 76.5 | - | +0.8 [-1.6, +3.2] / -0.3 [-2.0, +1.4] / +0.5 [-0.3, +1.3] |

Log-days fit (pure_th, within-day, days where N binds; mean history at 'all' = 179 days): per doubling of 2026 history +0.4 [-1.4, +2.1] / +1.0 [-0.0, +2.0] / +0.5 [-0.0, +1.1] (top 3 / 5 / 10).
Extrapolated gain from +365 days of comment-bearing rows (1.61 doublings): +0.6 [-2.2, +3.4] / +1.6 [-0.1, +3.2] / +0.9 [-0.0, +1.8].

## Answer: what 2025 comments would buy at 00:30

- The ridge blend (mrep, clean+th_n_pre) is flat in history length (all diffs within +-0.4): more days do not change its 5 weights.
- The model with comments inside (2026 rows only) gains +0.4 / +1.0 / +0.5 per doubling of 2026 history (top 3 / 5 / 10).
  Extrapolated to +365 days of comment-bearing rows: **+0.6 [-2.2, +3.4] / +1.6 [-0.1, +3.2] / +0.9 [-0.0, +1.8]**.
  All three intervals touch 0, so the top-3 gain is not established; top 5/10 lean positive.
- Direct what-if we can run now: arm 2 with comment inputs on 2026 rows and missing on 2025 rows (both_th, all) vs mrep: +0.8 [-1.6, +3.2] / -0.3 [-2.0, +1.4] / +0.5 [-0.3, +1.3]. Not a rule-5 deploy.
  The earlier "+0.8 [-1.1, +2.8] arm-2 base" run (maker_replies.py MR_BASE) was different: the LightGBM never saw comments; comments entered only
  through the ridge layer, fit on 2026 rows. This run is the first with the comment inputs inside the model.
- 2025 comments pull (created_at + author for every comment, all pages, no cap): 4,923 launches in the 2025 lists, 137,349 comments (median 15,
  p90 65, p99 185 per launch). Query: comments(first:20) with nested replies(first:20); 49% of comments are top-level in the 2026 dumps.
  Calls ~6,550 (one per launch plus top-level pages); upper bound ~9,500 if replies also need their own pages.
  Complexity per call is unmeasured (a nested 20x20 page is far heavier than a list page); at the pull's 3,125-point reserve this is days, not hours, of spare budget.
