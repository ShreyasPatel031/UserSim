# Re-read order for upvote_refresh (held data, Oct 1 - Nov 12)

Script `reread_order.py`, numbers in `results/reread_order.json`. Complete people only (69,483), dated upvotes from store_v3,
votes dated by the launch's PT day. A person counts for day d only if their upvotes tab was read after d closed (all
orders scored on the same people). Cost: max(1, ceil(upvotes since last read / 20)) pages per person; unread people
accumulate. Coverage = per-launch min(recovered upvoters, displayed votes), summed (the capped headline). Launch
bootstrap 1000; paired differences vs (a). Leak checks: orders use only votes on launches dated before d; E5's lists
assert reads_before <= d 00:00 PT and svd_max_lday < d (both pass).

## Oct 1 - Nov 12 (43 days, 1,287 launches). Reading everyone: 51.0% all / 76.8% top 3, ~64.7k pages/day

| people/day | order | votes recovered | cov all | cov top 3 | votes/page | all vs (a) | top 3 vs (a) |
|---|---|---|---|---|---|---|---|
| 1k | a 30-day count | 54,125 | 35.8 | 52.2 | 1.25 | - | - |
| 1k | c any vote 7d | 27,192 | 18.0 | 28.0 | 0.62 | -17.8 [-18.5,-17.1] | -24.1 [-25.9,-22.2] |
| 1k | d random | 1,259 | 0.8 | 1.3 | 0.03 | -34.9 | -50.9 |
| 1k | e 7-day count (extra) | 58,214 | 38.4 | 55.9 | 1.35 | +2.6 [+2.3,+2.9] | +3.8 [+2.9,+4.6] |
| 5k | a | 73,659 | 46.9 | 71.9 | 0.34 | - | - |
| 5k | c = e | 70,129 | 45.1 | 68.7 | 0.33 | -1.8 [-2.0,-1.6] | -3.2 [-3.8,-2.7] |
| 20k | a | 76,180 | 48.4 | 73.7 | 0.09 | - | - |
| 20k | c = e | 72,746 | 46.6 | 70.9 | 0.09 | -1.7 [-1.9,-1.6] | -2.9 [-3.4,-2.4] |

## Nov 8 - 12 (5 days with E5's CF-only lists, 155 launches, ~29k eligible people)

| people/day | order | cov all | cov top 3 | all vs (a) | top 3 vs (a) |
|---|---|---|---|---|---|
| 1k | a | 15.7 | 23.5 | - | - |
| 1k | b E5 CF-only first | 13.1 | 19.2 | -2.7 [-3.9,-1.6] | -4.4 [-8.2,-1.3] |
| 1k | c | 11.7 | 17.5 | -4.1 [-5.5,-2.9] | -6.1 [-10.8,-2.3] |
| 1k | e | 15.5 | 23.5 | -0.2 [-0.5,-0.1] | 0.0 [-0.7,+0.8] |
| 5k, 20k | b | identical to (a): E5's lists sit inside (a)'s top 5k | | 0 | 0 |

## Pages per day (order a)

| target | Oct days | Oct 1 - Nov 12 |
|---|---|---|
| Oct level 51.7% all | ~21.4k pages (~21.4k people) | not reachable (ceiling 51.0) |
| Oct level 83.6% top 3 | equals reading everyone (ceiling 83.5): ~69.5k | not reachable (ceiling 76.8) |
| 95% of read-everyone, all | ~24.3k | ~20.9k |
| 95% of read-everyone, top 3 | ~8.6k | ~8.6k |
| 99% of read-everyone, all / top 3 | ~59.8k / ~57.0k | ~55.4k / ~53.2k |

## Caveats
- Upvote times in the store are fetch snapshots, so votes are dated by launch day and the cost counts launch-dated votes.
- Only yesterday's votes are scored; people skipped are still recovered on a later read.
- The pool was seeded from Oct 29 - Nov 4 voters, which favours activity orders in that week.
- (e) was not in the brief; it wins at 1k on 43 days and loses at 5k and 20k, so it is not recommended without a test.
