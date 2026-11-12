# Same-point standard: variants, ranked lists, ceiling (orchestrator 10:25Z Nov 12)

Script: same_point.py. Adjudicator gemini-2.5-pro, temperature 0, sees the real comments. One blinded pooled call per launch.
Gemini spend about $1.2. Dev set: 28 PH-description launches (S300, BEST lists) + 17 page-read launches (fresh, site run).

**Same-point precision** (share of items making the same specific point as a real comment), [95% bootstrap]:

| list | PH description (28) | page read (17) |
|---|---|---|
| BASE (BEST / site run) | **23.2 [14.3, 32.7]** | **14.7 [3.9, 29.4]** |
| A specific points only | 16.7 (−6.5 [−14.3, 0.0]) | 13.7 (−1.0) |
| B1 retrieval + LLM pick | 18.5 (−4.8 [−13.1, 3.0]) | 13.7 (−1.0) |
| B2 retrieval frequency | 13.7 (−9.5 [−18.5, −1.2]) | 10.8 (−3.9) |
| C two-stage 15 → 5 | 22.9 (−0.4 [−10.5, 9.2]) | 12.9 (−1.8) |
| CONST generic 6 | 20.2 (−3.0 [−11.3, 5.4]) | **26.5 (+11.8 [−4.9, 26.5])** |
| CAT category points | 11.3 | 14.7 |

- No variant beats BASE, so the confirmation run was skipped and nothing is exported.
- D (raw excerpt for page input) returned no lists: the prompt failed on long page text. Not tested.
- BASE is not above the generic constant on PH descriptions (−3.0) and is below it on page reads.

**Ranked lists, same-point p@3 / hit@3:**

| | PH description: list / const / category | page read: list / const / category |
|---|---|---|
| concerns | **13.1** / 6.0 / 4.8; hit 32 / 18 / 14 | 7.8 / 7.8 / 2.0; hit 24 / 24 / 6 |
| questions | **16.7** / 7.1 / 2.4; hit 39 / 14 / 7 | 17.6 / 15.7 / 0.0; hit 35 / 41 / 0 |

- From PH descriptions, both ranked lists stay above both controls (about 2× the constant).
- From page reads, they tie the constant list.

**Ceiling** (real vs real): half of the commenters vs the other half, 51 launches with ≥ 10 comments, same adjudicator.
- Same-point precision **35.2 [29.8, 41.3]**, recall 25.9 [21.7, 30.1].
- BEST's 23–24 is about two thirds of the ceiling. The generic list's 20 is about 57%.

**Real points:** generic vs product-specific: 13% generic in the dev set (37 of 345), 13% in the ceiling set (47 of 353).

**Caveat:** recall in the pooled call is attributed by the adjudicator listing matching item numbers per theme. It undercounts (BASE 14 vs 44 in the per-list adjudication), so use precision and p@3 here.
