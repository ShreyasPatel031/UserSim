# Arm 3 - arm 2, pre-registered (orchestrator 20:31Z Nov 14). arm3_vs_arm2.py + arm3_vs_arm2_score.py

Registered before running: primary top 5, secondary top 10, tertiary top 3. 20 seeds per arm, rows sorted by (day, id), deterministic
row-wise LightGBM, TW.P0. Arm 3 = arm-2 inputs + E5 block A (same-day line-up, bge-small) + B / C (feature table arm3_dedup, strong names);
B / C non-null on 100% of test rows in both years. Truth: final daily rank <= k on days with >= 10 ranked launches. Paired day bootstrap 10,000.

| test | days | arm 2 (3/5/10) | arm 3 (3/5/10) | top 5 (primary) | top 10 | top 3 |
|---|---|---|---|---|---|---|
| 2026 Apr-Oct, month-forward (train 2025 + 2026 < m), warehouse truth | 183 | 57.4 / 64.8 / 76.6 | 56.3 / 66.3 / 77.6 | +1.5 [+0.2, +3.0] | +1.0 [+0.1, +1.9] | -1.1 [-3.1, +0.7] |
| 2025 Mar-Dec, month-forward (train 2025 < m) | 204 | 51.8 / 61.9 / 78.9 | 53.8 / 63.6 / 79.9 | +1.8 [+0.4, +3.1] | +1.0 [+0.1, +1.9] | +2.0 [-0.3, +4.4] |

Verdict: top 5 and top 10 clear 0 in BOTH years. Top 3 does not clear 0 in either year: 2026 points negative (-1.1), 2025 positive (+2.0).
2026 has 183 days here, not E5's 184: warehouse truth lacks May 10's after-close ranks. The 2026 arm-2 level is 57.4 / 64.8 / 76.6, not 58.0 / 65.2 / 76.5:
20 deterministic seeds vs 5, and the same truth difference. The comparison is paired on the same rows and truth, so it is unaffected.
