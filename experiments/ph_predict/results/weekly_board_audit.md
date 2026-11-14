# Audit: weekly board gain from inserting the next day's 00:05 line-up

Paired (b) - (a), share of the board's top k in the true weekly top k, mean over board days; week bootstrap 95%.

| variant | weeks | board days | top 3 | top 5 | top 10 |
|---|---|---|---|---|---|
| V0_published | 29 | 203 | +2.5 [+1.6, +3.3] (49.4 -> 51.9) | +5.2 [+4.4, +6.1] (54.4 -> 59.6) | +7.3 [+6.6, +8.2] (51.3 -> 58.7) |
| V1_truth_file | 28 | 196 | +2.4 [+1.5, +3.2] (49.5 -> 51.9) | +5.2 [+4.4, +6.1] (54.5 -> 59.7) | +7.3 [+6.5, +8.3] (51.1 -> 58.5) |
| V2_strict_calibration | 28 | 196 | +2.6 [+1.7, +3.4] (49.5 -> 52.0) | +5.1 [+4.2, +6.0] (54.5 -> 59.6) | +7.1 [+6.2, +8.0] (51.1 -> 58.2) |
| V3_no_median_fill | 28 | 196 | +2.6 [+1.7, +3.4] (49.5 -> 52.0) | +5.1 [+4.2, +6.0] (54.5 -> 59.6) | +7.1 [+6.2, +8.0] (51.1 -> 58.2) |

Excluding Mondays (the (a) board is empty on Monday, so it scores 0 by construction), V2: top 3 +1.2 [+0.4, +2.0], top 5 +3.1 [+2.3, +3.9], top 10 +5.5 [+4.6, +6.4].
By weekday (V2, top 3 / 5 / 10): Mon +10.7/+17.1/+16.8, Tue +8.3/+15.0/+16.8, Wed +1.2/+2.1/+9.6, Thu -1.2/+1.4/+5.0, Fri -1.2/0.0/+1.4, Sat 0.0/0.0/+0.7, Sun 0.0/0.0/-0.7.

Leak checks: predictions = stored arm-2 month-forward backtest (exact match, max abs diff 2e-15; trained on months < D's month);
V2/V3 calibration rows all dated before the week's Monday (asserted); inserted values are predictions, never the day's final
votes; (a) and (b) are paired on the same 196 board days. Week Apr 6 has no complete truth read in truth_weekly.json (28 weeks).
Remaining shared caveat: earlier days of the week enter both boards at stored final votes, not the votes at D's 00:05
(day-close reads are not held for Apr-Oct); this inflates both levels, not the paired difference by construction.
Published levels (a)/(b) top 3 were 49.9/52.4; re-derived 49.4/51.9 on today's warehouse votes; the difference is unchanged (+2.5).

Verdict: the number stands. Suggested wording: +2.6 / +5.1 / +7.1 (28 weeks, truth file, calibration fitted before each week),
most of it on Monday and Tuesday; +1.2 / +3.1 / +5.5 without Mondays.
