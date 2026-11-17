# Complaint and question recall before launch

E5, Nov 17 2026. Question: how much of what real users later complain about or ask can be named before launch, and by which method?

**Answer: about 1 in 7 complaints and 1 in 10 questions, with 10 predictions each. No arm is near 40%.**

## Data

- 2,179 held 2026 launches have at least 8 real comments from non-team users. 377 of them launched on or after Aug 1 and have a launch embedding; 300 were sampled at random (seed 0) as the test set. Median 13 commenters per launch.
- Truth (real outcome, tagged by Gemini): complaint themes and question themes per launch, counted by distinct commenters. Mean 2.07 complaint themes and 6.67 question themes per launch. 62 launches have no complaint at all and are left out of the complaint rows.
- Every arm returns 10 ranked complaints and 10 ranked questions from pre-launch inputs only.
- One blind judge call per launch and kind sees all arms' items pooled and shuffled, and matches each to a real theme only if it names the same specific issue. The same broad topic alone is not a match.
- Hand check: E5 read 50 pairs (25 judged matches, 25 judged non-matches) and agreed with 47 (94%). Two matches were too loose and one non-match was a real match, so the figures below are, if anything, slightly generous.
- Gemini cost: $4.15. Intervals are bootstraps over launches.

## Main arms, same launches (%)

| Arm | Complaint recall, top 5 | Complaint recall, top 10 | Complaint precision, top 10 | Question recall, top 5 | Question recall, top 10 | Question precision, top 10 |
|---|---|---|---|---|---|---|
| A. Persona panel as deployed | 7.1 [4.6, 9.9] | 9.0 [6.4, 12.0] | 3.2 [2.2, 4.3] | 3.0 [2.3, 3.7] | 4.9 [4.0, 6.0] | 3.9 [3.1, 4.6] |
| B. Persona-free prompt on the pitch | 8.6 [6.1, 11.2] | 13.5 [10.4, 16.9] | 3.9 [3.0, 4.8] | 6.1 [4.8, 7.4] | 10.4 [8.7, 12.1] | 7.3 [6.2, 8.4] |
| C. Retrieval only (5 similar earlier launches) | 2.9 [1.4, 4.8] | 5.0 [3.0, 7.3] | 1.3 [0.8, 1.8] | 2.1 [1.5, 2.9] | 3.3 [2.3, 4.3] | 2.3 [1.7, 3.0] |
| D. Panel + retrieval | 7.0 [4.5, 9.8] | 9.2 [6.4, 12.1] | 3.2 [2.3, 4.3] | 3.2 [2.4, 4.1] | 5.6 [4.6, 6.7] | 4.4 [3.6, 5.2] |
| F. Persona-free + retrieval (added) | 9.1 [6.6, 12.0] | 13.6 [10.3, 17.1] | 4.1 [3.2, 5.1] | 5.8 [4.6, 7.1] | 9.8 [8.2, 11.6] | 6.8 [5.6, 7.9] |

n = 223 launches for complaints and 273 for questions (all five arms returned, and the kind has at least one real theme). Weighting recall by the number of commenters behind each theme changes no figure by more than half a point.

## Paired differences at 10 predictions (points)

| Comparison | Complaint recall | Question recall |
|---|---|---|
| Panel minus persona-free | -4.5 [-7.3, -2.0] | -5.4 [-6.9, -3.9] |
| Retrieval minus persona-free | -8.5 [-12.5, -4.6] | -7.1 [-8.9, -5.4] |
| Panel + retrieval minus panel | +0.2 [-1.1, +1.4] | +0.7 [-0.2, +1.6] |
| Persona-free + retrieval minus persona-free | +0.1 [-3.3, +3.7] | -0.6 [-2.4, +1.1] |
| Panel + retrieval minus persona-free + retrieval | -4.4 [-8.0, -0.7] | -4.1 [-5.7, -2.6] |

- The persona-free prompt is the best single arm, and the persona panel is clearly worse than it on both kinds.
- Retrieval alone is the worst arm. Adding it to either other arm changes nothing.
- Pooling all five arms (50 predictions per kind) reaches 25.1 [20.7, 29.9]% of complaints and 19.4 [17.0, 21.8]% of questions.
- Share of launches where an arm reaches 40% complaint recall with 10 predictions: persona-free 14.8 [10.3, 19.7]%, panel 9.4 [5.8, 13.5]%.

## Task-run arm on held site captures

154 of the 300 launches have a usable held capture of the product's own site. Arm E runs the end-to-end test's shape as a prompt (6 prospective users × 6 tasks) on the captured site text. It is text only: no browser, no real task execution. Its control is the persona-free prompt given the same site text.

| Arm, site subset | Complaint recall, top 10 | Question recall, top 10 |
|---|---|---|
| E. Task run on site text | 7.8 [4.3, 11.8] | 8.2 [6.2, 10.4] |
| Persona-free with site text | 9.4 [6.0, 13.0] | 9.9 [7.7, 12.3] |
| Persona-free, pitch only | 8.8 [6.0, 12.1] | 10.5 [8.1, 13.1] |
| Persona-free + retrieval | 12.2 [8.0, 16.7] | 9.5 [7.3, 12.1] |

Task run minus persona-free with the same site text: complaints -1.7 [-5.0, +1.5], questions -1.7 [-3.9, +0.6]. Site text adds nothing over the pitch: +0.6 [-1.6, +2.8] and -0.6 [-2.9, +1.6]. n = 116 and 145.

## Splits (recall in the top 10, persona-free arm; other arms are in results.json)

| Split | n | Complaints | Questions |
|---|---|---|---|
| API | 26 | 14.9 [6.5, 24.9] | 11.7 [6.7, 17.6] |
| Developer Tools | 21 | 12.2 [1.6, 26.2] | 8.7 [4.0, 14.1] |
| Marketing | 15 | 11.5 [2.6, 21.8] | 8.8 [4.0, 13.6] |
| Open Source | 21 | 9.0 [0.0, 23.1] | 6.8 [2.0, 12.9] |
| Productivity | 61 | 13.6 [6.8, 21.5] | 12.4 [8.3, 16.8] |
| other | 129 | 14.3 [9.6, 19.5] | 10.1 [7.9, 12.5] |
| 12-19 | 127 | 12.6 [7.8, 17.9] | 9.2 [7.1, 11.4] |
| 20+ | 46 | 13.3 [6.5, 20.9] | 12.6 [9.2, 16.2] |
| 8-11 commenters | 100 | 14.8 [9.8, 20.2] | 10.9 [7.5, 14.5] |

No topic and no size band stands out; every cell is between 7% and 15%.

## Leak checks

- Retrieval: neighbours launched strictly before the target's day; only comments written before that day are used; launches sharing the hunter or any maker are excluded.
- Persona panel: people and card history from launch days strictly before the target day. Known limitation: segment definitions and profiles were fitted on Nov 16 from all held data. That could only help the panel, which is still the weaker arm.
- Site captures: the capture date is not recorded and is probably after launch for most. That could only help the site arms, which show no gain.
- The language model's own knowledge ends well before these launches.

## Why this is lower than earlier figures

- The earlier "theme recall 61%" matched broad themes (for example "pricing"). This run requires the same specific issue.
- The earlier "complaint recall 24% [9, 38]" came from 11 launches with a looser rule; its interval contains this run's 13.5%.
- Real complaints are few (about 2 per launch) and often specific to what happened on the day: a bounced support address, a crash in the trial, a missing platform. A pitch does not contain them.

Files: `run.py`, `analyze.py`, `results.json`, `handcheck_50_pairs.json`. Raw themes and predictions are not committed.
