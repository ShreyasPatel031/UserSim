# Retrieval instead of generation: concerns and questions (orchestrator 02:09Z Nov 13)

Script: retrieval_react.py. Same 70 launches as page_path (44 fresh, 26 held). Two input modes:
- **PH:** the real PH description.
- **page:** the raw page excerpt, which is the deployed page-path input.

Neighbours come from the site's reactions_retrieval_v1 bundle: points extracted from the REAL comments of earlier launches. Only launches dated strictly before the target day are used, the same slug stem is excluded, and neighbours are ranked by gemini-embedding cosine.

Arms:
- (a5) verbatim real points from the 5 nearest launches.
- (a5t) the same, nearest within the same topic.
- (b20) gemini-2.5-flash condenses the 20 nearest launches' real points into a ranked top 3.
- (c) deployed ranked().
- (d) constant list.

Adjudicator: gemini-2.5-pro at temperature 0, seeing the real comments. One call per launch per kind, with both modes pooled and blinded. Recall = the share of the launch's top-3 real points (flash extraction) matched by any of the arm's 3 items.

All numbers are % with [95% CI], n = 68–69. Gains are paired bootstrap over launches.

| | p@3 | recall | top-1 hit |
|---|---|---|---|
| **questions, page** b20 / c / d | 27.0 / 19.1 / 10.8 | 24.5 / 19.4 / 10.8 | 35.3 / 27.9 / 11.8 |
| b20 − c | **+7.8 [+2.0, +14.2]** | +5.1 [−2.9, +13.0] | +7.4 [−4.4, +19.1] |
| **concerns, page** b20 / c / d | 29.0 / 23.2 / 15.5 | 28.5 / 23.2 / 13.5 | 29.0 / 27.5 / 10.1 |
| b20 − c | +5.8 [−0.0, +12.1] | +5.3 [−2.4, +13.5] | +1.4 [−13.0, +14.5] |
| **questions, PH** b20 / c / d | 35.8 / 31.4 / 10.8 | 39.5 / 26.5 / 10.8 | 45.6 / 41.2 / 11.8 |
| b20 − c | +4.4 [−2.5, +11.3] | **+13.0 [+4.9, +21.3]** | +4.4 [−8.8, +17.6] |
| **concerns, PH** b20 / c / d | 42.0 / 26.6 / 15.5 | 44.4 / 23.4 / 13.5 | 49.3 / 33.3 / 10.1 |
| b20 − c | **+15.5 [+8.2, +23.2]** | **+21.0 [+12.6, +30.2]** | +15.9 [0.0, +31.9] |

- **Verbatim retrieval loses.** a5 and a5t are below deployed by 7–20 points everywhere and no better than the constant list.
- **b20 beats the constant list everywhere.** It beats deployed with a positive interval on page questions p@3 and on PH concerns and PH question recall.

**Cost per launch:**
- b20: one embedding plus two flash calls, about $0.002 (both kinds). That is no more than deployed ranked(), which makes 2 flash calls plus a rating call per kind.
- Evaluation: about $0.011 per launch for the adjudicator. The whole run cost about $1.05.

**Caveats:**
- Single run.
- The b20 prompt was fixed before the run (no tuning on these launches).
- Judge strictness depends on pool size, so compare arms only within this run.
