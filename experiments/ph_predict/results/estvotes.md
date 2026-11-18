# Hidden votes bracketed by the weekly rank before the reveal (Nov 12)

estvotes.py works from the latest snapshot fetched by T. Today's launches carry weekly_rank_at_fetch while their votes
are hidden. The week's earlier-day launches, sorted by votes, bracket each one, and the estimate is the geometric mean of
the two bracketing vote counts (top edge ×1.25, bottom edge ÷2). The earlier launches' votes come from the previous day's
23:50 PT monthly_reread when held, else their day-end votes. Mondays have no estimate.

**Validation at the reveal:** estimate at the last pre-reveal snapshot (03:45 PT) vs real votes at the reveal snapshot.

| day | earlier launches | Spearman | median abs log error | top-3 overlap |
|---|---|---|---|---|
| Nov 4 | 56 | 0.936 | 0.09 | 100 |
| Nov 8 | 170 | 0.923 | 0.14 | 67 |
| Nov 10 | 25 (Tuesday: Monday only) | 0.687 | 0.49 | 100 |
| Nov 11 | 75 | 0.965 | 0.06 | 100 |

The magnitudes are right to about 6–15% when the week already has enough launches. They are coarse early in the week.
"Inside the bracket" is low (0–26%; 90% on Nov 10) because day-end votes under-state the earlier launches' current
votes. The previous night's 23:50 read (held from Nov 11) fixes that going forward.

**As a ranking:** the estimate's order is the weekly-rank order, which is the same as the API's pre-reveal daily rank,
so it adds no new ordering. A velocity projection (estimate + 1-hour growth × hours to reveal + 2) hurts: at P4,
11 / 27 / 67 vs 56 / 80 / 80 for the plain estimate (3 days). The 1-hour change in a bracketed estimate is too
coarse to extrapolate.

**Live from Nov 12:** P files carry est_votes, est_vel60, weekly_rank and pred_rank_estvotes (estimate order) as extra
columns; pred_rank is unchanged. Use: an absolute vote level for today's launches before the reveal (gaps and near-ties,
the mid-day weekly call), not a new ranking.

**monthlyRank:** the raw 15-min API snapshots (snapshots/<ts>_api.jsonl) do carry monthlyRank. It was non-null for
26/26 rows pre-reveal on Nov 11 but only 5/53 on Nov 10. posts_ts does not store it. A finer bracket (the whole month,
Mondays included) needs monthly_rank_at_fetch in posts_ts, or a reader over the raw snapshots.
