# Vanilla frontier models vs our judge on WiserUI-Bench (2026-09-27 PT)

**Current round (06:37 AM PT request):** redone with the newest frontier models only, as of 2026-09-27. Cap $20, no tuning,
nothing enabled in GCP. The first round (06:28 AM PT) used older models; it is kept below under **Older models**.
**Claude 5 addendum (07:14 AM PT):** Claude Opus 5.5 and Sonnet 5 became reachable, so both were run in full on the same
252 pairs, with the same setup, under a separate cap ($25 total for the Claude round). See **Results: Claude 5 models** below.

## Results: Claude 5 models (252 pairs) -- `fullset/vanilla_compare_claude5.md`
| system | CA [95% CI] | OI | FA / SA | unparsed (of 504) | $/pair | total $ | wall (active) | dCA vs ours [95% CI] | McNemar p (ours-wrong-model-right / reverse) |
|---|---|---|---|---|---|---|---|---|---|
| **ours**: G-FOCUS single, T0, gemini-2.5-flash | 42.9 [36.5, 48.8] | 59.9 | 51.6 / 68.3 | 1 | 0.0110 | 2.77 | 89 s | (reference) | |
| **Claude Opus 5.5 vanilla** (`claude-opus-5-5`) | **66.7 [60.7, 72.6]** | 75.4 | 67.9 / 82.9 | 0 | 0.0562 | 14.16 | 146 s | **+23.8 [+16.3, +31.3]** | **1.5e-08** (87/27) |
| Claude Sonnet 5 vanilla (`claude-sonnet-5`) | 37.3 [31.3, 43.3] | 58.1 | 40.1 / 76.2 | 0 | 0.0258 | 6.50 | 149 s | -5.6 [-12.3, +1.2] | 0.14 (31/45) |

The same Claude runs against the two plain Gemini 3.x baselines (paired on the same 252 pairs, model minus baseline):

| Claude model | vs Gemini 3.1 Pro vanilla (57.9) | vs Gemini 3.8 Flash vanilla (54.4) |
|---|---|---|
| Opus 5.5 (66.7) | **+8.7 [+2.0, +15.1], p = 0.014** (48/26) | **+12.3 [+6.0, +18.7], p = 0.00024** (50/19) |
| Sonnet 5 (37.3) | **-20.6 [-27.4, -14.3], p = 5e-9** (15/67) | **-17.1 [-23.4, -10.7], p = 6e-7** (16/59) |

(Files: `fullset/vanilla_compare_claude5_vs_g31pro.md`, `fullset/vanilla_compare_claude5_vs_g38flash.md`.) Opus 5.5 vs Sonnet 5:
+29.4 [+21.8, +36.5], p = 2e-13.

**Verdicts (Claude 5):**
- **Claude Opus 5.5 is the best system measured: CA 66.7.** It beats ours by +23.8 points (p = 1.5e-8), and it significantly beats
  the previous best, vanilla Gemini 3.1 Pro (+8.7, p = 0.014), and Gemini 3.8 Flash (+12.3, p = 0.0002).
  The gain is not only position consistency: OI 75.4 (ours 59.9, 3.1 Pro 71.0), FA 67.9, SA 82.9.
- **It is the most expensive per pair:** $0.056/pair, 5.1x ours, 2.9x Gemini 3.1 Pro, 7.8x Gemini 3.8 Flash.
- **Claude Sonnet 5 is not better than ours:** 37.3 vs 42.9, -5.6 (not significant, p = 0.14), at 2.3x our cost. It has strong
  second-position bias (FA 40.1 / SA 76.2), like Sonnet 4.6 in round 1 (36.5). Both Gemini 3.x vanilla models beat it significantly.
- **Caveats:**
  - Claude 5-generation models reject a non-default temperature and always think adaptively. They therefore ran at default
    sampling with adaptive thinking (thinking tokens billed as output, max_tokens 2048 + 8192 headroom), not at T0. Results can
    vary a little between runs; each order was called once.
  - The contamination caveat below applies too: Opus 5.5's training data may include some of the public A/B write-ups.
