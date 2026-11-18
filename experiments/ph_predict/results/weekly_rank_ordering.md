# What the official weekly_rank / monthly_rank order by (held data, 14:00Z Nov 14)

Data: warehouse `launches` parts = every ranks-step read since Oct 28 (daily ~00:20 PT re-reads of the last 31 days: votes + weekly_rank +
monthly_rank at several ages; 37 parts, up to 17 reads per launch) + the Oct bulk read (one read for Apr-Sep). Raw API day files carry no
score field (fields: votesCount, commentsCount, dailyRank, weeklyRank, monthlyRank, createdAt, featuredAt, ...), so only vote-based
orderings can be tested.

**Finding: weekly_rank = order of votes at week close (Sunday 23:59 PT), then frozen.** In the SAME read, votes order matches weekly_rank
exactly right after the week closes and drifts as the read ages (launches keep collecting votes after the week; weekly_rank does not move:
71 of 1,243 launches with >= 2 post-week reads changed weekly_rank at all, vs 322 of 510 during the week):

| read age after week close | weeks | top 3 exact | top 5 exact | top 10 exact | top 3 / 5 / 10 hits |
|---|---|---|---|---|---|
| < 3 h | 2 | 1.00 | 1.00 | 1.00 | 1.00 / 1.00 / 1.00 |
| 3-26 h | 2 | 1.00 | 0.50 | 1.00 | 1.00 / 0.90 / 1.00 |
| 1-3 d | 3 | 1.00 | 0.60 | 1.00 | 1.00 / 0.92 / 1.00 |
| 3-12 d | 4 | 0.80 | 0.70 | 0.80 | 0.87 / 0.90 / 0.98 |
| > 12 d | 8 | 0.22 | 0.22 | 0.22 | 0.55 / 0.68 / 0.77 |

Spearman(votes, weekly_rank) in the same read: 0.9998 at < 3 h. Monthly_rank behaves the same (Oct read 7-8 h after month end: top 3 and
top 10 exact, Spearman 0.9998; May read 154 days later: 0 of top 10). Weeks are few (2 at < 3 h), so this is a mechanism finding, not a
precise rate; it is consistent across every read.

The 42% figure (final stored votes vs weekly_rank, Apr-Oct) is therefore a READ-AGE artifact: those votes were read 1-6 months after the
week. Swaps in the 17 of 29 disagreeing weeks: risers (final-votes top 3, not weekly top 3) spread over all weekdays (Mon 3, Tue 4, Wed 2,
Thu 3, Fri 4, Sat 1, Sun 2), median 3rd-4th vote gap 3.6%: post-week vote accrual among near-ties, not a featured/again or day-of-week
effect. (Sunday launches sit +3.6 places lower in weekly_rank than in final votes among the weekly top 20: they had the least time to
collect votes before the close, and collect the most after it.)

Candidates tested: votes at the first read after Sunday close (= weekly_rank), final votes (degrades with age), comments, daily rank then
votes (not better than votes at close; not pursued further given exact agreement). No candidate beats "current votes" for the LIVE board:
during the week current votes ARE votes-so-far, and at close they become the official order. So the board's base ordering stays current
votes; nothing to re-run for the live rule. The b1e4f767 backtest used final votes for earlier days (not held as-of for Apr-Sep): that
made both (a) and (b) score against a slightly wrong earlier-day order, the same for both, so the (b)-(a) deltas stand; absolute hit levels of
(a)/(b) on Thu-Sun are understated. For as-of earlier-day votes the daily re-reads since Oct 28 are the source going forward.
