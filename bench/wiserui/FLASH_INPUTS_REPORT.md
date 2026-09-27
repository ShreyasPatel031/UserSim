# Which extra inputs help gemini-2.5-flash on WiserUI? (2026-09-27 PT)

Branch `grokbot/pairwise-judge`, the same module as the G-FOCUS work (`mvp/pairwise.py`).
Model: gemini-2.5-flash only (Vertex, thinking off, 429 backoff with multi-region fallback).

**Baseline.** G-FOCUS single judge, v1 prompts, strict (every order runs its own goal, diffs, both-side reasons and Evaluator),
both orders, temperature 1. This is stream `gfocus` from GFOCUS_REPORT.md; its cached run is reused as the baseline.

**Arms.** Each arm adds ONE input to the baseline. Dev = the 75 dev pairs. Held-out = the other 177 of the 252 clean pairs.

## The inputs (all are `PairFlags` fields in `mvp/pairwise.py`)
Each input is computed once per pair, independent of order. It goes into EVERY G-FOCUS stage prompt (goal, diffs, reasons, Evaluator)
as an "Additional information" block, written in that order's First/Second terms. Crops are also attached as extra images.
`run_bench.py --inputs a,b` turns inputs on; `render_extras` / `gfocus_extras` build the blocks.

| flag | input | source in the bench | available in the product? | leak? |
|---|---|---|---|---|
| `gf_goal` | stated page goal | `ctx["task"]` / `ctx["goal"]` if given; otherwise one text-only call from company, page type and industry (the bench has no task text) | yes (the study's task list) | no |
| `gf_diff_list` | explicit A/B difference list | the existing JSON diffs step (`extract_goal_and_diffs`, both orders merged). Calls copied from the S2-strict ledger (same prompt, temperature 0) | yes | no. The orders share this input, so the per-order picks are no longer strictly independent |
| `gf_page_text` | each version's page text | `PairEvidence.summary`, filled with Tesseract OCR of the full-resolution screenshot (up to 2,500 chars each) | yes (DOM or accessibility text, cleaner than OCR) | no |
| `gf_crops` | zoomed crops of the regions that differ | `diff_regions`: pixel diff on a 16px grid. Boxes over 35% of the page fall back to the band between the first changed row from the top and from the bottom. Up to 3 crop pairs. 50/75 dev pairs got crops (the rest do not line up) | only for two versions of the SAME page; meaningless for rival sites | no |
| `gf_audience` | short target-user list | the 6 personas already planned for the page (name, role, goal) | yes | no |
| `gf_change` | what the test changed | the dataset's `ui_change` ({element: attributes}, e.g. "Button: Presence") | only for your own A/B test (the experimenter knows the change); not for rivals | **borderline**. Written by the annotator; says what changed, not which side won |
| (not used) | paper `rationale`: reasons and UX-law names | | no | **leaks**: written from the winner's side ("the right version ..."). Excluded |
| (not used) | `source` (goodui / vwo / abtest) | | no | not a leak, but not a product input |

I added one arm: `base_rep`, a second independent sample of the baseline. It measures run-to-run noise at temperature 1.

## Dev results (75 pairs)
`fullset/flash_inputs_dev.md`. Paired test: exact McNemar on per-pair CA, plus a 10k bootstrap CI on dCA.
Significant = p < 0.05 and the CI excludes 0.

| arm | CA [95% CI] | dCA vs base [95% CI] | McNemar p | significant | OI | $/pair |
|---|---|---|---|---|---|---|
| base (G-FOCUS single) | 49.3 [38.7, 60.0] | | | | 66.0 | 0.0114 |
| base_rep (same flags, new sample) | 46.7 [36.0, 58.7] | -2.7 [-14.7, +9.3] | 0.83 | no | 63.3 | 0.0115 |
| + goal | 46.7 [34.7, 57.3] | -2.7 [-14.7, +9.3] | 0.83 | no | 64.0 | 0.0115 |
| **+ diff_list** | **57.3 [46.7, 68.0]** | **+8.0 [-2.7, +18.7]** | 0.21 | no | 66.7 | 0.0126 |
| + page_text (OCR) | 40.0 [29.3, 50.7] | -9.3 [-21.3, +2.7] | 0.19 | no | 63.3 | 0.0124 |
| + crops | 46.7 [36.0, 57.3] | -2.7 [-14.7, +9.3] | 0.82 | no | 60.7 | 0.0131 |
| + audience | 50.7 [40.0, 62.7] | +1.3 [-12.0, +14.7] | 1.00 | no | 69.3 | 0.0127 |
| + change (borderline leak) | 50.7 [40.0, 62.7] | +1.3 [-12.0, +14.7] | 1.00 | no | 66.0 | 0.0102 |

- **Noise is the main finding.** The two baseline samples agree on per-pair CA for only 53 of 75 pairs, and 22 pairs flip.
  At n=75 an arm needs about +12 CA to be detectable.
- Against the mean of the two baseline samples, diff_list is +9.3 [+0.7, +18.0]. That excludes 0, but it is uncorrected across 6 arms.
  The others: audience +2.7, change +2.7, goal -1.3, crops -1.3, page_text -8.0 (all CIs include 0).
- page_text makes position bias worse (FA 48.0 vs SA 78.7). Noisy OCR text seems to push the model toward the second version.
  crops also lowers FA (49.3) and costs the most.
- **Picked for held-out:** diff_list (best dev CA) and audience (best dev OI and AA among arms available for rival comparisons too),
  plus their combination. change was not taken to held-out: it is borderline and unavailable for rival comparisons.

## Held-out results (177 pairs; the baseline is the cached G-FOCUS run) -- `fullset/flash_inputs_heldout.md`
| arm | CA [95% CI] | dCA vs base [95% CI] | McNemar p | significant | AA | FA / SA | OI | $/pair |
|---|---|---|---|---|---|---|---|---|
| base | 42.9 [35.6, 50.3] | | | | 61.0 | 54.2 / 67.8 | 61.3 | 0.0112 |
| + diff_list | 44.6 [37.3, 52.0] | +1.7 [-6.8, +10.7] | 0.80 | no | 61.6 | 50.8 / 72.3 | 61.9 | 0.0124 |
| + audience | 41.2 [33.9, 48.6] | -1.7 [-9.6, +6.2] | 0.78 | no | 60.5 | 55.9 / 65.0 | 60.5 | 0.0124 |
| + diff_list + audience | 44.6 [37.3, 52.0] | +1.7 [-6.8, +10.2] | 0.80 | no | 61.9 | 52.0 / 71.8 | 62.1 | 0.0135 |

By source (held-out CA, base -> diff_list): GoodUI 27.5 -> 36.2 (n=69), VWO 51.7 -> 48.3 (89), abtest 57.9 -> 57.9 (19).

## What helps
- **Nothing is a reliable win.** The dev +8 for diff_list shrinks to +1.7 on held-out (not significant). That is the expected shrinkage
  when picking the best of 6 noisy arms. The difference list may help GoodUI (the small UI changes), but that is not established.
- **audience** (target users) is neutral. **goal** (from metadata) adds nothing the prompt did not already have.
- **page_text (OCR)** and **pixel-diff crops** do not help and may hurt. OCR is noisy and the crops include inpainting smudges.
  Real DOM text could behave differently from OCR.
- **change hint** is neutral and borderline. It is not recommended for the product except for own-page A/B tests.
- The limiting factor looks like judgment noise (temperature 1, one sample) rather than missing inputs. Cheap next levers are
  temperature 0 and several samples per order (self-consistency). Those are output-side, not input-side.

## Spend
Smoke $0.04; dev arms $6.19 (7 new runs x 75 pairs, the baseline was cached); held-out $6.25 (3 x 177). **Total $12.49** (budget ~$15).
Cost per pair: baseline $0.0114. Every input adds $0.001-0.002 per pair, except change, whose run happened to produce shorter outputs.

## Outputs for the planned fine-tune ("final pick + brief reasoning")
`export_ft.py` writes one JSON line per (pair, order). Fields:
- arm and its input flags;
- index, order and image paths for the first and second version (crops can be recomputed with `diff_regions`);
- ctx, plus the inputs used: goal, key differences, and the "Additional information" block;
- `gold` (the winner's position: First or Second), `pick` and `correct`;
- `brief_reasoning` (the Evaluator's Key Rationale), `importance_ranking`, both reason lists and the raw Evaluator text.

Exported to `/workspace/bench/wiserui/ft/` on the box (not committed; they contain dataset-derived text):
- `flash_inputs_base.jsonl`: 504 rows, all 252 pairs;
- `flash_inputs_dev_<arm>.jsonl`: 150 rows each;
- `flash_inputs_heldout_<arm>.jsonl`: 354 rows each.

For training, a sensible filter is `correct == true` plus consistency across both orders.
**WiserUI is our eval set and CC BY-NC-SA**, so these rows are for building the format and pipeline and for sanity checks.
Real training rows should come from non-WiserUI pairs run through the same code path.

## Caveats
- 75 dev pairs cannot resolve effects under about 10 CA points given the run noise, and there is a single held-out sample per arm.
  The held-out baseline is the cached run, not a fresh sample, so its noise is uncorrected.
- The diff_list arm shares one merged difference list across both orders, so its orders are not fully independent (unlike strict G-FOCUS).
- Crops are pixel-diff boxes on auto-inpainted images: some boxes land on inpainting smudges or on shifted content, and 25 of 75 dev pairs got no crops.
- Every image in a multi-image Vertex request is downscaled to about 258 tokens, so crops add context rather than full resolution.