- **Details:**
  - Model IDs that worked: `claude-opus-5-5` and `claude-sonnet-5` on Vertex AI (publisher `anthropic`) in
    `project-amer-scs-sandbox`, `global` endpoint (the `us` multi-region endpoint also answered probes).
    The earlier 429 (Opus, no quota) and 404 (Sonnet 5) had cleared by 07:08 PT. The code fix: `claude_vertex_generate` now
    reaches the `us` / `eu` multi-region endpoints at `aiplatform.{us,eu}.rep.googleapis.com`.
  - Tokens per call: about 2.3k in for both models, 945 out (Opus) / 830 out (Sonnet), including thinking. Measured cost
    $0.0281/call (Opus) and $0.0129/call (Sonnet). Zero call errors and zero unparsed answers for both.
  - The Opus run was killed at 07:13 PT after 284 of 504 calls. It was resumed from the call cache (`calls.jsonl`, keyed by
    pair and order), so none of the 284 calls were re-paid; only the 220 missing calls ran. Wall time is the active call time:
    the run spans 07:09-07:19 PT (Opus) and 07:09-07:21 PT (Sonnet), including a 3-pair pilot and the gap after the kill.
  - **Hard budget cap:** `run_bench.py --max-cost` is now a hard cap on the ledger total. Every uncached call reserves its
    worst-case cost (8k input tokens + max_tokens + 8192 thinking headroom, at list price) before it starts, and is refused if
    the reservation would cross the cap. Short-pick pairs reserve both calls up front and wait for in-flight pairs, so a capped
    run stops on whole pairs in index order. Caps used: Opus ledger $24.91, then Sonnet ledger $25 - Opus total = $10.83.
    A separate watcher summed both ledgers every 5 s, with a kill at $24.99. Neither cap was reached.

**Spend, Claude round (list price $4/$20 per 1M tokens for Opus 5.5, $2/$10 for Sonnet 5):**

| item | $ |
|---|---|
| Opus 5.5: 3-pair pilot + 284 calls before the kill (07:09-07:13 PT) | 8.46 |
| Opus 5.5: the remaining 220 calls (07:18-07:19 PT) | 5.70 |
| Sonnet 5: 3-pair pilot | 0.09 |
| Sonnet 5: the remaining 498 calls (07:19-07:21 PT) | 6.42 |
| availability probes (4 x 16-token calls at 07:17 PT) | <0.01 |
| **total, Claude round** | **20.66** (cap $25) |
Set: the 252 clean pairs (`fullset/final_indices_main.txt`). Metric: strict CA, meaning right in both presentation orders
(chance 25%).

## Setup (unchanged from round 1)
- **Prompt:** the WiserUI paper's zero-shot prompt, verbatim (`inference/prompts_task1/zero_shot.txt`).
- **Calls:** one per presentation order. The answer is parsed from the last "More effective: First/Second". An unparsed answer
  counts as wrong, with no retries.
- **Images:** the same PNG bytes for every model (each screenshot fit into 1568 x 1568).
- **Output:** max 2048 tokens, plus thinking headroom where a model thinks.
- **Ours:** G-FOCUS single judge, strict, both orders, temperature 0, gemini-2.5-flash (`results/gfocus_t0_all252`). Reused,
  not rerun.

