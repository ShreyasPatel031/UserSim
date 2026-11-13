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

## Extensions (orchestrator 02:39Z Nov 13), scripts bank_v2.py and b20_ext.py: no recipe change

Setup:
- Same pooled 170 launches, both input paths.
- Recipe neighbour exclusions.
- Strict pro judge, one pooled call per launch per part. Compare arms only within a part; pool sizes differ between parts.
- Cost: about $3.7 for the judge, $2.8 for generation, and $0.06 for the bank.

**(1) Bank size.**
- v1 holds 3,371 launches (Jan 1 – Oct 24, ≥ 5 non-team comments, 6.0 themes per launch).
- v2 holds 4,517 launches (Jan 1 – Nov 10). It adds the launches with 3–4 comments and the Oct 27 – Nov 10 API pulls, at 5.8 themes per launch.

| | value |
|---|---|
| thin share below recipe thresholds, v1 → v2 | PH 36.5 → 34.7%, page 33.5 → 31.2% |
| concerns p@3, b20 on v2 − b20 on v1 | page −1.4 [−3.8, +0.8], PH −1.4 [−4.6, +1.6] |
| concerns top-1, v2 − v1 | page +4.2 [−0.6, +9.6], PH +1.8 [−3.0, +6.0] |

The bigger bank gives no gain. Keep v1.

The b20 replication against deployed holds again in this pool:
- p@3: page +4.2 [+0.4, +7.8], PH +10.6 [+6.4, +14.8].
- Recall: page +5.5 [+1.3, +9.9], PH +12.0 [+6.8, +17.3].

**(2) b20 for general reactions** (6 comments of any type, including praise). Compared against deployed step_reactions and a constant 6.

| b20-R − deployed | precision over 6 | p@3 | recall | top-1 |
|---|---|---|---|---|
| page | −4.4 [−7.5, −1.4] | +0.6 [−3.9, +5.1] | −2.1 [−5.1, +0.8] | +1.9 [−6.8, +9.3] |
| PH | −6.2 [−9.5, −2.6] | −2.5 [−7.0, +2.3] | −3.8 [−7.3, −0.4] | +8.6 [+0.6, +16.7] |

Levels for b20-R / deployed / constant (precision over 6): page 26.7 / 31.2 / 14.7, PH 41.8 / 47.9 / 14.7.

Deployed already grounds on the themes of its 10 nearest launches and also reads the page. b20-R loses on the main metric, so there is no reactions recipe.

The judge here (real-points prompt, 3-arm pool) is more lenient than in the earlier reactions runs (24% / 7–15%). Compare these levels only within this table.

**(3) Neighbour count × points sweep**, concerns, bank v1.

On the dev half (73 launches, p@3 mean over both paths), every setting lands between 18.5 and 22.1:

| | p2 | p4 | p8 |
|---|---|---|---|
| k10 | 19.2 | 21.7 | 19.9 |
| k20 | 20.5 | 21.7 | 18.5 |
| k40 | **22.1** | 21.7 | 21.9 |

The best setting, k40 p2, beats k20 p4 by only +0.5 [−2.3, +3.7] on the dev half.

On the confirmation half (93 page / 93 PH launches), k40 p2 − recipe k20 p4:
- p@3: page +1.1 [−2.2, +4.3], PH −1.8 [−6.1, +2.2].
- Recall: page +0.2, PH −4.1 [−9.1, +1.1].

The recipe itself again beats deployed on this half: p@3 page +6.5 [+1.8, +11.1], PH +9.3 [+3.9, +14.7].

**Verdict:** no change. Keep RECIPE_b20_concerns.md as it is: bank v1, k = 20, 4 points per neighbour, concerns on both paths and questions on the pasted path. Reactions stay on deployed.
