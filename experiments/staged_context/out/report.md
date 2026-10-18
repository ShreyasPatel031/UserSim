# Staged-context pilot: which customer-context data helps predict reviewer experience?

**Scope.** 3 products (Asana, Trello, ClickUp) × 8 input conditions × 2 replicates = 48 product-level forecasts, scored
against the same 60 held-out Capterra reviews (20 per product). This is a random retrospective test, not a historical
forecast: today's product pages may differ from what reviewers used, and the public model may have memorized reviews.

**Status of the scores.** Every reference claim was machine-extracted (Gemini 2.5 Pro) and every match was
machine-judged by the same model. No human has audited them yet. All non-rating numbers are provisional. The 12-review
audit sample is flagged in `reference_audit.jsonl` and every contradiction or strict win is in `audit_side_by_side.md`.

## Results (macro over 3 products, mean of 2 replicates)

| Condition | Task recall ↑ | Ease MAE ↓ | Ease RPS ↓ | Benefit/friction recall ↑ | Reference disagreement ↓ | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| S0 (M) | 0.334 | 0.830 | 0.124 | 0.166 | 0.033 | $0.15 |
| S1 (M+D) | 0.340 | 0.921 | 0.140 | 0.137 | 0.017 | $0.16 |
| S2 (M+D+O) | 0.239 | 0.918 | 0.140 | 0.118 | 0.028 | $0.16 |
| S3 (M+D+O+C) | 0.366 | 0.835 | 0.124 | 0.155 | 0.054 | $0.18 |
| S4 (M+D+O+C+T) | 0.340 | **0.630** | **0.103** | 0.202 | 0.021 | $0.18 |
| A1 (M+D+C) | 0.247 | 0.756 | 0.112 | 0.158 | 0.042 | $0.17 |
| A2 (M+D+C+T) | 0.360 | **0.630** | **0.103** | 0.255 | 0.019 | $0.18 |
| A3 (M+D+T) | **0.396** | **0.630** | **0.103** | **0.305** | **0.014** | $0.19 |
| *No model: mean of 975 target pool reviews* | — | *0.621* | *0.096* | — | — | $0 |
| *No model: 20 competitor-pack reviews* | — | *0.657* | *0.108* | — | — | $0 |
| *No model: uniform* | — | *1.417* | *0.224* | — | — | $0 |

M = product seed, D = public pages, O = O*NET occupations/tasks, C = 20 competitor reviews, T = 10 target reviews.
Cost is the prediction plus judging for one replicate. Total pipeline spend was $9.36, including $1.40 lost to a
truncated first judging pass (see Limitations).

**Replicate noise is as large as most effects.** For example, S3 task recall is 0.447 vs 0.284 across the two
replicates and A2 is 0.402 vs 0.318. Treat task-recall differences under ~0.1 as noise.

## Answers

1. **Did public pages help? (S1−S0): No.**
   - Task recall was flat (0.334 → 0.340), and the per-product deltas disagree: Asana −0.24 (bootstrap CI excludes 0),
     Trello +0.19, ClickUp +0.07.
   - Rating error got worse (MAE 0.83 → 0.92) and benefit/friction recall fell (0.166 → 0.137).
2. **Did O\*NET help before reviews? (S2−S1): No for tasks and experience; maybe for audience.**
   - Task recall fell to 0.239, driven by ClickUp (0.36 → 0.06).
   - Benefit/friction recall fell to 0.118.
   - Audience top-3 coverage was the only metric that rose (0.216 → 0.283), and the role codebook is noisy.
3. **Did competitor reviews help? (S3−S2): Yes relative to S2, but only back to the S0 level.**
   - Task recall recovered to 0.366 (Asana +0.14 and ClickUp +0.41, both CIs exclude 0; Trello −0.03).
     That is within noise of the plain model (0.334).
   - The rating MAE (0.835) is no better than S0. It is much worse than simply averaging the same competitor reviews'
     ratings without a model (0.657).
4. **Did target reviews help? (S4−S3): Yes for ratings and experience, not for tasks.**
   - Rating MAE fell 0.835 → 0.630 in all 3 products.
   - Benefit/friction recall rose in all 3 (0.155 → 0.202).
   - Task recall moved −0.03, negative in all 3 but every CI includes 0.
   - **Caveat:** with T present, the model's rating forecast is *exactly* the empirical distribution of the 10 T
     reviews, in every condition and replicate (e.g. Trello [0, 0, 0, .2, .8]). The model adds nothing beyond
     aggregation; it ties the no-model T-pack baseline (0.630) and slightly loses to the full-pool mean (0.621).
5. **Did O\*NET still help with reviews? Inconsistent: the sign flips.**
   - S3 vs A1 (with competitor reviews): O raised task recall 0.247 → 0.366 (Asana and Trello CIs exclude 0) but
     worsened MAE (0.756 → 0.835).
   - S4 vs A2 (with both review sources): O lowered task recall (0.360 → 0.340; Asana and Trello CIs exclude 0) and
     benefit/friction recall (0.255 → 0.202).
6. **Did competitors add value once target reviews existed? (A2 vs A3): No.**
   - A3 (no competitors) was at least as good: task 0.396 vs 0.360, benefit/friction 0.305 vs 0.255, identical ratings.
   - Per product the task delta is mixed (Asana +0.17 for A2; Trello and ClickUp favour A3).