## Model selection (newest per family, checked 2026-09-27)
| family | newest model | source proving it is current | access in our accounts | run? |
|---|---|---|---|---|
| Claude Opus | **Claude Opus 5.5** (`claude-opus-5-5`, $4/$20) | platform.claude.com/docs/en/models/overview (current lineup: Fable 5.1, Opus 5.5, Sonnet 5, Haiku 4.5) | **Available by 07:08 PT; run in the Claude 5 addendum.** At 06:40 PT it was unavailable: Every call returns 429 "Quota exceeded ... input_tokens_per_minute_per_base_model" on a 16-token call, in global, us-east5, us-central1, us-east1, europe-west1, europe-west4 and asia-southeast1, again 1 min later. The model exists (not a 404), but the project has no quota for it. Raising quota is a GCP change, so it was not requested. | addendum |
| Claude Sonnet | **Claude Sonnet 5** (`claude-sonnet-5`, $2/$10, released 2026-06-30) | same Anthropic page | **Available by 07:08 PT; run in the Claude 5 addendum.** At 06:40 PT it was unavailable: 404 "not found or your project does not have access" in all 12 regions tried plus global. Not enabled; nothing was enabled. | addendum |
| OpenAI | **GPT-6 Sol** (`gpt-6-sol`, $2/$10): the "balance intelligence and cost" flagship-tier model | developers.openai.com/api/docs/models ("use GPT-6 Astra, our flagship ... GPT-6 Sol to balance intelligence and cost, or GPT-6 Luna for cost-sensitive, high-volume workloads"). `models.list` on our key lists gpt-6-astra, gpt-6-sol, gpt-6-luna (plus the older gpt-5.6-sol/terra/luna). | yes (probe OK) | yes |
| OpenAI (small) | **GPT-6 Luna** (`gpt-6-luna`, $0.10/$0.50) | same OpenAI page | yes | yes |
| OpenAI (top) | GPT-6 Astra (`gpt-6-astra`, $10/$50, reasoning at least `low`) | same OpenAI page | listed on our key; not probed | **skipped**: estimated ~$32 for 252 pairs alone, over the $20 cap (and excluded as an expensive flagship in round 1) |
| Gemini Flash | **Gemini 3.8 Flash** (`gemini-3.8-flash`, GA 2026-09-02, $0.75/$3.75 intro price on the global endpoint through 2026-12-31) | Google Cloud Gemini 3.8 Flash developer's guide and model-versions page; Vertex pricing page (cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing) | yes (global) | yes |
| Gemini Pro | **Gemini 3.1 Pro (preview)** (`gemini-3.1-pro-preview`, $2/$12). No newer Pro exists. | Vertex model-versions and pricing pages | yes (global) | yes |

Settings:
- **GPT-6 Sol and Luna:** `reasoning_effort=none` with temperature 0. Both accept this, and it is the closest match to the
  vanilla temperature-0 setup.
- **Gemini 3.x:** temperature 0 and `thinking_level=low`, the lowest level both models support. Thinking tokens are billed as
  output and are included in the cost.
- **Claude 5-generation models:** the code now omits temperature for them, since they reject non-default sampling and always
  think adaptively. They were not run.

**Pre-run cost estimate:** measured round-1 tokens per call (about 2.3k in; about 350 out for non-reasoning models, about
700 out for thinking Flash) × list price, 504 calls per model.

| model | estimate | outcome |
|---|---|---|
| Opus 5.5 | ~$13 | unavailable |
| GPT-6 Sol | ~$4.3 | run |
| Sonnet 5 | ~$6.7 | unavailable |
| GPT-6 Luna | ~$0.2 | run |
| Gemini 3.8 Flash | ~$2.7 | run |
| Gemini 3.1 Pro | ~$8.1 | run |
| GPT-6 Astra | ~$32 | skipped |

The runnable set came to ~$15.3, under the cap, so all four ran at once.

## Results: current models (252 pairs) -- `fullset/vanilla_compare_current.md`
| system | CA [95% CI] | OI | FA / SA | unparsed (of 504) | $/pair | total $ | wall | dCA vs ours [95% CI] | McNemar p (ours-wrong-model-right / reverse) | verdict vs ours |
|---|---|---|---|---|---|---|---|---|---|---|
| **ours**: G-FOCUS single, T0, gemini-2.5-flash | 42.9 [36.5, 48.8] | 59.9 | 51.6 / 68.3 | 1 | 0.0110 | 2.77 | 89 s | (reference) | | |
| GPT-6 Sol vanilla (effort none, T0) | 44.4 [38.5, 50.8] | 58.1 | 49.2 / 67.1 | 0 | 0.0115 | 2.90 | 65 s | +1.6 [-5.2, +8.7] | 0.74 (44/40) | tie (not significant) |
| GPT-6 Luna vanilla (effort none, T0) | 36.5 [30.6, 42.5] | 55.6 | 38.9 / 72.2 | 0 | 0.0006 | 0.15 | 62 s | -6.3 [-13.5, +1.2] | 0.11 (36/52) | ours ahead, not significant |
| Gemini 3.8 Flash vanilla (T0, thinking low) | 54.4 [48.0, 60.7] | 65.9 | 56.7 / 75.0 | 0 | 0.0072 | 1.80 | 83 s | **+11.5 [+4.8, +18.3]** | **0.0019** (56/27) | **model significantly better** |
| Gemini 3.1 Pro vanilla (T0, thinking low) | 57.9 [52.0, 63.9] | 71.0 | 61.1 / 80.6 | 1 | 0.0192 | 4.84 | 118 s | **+15.1 [+8.3, +21.8]** | **4.1e-05** (61/23) | **model significantly better** |

