# TIES-1 (Nov 24 2026): is the person's tie to the team the missing signal?

Round 1 found that once activity is matched, nothing separates voters from non-voters (logistic 0.518, taste-v1 0.529,
language models about 0.52). TIES-1 adds the one untested input: the person's tie to the launch's makers and hunter.
Same HARD rows as round 1 (50,100 test rows, 394 launches, Nov 11-22); models are logistic regressions fit on
VAL-HARD (Nov 1-10) and scored once on HARD. No model spend.

**Read: ties are a real signal and a small one; they are not the missing signal.** Dated ties lift HARD AUC from 0.518
to 0.547 and full-pool recall@N from 38.5 to 39.2, both clear of zero. Strong ties are rare (on the team, or backed by
the team before: under 2% of held voters), and the common one (backed an earlier launch by anyone on the team) is as
frequent among matched non-voters (66%) as among voters (67%). The larger gap is whether the person was on the site
that day at all: 81% of voters and 58% of matched non-voters upvoted some other launch the same day.

## Features (`simharness/ties.py`)
Dated, leak-free (only launches and events before day D; the launch's team as listed at 00:05 PT):
- on the team; earlier launches by anyone on the team that the person upvoted or commented on (any, count,
  recency-weighted count with a 90-day half-life, recency of the last one);
- overlap of the person's earlier upvotes with a held team member's (count, cosine; max over members);
- reciprocity: earlier launches the person made that a held team member backed (any, count).

Undated, upper bound only: the person follows a team member (any, count); a team member follows the person. Follow
edges in the store are snapshots with no date, so a follow made after the launch can leak in.

Coverage: 361 of 396 test launches were on the 00:05 list (95.8% of HARD rows); the others have no team at 00:05 and
get zero tie features. Validation teams exist for 197 of 316 launches (Nov 5-7 have no capture; Nov 1-3 use a
same-day capture). Of 653 team members, 362 are held people (their upvotes are known) and 285 have a following list.

## HARD (day-clustered 95% intervals)

| Model | HARD AUC | mean per-launch AUC | vs round-1 logistic | vs taste-v1 |
|---|---|---|---|---|
| round-1 logistic | 0.518 [0.514, 0.523] | 0.523 [0.514, 0.533] | | |
| round-1 taste-v1 | 0.529 [0.519, 0.537] | 0.541 [0.529, 0.554] | | |
| dated ties | 0.539 [0.528, 0.549] | 0.525 [0.515, 0.535] | +0.022 [+0.008, +0.034] | +0.011 [+0.001, +0.020] |
| dated ties + logistic features | 0.547 [0.536, 0.557] | 0.547 [0.539, 0.556] | +0.030 [+0.016, +0.042] | +0.019 [+0.008, +0.028] |
| dated ties + taste-v1 | 0.544 [0.533, 0.554] | 0.548 [0.535, 0.562] | +0.027 [+0.011, +0.039] | +0.016 [+0.012, +0.020] |
| dated ties + logistic features + taste-v1 | 0.545 [0.534, 0.555] | 0.544 [0.530, 0.559] | +0.028 [+0.012, +0.040] | +0.017 [+0.012, +0.022] |
| follow ties only (undated, upper bound) | 0.531 [0.523, 0.538] | 0.519 [0.511, 0.531] | +0.013 [+0.003, +0.022] | +0.002 [-0.007, +0.011] |
| dated + follow ties (upper bound) | 0.550 [0.537, 0.563] | 0.533 [0.520, 0.550] | +0.033 [+0.017, +0.047] | +0.021 [+0.009, +0.032] |
| dated + follow ties + logistic features (upper bound) | 0.556 [0.543, 0.568] | 0.554 [0.544, 0.567] | +0.038 [+0.023, +0.052] | +0.027 [+0.016, +0.037] |
| dated + follow ties + taste-v1 (upper bound) | 0.556 [0.543, 0.568] | 0.554 [0.538, 0.573] | +0.038 [+0.021, +0.052] | +0.027 [+0.020, +0.034] |

Best leak-free model: dated ties + logistic features. On the mean per-launch AUC it is clear of the logistic
(+0.024 [+0.011, +0.037]) but not of taste-v1 (+0.006 [-0.008, +0.020]). Follow edges add at most another 0.01.

## Who has a tie (HARD test rows: 25,050 voters, 25,050 matched non-voters)

| Tie | voters | matched non-voters |
|---|---|---|
| on the team | 0.22% (56) | 0.00% (1) |
| backed an earlier launch of the team | 67.35% (16,870) | 65.72% (16,463) |
| a team member backed the person's earlier launch | 1.35% (338) | 0.57% (142) |
| shares an earlier upvote with a held team member | 23.76% (5,953) | 21.52% (5,391) |
| any dated tie (team / backed / reciprocal) | 67.53% | 65.80% |
| follows a team member (undated) | 25.94% (6,497) | 20.30% (5,086) |
| followed by a team member (undated) | 2.77% (694) | 1.32% (330) |
| any follow tie (undated) | 26.73% | 20.80% |

"Backed an earlier launch of the team" is that common because a few hunters post hundreds of launches and the HARD
rows are heavy voters.

## Full pool (all 394 test launches; weights fit on a weighted validation pool sample)

| Model | recall@N | vs logistic |
|---|---|---|
| logistic (round 1) | 38.5 [36.6, 40.5] | |
| logistic + dated ties | 39.2 [37.5, 41.0] | +0.7 [+0.2, +1.1] |
| logistic + dated + follow ties (upper bound) | 39.0 [37.2, 40.8] | +0.5 [-0.1, +1.2] |

## Presence diagnostic (uses the day's outcomes to split rows; not a model input)
- Upvoted at least one OTHER launch that day: 80.8% of voters, 58.4% of matched non-voters (median 3 vs 1 other
  upvotes). Ranking HARD rows by that count alone gives AUC 0.651. It is not known at 00:05 PT.
- Among the 34,868 rows where the person was present that day: logistic 0.503, dated ties 0.498, dated ties +
  logistic features 0.507, taste-v1 0.524 [0.516, 0.534], with follow edges 0.528. So the dated-tie gain on HARD comes
  from saying who shows up, not which launch they pick; only taste (and undated follows) keeps any edge on the pick.
  Caveat: this subset is no longer matched (most-active scores 0.473 on it).

## Leak checks (`results.json` -> `leak_checks`)
- Delete-the-future test: on 3 test days (10,072 rows) the dated features are identical (max difference 0.0) after
  every backing, launch and team row dated on or after the day is removed from the tables.
- The team of every scored test launch comes from that day's 00:05 PT capture (361 launches); earlier launches' teams
  come from the item table, earlier captures and held people's exactly dated launched / hunted events.
- The launch itself is excluded from its own tie features; comments count from their own date.
- Tables hold integer keys only (person index, launch index, entity number); no username in any output.
- Known and unchanged: upvotes are undated and attributed to the launch day. Follow edges are undated (upper bound).

## Next
1. Presence first: a per-person model of "upvotes anything on day D" from dated signals (weekday habit, days since
   the last upvote, streak state, the day's line-up size), then choice given presence. Score both stages separately.
2. A choice benchmark that controls for presence (negatives = people who upvoted another launch that day), and the
   language models re-scored there: on round-1 HARD they were mostly being asked who shows up.
3. Ties as a feature of the deployed backer list: +0.7 points of recall@N is clear and free.

## Reproduce
`python -m simharness.run_ties {data,leak,hard,full,presence,agg}` (see the module docstring). Rows and tables:
`gs://.../simharness/bench_v0/round1/ties/` (private).
