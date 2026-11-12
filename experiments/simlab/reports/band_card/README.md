# The /try launch card's numbers, validated out of sample (orchestrator 08:56Z Nov 12, task B)

Script: band_card.py.
- Band: the page band recipe (d_both, LLM read), trained on launches up to Aug 31.
- Test: the 856 = 726 held + 130 fresh.
- Controls: CAT (deciles of the category mean) and CONST (one band for all).
- Coverage is the share of launches inside the band, with a 95% bootstrap. Nominal is 80% unless stated.

## As served today

| check | page band | CAT | CONST |
|---|---|---|---|
| Spearman of score with final votes | **0.310** (vs CAT +0.137 [+0.071, +0.199]) | 0.173 | 0 |
| rank band p10–p90, all | 83.5 [81.0, 86.1] | 80.6 | 83.9 |
| … small days (≤ 20 launches) / mid / large (> 31) | **91.0 / 93.2 / 76.3** | 88.0 / 91.8 / 72.7 | 92.2 / 95.5 / 75.5 |
| … fresh 130 | 85.4 | 80.8 | 85.4 |
| … top / bottom predicted quartile | 87.4 / 82.9 | 80.6 / 78.3 | 85.6 / 82.9 |
| votes band p10–p90, all | **66.1** [63.0, 69.3] | 67.1 | 67.4 |
| … small / mid / large days | 94.0 / 80.5 / 49.5 | | |
| "top-3 chance" predicted vs actual | 15.0 vs 12.3 (small days 21.6, large 7.2) | | 15.1 vs 12.3 |
| "top-10 chance" predicted vs actual | **43.3 vs 33.2** (small days 61.1, large 18.3) | | 43.3 vs 33.2 |

At the extremes the band is honest: top quartile 87%, bottom 83% coverage. Within the bottom quartile the top-10 chance is
overstated: 34% predicted vs 19% actual.

The failures come from what the card does not know: the day's line-up size. Ranks, votes and top-k chances all scale with it.

## Fixes, same out-of-sample test

| fix | all | small / mid / large days | fresh | top / bottom quartile |
|---|---|---|---|---|
| percentile-of-day band (rank ÷ line-up, p10–p90) | **79.8** [77.0, 82.5] | 81.4 / 80.9 / 78.7 | 82.3 | 79.3 / 84.8 |
| share of the day's votes, p15–p85 | **77.6** | 74.3 / 87.7 / 74.0 | 83.8 | 80.6 / 76.5 |
| P(top 10% of the day), predicted vs actual | **8.2 vs 9.2** (Brier 0.0820 vs const 0.0839) | 8.3/7.2 · 8.7/10.9 · 8.0/9.2 | 8.7 / 10.0 | 16.6/18.5 · 2.9/4.1 |
| votes band p5–p95 (rejected) | 81.0 | 98.2 / 94.1 / 68.7 | | |
| votes band from the last 60 days (rejected) | 48.4 | | | |

## Export

Coverage was off by more than 5 points, so the corrected banding is exported:
- File: gs://usersim-bakeoff-347838016394/tmp/e5/website/launch_band_card_v2.json (band_card_export.py). Nothing was overwritten.
- It is keyed to the served v1 deciles; the cuts are identical.
- Per decile it carries:
  - the percentile-of-day band, plus ranks for a typical day (median of the last 8 weeks);
  - the share-of-day-votes band;
  - P(top 10% of the day);
  - the top-3 and top-10 chances per day-size bucket.