- dCA = model minus ours.
- Paired test: a 10k bootstrap CI and an exact McNemar test on the 252 pairs. "Significant" means p < 0.05 and the CI excludes 0.
- Columns are as in round 1. FA / SA = accuracy with the winner shown first / second. OI = one order-free pick per pair.
- Wall = each run's span. All four ran at the same time (64 pairs in flight each), from 06:41:07 to 06:43:08 PT, 2 min total.

**Verdicts:**
- (Superseded by the Claude 5 addendum above: vanilla Opus 5.5 scores 66.7, above all of these.)
- **Ours is no longer the best system.** Plain zero-shot Gemini 3.1 Pro (+15.1, p = 4e-5) and Gemini 3.8 Flash (+11.5,
  p = 0.002) are both significantly better than our G-FOCUS pipeline on 2.5 Flash.
- **Gemini 3.8 Flash beats ours on cost too:** $0.0072/pair vs $0.0110 (0.65x), and higher CA. It is the new cost-efficiency
  point to beat.
- **GPT-6 Sol ties ours** (44.4 vs 42.9, p = 0.74) at about the same cost ($0.0115 vs $0.0110/pair).
- **GPT-6 Luna** is 6.3 points behind ours (not significant) at 1/18 of our cost ($0.0006/pair).
- **The Gemini 3.x gains are not only position consistency.** OI (order-free preference accuracy) rises to 66-71 from our
  59.9, and both FA and SA rise.

**Same model, with and without G-FOCUS (75 dev pairs)** -- `fullset/vanilla_compare_current_dev75.md`:

| system | CA [95% CI] | $/pair |
|---|---|---|
| G-FOCUS T0 on 3.1 Pro (NOISE_REPORT step 5) | 50.7 [40.0, 61.3] | 0.070 |
| vanilla 3.1 Pro | 68.0 [57.3, 78.7] | 0.019 |

- Vanilla 3.1 Pro vs ours on dev: +14.7 [+2.7, +26.7], p = 0.035.
- **On a strong model, the G-FOCUS scaffolding lowers accuracy at 3.7x the cost.** It helped 2.5 Flash (vanilla 25.8 → 42.9)
  but hurts 3.1 Pro. Dev is 75 pairs, so this comparison is suggestive, not conclusive.

**Caveat (contamination, unverified):**
- WiserUI-Bench (May 2025) is built from public A/B-test write-ups. Models with 2026 knowledge cutoffs may have seen some
  outcomes.
- GPT-6 Sol (cutoff Apr 2026) did not jump, so a later cutoff alone does not explain the Gemini gain, but it cannot be ruled out.

## Spend (this round, list price)
| item | $ |
|---|---|
| GPT-6 Sol vanilla | 2.90 |
| GPT-6 Luna vanilla | 0.15 |
| Gemini 3.8 Flash vanilla | 1.80 |
| Gemini 3.1 Pro vanilla | 4.84 |
| availability probes (tiny calls; the Claude 5 probes all failed and were not billed) | <0.01 |
| **total** | **9.70** (cap $20) |

- A live watcher summed every call at list price every 5 s, with a kill at $19.90. It was never triggered.
- Code changes:
  - `openai_generate` treats `gpt-6*` as a reasoning model; with effort `none` it also sends the temperature.
  - `claude_vertex_generate` omits temperature and adds 8192 tokens of max_tokens headroom for Claude Opus 5 / Sonnet 5 / Fable.
  - New prices in `run_bench.py` / `arm_compare.py`.

---

## Older models (round 1, 06:28 AM PT; superseded, kept for reference)
These models are no longer current: gpt-4o, gpt-4.1-mini, gpt-5-mini, Claude Sonnet 4.6, and vanilla gemini-2.5-flash.
They ran under the same setup and were not rerun. gpt-5-mini ran at `reasoning_effort=minimal`.

