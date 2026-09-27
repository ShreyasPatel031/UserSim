# Vanilla cost-efficient models vs our judge on WiserUI-Bench (2026-09-27 PT)

Approved by Shreyas at 6:28 AM PT. Cap $20, no tuning, no flagship models.
Set: the 252 clean pairs (`fullset/final_indices_main.txt`). Metric: strict CA (right in both presentation orders; chance 25%),
as in the earlier reports.

## Systems
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

## Results (252 pairs) -- `fullset/vanilla_compare_252.md`
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

**Verdicts:**
- **Ours is significantly better than:**
  - gpt-4o vanilla: -21.0, p = 8e-9.
  - gemini-2.5-flash vanilla, the same model without G-FOCUS: -17.1, p = 6e-7.
  - gpt-4.1-mini vanilla: -11.1, p = 0.003.
- **Not significant:**
  - gpt-5-mini: -7.5 [-14.7, -0.4], p = 0.053. The CI just excludes 0 but McNemar misses. Borderline.
  - Claude Sonnet 4.6: -6.3 [-13.1, +0.8], p = 0.097.

**Other observations:**
- Sonnet 4.6 is the strongest vanilla model (CA 36.5), but at 2.1x our cost per pair.
- gpt-5-mini is close behind (35.3) at a third of our cost.
- **G-FOCUS mainly buys consistency across orders, not raw preference accuracy.** Every system's OI sits at 55-60 (ours 59.9,
  Sonnet 59.3). Vanilla models fail CA mostly through position bias: Sonnet FA 38.9 / SA 79.8, Flash 27.4 / 81.3.
- **gpt-4o refused 71 of 504 answers** ("...if you describe the differences, I can assist..."), which cost it CA. The paper's code
  re-asked up to 5 times when the "More effective:" line was missing. Here refusals count as wrong, as specified.
  Flash left 13 unparsed ("Both are equally effective" or no final line). Ours had 1 (an Evaluator with no verdict after retries).

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

Our gpt-4o vanilla (21.8) is close to the paper's GPT-4o zero-shot (24.67). Current cheap models run vanilla land at 26-37.
Ours (42.9) is in line with the paper's G-FOCUS numbers (43.3 / 45.1) on a cheaper model.
Caveats: the set is not the same (252 of 300, our auto-inpainted images), there is no OmniParser and no self-consistency, and we ran at T0.

## Spend (new calls, list price)
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
