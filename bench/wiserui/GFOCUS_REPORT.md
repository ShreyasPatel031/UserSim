# WiserUI-Bench: full G-FOCUS arm (strict, per-order) + cost analysis (2026-09-27 PT)

Branch `grokbot/pairwise-judge`. Judge gemini-2.5-flash on Vertex, thinking off, 429 backoff with multi-region fallback
(`mvp.e2e_ui_run.gemini_generate`). Set: the 252 clean pairs (`fullset/final_indices_main.txt`), held-out = minus the 75 dev pairs (177).

## What was added
`mvp/pairwise.py`, behind new `PairFlags` fields. Existing flags keep their semantics, and the defaults are unchanged:
- `argue_both`: G-FOCUS steps 3-4 (arXiv 2505.05026**v1**, Appendix E, Parts 3-4). "Assume the first version was more visually
  persuasive ... make reasonable reasons", then separately the same for the second version. An Evaluator gets both reason
  lists, ranks them by importance and answers `Better version: First/Second`. This replaces the 1-10 ratings.
- `v1_prompts`: steps 1-2 use Appendix E Part 1 (goal) and Part 2 (goal-conditioned key UI differences: design priorities,
  UI areas, then "First UI ..., Second UI ..." lines) instead of our JSON `_GOAL_DIFFS`. These run **per presentation order**,
  so each order has its own goal, diffs, reasons and verdict and the orders are fully independent (strict, as in the paper).
- `use_personas=False`: one neutral evaluator (the paper). With personas, "Assume that a user is currently engaging with the page"
  names the persona (name, role, bio, own goal). The evaluator also "concludes from this user's point of view" and adds
  `Confidence: 1-5`. An order's pick is the confidence-weighted persona vote.
- `argue_temperature=1.0`: the paper ran every model at temperature 1 (Appendix F). Calls are text mode (not JSON),
  and the prompt is followed by the two screenshots unlabelled, as in the repo's inference code. If the evaluator reply has
  no parseable verdict it is asked again up to 2 more times, as the repo re-asks when the answer format is missing.
- Prompts are the v1 appendix text verbatim. The only edits: placeholders filled (company, industry, page type, web/mobile),
  curly quotes and arrows turned into ASCII, and the PDF typo "is industry domain}" read as the `{industry domain}` placeholder.
- run_bench streams: `gfocus` (a) and `gfocus_personas` (b). (b) reuses (a)'s goal and diff calls (copied into its ledger at $0),
  so (a) and (b) differ only in steps 3-4. (b) uses the same personas as S2-strict (A0 planner, or preplan copies from pw_all_s2strict).
- Tests: `mvp/test_pairwise.py` has 4 new tests (15 pass).

## Results (CA = right in both orders, the paper's headline; chance 25%)
| arm | CA all 252 [95% CI] | CA held-out 177 | AA | FA / SA | OI | GoodUI 102 | VWO 131 | abtest 19 | recovered 25 |
|---|---|---|---|---|---|---|---|---|---|
| S2-strict (6 personas, 1-10 ratings) | 40.5 [34.5, 46.4] | 39.5 [32.2, 46.9] | 57.3 | 46.8 / 67.9 | 61.1 | 31.4 | 48.9 | 31.6 | 40.0 |
| **(a) G-FOCUS single judge (paper-faithful)** | **44.8 [38.5, 51.2]** | 42.9 [35.6, 50.3] | 62.1 | 56.3 / 67.9 | 62.7 | 32.4 | 52.7 | 57.9 | 60.0 |
| (b) G-FOCUS + 6 personas | 41.7 [35.7, 47.6] | 41.8 [34.5, 49.2] | 57.9 | 58.3 / 57.5 | 63.1 | 29.4 | 48.1 | 63.2 | 60.0 |
| paper (all 300, GPT-4o): best baseline, multi-agent debate | 39.0 | | | | | | | | |
| paper: G-FOCUS v1 (GPT-4o) | 43.3 | | | | | | | | |
| PerceptUI | 44.3 | | | | | | | | |

