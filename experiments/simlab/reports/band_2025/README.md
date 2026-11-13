# Description-only rank band with 2025 training rows (orchestrator 11:33Z Nov 13): null, no model change

Script: band_2025.py. It uses the deployed product-only ridge recipe, month-forward. The 2025 rows are 5,067 launches with a dailyRank over 350 days. Median launches per day: 13 in 2025 against 19 in 2026.

**Targets.** Day sizes differ, so the target needs care across years:
- Y_LN = ln(1+votes), the deployed target. 2025 votes are counts as of fetch, with ranks frozen.
- Y_PCT = within-day rank percentile, 1 − (rank − 0.5) / n. This is comparable across years.
- Y_ZLN = within-day z of ln votes.

Test: pooled Spearman with final rank, on the same 856 launches (Sep – Nov) and the 130 most recent.

| arm | 856 | Δ vs current | 130 most recent | Δ | 80% band coverage / width |
|---|---|---|---|---|---|
| A0 2026, ln votes (current) | 0.353 [0.293, 0.411] | – | 0.417 | – | 75.5% / 72.6 |
| A1 2026, percentile | 0.274 | −0.079 [−0.117, −0.042] | 0.429 | +0.012 | 76.2 / 72.5 |
| A2 2025+2026, percentile | 0.275 | −0.078 [−0.120, −0.037] | 0.414 | −0.003 | 77.5 / 73.5 |
| A3 2025+2026, within-day z ln votes | 0.277 | −0.076 | 0.403 | −0.014 | 77.1 / 73.9 |
| **A4 2025+2026, ln votes** | **0.356** | **+0.003 [−0.027, +0.036]** | 0.367 | −0.050 [−0.126, +0.026] | 75.0 / 73.7 |

Within-day targets lose about 0.08 pooled even without 2025 (A1). The pooled metric rewards the absolute vote level that ln(votes) carries. With the same target (A4), adding 2025 changes nothing on the 856 and is slightly worse on the 130 most recent. Calibration is unchanged.

**Beyond the clean 00:05 base** (234 days, within-day partial correlation; month-forward ridge on 193 days):
- The current text ridge (A0) has partial +0.014 [−0.017, +0.045]. A4 has +0.024 [−0.009, +0.056]. A3 (within-day z, both years) has **+0.046 [+0.016, +0.079]**.
- Top 3 / 5 / 10: clean + A4 − clean + A0 = −1.0 [−1.9, −0.3] / −0.6 / −0.1. Clean + A0 + A4 − clean + A0 = −0.7 / −0.4 / 0.0.

**Verdict.** No gain for the band, so the model file and claims stay as they are. Beyond the clean base, the both-years within-day text score has a small positive partial, but it adds nothing to top-k. There is nothing to hand to the PH agent.
