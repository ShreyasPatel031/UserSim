# Page-read path under the same-point standard (orchestrator 12:44Z Nov 12)

Script: page_path.py.
- Launches: 70 = 44 fresh page reads (Oct 27 – Nov 10) + 26 held Sep–Oct page reads (fetched Oct 25, flagged late), each with ≥ 5 real comments.
- Ranked concerns / questions (try_fixes.ranked, retrieval strictly earlier) from three inputs on the same launches.
- Adjudicator: gemini-2.5-pro at temperature 0, seeing the real comments, top-3 items pooled per launch.
- About $0.5 for the adjudicator plus flash generation.

| top-3 same-point precision (p@3) [95%] | concerns | questions |
|---|---|---|
| (a) page read summary (current site) | 25.2 [19.5, 31.4] | 29.5 [22.9, 36.2] |
| (b) raw page excerpt | 29.5 [23.8, 35.2] | 31.4 [24.3, 38.6] |
| (c) pasted PH description (reference) | **37.1 [31.0, 44.3]** | **37.1 [30.5, 43.8]** |
| constant list | 24.3 [17.1, 31.4] | 22.4 [15.7, 29.5] |
| category points | 5.8 | 5.8 |
| **ceiling: real vs real split-half** (35 launches with ≥ 10 comments) | 32.4 [21.0, 44.3] | 34.8 [23.5, 45.6] |

| paired difference vs the constant list (p@3) | concerns | questions |
|---|---|---|
| (a) page read summary | +1.0 [−6.7, +8.1] | +7.1 [−1.4, +15.7] |
| (b) raw excerpt | +5.2 [−3.3, +13.3] | +9.0 [−1.0, +19.0] |
| (c) PH description | **+12.9 [+4.3, +21.0]** | **+14.8 [+8.1, +21.0]** |
| raw minus read summary | +4.3 [−1.9, +10.0] | +1.9 [−5.2, +9.5] |

hit@3 (at least one of three matches): read 59 / 59; raw 66 / 60; PH 76 / 71; constant 46 / 44.

Fresh-only (44) p@3, a / b / c / constant:
- concerns 31.1 / 31.1 / 36.4 / 24.2;
- questions 32.6 / 34.8 / 37.1 / 23.5.

**Verdict:**
- No page-read input beats the constant list with the interval above zero.
- The pasted launch description does, for both lists, and reaches the real-vs-real ceiling. That ceiling is set with half of the comments, so it is a floor for the true ceiling.
- Product statement: "Paste your launch description for concerns and questions; a URL alone gives the rank band and topic-level reactions only."

**Note on levels:** p@3 here is higher than in same_point.py (PH concerns 37 vs 13). That run pooled 30–60 items per adjudicator call; this one pools about 20 top-3 items. The adjudicator's strictness depends on pool size, so compare within a run, not across runs.