Paired bootstrap (10k, pair level):
| comparison | dCA all | dCA held-out | dOI all |
|---|---|---|---|
| (a) G-FOCUS - S2-strict | +4.4 [-2.8, +11.5] | +3.4 [-5.1, +11.9] | +1.6 [-4.6, +7.7] |
| (b) G-FOCUS+personas - S2-strict | +1.2 [-5.2, +7.5] | +2.3 [-5.6, +10.2] | +2.0 [-3.8, +7.7] |
| (b) - (a) | -3.2 [-9.1, +2.8] | -1.1 [-8.5, +6.2] | +0.4 [-5.2, +6.0] |

Full tables: `fullset/gfocus_vs_s2strict.md`, `fullset/gfocus_personas_vs_s2strict.md`, `fullset/gfocus_personas_vs_gfocus.md`.

Reading:
- The paper-faithful G-FOCUS on gemini-2.5-flash reaches CA 44.8. That is above the paper's G-FOCUS/GPT-4o (43.3) and level with
  PerceptUI (44.3), but the CI [38.5, 51.2] covers all of them, and it is **not significantly better than S2-strict** (+4.4, CI crosses 0).
  Most of the gain is FA (winner shown first): 46.8 -> 56.3, so G-FOCUS removes part of S2's second-position bias.
- Personas do not help G-FOCUS: (b) is 3.2 CA below (a) (not significant). (b) is the least position-biased arm (FA 58.3 vs SA 57.5).
  Pure majority vote without the confidence weights gives CA 38.5 (55 of 504 orders end in 3-3 ties). Persona confidences are almost
  always 4-5, so the weights add little.
- GoodUI stays near chance-level CA (~30%) for every arm. The gains are on VWO, abtest.design and the recovered composites
  (small n: 19 and 25).
- Unparsed verdicts: (a) 3 of 504 evaluator verdicts after retries (89: "Better version: None", the model saw no difference;
  188 and 255: the model claimed the images were missing or wrong, which is worth an image check). (b) 14 of 3024. These count as wrong.

## Spend (Vertex usage metadata, list price)
(a) $2.84 (including a $0.03 3-pair smoke run), (b) $12.89. **Total this job about $15.7** (about 5% over the ~$15 budget; (b) is 12 persona-order chains per pair).

## Cost analysis
Prices were checked 2026-09-27 PT. Sources:
- Vertex AI (Gemini Enterprise Agent Platform) generative AI pricing: https://cloud.google.com/vertex-ai/generative-ai/pricing
- Gemini Developer API pricing (page "last updated 2026-09-24 UTC"): https://ai.google.dev/gemini-api/docs/pricing
- Supervised tuning, supported models and limits (page "last updated 2026-09-25 UTC"): https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/tuning/supervised-tuning
- Image tokens: https://ai.google.dev/gemini-api/docs/generate-content/tokens and https://ai.google.dev/gemini-api/docs/generate-content/media-resolution
- Thinking (2.5 Pro minimum budget 128, cannot be turned off; Gemini 3.x cannot be turned off): https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking

