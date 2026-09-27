# WiserUI-Bench, full set: recovered composites + S2 / S2-strict with paper metrics (2026-09-27 PT)

Branch `grokbot/pairwise-judge`. Judge: gemini-2.5-flash (Vertex, thinking off), the same S2 arm as PAIRWISE_REPORT.md
(both orders, 1-10 ratings, goal and diffs, no debias, 6 personas: A0's cached planner, or `ab_personas` for pairs A0 never saw).

## Data recovery (300 dataset items)
- 225 original clean pairs, unchanged.
- **20 / 21 (404):** the loser images still exist on goodui.org under other folder ids (`files/5009/leak047_ffull.jpg`,
  `files/5097/leak047_hfull.jpg`; the dataset has `files/5006/...`). Cleaned with the repo's `image_preprocess.process_image`. Both recovered.
- **103 (no URL):** the VWO page no longer shows the test. A Wayback snapshot (2023-06-04) has the composite
  `uploads/2022/12/Human-Interest-2.png`. The variation won (+75.84%, as the page says). Recovered as a composite.
- **73 composites** (72 plus 103): `composites.py split`. gemini-2.5-pro (thinking) gets the composite, the item's ui_change and rationale,
  and the source page text. It returns tight panel boxes for this item's two versions and says which one won (evidence plus confidence).
  The panels are cropped as-is (no masking or inpainting, per the user). Every winner call came back "high" confidence.
  - Multi-variant composites that several items share: the model picked the headline "winner vs control" pair for each item,
    which duplicated pairs. I assigned them by hand from the rationale and source (`PAIR_HINTS`): 158 = V2>V1, 159 = V2>V3
    (Trent Drains), 293 = C>B and 294 = A>B (Unacademy: C 13k > A 9k > B 7k clicks). 157 = V2>Control and 292 = C>A were already right.
  - 280: the pro model answered boxes on a ~0-1920 x scale twice. I rescaled x by 1/1.92 and checked the crop by eye.
  - **6 unrecoverable** (the image shows only ONE version): 62 (GoodUI thumbnail), 149, 174, 228, 269, 270.
- **Leak check** (`composites.py leak`): gemini-2.5-flash on the composite and on each crop. JSON: leak, cue type/text/location, single_full_ui.
  A pair counts as leaky if either crop leaks. **24 leaky** (list in fullset/sets.json and below). **43 Gemini-clean**.
- **Manual review** (contact sheets of every crop plus pixel checks) found cues that Gemini missed in 9 of the 43:
  - publisher highlight boxes in the winner panel: 168, 212, 226
  - abtest.design A/B badge fragments at a crop corner (blue B/C on the winner, gray A on the loser): 273, 279, 282, 284, 295, 297
  - borderline, VWO frame-color residue at crop edges (orange/purple = variation, blue = control): 103, 117, 150, 158, 159, 181, 232, 239, 240
- Headline set **"clean" = 227 + 25 = 252 pairs** (no leak found by Gemini or by me, frame residue excluded).
  Sensitivity: 261 (plus frame residue) and 270 (every Gemini-clean pair).

## S2-strict
`PairFlags.strict_orders`: each presentation order uses only the goal and diffs extracted in THAT order (no merge across orders),
so the two per-order picks are independent, as in the paper's per-order evaluation. Stream `s2strict` in run_bench.py.
Same personas as S2 (preplan.py writes the same planner call into both ledgers). The goal-extraction calls are identical and were reused from the cache.

## Metrics (paper eval/task1_eval.py): CA = right in both orders (chance 25%); AA = mean per-order accuracy; FA/SA = winner shown first/second;
OI = one order-free pick from ratings averaged over both orders, tie = 0.5 (chance 50%, not in the paper). 95% CIs: 10k pair bootstrap.

### Clean set (252) -- `fullset/pw_all_main.md`
| view | n | S2 CA [95% CI] | S2-strict CA [95% CI] | S2 AA | strict AA | S2 OI | strict OI |
|---|---|---|---|---|---|---|---|
| all | 252 | 49.2 [42.9, 55.2] | 40.5 [34.5, 46.4] | 58.1 | 57.3 | 62.1 | 61.1 |
| held-out (minus 75 dev) | 177 | 48.0 [40.7, 55.4] | 39.5 [32.2, 46.9] | 57.6 | 55.6 | 62.1 | 60.2 |
| GoodUI | 102 | 45.1 [35.3, 54.9] | 31.4 [22.5, 40.2] | 54.4 | 52.5 | 60.8 | 57.8 |
| VWO | 131 | 52.7 [44.3, 61.1] | 48.9 [40.5, 57.3] | 61.5 | 61.5 | 63.7 | 64.1 |
| abtest.design | 19 | 47.4 [26.3, 68.4] | 31.6 [10.5, 52.6] | 55.3 | 55.3 | 57.9 | 57.9 |
strict - S2: dCA -8.7 [-13.9, -4.0] (all), -8.5 [-14.7, -2.3] (held-out); dOI -1.0 [-6.0, +4.0].

### Every Gemini-clean pair (270) -- `fullset/pw_all_gclean.md`
all: S2 49.6 [43.7, 55.6] / strict 40.7 [34.8, 46.7]; held-out (195): 48.7 [42.1, 55.4] / 40.0 [33.3, 46.7];
abtest (25): 48.0 / 28.0; recovered composites only (43): 55.8 / 41.9; original 227: 48.5 / 40.5.

Reference (CA): chance 25%, paper best 39.0% (GPT-4o + multi-agent debate, all 300), G-FOCUS v1 43.3% (GPT-4o), PerceptUI 44.3%.

## Cost (Vertex usage metadata, list price)
Composite split (pro) + leak (flash) $2.53; S2 new pairs $0.40 (the 225 old pairs are cached from pw_s2 / pw_test_s2); S2-strict $1.72.
This round **about $4.66**; cumulative with the earlier ablation about $7.5.

## Caveats
- Not the paper's set: 252 of 300 (6 single-version images, 24 Gemini-leaky and 18 manual flags are out), and the paper cleaned its images by hand.
  The GoodUI images carry the repo's automatic inpainting smudges.
- S2 CA gets help from the cross-order diff merge. The paper-style number is **S2-strict, 40.5 [34.5, 46.4]**: above the paper's 39.0,
  below G-FOCUS 43.3 and PerceptUI 44.3, and the CI covers all three. The order-free OI barely moves (62 vs 61).
- The dev pairs (75) chose S2, so the held-out view is the fair one. The 227 base pairs come from the same runs as the earlier report (cache).
- Crops are unmasked. The Gemini leak check missed obvious highlight boxes and badge fragments (found by eye), so more subtle cues may remain.
  Some crops are partial or small (181 is about 205x350; 159, 247 and 291 are cut off as in the source composite).
- Two images per call are downscaled by Vertex (about 258 tokens each), so small text changes may be unreadable, as before.
- Winner labels for composites come from the rationale and source text through gemini-2.5-pro; all were spot-checked on the contact sheets. 232 is V2 vs Control (the loser could arguably be V1).