7. **Smallest bundle that performed best, per output:**
   - **Tasks:** none clearly beats S0 (M only, 0.334). A3 has the top mean (0.396), but the gap is inside replicate noise.
   - **Ratings:** no model at all. The mean rating of target reviews (0.621) beats every model condition; if there are
     no target reviews, the competitor-review average (0.657) beats every model condition without T.
   - **Experience (benefit/friction):** A3 (M+D+T), 0.305. Friction recall goes 0.175 for S0 → 0.304 for A3.
     D-free "M+T" was not in the design, so whether D matters here is untested.
   - **Audience:** S2 (M+D+O), 0.283, but per product it ranges from 0.14 to 0.35. Inconclusive.
8. **Consistency across products.**
   - Gains from target reviews on ratings and on benefit/friction recall are consistent across all three products.
   - Almost every task-recall comparison flips sign across products. ClickUp's collapse in S2 and Trello's high A3
     score (0.525) drive the macro task differences.
9. **Blocked, machine-judged, unconfirmed or inconclusive.**
   - All task, benefit/friction and contradiction numbers are machine-judged by the same model family as the
     extractor, and unaudited.
   - Strict matching looks lenient for generic tasks. The best-confirmed task hypotheses are generic ("track project
     progress"), and they match because many reference tasks are generic too.
   - Task conclusions are inconclusive given replicate noise and 14–19 task-bearing reviews per product.
   - Nothing was blocked in this pilot. The O*NET alternate-titles file was not used: it is optional and is not
     published under that name in O*NET 31.0.

## Examples (machine-selected; see `audit_side_by_side.md`)

Improvements (a hidden reference task gained a strict match):
- **Asana, S0 → S1 (+D):** no match before; after, "Manage workloads and resource allocation for team members".
  Hidden: "managing our project resources".
- **Trello, S1 → S2 (+O):** no match before; after, "Organize daily to-dos for personal or team accountability".
  Hidden: "organize and execute multiple projects and to-do lists while collaborating with other team members".
- **ClickUp, S2 → S3 (+C):** no match before; after, "Search and consolidate information across connected apps".
  Hidden: "manejar todo en un solo lugar".

Regressions (a strict match was lost):
- **Asana, S0 → S1 (+D):** before, "Create and assign tasks to team members"; no match after.
  Hidden: "assign work to colleagues with deadlines to keep a project moving along".
- **Trello, S1 → S2 (+O):** before, "Track task progress by adding due dates and marking cards as 'Done'"; no match
  after. Hidden: "managing in progress work".
- **ClickUp, S2 → S3 (+C):** before, "Track project progress with assignees and due dates"; no match after.
  Hidden: "track the workflow every day".

Contradiction pattern (Trello, A2): the predicted friction "requires some learning or setup time" was contradicted by
eight separate reviewers who called Trello easy to use. Without target reviews the model systematically under-predicts
ease. Expected ease in S0 was 3.8 / 4.0 / 3.4 against actual means of 4.6 / 4.5 / 4.05 (Asana / Trello / ClickUp).

## Recommendation

| Data source | Tasks | Audience | Experience (benefit/friction/rating) |
| --- | --- | --- | --- |
| D: public pages | drop | collect more | drop (MAE and recall worsened) |
| O: O*NET | drop (sign flips) | collect more (only positive signal; noisy) | drop |
| C: competitor reviews | collect more (no gain over S0) | collect more | **keep as a numeric rating prior** for a new product without reviews (0.657, beats every no-T model condition); drop as LLM prompt context |
| T: target reviews | drop for tasks (no gain) | collect more | **keep**: biggest, most consistent gain; for ratings, use the plain average rather than routing it through the model |

**For a new product** (no target reviews), nothing we added improved task or experience prediction over the plain
model. The one usable signal is numeric: competitors' review ratings give a better ease-of-use prior than anything the
model produced. Once even 10 target reviews exist, they dominate. The next test is the matched reviewer-task pilot
below, which asks whether UserSim execution adds information that this context cannot.

## Matched reviewer-task pilot (UserSim): status

Requested mid-run. Code is in `matched.py`; outputs go to `out/matched/`. Unit: one review. Visible: role, industry,
company-size band, tenure band, and a neutral description of the reviewer's dominant task, with evaluative wording
rejected by a filter. Hidden: ease rating, pros/cons, frictions. Conditions A (D + card), B (A + O + C), C (B + generic
agent observations) and D (B + UserSim observations with reviewer context) use the same final predictor and the same
cases. Baselines: the target pool mean rating and the competitor-pack distribution. See the session notes for run
status and blockers.

## Limitations

- Three products, 20 reviews each, 2 replicates: a diagnostic pilot, not evidence about other products.
- The first judging pass truncated 24/48 sets: Gemini 2.5 Pro thinking tokens count against the output limit. All 48
  were re-judged with identical settings (16k output, 2,048 thinking budget). Failed judgments are now treated as
  missing, never zero. The truncated pass is kept in `judgments_v1_truncated.jsonl`.
- Token counts in the evidence manifest are approximate (chars/4). Actual API tokens are in `call_log.jsonl`.
- Trello's public pages are thin: about 580 target tokens vs about 1,500 for Asana and ClickUp.
- O*NET task selection is lexical: Core tasks first, then word overlap with D. It picked some off-topic tasks (e.g. a
  sustainability task under Marketing Managers).
- Conditions with more packs also have longer prompts. Gains are not length-controlled.