### Prices (USD per 1M tokens, <=200k context; Vertex standard PayGo; Gemini API paid tier is the same for these models)
| model (status) | input (text/image) | output (incl. thinking) | batch / flex | priority | SFT training | tuned-model inference |
|---|---|---|---|---|---|---|
| gemini-2.5-flash (GA) | 0.30 | 2.50 | 0.15 / 1.25 | 0.54 / 4.50 | $5.00 per 1M (`$0.005/1k`) | same as base |
| gemini-2.5-pro (GA) | 1.25 (2.50 >200k) | 10.00 (15.00 >200k) | 0.625 / 5.00 | 2.25 / 18.00 | $25.00 per 1M | same as base |
| gemini-2.5-flash-lite (GA) | 0.10 | 0.40 | 0.05 / 0.20 | 0.18 / 0.72 | $1.50 per 1M | same as base |
| gemini-3.8 / 3.7 / 3.6 Flash (GA), intro through 2026-12-31 | 0.75 global (0.825 regional) | 3.75 (4.125) | 0.375 / 1.875 | 1.35 / 6.75 | not tunable | n/a |
| same, from 2027-01-01 | 1.50 (1.65) | 7.50 (8.25) | 0.75 / 3.75 | 2.70 / 13.50 | | |
| gemini-3.5-flash (GA) | 1.50 (1.65) | 9.00 (9.90) | 0.75 / 4.50 | 2.70 / 16.20 | $10.00 per 1M (SFT, RL) | 1.5x base |
| gemini-3.1-flash-lite (GA) | 0.25 | 1.50 | 0.125 / 0.75 | 0.45 / 2.70 | $3.00 per 1M | 1.5x base |
| gemini-3.1-pro-preview (**preview**; no GA 3.x Pro yet, 3.5 Pro not public) | 2.00 (4.00 >200k) | 12.00 (18.00) | 1.00 / 6.00 | 3.60 / 21.60 | not tunable | n/a |

Notes on the prices:
- **Image tokens.** Gemini 2.5: an image of 384 px or less on both sides = 258 tokens; larger images are tiled into 768x768 tiles of 258 each.
  Our Vertex 2-image calls came out at about 258 tokens per image (Vertex downscales them). Gemini 3.x uses `media_resolution`:
  default/high 1120 tokens per image, medium 560, low 280, ultra_high 2240. Images are billed at the text input rate.
- **Batch and Flex** are 50% off standard on both input and output. Priority is 1.8x.
- For Gemini 3+ on **non-global (regional) endpoints**, prices are 10% higher from 2026-07-01. Our multi-region fallback uses regional endpoints.
- **SFT** is billed on training tokens = dataset tokens x epochs. Vertex lists **no hosting or node-hour fee** for tuned Gemini endpoints: they are
  billed per token. For Gemini 2.5 a tuned endpoint costs the same as the base model. "For model inference starting from Gemini 3, tuned model
  endpoint prediction price will be 1.5 times of the base model." SFT-capable models: 3.5 Flash, 3.1 Flash-Lite, 2.5 Pro, 2.5 Flash,
  2.5 Flash-Lite. Up to 300K multimodal examples, 131k tokens per example. 3.5 Flash and 3.1 Flash-Lite tune only in us-central1 and
  europe-west4 and serve only from the us/eu multi-region endpoints. Preference tuning is listed for 2.5 Flash and Flash-Lite, RL tuning for 3.5 Flash.

### Tokens and cost per pair (measured on our logs, 252 pairs each; both orders)
| arm | calls/pair | tokens in/pair | tokens out/pair | 2.5 Flash $/pair | 2.5 Pro $/pair, same tokens | 2.5 Pro $/pair, +500 thinking tokens/call |
|---|---|---|---|---|---|---|
| S2-strict (planner + 2 goal + 12 judge) | 15.0 | 12,529 | 2,030 | **0.0088** | 0.036 | ~0.10 |
| (a) G-FOCUS single (2 goal + 2 diff + 4 reason + 2 eval) | 10.0 | 10,892 | 3,205 | **0.0113** | 0.046 | ~0.096 |
| (b) G-FOCUS + 6 personas (4 + 36 + planner) | 41.1 | 52,092 | 15,929 | **0.0555** | 0.224 | ~0.42 |

Per call: S2 judge 890 in / 98 out; G-FOCUS goal 635/62, diffs 980/364, each reason 976/~312, evaluator 1,857/547.
Full per-model table (3.8/3.5 Flash, 3.1 Pro): `fullset/cost_per_pair.md`, `fullset/cost_project.md`.

