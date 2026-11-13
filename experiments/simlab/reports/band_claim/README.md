# Description-path band claim correction (orchestrator 02:36Z Nov 13)

**Site, claude/ph-website 2885d961.**
- claims.json try_e2e reads: spearman_ph 0.59, coverage_ph 0.89, 130 "fresh" launches.
- try_sim._input_note shows those figures. The page-path note also calls a pasted description "the stronger input (0.59)".

**Why that is in-sample.** results/web/launch_band.json trained_on covers 6,963 launches, 2026-01-01 to 2026-11-10, which includes all 130 launches (Oct 27 – Nov 10).

**Honest forward figures** (same recipe retrained month-forward: landing_retrieval base, rows in band_knn_rows.parquet):
- Pooled Spearman: 0.417 [0.265, 0.562] on the 130, and 0.353 [0.292, 0.412] on the 856 Sep–Nov launches.
- The file's own month-forward held-out within-day Spearman is 0.333 (222 days).
- 80% band coverage, cross-fit on the 856: 75.5%.
- Pasted minus page on the same launches: +0.075 [+0.006, +0.144] on the 856; +0.014 [−0.161, +0.176] on the 130.

**Corrected sentence:** "Scored from the description you pasted with a model trained on Product Hunt launch descriptions. Tested only on launches it had not seen: rank correlation 0.35 on 856 Sep–Nov launches (0.42 on the 130 most recent), real rank inside the band about 3 times in 4."