### Results, older models (252 pairs) -- `fullset/vanilla_compare_252.md`
| system | CA [95% CI] | OI | FA / SA | unparsed (of 2n) | $/pair | total $ | wall | dCA vs ours [95% CI] | McNemar p (ours-wrong-model-right / reverse) | ours significantly better? |
|---|---|---|---|---|---|---|---|---|---|---|
| ours: G-FOCUS single, T0, gemini-2.5-flash | 42.9 [36.5, 48.8] | 59.9 | 51.6 / 68.3 | 1 | 0.0110 | 2.77 | 89 s | (reference) | |  |
| claude-sonnet-4-6 vanilla | 36.5 [30.6, 42.5] | 59.3 | 38.9 / 79.8 | 0 | 0.0234 | 5.90 | 142 s | -6.3 [-13.1, +0.8] | 0.097 (33/49) | no |
| gpt-4o vanilla | 21.8 [16.7, 27.0] | 56.3 | 36.5 / 61.9 | 71 | 0.0127 | 3.21 | 96 s | -21.0 [-27.8, -14.3] | 8.4e-09 (17/70) | yes |
| gpt-4.1-mini vanilla | 31.7 [26.2, 37.3] | 56.7 | 36.9 / 76.6 | 0 | 0.0034 | 0.86 | 110 s | -11.1 [-17.9, -4.0] | 0.0026 (27/55) | yes |
| gpt-5-mini vanilla (minimal) | 35.3 [29.4, 41.3] | 55.0 | 41.3 / 68.7 | 0 | 0.0038 | 0.96 | 117 s | -7.5 [-14.7, -0.4] | 0.053 (34/53) | no |
| gemini-2.5-flash vanilla | 25.8 [20.2, 31.3] | 55.8 | 27.4 / 81.3 | 13 | 0.0030 | 0.77 | 128 s | -17.1 [-23.4, -10.7] | 6.1e-07 (16/59) | yes |

- **Columns:**
  - FA / SA = accuracy with the winner shown first / second (position bias).
  - OI = one order-free pick per pair (tie = 0.5).
  - "unparsed" counts per-order answers out of 504.
  - $/pair and total $ are every call for the 252 pairs at list price. Ours includes the 75 cached dev pairs at their original
    cost; its new spend was $1.93.
  - Wall = the span of each run's new calls. All runs ran at the same time, 64-96 pairs in flight each.
- **Paired test vs ours:** 10k bootstrap CI of dCA, exact McNemar. "Significantly better" = p < 0.05 and the CI excludes 0.

**Verdicts (older models):**
- **Ours is significantly better than:**
  - gpt-4o vanilla: -21.0, p = 8e-9.
  - gemini-2.5-flash vanilla, the same model without G-FOCUS: -17.1, p = 6e-7.
  - gpt-4.1-mini vanilla: -11.1, p = 0.003.
- **Not significant:**
  - gpt-5-mini: -7.5 [-14.7, -0.4], p = 0.053. The CI just excludes 0 but McNemar misses. Borderline.
  - Claude Sonnet 4.6: -6.3 [-13.1, +0.8], p = 0.097.

**Other observations (older models):**
- Sonnet 4.6 is the strongest vanilla model (CA 36.5), but at 2.1x our cost per pair.
- gpt-5-mini is close behind (35.3) at a third of our cost.
- **G-FOCUS mainly buys consistency across orders, not raw preference accuracy.** Every system's OI sits at 55-60 (ours 59.9,
  Sonnet 59.3). Vanilla models fail CA mostly through position bias: Sonnet FA 38.9 / SA 79.8, Flash 27.4 / 81.3.
- **gpt-4o refused 71 of 504 answers** ("...if you describe the differences, I can assist..."), which cost it CA. The paper's code
  re-asked up to 5 times when the "More effective:" line was missing. Here refusals count as wrong, as specified.
  Flash left 13 unparsed ("Both are equally effective" or no final line). Ours had 1 (an Evaluator with no verdict after retries).


### Round-1 setup details
- **Ours:** G-FOCUS single judge, strict, both orders, temperature 0, no extra inputs, gemini-2.5-flash (stream `gfocus`,
  `--argue-temperature 0`). The 75 dev pairs reuse the T0 run 1 cache. The other 177 ran fresh (`results/gfocus_t0_all252`).