### Per product study: our product vs 2 rivals, 6 personas, both orders = 2 pair comparisons (personas exist already, planner excluded)
| arm | 2.5 Flash | 2.5 Pro (+thinking) | 3.8 Flash intro (+1120 tokens/image, +thinking) | 3.8 Flash 2027 | 3.1 Pro preview (+adj) |
|---|---|---|---|---|---|
| S2-strict | **$0.015** | $0.06 ($0.20) | $0.03 ($0.12) | $0.06 ($0.24) | $0.09 ($0.35) |
| G-FOCUS single | **$0.023** | $0.09 ($0.19) | $0.04 ($0.10) | $0.08 ($0.21) | $0.12 ($0.31) |
| G-FOCUS + personas | **$0.108** | $0.44 ($0.84) | $0.19 ($0.45) | $0.39 ($0.90) | $0.58 ($1.34) |

Batch/Flex halves every number. Assumptions: one screenshot per side, as in the bench. Each extra screenshot per side adds about 516 input
tokens per call on 2.5 (for S2-strict about +$0.002 per pair on Flash) and 2,240 per call on Gemini 3 at default resolution. The judging
step is a rounding error next to the study's browsing and persona-run cost at every model tier.

### Fine-tuning estimate (3 epochs; tokens per example from our logs)
| example | tokens/example | 1k examples | 5k | 20k |
|---|---|---|---|---|
| verdict-only (one S2 judge call: 2 images + persona prompt -> ratings) | ~990 | 2.5 Flash $15 / 3.5 Flash $30 / 2.5 Pro $74 | $74 / $148 / $370 | $296 / $592 / $1,481 |
| one-call G-FOCUS distill (2 images + prompt -> ranked reasons + verdict) | ~1,750 | $26 / $53 / $131 | $131 / $263 / $657 | $526 / $1,052 / $2,630 |
| full G-FOCUS chain (all 5 stages of one order as examples) | ~7,050 | $106 / $211 / $529 | $529 / $1,057 / $2,643 | $2,115 / $4,229 / $10,573 |

A distilled one-call judge would cost about 2 calls per pair, about $0.002-0.003 per pair on tuned 2.5 Flash (tuned inference is the same price).
That is 4-5x cheaper than running G-FOCUS (a).

Where the training data could come from:
1. Real A/B outcomes (the only true labels). Public galleries: GoodUI, VWO case studies, abtest.design (the WiserUI sources), plus the
   older ones they archive. Check licences. WiserUI itself is CC BY-NC-SA and is our eval set, so it must never be trained on.
   Realistically this gives a few hundred to low thousands of pairs, x2 for both orders.
2. Customer experiment histories (Optimizely/VWO/GA4 exports), with consent. This is the best source for 5k-20k examples.
3. Distillation: label product pairs with a stronger teacher (2.5 Pro or G-FOCUS, both orders, keep only order-consistent verdicts).
   Cheap, but it copies the teacher's biases and caps accuracy at the teacher.
4. Synthetic contrast pairs: degrade a real page along a known UX law (hide the CTA, add choice overload, bury the price).
   Useful as augmentation, not as ground truth.

## Caveats
- Not the paper's set (252 of 300; see FULLSET_REPORT.md), not the paper's model (gemini-2.5-flash vs GPT-4o), and our images are auto-inpainted.
  The comparison with published numbers is indicative only. All three published numbers fall inside our CI.
- Temperature 1 makes G-FOCUS stochastic. A rerun would move CA by a few points; the paired CIs above include pair sampling only, not run-to-run variance.
- (b) is our persona adaptation, not the paper's method (persona in the reasoning and evaluator prompts, plus a 1-5 confidence).
- Pro and Gemini 3 costs are **projections**: the same token counts re-priced, plus a flat 500 thinking tokens per call and Gemini 3's
  default 1120 tokens per image. Real Pro outputs are usually longer, and 3.x with `media_resolution=low` (280 per image) would cost close
  to the "as measured" column. Pro accuracy was not measured.
- The fine-tuning token counts assume the same image tokenization as our 2-image inference calls. A single large screenshot per side in
  training data may tile into more tokens.
