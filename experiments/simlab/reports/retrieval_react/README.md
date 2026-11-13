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

## Replication (orchestrator 02:16Z Nov 13), script retrieval_rep.py

**Setup:**
- Recipe frozen.
- New set: 100 launches, Sep 28 – Oct 19, not in the first 70. No unused fresh page read had ≥ 5 comments, so these are all held page reads (fetched Oct 25, 1–4 weeks late).
- All 170 launches were re-adjudicated on a b20 / c / d pool. The first-70 numbers therefore differ slightly from the table above.

**b20 − deployed (c), % [95% CI]:**

| | new 100 | pooled 170 | pooled, excluding leak-flagged targets |
|---|---|---|---|
| **questions, page** p@3 | **0.0 [−4.5, +4.5]** | +3.0 [−1.0, +6.9] | +0.7 [−3.4, +4.6] |
| questions, page recall / top-1 | +1.2 / +2.1 (ns) | +3.0 / +3.0 (ns) | |
| concerns, page p@3 | +4.9 [−0.4, +10.9] | **+7.5 [+3.0, +12.0]** | **+7.4 [+2.8, +12.0]** |
| concerns, page recall | +5.8 [−1.6, +13.3] | +6.5 [+0.9, +12.1] | |
| concerns, PH p@3 | **+12.3 [+6.3, +18.6]** | **+12.4 [+7.9, +17.1]** | **+12.5 [+7.8, +18.0]** |
| concerns, PH recall / top-1 | +11.8 / +14.7 (both > 0) | +13.5 / +14.6 (both > 0) | |
| questions, PH p@3 / recall | +5.2 [−0.3, +10.7] / **+10.8 [+3.6, +17.9]** | +4.9 [+0.6, +9.3] / +7.9 [+2.6, +13.1] | +5.2 / +8.0 (both > 0) |

**Verdict:** the page-path questions gain did NOT replicate. Concerns replicate on both paths, strongly on the PH description.

**Thin neighbours** (top-1 cosine in the bottom third, about 0.89 or below):
- No gain with an interval above 0.
- On the page path, both b20 and deployed fall below the constant list (concerns p@3: 9 / 6 vs 16). A weak page read is the likely cause.

**PH description under 40 words (n = 30):**
- Concerns, PH: +12.2 [+3.3, +22.2].
- Questions, PH recall: +15.1 [+4.3, +26.3].
- Everything else is not distinguishable from zero.

**Judge noise** (second item order, 26–28 new launches):
- Item labels agree 92–94%.
- The b20 − c p@3 estimate moves by up to 4 points between the two orders.

**Leak check** (20 neighbours × 170 targets × 2 modes):
- The run excludes only the exact slug stem. "-N" relaunch variants slip through: 7 targets (PH) and 3 (page) have an earlier launch of the same product among their neighbours.
- 21 / 17 have a name or slug containing the target's.
- 14 / 10 neighbours share a named maker. 163 of 170 targets have at least one named maker; the rest are redacted.
- These are earlier launches, so there is no future leak. Excluding every flagged target (23 PH / 19 page) leaves the results unchanged, as the last column shows.
- If shipped, the recipe should also exclude "-N" stems and shared makers.

**Cost:** adjudicator about $1.8 for this run.