- **Vanilla:** the WiserUI paper's zero-shot baseline prompt, verbatim from the repo (`inference/prompts_task1/zero_shot.txt`),
  one call per presentation order (stream `vanilla`, `PairFlags(short_pick=True, vanilla=True)`). The answer is parsed from the
  last "More effective: First/Second", tolerating markdown, brackets and case (`parse_vanilla`). An unparsed answer counts as
  wrong, with no retries.
- **Same inputs for every model:** the same images (each screenshot fit into 1568 x 1568, Claude's own limit, so every model gets
  identical PNG bytes), the same prompt, max 2048 output tokens, temperature 0.
  gpt-5-mini is the exception: it takes no temperature, so it ran at `reasoning_effort=minimal`.
- **Models and where they ran:**
  - Claude on Vertex AI in `project-amer-scs-sandbox`, `global` endpoint, with retries rotating to `us-east5` / `europe-west1` on
    429s. **Claude Sonnet 4.6** (`claude-sonnet-4-6`) is the latest 4.x Sonnet; Sonnet 4.5 is also enabled.
  - **Claude Haiku is not enabled** in the project (404 "not found or no access" for `claude-haiku-4-5@20251001`,
    `claude-haiku-4-5`, `claude-3-5-haiku@20241022` and `claude-3-haiku@20240307` in global, us-east5 and europe-west1). Nothing was
    enabled and Haiku was not run.
  - OpenAI API: `gpt-4o` (the paper's model family), `gpt-4.1-mini` and `gpt-5-mini`. All three names were available, so no
    substitutes were needed.
  - Vertex: `gemini-2.5-flash`.
- **Code (product):**
  - `mvp/e2e_ui_run.py`: `llm_generate` routes `claude-*` to Claude on Vertex (`claude_vertex_generate`), `gpt-*`/`o*` to OpenAI
    (`openai_generate`) and everything else to Gemini. All clients take the same (text, image bytes) contents list, return
    (text, tokens_in, tokens_out) and retry on 429/5xx/timeouts.
  - `mvp/pairwise.default_call` now uses `llm_generate`, so any judge path can run on any provider via `PairFlags.model`.
  - The OpenAI key is read from the environment or `/workspace/.openai.env`. It is never logged or committed.
- **Prices ($/1M in/out, list):** Sonnet 4.6 3/15, gpt-4o 2.5/10, gpt-4.1-mini 0.4/1.6, gpt-5-mini 0.25/2 (reasoning billed as
  output), gemini-2.5-flash 0.3/2.5.


### Spend, round 1 (new calls, list price)
| item | $ |
|---|---|
| ours: the 177 non-dev pairs | 1.93 |
| Claude Sonnet 4.6 vanilla (including a 3-pair pilot) | 5.90 |
| gpt-4o vanilla (including pilot) | 3.21 |
| gpt-4.1-mini vanilla (including pilot) | 0.86 |
| gpt-5-mini vanilla (including pilot) | 0.96 |
| gemini-2.5-flash vanilla (including pilot) | 0.77 |
| availability probes (5-token calls) | <0.01 |
| **total** | **13.63** (cap $20) |

Wall time:
- All five vanilla models ran together from 06:31:14 to 06:33:08 PT (114 s). Sonnet was last.
- Ours (177 new pairs) ran from 06:30:45 to 06:32:15 PT (90 s).

## Published numbers (context, not the same setup)
From the G-FOCUS paper (arXiv 2505.05026v1, Table 1): all 300 pairs, temperature 1, OmniParser set-of-mark inputs, self-consistency
over 3 samples for the baselines, hand-cleaned images.

| paper system | CA |
|---|---|
| GPT-4o zero-shot | 24.67 |
| Claude 3.5 Sonnet zero-shot | 21.33 |
| o1 | 20.00 |
| GPT-4o best baseline (MAD round 1) | 30.67 |
| GPT-4o G-FOCUS | 43.33 |
| Claude 3.5 Sonnet G-FOCUS | 45.09 |

Our gpt-4o vanilla (21.8) is close to the paper's GPT-4o zero-shot (24.67). Older cheap models run vanilla land at 26-37; current Gemini 3.x vanilla reaches 54-58.
Ours (42.9) is in line with the paper's G-FOCUS numbers (43.3 / 45.1) on a cheaper model.
Caveats: the set is not the same (252 of 300, our auto-inpainted images), there is no OmniParser and no self-consistency, and we ran at T0.

