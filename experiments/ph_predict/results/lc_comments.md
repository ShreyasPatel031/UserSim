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

