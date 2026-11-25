# CEILING-1 (Nov 25 2026): reaction metrics against a human ceiling

Code: `simharness/ceiling1.py`. Numbers: `ceiling1.json` (also in the bucket under simharness/bench_v0/ceiling1/).
Spend: $4.47 of $5 (launch level $3.76 Gemini Flash, 4,184 calls; person level $0.71 Opus judge), from usage_metadata.

## Leaderboard (metric x arm x ceiling)

| Level | Metric | Ceiling (value) | Arm | Arm value | Arm / ceiling | Arm - ceiling |
|---|---|---|---|---|---|---|
| launch | theme recall | real half A vs half-B themes: 61.1 [53.7, 68.7] | deployed (persona + 15 person-built) | 69.0 [62.5, 75.6] | 1.17 [1.05, 1.31] | +8.0 [+2.0, +14.0] |
| launch | theme recall | same | persona only | 69.3 [62.0, 76.6] | 1.17 [1.05, 1.31] | +8.2 [+2.5, +14.3] |
| launch | weighted recall | 68.4 [60.9, 75.4] | deployed | 74.7 [67.7, 81.3] | 1.12 [1.01, 1.23] | +6.2 [+0.4, +12.1] |
| launch | weighted recall | same | persona only | 74.4 [67.3, 81.0] | 1.12 [1.01, 1.25] | +6.0 [+0.5, +11.9] |
| launch | precision | 48.3 [43.2, 53.4] | deployed | 56.5 [47.4, 65.9] | 1.20 [1.00, 1.39] | +8.2 [-0.5, +16.8] |
| launch | precision | same | persona only | 45.5 [35.4, 55.8] | 0.96 [0.75, 1.17] | -2.8 [-12.6, +7.2] |
| launch | complaint recall | 33.0 [24.4, 42.1] | deployed | 34.0 [27.1, 41.1] | 1.44 [0.94, 2.04] (ratio of means 1.03) | +1.0 [-9.8, +11.5] |
| launch | complaint recall | same | persona only | 33.3 [26.4, 40.3] | 1.40 [0.94, 1.96] (ratio of means 1.01) | +0.4 [-10.2, +10.7] |
| person | same point | another real commenter: 15.9 [10.5, 20.9] | A0 Flash + launch block | 25.3 [20.0, 30.0] | 1.60 | +9.5 (POINT-1) |
| person | same point | the person's own comment on their most similar earlier launch: 6.1 [3.6, 8.5] | A0 Flash + launch block | 25.3 | 4.17 | +19.3 |

Launch level: 16 launches (Nov 15-20, median 19 real commenters), 20 random half splits each, one judge run per split,
launch-bootstrap intervals. Person level: the 296 POINT-1 rows, day-bootstrap intervals; the own-comment arm judged by
the same same-point-v1 judge, 2 runs, 1-1 counted as no (as in POINT-1).

## Read before using these numbers
- **The launch-level ceiling is size-limited.** Half A is about 11 real comments (median); the persona panel is about
  22 items and the deployed panel about 37. Theme recall grows with list length, so a simulated list can pass the
  half-split ceiling without being better per comment. A fair ceiling compares equal-sized lists (subsample each arm to
  half A's size against the same half-B themes). Not run: the half-B themes were not stored and re-extracting them would
  exceed the budget (about $1.2 more). Precision is per item and less affected: deployed 1.20 of the ceiling
  [1.00, 1.39], persona only 0.96 [0.75, 1.17].
- **No launch had the launch-page block.** The 16 sampled launches fall on Nov 15-20; their person-built comments are
  the Nov 25 re-generation without the maker's comment. 56 launches qualified; budget allowed 16 at 20 resamples.
- **Complaint-recall ratios** are means of per-launch ratios and are inflated by launches where the ceiling is small;
  the ratio of means is about 1.0.
- **The "stronger" person ceiling is not stronger.** A person's own comment on their most similar earlier launch
  (median cosine 0.68) makes the same point as their real comment on 6.1% of rows, below another real commenter on the
  same launch (15.9%). The same-point judge asks for the same specific point about this launch, which an old comment on
  another launch rarely makes. Use it as a floor (the person's style without the launch), not as a ceiling.
