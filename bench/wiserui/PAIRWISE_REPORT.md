# WiserUI-Bench: shared pairwise judge (mvp/pairwise.py) incremental ablation, 2026-09-27 PT

Branch `grokbot/pairwise-judge` (commit 372b405: module, loader, ablate.py, split). Model gemini-2.5-flash on Vertex,
thinking off, persona temperature 0.4, two separate images per call (default resolution, as A0). Every arm uses the
**same six personas per page as A0** (A0's cached planner output, run through `mvp.fast_plan.ab_personas`), so arms differ only in the judge.
Split: seed 20260927, stratified by source, 75 dev (VWO 42, GoodUI 33) / 150 test (VWO 83, GoodUI 67), from the 225 clean pairs.
Side A = winner for about half the pairs (hash of the index).

Arms (one flag added per step): A0 = old 6-persona single-pick vote, both orders. S1 = neutral Version X/Y, reasons then a 1-10 rating
per version, averaged across orders, soft p(A>B). S2 = S1 + goal/diff extraction (G-FOCUS style, both orders, merged; personas judge only the listed differences).
S3 = S2 + SimAB-style debias wording.

Metrics: CA = per-order pick (mean X-Y rating over 6 personas in that order) right in both orders, the paper metric (chance 25%). FA/SA = accuracy when the winner is shown first/second.
OI = one pick per pair from both orders (pw: p(A>B); A0: 12 pooled votes), tie = 0.5 (chance 50%). Ties count as wrong in CA/FA/SA. CIs: 10k pair bootstrap.

## Dev (n=75)
| arm | CA [95% CI] | FA / SA | OI [95% CI] | 1st-slot / tie | persona agree / order-consistent | calls, $ per pair | goodui CA / OI (n=33) | vwo CA / OI (n=42) |
|---|---|---|---|---|---|---|---|---|
| A0 | 28.0 [18.7, 38.7] | 41.3 / 65.3 | 60.0 [50.0, 70.0] | 34.0 / 11.3 | 80.8 / 53.3 | 13.0, $0.0070 | 27.3 / 56.1 | 28.6 / 63.1 |
| S1 | 34.7 [24.0, 45.3] | 41.3 / 66.7 | 62.7 [51.3, 73.3] | 32.7 / 8.7 | 61.9 / 39.8 | 12.0, $0.0055 | 30.3 / 62.1 | 38.1 / 63.1 |
| S2 | 52.0 [41.3, 64.0] | 54.7 / 64.0 | 62.0 [50.7, 72.7] | 44.0 / 2.7 | 78.2 / 70.0 | 14.0, $0.0077 | 48.5 / 56.1 | 54.8 / 66.7 |
| S3 | 45.3 [34.7, 56.0] | 50.7 / 64.0 | 55.3 [44.7, 66.7] | 42.0 / 5.3 | 71.6 / 62.0 | 14.0, $0.0080 | 39.4 / 48.5 | 50.0 / 60.7 |

| comparison | dCA [95% CI] | dOI [95% CI] |
|---|---|---|
| S1 - A0 | +6.7 [-5.3, +18.7] | +2.7 [-6.0, +12.0] |
| S2 - S1 | +17.3 [+5.3, +29.3] | -0.7 [-11.3, +9.3] |
| S3 - S2 | -6.7 [-17.3, +4.0] | -6.7 [-16.7, +3.3] |
| S2 - A0 | +24.0 [+12.0, +37.3] | +2.0 [-8.0, +12.0] |
| S3 - A0 | +17.3 [+6.7, +29.3] | -4.7 [-16.0, +6.7] |
| S3 - S1 | +10.7 [-1.3, +22.7] | -7.3 [-20.0, +5.3] |

Best on dev: **S2** (goal+diffs). S3 (debias wording) did not help: -6.7 CA and -6.7 OI vs S2, neither significant.

## Test (n=150), S2 run once
| arm | CA [95% CI] | FA / SA | OI [95% CI] | 1st-slot / tie | persona agree / order-consistent | calls, $ per pair | goodui CA / OI (n=67) | vwo CA / OI (n=83) |
|---|---|---|---|---|---|---|---|---|
| A0 | 30.7 [23.3, 38.0] | 44.7 / 62.0 | 56.3 [49.0, 63.7] | 38.3 / 4.7 | 80.7 / 55.8 | 13.0, $0.0070 | 20.9 / 49.3 | 38.6 / 62.0 |
| S2 | 46.0 [38.0, 54.0] | 49.3 / 63.3 | 61.3 [53.7, 69.0] | 41.3 / 4.0 | 76.8 / 67.2 | 14.0, $0.0078 | 41.8 / 61.9 | 49.4 / 60.8 |

| comparison | dCA [95% CI] | dOI [95% CI] |
|---|---|---|
| S2 - A0 | +15.3 [+6.7, +24.0] | +5.0 [-4.0, +14.0] |

Against published numbers (CA, chance 25%): paper best 39.0% (GPT-4o + multi-agent debate, all 300 pairs); G-FOCUS v1 43% (GPT-4o);
PerceptUI 44%. S2 test CA 46.0% [38.0, 54.0]. The CI overlaps all three, and the evaluated set is different (see caveats).

## A/A check (the same screenshot as both versions, 5 pairs, S3 flags = every component on)
All 5: p(A>B) = 0.500, mean diff 0.00, 6/6 persona ties, both orders 0.00, and the extractor returned 0 differences. Cost $0.031.

## Cost
Dev S1 $0.41, S2 $0.57, S3 $0.60; test S2 $1.16; A/A $0.03; smoke $0.02. Total **about $2.80** (Vertex usage metadata, list price). 0 failed calls, 0 unparseable judgments.
Per pair: S1 12 calls ($0.0055), S2/S3 14 calls ($0.008), A0 13 calls ($0.007).

## Caveats
- **The CA gain is mostly order consistency, not better direction.** OI (the order-free pick) moves little: dev S2 vs A0 +2.0 [-8, +12]; test +5.0 [-4, +14], not significant.
  S2 makes the two orders agree (persona order-consistency 53-56% -> 67-70%), so fewer pairs split across orders.
- **In S2 the per-order predictions are not independent.** The difference list is extracted in BOTH orders and merged, and the same list is used for both judging orders.
  This couples the two per-order picks, which favors CA relative to a strictly single-order system like the paper's. A stricter CA would extract per order only.
- Dev-to-test drop: S2 CA 52.0 -> 46.0 (selection on 75 dev pairs; 3 arms compared).
- A different set from the paper: 225 clean pairs (no abtest.design, 72 composite pairs excluded), inpainting smudges on GoodUI images; the paper uses 300 manually cleaned pairs with GPT-4o.
- Two images per call are shrunk to about 258 tokens each on Vertex, so small text may be unreadable. The extractor still named concrete text changes (for example CTA wording), but it may hallucinate some.
- S1 alone (ratings + order averaging) is not significantly better than A0 (+6.7 CA [-5, +19]).
- Persona agreement drops in S1 (61.9%), because ratings allow ties/near-ties that the forced single pick hid.

## Test suite
`pytest` in the worktree: 339 passed, 3 skipped, 1 failed (known: test_strength_and_weakness_cite_step_ax_and_the_final_screenshot). The 11 new tests are in mvp/test_pairwise.py.

## Product wiring
Not done by this agent (per the change of plan: an Opus cloud agent does the code on a branch off grokbot/pairwise-judge). Next step: in `mvp/comparison.py apply_comparison_llm`,
replace `persona_pick()` with `compare_pair` on run screenshots (PairEvidence per site), with flags = S2, within the 75 s budget (14 calls per pair, about 6-12 s wall at full concurrency).

Raw data: results/pw_s{1,2,3}/, pw_test_s2/, pw_aa/ (calls.jsonl, pairs.jsonl, judgments.jsonl, config.json), pw_dev_ablation.{md,json}, pw_test_ablation.{md,json}.
