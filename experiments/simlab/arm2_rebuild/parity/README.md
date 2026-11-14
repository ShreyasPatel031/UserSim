# Live vs backtest input parity for arm 2 (parity_check.py), 15 nights: Oct 25 – Nov 12, excluding Nov 5–7 and Oct 29
Oct 29 first failed on 2 repeated live ids (fixed in parity_check; re-run included, 16 nights total in parity_summary.json). Rows: 374 appear in both inputs, 2 only live, 19 only backtest.
Ranking effect: swapping in all live columns at once changes, on average, 0.13 / 0.20 / 0.27 of the top 3 / 5 / 10 per night (bootstrap 95% CI upper bounds 0.33 / 0.40 / 0.60). The worst night changes 1 / 1 / 2.
Unexpected differing columns: n_makers, n_media, desc_len, tagline_len, and rarely has_video, n_topics, name_len and hunter_age_d. About 4% of rows differ, because the backtest reads the final list, which carries post-launch edits. The dayrank columns differ further on about half the rows because the lineups differ (the expected ph_day_n_launches column differs on 7 nights).
Details: parity_summary.json; per-night JSON 2026-*.json.
