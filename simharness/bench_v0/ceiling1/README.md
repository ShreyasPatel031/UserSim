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

Launch level: 16 launches (Nov 15-22 (Nov 15, 16, 17, 18, 19, 22), median 19 real commenters), 20 random half splits each, one judge run per split,
launch-bootstrap intervals. Person level: the 296 POINT-1 rows, day-bootstrap intervals; the own-comment arm judged by
the same same-point-v1 judge, 2 runs, 1-1 counted as no (as in POINT-1).

## Read before using these numbers
- **The launch-level ceiling is size-limited.** Half A is about 11 real comments (median); the persona panel is about
  22 items and the deployed panel about 37. Theme recall grows with list length, so a simulated list can pass the
  half-split ceiling without being better per comment. A fair ceiling compares equal-sized lists (subsample each arm to
  half A's size against the same half-B themes). Not run: the half-B themes were not stored and re-extracting them would
  exceed the budget (about $1.2 more). Precision is per item and less affected: deployed 1.20 of the ceiling
  [1.00, 1.39], persona only 0.96 [0.75, 1.17].
- **No launch had the launch-page block.** The 16 sampled launches fall on Nov 15-22 (Nov 15, 16, 17, 18, 19, 22); their person-built comments are
  the Nov 25 re-generation without the maker's comment. 56 launches qualified; budget allowed 16 at 20 resamples.
- **Complaint-recall ratios** are means of per-launch ratios and are inflated by launches where the ceiling is small;
  the ratio of means is about 1.0.
- **The "stronger" person ceiling is not stronger.** A person's own comment on their most similar earlier launch
  (median cosine 0.68) makes the same point as their real comment on 6.1% of rows, below another real commenter on the
  same launch (15.9%). The same-point judge asks for the same specific point about this launch, which an old comment on
  another launch rarely makes. Use it as a floor (the person's style without the launch), not as a ceiling.

# CEILING-2 (Nov 25 2026): equal-size panels against the half-split ceiling

Code: `simharness/ceiling1.py launch2 / table2`. Numbers: `ceiling2.json`; per-row results with the stored half-B themes
and complaints: bucket `simharness/bench_v0/ceiling1/private/launch2_rows.jsonl`. Spend $1.67 measured (plus about
$0.1 of a restarted first attempt), of $2.5.

Each arm is subsampled to half A's comment count (fixed seed per launch and resample) and judged against the same
half-B themes as half A. 22 launches, 8 resamples each, launch-bootstrap intervals. Fraction = mean of per-launch
ratios; ratio of means in brackets.

| Launches | Metric | Ceiling (half A) | Deployed, equal size | Fraction | Persona only, equal size | Fraction |
|---|---|---|---|---|---|---|
| all 22 | theme recall | 62.2 [56.0, 68.1] | 55.2 [49.8, 60.7] | 0.92 [0.82, 1.05] (0.89) | 58.9 [52.3, 65.1] | 0.97 [0.87, 1.09] (0.95) |
| all 22 | weighted recall | 68.9 | 61.2 | 0.91 [0.81, 1.03] (0.89) | 63.7 | 0.95 [0.85, 1.06] (0.93) |
| all 22 | precision | 50.8 [46.1, 55.3] | 58.5 [52.2, 65.0] | **1.20 [1.04, 1.34]** (1.15) | 53.3 | 1.09 [0.94, 1.24] (1.05) |
| all 22 | complaint recall | 31.8 [23.5, 39.9] | 24.4 [19.0, 30.3] | 0.91 [0.65, 1.21] (0.77) | 25.9 | 1.07 [0.71, 1.54] (0.82) |
| 6 Nov 24-25 launches (POINT-1 prompt) | theme recall | 64.5 | 55.5 | **0.87 [0.80, 0.94]** | 62.7 | 0.98 [0.93, 1.02] |
| same | precision | 51.6 | 62.0 | **1.20 [1.11, 1.29]** | 59.4 | 1.15 [1.07, 1.23] |
| same | complaint recall | 32.9 | 18.8 | **0.63 [0.41, 0.95]** | 21.5 | 0.66 [0.54, 0.76] |

Reading:
- At equal size the simulated panels are at about 0.9-1.0 of the human ceiling on theme recall and above it on
  precision (deployed 1.20 [1.04, 1.34]): their comments are more often on a real theme than a real commenter's, but they
  cover slightly fewer themes. The CEILING-1 recall "above the ceiling" was list length.
- Complaints are where the gap is: 0.77-0.82 of the ceiling by ratio of means on all launches, and 0.57-0.65 on the
  Nov 24-25 launches.
- Adding the person-built comments to the persona panel raises precision and lowers recall and complaint recall at
  equal size (deployed vs persona only); none of these differences is clear on its own.
- Caveats: only 1 of the 6 Nov 24-25 launches had the maker's comment in its launch block at run time (the others ran
  the POINT-1 prompt without it); Nov 25's comments were read mid-day (launch day still open, both halves from the same
  partial set). The CEILING-1 launches span Nov 15-22 (not Nov 15-22 (Nov 15, 16, 17, 18, 19, 22) as first written). 8 resamples per launch, not 20,
  to cover the Nov 24+ launches within the budget.
