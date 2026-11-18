# Live vs backtest parity of the 00:05 launch-model forecast (Nov 11)

**Setup.** Pipeline VM, read-only: parity_live.py and parity_swap.py. Same 14 live days: Oct 25 – Nov 4, Nov 8, 9, 10.
Nov 5–7 have no 00:05 snapshot. Daily top 3 / 5 / 10 against final daily rank; paired day-bootstrap 95% intervals.

| line | top 3 | top 5 | top 10 |
|---|---|---|---|
| live published (warehouse forecasts, launch_model) | 50.0 | 61.4 | 72.9 |
| replay A: today's code, trained on days < d, 00:05 inputs (data/today/<d>.json) | 57.1 | 64.3 | 77.9 |
| replay B: same model, same launches, later re-read inputs (data/days/<d>.json) = the backtest condition | 59.5 | 67.1 | 77.9 |
| replay B over the final ranked line-up (launches missing at 00:05 included) | 59.5 | 65.7 | 77.9 |

Paired differences:
- A − live: +7.1 [−5, +19] / +2.9 [−3, +10] / +5.0 [−1, +13]
- B − A (input drift after 00:05): +2.4 [−5, +10] / +2.9 [−3, +9] / 0.0 [−2, +2]
- B_all − B (line-up): 0 / −1.4 / 0

**1) Is the gap real on common days?** Mostly no.
- On these 14 days the backtest condition (B) scores 59.5 / 67 / 78, close to the honest offline 63 / 69 / 75 on 207 days.
- The live line scores 50 / 61 / 73 here.
- The "39 / 60 / 77" figure was a smaller and different day set. The per-day numbers swing by ±33 points in top 3 (3 launches), so n = 14 days cannot separate 7 points.
- None of the paired differences excludes 0.

**2) Attribution: swapping each changed input from its 00:05 value to its re-read value** (parity_swap.parquet).
- All changed inputs together: +2.4 top 3, −1.4 top 5, −0.7 top 10, all of it from the maker / maker-history columns. Every other single column moves nothing.
- Inputs that differ at 00:05:
  - ph_day_n_launches (line-up size): 58% of launches.
  - hist_maker_n: 12.5% of launches, mean |diff| 685. These are placeholder maker ids, "0" or empty, on 4–11 launches per day at 00:05, which match thousands of past launches.
  - ph_n_makers / x_n_makers_with_x: 8–9%.
  - Maker ages and history: 7.5%.
- **No backtest leak found among these** beyond the follower / follow / promo inputs that HONEST=1 already drops. The re-read values of the remaining inputs barely change the ranking.

**3) Line-up.**
- Final ranked launches missing from the 00:05 line-up: 1.0 per day on average (0–4).
- Top-10 finishers among them: 2 in 14 days, both on Oct 29. Top-3 finishers: 0.
- Scoring on the full line-up changes nothing (B_all = B). A 00:30 or 01:00 PT re-run would not move the score.

**4) Outcome.**
- (a) **Live fix 1: maker-id placeholders at 00:05.** Re-read the makers for launches whose maker ids are "0" or empty before forecasting, or treat them as missing instead of joining on "0". Expected gain about +2 top 3, not significant.
- (b) **The live line vs replay A gap (+7 / +3 / +5, n.s.)** is not explained by input values or the line-up. It comes from what the model was at the time:
  - code and filter changes deployed during the period (the HONEST=1 filter, llm_full drop);
  - training rows' values at the time;
  - seeds.
  Today's code on the same 00:05 inputs is the expected live level from now on.
- (c) **No downward correction of the honest backtest is warranted** by this check: B ≈ A + 2.

**Shadow.** I'll keep scoring live forward against A-style replays instead of adding a new deployed forecast.
