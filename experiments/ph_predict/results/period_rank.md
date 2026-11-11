# Product Hunt's weekly / monthly rank: votes, frozen at the period end

## month (9 periods, month-forward)

| scorer | top 3 | top 5 | top 10 |
|---|---|---|---|
| votes | 88.9 [78, 100] | 82.2 [76, 89] | 84.4 [79, 91] |
| learned | 81.5 [59, 96] | 80.0 [73, 87] | 85.6 [79, 92] |
| learned_minus_votes | -7.4 [-26, +7] | -2.2 [-9, +4] | +1.1 [-2, +4] |

## week (39 periods, month-forward)

| scorer | top 3 | top 5 | top 10 |
|---|---|---|---|
| votes | 78.6 [72, 85] | 85.1 [80, 90] | 87.9 [85, 90] |
| learned | 77.8 [69, 86] | 84.1 [78, 89] | 88.2 [86, 91] |
| learned_minus_votes | -0.9 [-8, +6] | -1.0 [-5, +3] | +0.3 [-2, +3] |

## Reading

**Mechanism.** PH's weekly and monthly ranks are votes frozen at (or around) the period end.
- Nov 11 live read: monthlyRank vs current votes Spearman 0.9993. The top-3 disagreement (67 / 80 / 90) comes from recent launches ranked below where their current votes would put them: a lag, not another signal.
- Warehouse: final monthly rank vs final votes is 80 / 82 / 85 over 10 months.
- Among inverted top-15 pairs, the higher-vote but lower-ranked launch came later in the month (day 17.3 vs 12.9). Our "final" votes were read weeks later (mostly Oct 28), after late-month launches kept growing.

**Learning it from held data does not work** (table above): learned − votes is −7.4 [−26, +7] top 3 for months and −0.9 [−8, +6] for weeks. The post-period growth is not observable in held data.

**The live fix is the right input, not a model.** Rank by votes read at the period end. Data Feeder's daily 23:50 PT monthly_reread provides exactly that:
- monthly_live's "votes" line, at the last day of the month, is the month-end call;
- weekly_live gains a "reread" point: the week's launches by votes in each day's 23:50 PT read. Sunday's file is the week-end call. monthly_live writes it and weekly_live score() scores it.

**Next check (needs a second read file):** does today's running monthlyRank equal the order of votes in an earlier read (e.g. yesterday's 23:50 PT)? That would give PH's update lag.
